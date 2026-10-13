# -*- coding: utf-8 -*-
"""「快速识屏」本地 OCR：截图像素 → 带阅读顺序的文本块。

设计定稿的四条硬约束，以及它们在这一层各自的落点：

1. **本地 + 断网可用**。引擎是 RapidOCR（PaddleOCR 的 PP-OCR 模型，ONNXRuntime
   推理），模型文件随包放在 ``resources/rapidocr_models/``。加载路径上**不存在**
   下载分支：每个模型都由本模块自己按显式路径建 session 再交给 rapidocr，
   而 rapidocr 一旦拿到外部 session 就直接返回，连"模型路径 → 下载"那段代码都
   不会进（见 :func:`_attach_sessions`）。
2. **CPU、1~2 线程、关自旋、首版禁 GPU**。``SessionOptions`` 显式写死
   ``intra_op_num_threads``（1~2）、``inter_op_num_threads=1``、
   ``allow_spinning=0``，执行提供者只有 ``CPUExecutionProvider``。桌宠是常驻
   后台程序，识别期间把整机 CPU 打满、或让工作线程空转让风扇起飞，都是不可接受
   的代价。
3. **懒加载：进程内单后台线程**。``import`` 这个模块不碰 numpy/onnxruntime/
   rapidocr；模型加载发生在首次使用（``recognize`` 或 ``preload``）时启动的
   那**一个**后台线程里。并发的调用方一起等同一个 ``Event``，不会各起一个线程
   把同一份模型加载三遍。
4. **错误说人话**。模型缺失 / 依赖缺失 / 加载失败 / 识别失败四类故障各有自己的
   异常类型与一句能直接给用户看的中文说明，并且**失败只试一次**——坏掉的东西
   不会在几百毫秒后自己好起来，每次点击都重跑一遍加载只是把等待时间再收一遍。
5. **用完就丢**。一次识屏结束后由编排层调 :func:`release_engine`（引擎侧是
   :meth:`OcrEngine.unload`）：丢弃引擎与三份 session、跑一次 ``gc``。释放后
   再触发会**重新加载**（同一份模型再建 session），不需要重启进程——这是
   「不想常驻 100 MB，但也不能因为丢掉了就再也用不了」这个取舍的落点。
   实测口径（本机 2026-10-13，见 ``.scratch/screen-capture/probe_ocr_unload_rss.txt``）：
   加载后 RSS +108 MB、识别后的平台期约 159 MB；``unload()`` 耗时约 48 ms，
   **只回吐约 30 MB**（152.4 → 122.5 MB），再手动 ``gc.collect()`` 与等 5 秒
   都不再变。也就是说：释放的是进程内的引用与 ONNXRuntime 会话对象，
   **native 堆与已 import 的 cv2/numpy 模块内存不还给操作系统**——RSS 回不到
   加载前的水位（仍高出约 78 MB）。冻结包里同一组数字（42.6 → 137.3，
   unload 后 108.3）：结论一样。这里如实记下来，不把"逻辑上释放了"说成
   "内存还回去了"。

模型文件的来源与体积（真机实测，2026-10-13）：

===========================================  ==========
文件                                           体积
===========================================  ==========
``PP-OCRv6_det_small.onnx``（文本检测）         9.5 MB
``PP-OCRv6_rec_small.onnx``（文本识别）        20.2 MB
``ch_ppocr_mobile_v2.0_cls_mobile.onnx``（方向分类） 0.6 MB
===========================================  ==========

三个文件都直接取自 ``rapidocr`` wheel 自带的 ``rapidocr/models/``（同一版本、
逐字节相同），重新取出/换版本的命令::

    python -c "import os, rapidocr, shutil; src=os.path.join(os.path.dirname(rapidocr.__file__),'models'); [shutil.copy2(os.path.join(src,n), 'resources/rapidocr_models/') for n in os.listdir(src) if n.endswith('.onnx')]"

识别模型的字符表（18708 个字符）**内嵌在 onnx 元数据里**（实测
``custom_metadata_map['character']``），所以不需要额外的 ``ppocr_keys_v1.txt``
——这也是"断网可用"能成立的另一半：字典不会在首次识别时被顺手下拉。

隐私与职责边界：本层只做"像素进、文本出"，不落盘、不联网、不管 UI，也不决定
识别结果怎么展示。
"""

from __future__ import annotations

import gc
import importlib.util
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from PySide6.QtGui import QImage

log = logging.getLogger("dsh-pet-standalone")

__all__ = [
    "MODEL_FILES",
    "MODEL_RELATIVE_DIR",
    "MODEL_SHA256",
    "OCR_MODEL_DIR_ENV",
    "OcrEngine",
    "OcrError",
    "OcrLoadError",
    "OcrModelMissingError",
    "OcrRecognitionError",
    "OcrUnavailableError",
    "TextBlock",
    "bundled_model_dir",
    "model_problem",
    "reading_order",
    "recognize",
    "release_engine",
    "resolve_model_dir",
    "shared_engine",
    "to_bgr_array",
]

#: 模型在源码树 / 冻结包里的相对目录。冻结包按 ``sys._MEIPASS`` 为根（与
#: ``pet/game_fps.py::bundled_backend_path`` 同一约定）。
MODEL_RELATIVE_DIR = ("resources", "rapidocr_models")

#: 三个模型文件（键就是 rapidocr 配置里的段名，注入 session 时按它对应）。
MODEL_FILES = {
    "Det": "PP-OCRv6_det_small.onnx",
    "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "Rec": "PP-OCRv6_rec_small.onnx",
}

#: 三个模型文件的 sha256（2026-10-13 按随包文件实测值登记）。
#:
#: 这是**构建期硬门**（``scripts/verify_rapidocr_models.py``）的唯一真相源：模型
#: 要是被截断、换成了同名的另一版、或者混进别的语言模型，产品**不会崩**——识别
#: 结果会静默变差（错字、漏行），用户只会觉得"这个识屏不准"。所以在打包阶段就按
#: 名字 + 摘要挡住，而不是等用户发现问题。运行期**不**校验：每次启动多读 31 MB
#: 只为一件 CI 该做的事（与 ``pet/game_fps.py::REQUIRED_SHA256`` 同一取舍）。
#:
#: 换模型版本时：改 ``MODEL_FILES`` + 本表 + THIRD_PARTY_NOTICES.md，三处必须同时改。
MODEL_SHA256 = {
    "Det": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    "Cls": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    "Rec": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
}

#: 模型目录覆盖开关（开发/自定义部署用）。正式包不设它，走随包目录。
OCR_MODEL_DIR_ENV = "DSH_PET_OCR_MODEL_DIR"

#: 交给 rapidocr 的固定配置。GPU 相关的开关在这里显式关一遍，作为"执行提供者只有
#: CPU"的第二道防线（第一道是本模块自建 session 时写死的 providers）。日志放到
#: ``error``：rapidocr 在整张图没检出文字时会打一条 WARNING，而"截了一张没有文字的
#: 图"是**正常输入**，不该污染用户的日志。
_RAPIDOCR_PARAMS = {
    "Global.log_level": "error",
    "EngineConfig.onnxruntime.use_cuda": False,
    "EngineConfig.onnxruntime.use_dml": False,
    "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
}

#: 线程预算的上下界（设计约束：CPU 限定 1~2 线程）。
_MIN_CPU_THREADS = 1
_MAX_CPU_THREADS = 2

#: 默认加载超时。模型加载实测 ~0.6 s（本机），给 60 s 是"慢机器 + 杀毒软件首扫"
#: 的宽预算；真挂住时也不能让调用方无限等下去——桌宠是个 GUI 程序。
_DEFAULT_LOAD_TIMEOUT = 60.0


# ---------------------------------------------------------------------- 异常


class OcrError(RuntimeError):
    """本地 OCR 的失败基类：``str(exc)`` 就是可以直接给用户看的那句话。"""


class OcrUnavailableError(OcrError):
    """本机没有 OCR 依赖（rapidocr / onnxruntime 未安装）——安装不完整。"""


class OcrModelMissingError(OcrError):
    """模型文件缺失——安装不完整，换图重试没有意义。"""


class OcrLoadError(OcrError):
    """模型/引擎加载失败（文件损坏、DLL 不匹配、加载超时）。"""


class OcrRecognitionError(OcrError):
    """引擎起来了但这一次识别失败。"""


# ------------------------------------------------------------------ 数据契约


@dataclass(frozen=True)
class TextBlock:
    """一块被识别出来的文字。

    ``box`` 是四个角点 ``((x, y) × 4)``，顺序为左上 → 右上 → 右下 → 左下
    （就是检测模型给出的四边形）。保留四边形而不是只留外接矩形，是因为倾斜的
    一块文字用外接矩形圈出来会盖住旁边的内容。
    """

    text: str
    score: float
    box: tuple[tuple[float, float], ...]

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """外接矩形 ``(left, top, width, height)``，与 ``QImage`` 的像素坐标同口径。"""
        if not self.box:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [point[0] for point in self.box]
        ys = [point[1] for point in self.box]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @property
    def center(self) -> tuple[float, float]:
        left, top, width, height = self.bounds
        return (left + width / 2, top + height / 2)


def reading_order(blocks: Iterable[TextBlock]) -> list[TextBlock]:
    """按阅读顺序重排文本块：先按行自上而下，行内自左而右。

    分行的判据是**竖向重叠比**（重叠高度 > 较短一方高度的一半）。用固定阈值去比
    上沿坐标会散架：同一行里字号/基线略有差别的两块（正文与行内代码、中英文混排）
    上沿本来就不齐，按阈值切会把一行拆成两行，输出读起来就是乱的。
    """
    ordered = sorted(blocks, key=lambda block: block.bounds[1])
    if not ordered:
        return []

    lines: list[list[TextBlock]] = []
    spans: list[tuple[float, float]] = []
    for block in ordered:
        _, top, _, height = block.bounds
        bottom = top + height
        if lines:
            line_top, line_bottom = spans[-1]
            overlap = min(line_bottom, bottom) - max(line_top, top)
            if overlap > 0 and overlap > 0.5 * min(line_bottom - line_top, height):
                lines[-1].append(block)
                spans[-1] = (min(line_top, top), max(line_bottom, bottom))
                continue
        lines.append([block])
        spans.append((top, bottom))

    result: list[TextBlock] = []
    for index in sorted(range(len(lines)), key=lambda i: (spans[i][0], min(b.bounds[0] for b in lines[i]))):
        result.extend(sorted(lines[index], key=lambda block: block.bounds[0]))
    return result


# ------------------------------------------------------------------ 模型路径


def bundled_model_dir() -> Path:
    """随包模型目录（**纯函数**，不碰文件系统，也不做回退）。

    冻结包取 ``sys._MEIPASS/resources/rapidocr_models``，源码运行取仓库根的同一
    相对路径；``DSH_PET_OCR_MODEL_DIR`` 可以整个覆盖它。与
    ``pet/game_fps.py::bundled_backend_path`` 同一套写法，理由也一样：模型必须
    来自我们知道的那一份，不能在 PATH / 环境里"就近找一个"。
    """
    override = os.environ.get(OCR_MODEL_DIR_ENV)
    if override:
        return Path(override)
    meipass = getattr(sys, "_MEIPASS", None)
    root = Path(meipass) if meipass else Path(__file__).resolve().parents[2]
    return root.joinpath(*MODEL_RELATIVE_DIR)


def model_problem(directory: Path | None = None) -> str:
    """模型目录不可用的**人话**原因；可用返回 ``""``。

    只判存在性：文件在不在是安装完整性问题；内容对不对要等 ONNXRuntime 加载时
    才知道（那时由 :class:`OcrLoadError` 接手）。缺哪个文件就报哪个，用户拿着
    这句话才知道该重装还是该补文件。
    """
    target = Path(directory) if directory is not None else bundled_model_dir()
    missing = [name for name in MODEL_FILES.values() if not (target / name).is_file()]
    if not missing:
        return ""
    return (
        f"缺少本地 OCR 模型文件 {', '.join(missing)}（找过的目录：{target}）"
        "——模型随安装包分发，缺失说明安装不完整，请重新安装"
    )


def _installed_models_dir() -> Path | None:
    """已安装的 rapidocr wheel 自带的模型目录（开发环境的回退）。"""
    try:
        import rapidocr
    except ImportError:
        return None
    return Path(rapidocr.__file__).resolve().parent / "models"


def resolve_model_dir(explicit: Path | None = None) -> Path:
    """实际使用的模型目录：显式指定 > 随包 ``resources/`` > 已装 wheel 自带。

    中间那条回退是给**开发环境**的：干净 clone 里 ``resources/rapidocr_models/``
    可能还没落盘，而 ``rapidocr`` 依赖本身就带着同一批模型文件（版本钉死）。
    两者都不可用时返回随包路径——报错要报用户机器上的那一个，不是开发机的。
    """
    if explicit is not None:
        return Path(explicit)
    packaged = bundled_model_dir()
    if model_problem(packaged) == "":
        return packaged
    installed = _installed_models_dir()
    if installed is not None and model_problem(installed) == "":
        return installed
    return packaged


# ---------------------------------------------------------------- 引擎加载器


def _import_rapidocr():
    """厚重导入的唯一入口。

    单独成函数有两个理由：模块 import 期不把 rapidocr（连带 numpy / opencv /
    onnxruntime，实测 import 1.7 s）拖进进程；以及让"依赖没装"这条错误路径可以
    被精确注入测试，而不必去动 ``sys.modules``。
    """
    import rapidocr

    return rapidocr


def _describe(exc: BaseException) -> str:
    """异常 → 一句可读的原因；消息为空时退回到类型名。

    实测（冻结包缺 numpy，2026-10-13）：``ImportError`` 系异常在冻结环境里可能
    ``str(exc) == ""``，直接拼进人话里就得到"……加载失败（x.onnx）："这种以冒号
    结尾的空话——用户拿它什么都做不了，排查的人也无从下手。
    """
    detail = str(exc).strip()
    return detail if detail else type(exc).__name__


def _new_session(model_path: Path, cpu_threads: int):
    """按设计约束建一个 CPU-only、关自旋的 ONNXRuntime session。"""
    from onnxruntime import GraphOptimizationLevel, InferenceSession, SessionOptions

    options = SessionOptions()
    # 4 = 只报 fatal：onnxruntime 的 info 级日志会把控制台刷满。
    options.log_severity_level = 4
    options.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = cpu_threads
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    for key in ("session.intra_op.allow_spinning", "session.inter_op.allow_spinning"):
        try:
            options.add_session_config_entry(key, "0")
        except Exception as exc:  # 不同 ORT 版本对配置键的接受度不一样
            log.debug("本地 OCR：%s 设置失败，沿用 ONNXRuntime 默认值 (%s)", key, exc)
    # 只挂 CPU：首版禁 GPU（没有实机验证过 GPU 路径，宁可慢也不给用户装一个
    # 会在别的机器上崩的默认值）。
    return InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])


def _attach_sessions(engine, sessions: dict) -> None:
    """把本模块自建的 session 塞进 rapidocr 的配置。

    rapidocr 的 ``OrtInferSession`` **本来**就支持外部传入 session（``cfg["session"]``，
    上游 PR #451），但它的参数入口经 OmegaConf，拒收任意对象值（实测
    ``UnsupportedValueType: Value 'InferenceSession' is not a supported primitive
    type``），所以只能建好引擎之后写回它自己的 cfg；``allow_objects`` 正是
    OmegaConf 为这种"配置里要挂一个活对象"提供的开关。

    为什么非走这条路不可：rapidocr 自建 session 时会去读 ``Det/Rec/Cls`` 的
    ``model_path``，而该字段为空时它**会去网上下**（``DownloadFile.run``）。把
    session 从外面塞进去，那条分支直接短路——"断网可用"于是是结构保证，而不是
    "但愿文件都在"。
    """
    from omegaconf import OmegaConf

    for section, session in sessions.items():
        node = OmegaConf.create(
            OmegaConf.to_container(engine.cfg[section]), flags={"allow_objects": True}
        )
        node.session = session
        engine.cfg[section] = node


def _load_rapidocr(model_dir: Path | None, cpu_threads: int):
    """默认加载器：跑在后台线程里，返回一个 ``callable(ndarray) -> 结果``。

    失败一律抛 :class:`OcrError` 子类（``str(exc)`` 即人话），调用方只负责
    记录与展示。
    """
    directory = resolve_model_dir(model_dir)
    problem = model_problem(directory)
    if problem:
        raise OcrModelMissingError(problem)

    if importlib.util.find_spec("onnxruntime") is None:
        raise OcrUnavailableError(
            "本地 OCR 运行库 onnxruntime 没装——依赖随安装包分发，缺失说明安装不完整，请重新安装"
        )
    try:
        rapidocr = _import_rapidocr()
    except ImportError as exc:
        raise OcrUnavailableError(
            f"本地 OCR 库 rapidocr 不可用（{exc}）——依赖随安装包分发，缺失请重新安装"
        ) from exc

    sessions = {}
    for section, file_name in MODEL_FILES.items():
        try:
            sessions[section] = _new_session(directory / file_name, cpu_threads)
        except Exception as exc:
            raise OcrLoadError(f"本地 OCR 模型加载失败（{file_name}）：{_describe(exc)}") from exc

    try:
        engine = rapidocr.RapidOCR(params=dict(_RAPIDOCR_PARAMS))
    except Exception as exc:
        raise OcrLoadError(f"本地 OCR 引擎初始化失败：{_describe(exc)}") from exc
    _attach_sessions(engine, sessions)
    log.info(
        "快速识屏：本地 OCR 引擎就绪（模型目录 %s，CPU 线程 %d）", directory, cpu_threads
    )
    return engine


# ---------------------------------------------------------------- 像素 → 数组


def to_bgr_array(image: QImage):
    """``QImage`` → 连续 BGR ``ndarray``（OpenCV 口径，rapidocr 直接吃）。

    用 Qt 自己的 ``Format_BGR888`` 转换，而不是"先取 RGB 再翻通道"：通道顺序由
    Qt 保证，少一次全图逐像素操作。``bytesPerLine`` 会把每行对齐到 4 字节，
    宽度不是 4 的倍数时行尾有垃圾字节——不按 stride 剥掉就会把整张图错位，
    所以这里先按 stride 取行、再切前 ``width*3`` 个字节。
    """
    import numpy as np

    if image.format() != QImage.Format.Format_BGR888:
        converted = image.convertToFormat(QImage.Format.Format_BGR888)
        if converted.isNull():
            raise OcrRecognitionError("图像转换失败：无法把截图转成 8-bit BGR")
        image = converted

    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    buffer = np.frombuffer(image.constBits(), dtype=np.uint8)
    if buffer.size < stride * height:
        raise OcrRecognitionError(
            f"图像缓冲区不完整（{buffer.size} 字节 < {stride * height} 字节）"
        )
    rows = buffer[: stride * height].reshape(height, stride)[:, : width * 3]
    # 显式 copy：stride == width*3 时上面取到的是 QImage 自己的内存视图，
    # 让引擎拿着一个指向 Qt 缓冲区的数组跑推理是在赌生命周期，不值得省这一次拷贝。
    return np.array(rows.reshape(height, width, 3), dtype=np.uint8, order="C", copy=True)


def _to_blocks(result: Any) -> list[TextBlock]:
    """引擎原始输出 → 阅读顺序的文本块列表（没文字就是空列表，不是错误）。"""
    if result is None:
        # 引擎不返结果 ≠ 图里没字：前者是故障，必须报出来，不能让上层显示"没有识别到文字"。
        raise OcrRecognitionError("本地 OCR 引擎没有返回结果")
    texts = getattr(result, "txts", None)
    if not texts:
        return []
    boxes = getattr(result, "boxes", None)
    scores = getattr(result, "scores", None)
    if boxes is None or len(boxes) < len(texts):
        raise OcrRecognitionError(
            f"识别结果缺框坐标（文字 {len(texts)} 块，框 {0 if boxes is None else len(boxes)} 个）"
        )

    blocks: list[TextBlock] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        score = float(scores[index]) if scores is not None and index < len(scores) else 0.0
        box = tuple((float(point[0]), float(point[1])) for point in boxes[index])
        blocks.append(TextBlock(str(text), score, box))
    return reading_order(blocks)


# -------------------------------------------------------------------- 引擎


class OcrEngine:
    """本地 OCR 引擎：懒加载、线程安全、一次调用认一张图。

    线程模型（三把锁各司其职，别合并）：

    - ``_state_lock``：保证**只有一个**加载线程被创建（决定谁去加载）；
    - ``_ready``：所有调用方一起等同一份加载结果（等加载）；
    - ``_infer_lock``：识别串行化。rapidocr 的流水线在实例上存可变状态
      （每次调用重写 ``preprocess_op``、``update_params``），并行跑它不是"更快"
      而是错误用法——races 不会稳定复现，只会在某个用户机器上偶发错行。

    ``engine_factory`` 是可注入的加载缝（签名 ``(model_dir, cpu_threads) -> engine``），
    默认走 :func:`_load_rapidocr`；``engine`` 只需要能被 ``call`` 并返回带
    ``txts`` / ``scores`` / ``boxes`` 的结果对象。

    生命周期还有一个 :meth:`unload`（"用完就丢"）：它把已加载的引擎与状态一起
    丢掉，此后 ``recognize``/``preload`` 会重新加载。**加载中的加载**用 ``_generation``
    计数防串台：每次 ``unload`` 递增，加载线程在写回状态前对比自己出发时的代次，
    代次不符就把结果丢弃（引擎对象随本线程退出被回收），绝不写回——否则"已经释放"
    会退回成"又有了一份引擎"。
    """

    def __init__(
        self,
        *,
        model_dir: Path | None = None,
        cpu_threads: int = _MAX_CPU_THREADS,
        load_timeout: float = _DEFAULT_LOAD_TIMEOUT,
        engine_factory: Callable[[Path | None, int], Any] | None = None,
    ) -> None:
        self._model_dir = Path(model_dir) if model_dir is not None else None
        self.cpu_threads = max(_MIN_CPU_THREADS, min(_MAX_CPU_THREADS, int(cpu_threads)))
        self._load_timeout = float(load_timeout)
        self._engine_factory = engine_factory if engine_factory is not None else _load_rapidocr

        self._state_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._ready = threading.Event()
        self._loader: threading.Thread | None = None
        self._engine: Any = None
        #: 加载代次（见类说明）。只由 ``unload`` / ``_start_loader`` 读写。
        self._generation = 0
        #: 加载失败的「类型 + 人话」；只由加载线程写，失败后不再重试。
        self._failure: tuple[type[OcrError], str] | None = None

    # ---------------------------------------------------------------- 释放

    def unload(self) -> bool:
        """丢掉引擎与加载状态（"用完就丢"），返回是否真的丢了东西。

        语义与边界：

        - **同步**：返回时 ``loaded`` 已为 False。正在跑的识别不会被中途掐断
          （本方法不碰 ``_infer_lock``，那条线程手里的引擎对象是它自己的强引用，
          跑完自然释放）；已经在途的**加载**会被作废——代次 +1 后它写不回来。
        - **加载在途时释放，会让两份引擎短暂并存**：在途那条加载线程**停不下来**
          （它已经在 rapidocr/ONNXRuntime 里造引擎了），代次只是让它写不回状态；而紧接着
          的下一次 ``recognize``/``preload`` 会另起一条新加载线程。两份各 ~100 MB 常驻，
          一直并存到在途那条跑完、把它手上那份交还给 GC 为止（实测见
          ``.scratch/screen-capture/probe_ocr_unload_rss.txt``）。这是刻意的取舍：
          掐断一条正在 ``import``/建 session 的线程，比多占一会儿内存危险得多——
          "同一份引擎半拆半用"才是真事故（同 :func:`release_engine` 的"短暂两份"）。
        - **幂等**：没加载过、或加载已经失败时返回 False，也不清掉失败记录
          （"失败只试一次"是设计约束，不能靠一次 unload 把它绕开）。
        - **可重来**：释放后再调 ``recognize``/``preload`` 会重新加载同一份模型。
        - **不假装**：只丢进程内的引用与 ONNXRuntime 会话对象，``gc.collect()``
          只回收 Python 侧对象；native 堆与已 import 的 cv2/numpy 模块内存**不会**
          还给操作系统。RSS 因此回不到加载前的水位（实测见模块说明第 5 条）。
        """
        with self._state_lock:
            engine, self._engine = self._engine, None
            in_flight = self._loader is not None and self._loader.is_alive()
            if engine is None and not in_flight:
                return False
            self._generation += 1
            self._loader = None
            self._ready.clear()
        del engine
        gc.collect()
        return True

    # ------------------------------------------------------------ 只读视图

    @property
    def loaded(self) -> bool:
        """模型是否已经加载成功（失败的加载不算 loaded）。"""
        return self._ready.is_set() and self._failure is None

    # ---------------------------------------------------------------- 入口

    def preload(self, timeout: float | None = None) -> None:
        """主动把模型加载出来（仍走那唯一一个后台线程），失败直接抛。"""
        self._ensure_ready(timeout)

    def recognize(self, image: QImage) -> list[TextBlock]:
        """认一张图，返回按阅读顺序排好的文本块；没有文字返回空列表。

        空图在**加载模型之前**就被拒掉：一次无谓的模型加载要等几百毫秒到几秒，
        而空图是调用方的 bug，不该罚用户等。
        """
        if not isinstance(image, QImage):
            raise TypeError(f"recognize() 需要 QImage，收到 {type(image).__name__}")
        if image.isNull() or image.width() <= 0 or image.height() <= 0:
            raise ValueError("待识别的图像为空（宽高为 0 或 QImage.isNull()）")

        engine = self._ensure_ready()
        pixels = to_bgr_array(image)
        with self._infer_lock:
            try:
                return _to_blocks(engine(pixels))
            except OcrError:
                raise
            except Exception as exc:
                raise OcrRecognitionError(f"本地 OCR 识别失败：{_describe(exc)}") from exc

    # ---------------------------------------------------------------- 加载

    def _ensure_ready(self, timeout: float | None = None):
        effective = self._load_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + effective
        while True:
            if not self._ready.is_set():
                self._start_loader()
                self._ready.wait(max(0.0, deadline - time.monotonic()))

            failure = self._failure
            if failure is not None:
                raise failure[0](failure[1])
            if self._engine is not None:
                return self._engine
            # 走到这里只有两种可能：等超时（后台线程还在加载），或者引擎在等的
            # 过程中被 unload() 丢掉了。两种都按同一条预算继续等/重来——绝不
            # 返回 None 让调用方去 call 一个空对象。
            if time.monotonic() >= deadline:
                raise OcrLoadError(
                    f"本地 OCR 模型加载超时（等待 {effective:g} 秒仍未就绪）"
                    "——已放弃等待，可稍后重试"
                )

    def _start_loader(self) -> None:
        """启动唯一的加载线程（已经起过就直接返回，后来的调用方只等结果）。"""
        with self._state_lock:
            if self._loader is not None:
                return
            thread = threading.Thread(
                target=self._load_in_background, args=(self._generation,),
                name="dsh-pet-ocr-loader", daemon=True,
            )
            self._loader = thread
            thread.start()

    def _load_in_background(self, generation: int) -> None:
        engine: Any = None
        failure: tuple[type[OcrError], str] | None = None
        try:
            engine = self._engine_factory(self._model_dir, self.cpu_threads)
            if engine is None:
                raise OcrLoadError("本地 OCR 加载器没有返回引擎")
        except OcrError as exc:
            failure = (type(exc), _describe(exc))
        except Exception as exc:  # 加载器里什么都能炸：DLL 缺失、文件损坏、超时……
            failure = (OcrLoadError, f"本地 OCR 引擎加载失败：{_describe(exc)}")
        finally:
            # 失败也置位：等结果的调用方要立刻拿到结论，而不是各自等满超时。
            self._publish_load(generation, engine, failure)

    def _publish_load(self, generation: int, engine: Any,
                      failure: tuple[type[OcrError], str] | None) -> None:
        """把加载结果写回状态；代次不符就丢弃（这次加载已经被 ``unload()`` 作废）。"""
        if engine is None and failure is None:  # 加载线程被更底层的东西打断（BaseException）
            failure = (OcrLoadError, "本地 OCR 引擎加载失败")
        with self._state_lock:
            if generation != self._generation:
                log.debug("快速识屏：放弃已作废的模型加载结果（已被释放）")
                return
            self._engine = engine
            self._failure = failure
            self._ready.set()


# --------------------------------------------------------------- 进程内单例

_SHARED_LOCK = threading.Lock()
_SHARED_ENGINE: OcrEngine | None = None


def shared_engine() -> OcrEngine:
    """进程内共享的默认引擎（"进程内单后台线程"这句话的落脚点）。

    一次识屏只会用到一个引擎，而每个引擎各自持有三份 ONNXRuntime session
    （实测约 100 MB 常驻）。让每个调用方自己 ``new`` 一个，等于按调用次数
    把这份内存翻倍。所以上限是**一份**；闲置回收由 :func:`release_engine`
    在会话收口时显式触发（"用完就丢"），不靠后台定时器去猜。
    """
    global _SHARED_ENGINE
    with _SHARED_LOCK:
        if _SHARED_ENGINE is None:
            _SHARED_ENGINE = OcrEngine()
        return _SHARED_ENGINE


def release_engine() -> bool:
    """丢弃进程内共享引擎（"用完就丢"的模块级入口）；返回是否真的丢了东西。

    **同步**：返回时共享单例已经摘掉、引擎状态已清空，下一次 ``recognize``
    会重新加载（不是"丢了就再也用不了"）。没加载过（模块级没有单例）时立刻返回
    False——这条路径每次截图收口都会走，没加载过就不该付 ``gc.collect()`` 的代价。

    **摘掉单例**是刻意的：调用方刚释放完立刻再触发时，拿到的是另一份干净的引擎，
    不会跟正在拆的那份纠缠。代价是"释放期间又立刻用"会短暂同时存在两份引擎
    （各 ~100 MB）；这比"同一份引擎半拆半用"要安全得多。

    也因此**加载失败不跨会话保留**：摘掉单例后下一次是新引擎、会重新尝试加载
    （引擎对象内部仍然"失败只试一次"，见 :meth:`OcrEngine.unload`）。这是有意的
    ——装坏了的模型/依赖用户重装一次就好，程序不该在整个进程生命周期里都判它死刑；
    代价是坏安装下每次点击多花一次加载尝试（模型缺失/依赖缺失这两条都是**文件系统
    级**的快速判定，实际约 0 ms）。
    """
    global _SHARED_ENGINE
    with _SHARED_LOCK:
        engine, _SHARED_ENGINE = _SHARED_ENGINE, None
    if engine is None:
        return False
    return engine.unload()


# -------------------------------------------------------------- 同包 seam

def recognize(image: QImage) -> str:
    """模块级入口：``recognize(QImage) -> str``——切片的接入点。

    这是同一功能面向 UI 的一层薄壳：结果按阅读顺序用换行拼成一段纯文本，没有文字
    返回空串，失败抛 :class:`OcrError`（``str(exc)`` 直接展示给用户）。切片 3 的
    ``pet/screen_capture/actions.py`` 就是按这个契约解析同包入口的
    （``OCR_MODULE = "ocr"`` / ``OCR_ENTRY = "recognize"``，同步、纯本地、不联网）。

    要**结构化**结果（每块的置信度与框坐标）请用 :meth:`OcrEngine.recognize`：
    那一层是契约测试钉死的主接口，本函数只是它的文本视图。
    """
    blocks = shared_engine().recognize(image)
    return "\n".join(block.text for block in blocks)
