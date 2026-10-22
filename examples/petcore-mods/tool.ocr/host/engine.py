"""本地 OCR 引擎（rapidocr + onnxruntime，CPU、离线、无 Qt）。

模型随安装包放在 ``resources/rapidocr_models``，由 Core 的 ``resources`` 端口给出
目录；本模块**不下载模型**：每个 ONNX session 都按显式路径自建后塞进 rapidocr 的
配置（``session`` 字段），rapidocr 那条「路径为空就去下载」的分支因此永远不会进。

识别在主进程里惰性加载并常驻（拖动截图动作条时不必每次重新加载模型）；这是与主
分支「一次识别一个子进程」的唯一差异，内存代价记录在 P8 报告里。
"""

from __future__ import annotations

import importlib.util
import logging
import threading

logger = logging.getLogger("petcore.mod.ocr")

MODEL_FILES = {
    "Det": "PP-OCRv6_det_small.onnx",
    "Rec": "PP-OCRv6_rec_small.onnx",
    "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
}

_PARAMS = {
    "Global.log_level": "error",
    "EngineConfig.onnxruntime.use_cuda": False,
    "EngineConfig.onnxruntime.use_dml": False,
    "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
}

_lock = threading.Lock()
_engine = None
_engine_dir = ""


class OcrUnavailable(RuntimeError):
    """引擎/模型不可用；``str(exc)`` 是给日志看的人话（不直接弹给用户）。"""


def model_dir(ports):
    resources = getattr(ports, "resources", None)
    if resources is None:
        return None
    try:
        return resources.bundle_path("resources", "rapidocr_models")
    except Exception:
        return None


def model_problem(directory) -> str:
    if directory is None:
        return "没有可用的资源目录"
    if not directory.is_dir():
        return f"OCR 模型目录不存在：{directory}"
    missing = [name for name in MODEL_FILES.values() if not (directory / name).is_file()]
    if missing:
        return f"OCR 模型缺失：{', '.join(missing)}"
    return ""


def available(ports) -> bool:
    if importlib.util.find_spec("rapidocr") is None:
        return False
    if importlib.util.find_spec("onnxruntime") is None:
        return False
    return not model_problem(model_dir(ports))


def _new_session(model_path, cpu_threads: int = 2):
    from onnxruntime import GraphOptimizationLevel, InferenceSession, SessionOptions

    options = SessionOptions()
    options.log_severity_level = 4
    options.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
    options.intra_op_num_threads = max(1, int(cpu_threads))
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    for key in ("session.intra_op.allow_spinning", "session.inter_op.allow_spinning"):
        try:
            options.add_session_config_entry(key, "0")
        except Exception:  # 不同 ORT 版本接受度不同，失败不影响识别
            pass
    return InferenceSession(
        str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def _attach_sessions(engine, sessions: dict) -> None:
    """把自建 session 写回 rapidocr 的 cfg（OmegaConf 需要 ``allow_objects``）。"""
    from omegaconf import OmegaConf

    for section, session in sessions.items():
        node = OmegaConf.create(
            OmegaConf.to_container(engine.cfg[section]), flags={"allow_objects": True}
        )
        node.session = session
        engine.cfg[section] = node


def _load_engine(directory) -> object:
    problem = model_problem(directory)
    if problem:
        raise OcrUnavailable(problem)
    try:
        import rapidocr
    except Exception as exc:  # noqa: BLE001 - 依赖缺失就是不可用，交给 AI 回退
        raise OcrUnavailable(f"rapidocr 不可用：{type(exc).__name__}") from exc
    sessions = {}
    for section, name in MODEL_FILES.items():
        try:
            sessions[section] = _new_session(directory / name)
        except Exception as exc:  # noqa: BLE001
            raise OcrUnavailable(
                f"模型加载失败（{name}）：{type(exc).__name__}"
            ) from exc
    try:
        engine = rapidocr.RapidOCR(params=dict(_PARAMS))
        _attach_sessions(engine, sessions)
    except Exception as exc:  # noqa: BLE001
        raise OcrUnavailable(f"OCR 引擎初始化失败：{type(exc).__name__}") from exc
    return engine


def _engine_for(directory):
    global _engine, _engine_dir
    key = str(directory)
    with _lock:
        if _engine is None or _engine_dir != key:
            _engine = _load_engine(directory)
            _engine_dir = key
        return _engine


def release_engine() -> None:
    """扔掉常驻引擎（设置页「释放内存」/退出前调用）。"""
    global _engine, _engine_dir
    with _lock:
        _engine = None
        _engine_dir = ""


def _blocks(result) -> list[tuple[str, float, float, float, float]]:
    """引擎输出 → ``(text, left, top, width, height)``；没文字返回空列表。"""
    texts = getattr(result, "txts", None)
    if not texts:
        return []
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) < len(texts):
        raise OcrUnavailable("识别结果缺少文字框")
    out: list[tuple[str, float, float, float, float]] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        points = boxes[index]
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        out.append(
            (
                str(text),
                min(xs),
                min(ys),
                max(xs) - min(xs),
                max(ys) - min(ys),
            )
        )
    return out


def reading_text(blocks) -> str:
    """按阅读顺序拼文本：行自上而下，行内自左而右（竖向重叠判行，同主分支口径）。"""
    if not blocks:
        return ""
    ordered = sorted(blocks, key=lambda item: item[2])
    lines: list[list[tuple[str, float, float, float, float]]] = []
    for block in ordered:
        top, height = block[2], block[4]
        for line in lines:
            line_top = min(item[2] for item in line)
            line_bottom = max(item[2] + item[4] for item in line)
            overlap = min(line_bottom, top + height) - max(line_top, top)
            span = min(height, line_bottom - line_top)
            if span > 0 and overlap > span * 0.5:
                line.append(block)
                break
        else:
            lines.append([block])
    lines.sort(key=lambda line: min(item[2] for item in line))
    merged: list[str] = []
    for line in lines:
        merged.append(" ".join(item[0] for item in sorted(line, key=lambda i: i[1])))
    return "\n".join(merged)


def recognize(png: bytes, ports) -> str:
    """识别一块 PNG（内存）并返回文本；不可用/失败抛 :class:`OcrUnavailable`。"""
    directory = model_dir(ports)
    engine = _engine_for(directory)
    try:
        import cv2
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        raise OcrUnavailable(f"图像库不可用：{type(exc).__name__}") from exc
    array = cv2.imdecode(np.frombuffer(bytes(png or b""), np.uint8), cv2.IMREAD_COLOR)
    if array is None:
        raise OcrUnavailable("截图无法解码")
    try:
        result = engine(array)
    except Exception as exc:  # noqa: BLE001
        raise OcrUnavailable(f"识别失败：{type(exc).__name__}") from exc
    return reading_text(_blocks(result))
