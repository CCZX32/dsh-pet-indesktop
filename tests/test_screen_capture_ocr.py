# -*- coding: utf-8 -*-
"""「快速识屏」本地 OCR 引擎契约（offscreen 可跑）。

这一层要钉死三件事：

1. **识别**：程序画出来的已知文字能被读回来，且返回的块序就是阅读顺序
   （从上到下、行内从左到右），每块带置信度与框坐标。
2. **错误**：模型缺失 / 依赖缺失 / 加载失败 / 识别失败四种故障各自翻译成
   一句人话，且**不在下一次调用时反复重试**（坏掉的东西不会自己好，
   重试只是把等待时间再收一遍）。
3. **并发**：多个线程同时调 ``recognize`` 时模型只加载一次，且推理不重叠
   ——``rapidocr`` 的流水线在实例上存了可变状态（每帧重写 ``preprocess_op``
   与 ``update_params``），并行跑它是错误用法，不是"更快"。

字体说明（真机实测）：``QT_QPA_PLATFORM=offscreen`` 下 Qt 的字体库**是空的**
（Windows 上 ``QFontDatabase.families()`` 返回 0 个家族），直接画字只会得到
一串豆腐块。所以测试图必须先用 ``addApplicationFont`` 显式注册一个真实字体
文件；注册不到就跳过（那是环境缺字体，不是被测代码的问题）。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet.screen_capture import ocr  # noqa: E402
from pet.screen_capture.ocr import (  # noqa: E402
    OcrEngine,
    OcrLoadError,
    OcrModelMissingError,
    OcrRecognitionError,
    OcrUnavailableError,
    TextBlock,
    reading_order,
)

#: 拉丁字体候选（三端常见路径）。取第一个能注册成功的。
_LATIN_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)

#: 中文字体候选。CI 的 Linux runner 装了 fonts-noto-cjk，Windows 有微软雅黑。
_CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
)

_LATIN_LINES = ("hello world 12345", "quick brown fox", "deepseek pet 2026")


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _register_font(candidates) -> str | None:
    """注册第一个存在的字体文件，返回家族名；一个都没有返回 None。"""
    for path in candidates:
        if not Path(path).is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return None


@pytest.fixture(scope="module")
def latin_family():
    family = _register_font(_LATIN_FONT_CANDIDATES)
    if family is None:
        pytest.skip("本机没有可注册的拉丁字体文件，画不出测试图")
    return family


@pytest.fixture(scope="module")
def cjk_family():
    family = _register_font(_CJK_FONT_CANDIDATES)
    if family is None:
        pytest.skip("本机没有可注册的中文字体文件，画不出中文测试图")
    return family


def _screenshot(family: str | None, lines=_LATIN_LINES, *, width=800, height=400,
                pixel_size=30) -> QImage:
    """按像素画一张"像截图"的白底黑字图（行距固定，方便断言阅读顺序）。"""
    image = QImage(width, height, QImage.Format.Format_RGB888)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setPen(QColor(0, 0, 0))
    font = QFont(family) if family else QFont()
    font.setPixelSize(pixel_size)
    painter.setFont(font)
    for index, line in enumerate(lines):
        painter.drawText(30, 60 + index * 80, line)
    painter.end()
    return image


def _blank(width=64, height=32) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB888)
    image.fill(QColor(255, 255, 255))
    return image


class _FakeOutput:
    """``RapidOCROutput`` 的最小形状替身（引擎契约只依赖这三个字段）。

    刻意用**纯列表**而不是 numpy 数组：这样只装 PySide6 的环境也能跑完
    这一整族契约测试，不必为了造一个假输出把重型依赖拖进来。
    """

    def __init__(self, *lines) -> None:
        self.txts = tuple(line[0] for line in lines)
        self.scores = tuple(line[1] for line in lines)
        self.boxes = [list(line[2]) for line in lines]


class _FakeEngine:
    """假引擎：记录调用次数与"同时在跑"的最大值，用来验证串行化。"""

    def __init__(self, text="ok", delay=0.05) -> None:
        self.text = text
        self.delay = delay
        self.calls = 0
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()

    def __call__(self, _image):
        with self._lock:
            self.calls += 1
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(self.delay)
        with self._lock:
            self._active -= 1
        return _FakeOutput((self.text, 0.99, _box(10, 5, 60, 30)))


class _ScrambledEngine:
    """故意把块**乱序**返回（含同行内右块比左块高的情况），用来验证拼接顺序。"""

    def __call__(self, _image):
        return _FakeOutput(
            ("第二行", 0.9, _box(10, 60, 60, 30)),
            ("右", 0.9, _box(120, 10, 60, 30)),
            ("左", 0.9, _box(10, 14, 60, 30)),
        )


def _factory(engine, calls: list | None = None, *, delay=0.0):
    def _build(model_dir, cpu_threads):
        if calls is not None:
            calls.append((model_dir, cpu_threads))
        if delay:
            time.sleep(delay)
        return engine

    return _build


def _box(left: float, top: float, width: float, height: float):
    return ((left, top), (left + width, top), (left + width, top + height), (left, top + height))


# ------------------------------------------------------------------ 模型路径


def test_bundled_model_dir_points_at_repo_resources():
    directory = ocr.bundled_model_dir()

    assert directory.name == "rapidocr_models"
    assert directory.parent.name == "resources"


def test_bundled_model_dir_honours_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(ocr.OCR_MODEL_DIR_ENV, str(tmp_path))

    assert ocr.bundled_model_dir() == tmp_path


def test_model_problem_names_the_missing_file(tmp_path):
    problem = ocr.model_problem(tmp_path)

    assert problem, "空目录必须判定为模型缺失"
    assert str(tmp_path) in problem, "人话原因里要带上找过的路径，用户才知道去哪补"


def test_model_problem_is_empty_when_all_files_present(tmp_path):
    for name in ocr.MODEL_FILES.values():
        (tmp_path / name).write_bytes(b"")

    assert ocr.model_problem(tmp_path) == ""


def test_resolve_model_dir_finds_a_usable_directory():
    directory = ocr.resolve_model_dir()

    assert ocr.model_problem(directory) == "", (
        f"既没找到随包模型（{ocr.bundled_model_dir()}）也没找到已装 wheel 自带的模型"
    )


def test_resolve_model_dir_prefers_an_explicit_directory(tmp_path):
    assert ocr.resolve_model_dir(tmp_path) == tmp_path


# -------------------------------------------------------------- 像素 → 数组


def test_to_bgr_array_strips_row_padding():
    """宽度不是 4 的倍数时 QImage 每行有对齐填充，不剥掉整张图会错位。"""
    image = QImage(13, 3, QImage.Format.Format_RGB888)
    image.fill(QColor(0, 0, 0))
    image.setPixelColor(0, 0, QColor(255, 0, 0))
    if image.bytesPerLine() == image.width() * 3:
        pytest.skip("本平台的 QImage 不按 4 字节对齐，构造不出带填充的行")

    array = ocr.to_bgr_array(image)

    assert array.shape == (3, 13, 3), "行填充没被剥掉"
    assert tuple(int(v) for v in array[0, 0]) == (0, 0, 255), "通道顺序必须是 BGR"
    assert tuple(int(v) for v in array[1, 12]) == (0, 0, 0)


def test_to_bgr_array_accepts_non_rgb888_input():
    """上游给的是 RGB888，但 recognize 不该因为别人给了 RGB32 就炸。"""
    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(QColor(10, 20, 30))

    array = ocr.to_bgr_array(image)

    assert array.shape == (4, 8, 3)
    assert tuple(int(v) for v in array[0, 0]) == (30, 20, 10)


# ---------------------------------------------------------------- 阅读顺序


def test_reading_order_sorts_lines_top_to_bottom_and_left_to_right():
    """同行的两块上沿差 2 px、不同行差 90 px——纯按上沿排会把同行两块排反。"""
    blocks = [
        TextBlock("右下", 0.9, _box(300, 100, 60, 30)),
        TextBlock("左上", 0.9, _box(10, 12, 60, 30)),
        TextBlock("左下", 0.9, _box(10, 100, 60, 30)),
        TextBlock("右上", 0.9, _box(300, 10, 60, 30)),
    ]

    assert [b.text for b in reading_order(blocks)] == ["左上", "右上", "左下", "右下"]


def test_reading_order_keeps_baseline_shifted_boxes_on_one_line():
    """同一行里右边那块比左边高 4 px（字号/基线不同），不能因此把顺序颠倒。"""
    blocks = [
        TextBlock("右", 0.9, _box(120, 10, 60, 30)),
        TextBlock("左", 0.9, _box(10, 14, 60, 30)),
        TextBlock("下一行", 0.9, _box(10, 60, 60, 30)),
    ]

    assert [b.text for b in reading_order(blocks)] == ["左", "右", "下一行"]


def test_reading_order_accepts_empty_input():
    assert reading_order([]) == []


def test_text_block_bounds_and_center():
    block = TextBlock("x", 0.5, _box(10, 20, 30, 40))

    assert block.bounds == (10.0, 20.0, 30.0, 40.0)
    assert block.center == (25.0, 40.0)


# ------------------------------------------------------------------ 懒加载


def test_engine_loads_only_on_first_use():
    calls: list = []
    engine = OcrEngine(engine_factory=_factory(_FakeEngine(), calls))

    assert engine.loaded is False
    assert calls == [], "构造 OcrEngine 不该加载模型"

    engine.recognize(_blank())

    assert engine.loaded is True
    assert len(calls) == 1


def test_preload_loads_without_recognizing():
    calls: list = []
    engine = OcrEngine(engine_factory=_factory(_FakeEngine(), calls))

    engine.preload()

    assert engine.loaded is True
    assert len(calls) == 1


def test_preload_is_idempotent():
    calls: list = []
    engine = OcrEngine(engine_factory=_factory(_FakeEngine(), calls))

    engine.preload()
    engine.preload()
    engine.recognize(_blank())

    assert len(calls) == 1


def test_shared_engine_is_a_single_instance():
    assert ocr.shared_engine() is ocr.shared_engine()


def test_module_level_recognize_joins_blocks_in_reading_order(monkeypatch):
    """切片 3 的 seam 契约：``ocr.recognize(QImage) -> str``（同步、纯本地、不联网）。"""
    engine = OcrEngine(engine_factory=_factory(_ScrambledEngine()))
    monkeypatch.setattr(ocr, "shared_engine", lambda: engine)

    assert ocr.recognize(_blank()) == "左\n右\n第二行"


def test_module_level_recognize_returns_empty_string_for_a_blank_image(real_engine, monkeypatch):
    monkeypatch.setattr(ocr, "shared_engine", lambda: real_engine)

    assert ocr.recognize(_blank(800, 400)) == ""


def test_engine_passes_cpu_thread_budget_to_the_loader():
    calls: list = []
    engine = OcrEngine(cpu_threads=1, engine_factory=_factory(_FakeEngine(), calls))

    engine.preload()

    assert calls[0][1] == 1, "CPU 线程预算必须传给加载器（设计约束：1~2 线程）"


def test_cpu_threads_is_clamped_to_the_design_budget():
    assert 1 <= OcrEngine(cpu_threads=99).cpu_threads <= 2
    assert OcrEngine(cpu_threads=0).cpu_threads == 1
    assert OcrEngine(cpu_threads=-4).cpu_threads == 1


# -------------------------------------------------------------------- 并发


def test_concurrent_recognize_loads_once_and_serializes_inference():
    calls: list = []
    fake = _FakeEngine(text="并发安全", delay=0.05)
    engine = OcrEngine(engine_factory=_factory(fake, calls, delay=0.05))

    results: list = [None] * 8
    barrier = threading.Barrier(8)

    def worker(index: int) -> None:
        barrier.wait(timeout=30)
        results[index] = engine.recognize(_blank())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not any(thread.is_alive() for thread in threads), "并发 recognize 卡死了"
    assert len(calls) == 1, f"模型只该加载一次，实际 {len(calls)} 次"
    assert all(len(r) == 1 and r[0].text == "并发安全" for r in results)
    assert fake.max_active == 1, "推理必须串行：rapidocr 流水线在实例上存了可变状态"


def test_concurrent_preload_and_recognize_share_one_load():
    calls: list = []
    fake = _FakeEngine(delay=0.02)
    engine = OcrEngine(engine_factory=_factory(fake, calls, delay=0.05))

    barrier = threading.Barrier(4)
    errors: list = []

    def preloader() -> None:
        barrier.wait(timeout=30)
        try:
            engine.preload()
        except Exception as exc:  # noqa: BLE001 - 测试要看清到底炸在哪
            errors.append(exc)

    def recognizer() -> None:
        barrier.wait(timeout=30)
        try:
            engine.recognize(_blank())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=preloader) for _ in range(2)]
    threads += [threading.Thread(target=recognizer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    assert len(calls) == 1


# -------------------------------------------------------------------- 错误


def test_missing_models_are_reported_in_plain_language(tmp_path):
    engine = OcrEngine(model_dir=tmp_path, engine_factory=ocr._load_rapidocr)

    with pytest.raises(OcrModelMissingError) as excinfo:
        engine.preload()

    message = str(excinfo.value)
    assert "模型" in message and str(tmp_path) in message


def test_partial_model_set_names_the_missing_file(tmp_path):
    present = list(ocr.MODEL_FILES.values())[0]
    (tmp_path / present).write_bytes(b"")
    engine = OcrEngine(model_dir=tmp_path)

    with pytest.raises(OcrModelMissingError) as excinfo:
        engine.preload()

    missing = [name for name in ocr.MODEL_FILES.values() if name != present]
    assert any(name in str(excinfo.value) for name in missing)


def test_empty_image_is_rejected_before_loading():
    calls: list = []
    engine = OcrEngine(engine_factory=_factory(_FakeEngine(), calls))

    with pytest.raises(ValueError):
        engine.recognize(QImage())

    assert calls == [], "空图不该触发一次几秒钟的模型加载"


def test_loader_crash_becomes_load_error():
    def boom(_model_dir, _cpu_threads):
        raise RuntimeError("onnxruntime 初始化崩了")

    engine = OcrEngine(engine_factory=boom)

    with pytest.raises(OcrLoadError) as excinfo:
        engine.recognize(_blank())

    message = str(excinfo.value)
    assert "加载" in message
    assert "onnxruntime 初始化崩了" in message, "原始错误必须带出来，否则没人能定位"


def test_missing_dependency_is_reported_as_unavailable(monkeypatch, tmp_path):
    for name in ocr.MODEL_FILES.values():
        (tmp_path / name).write_bytes(b"")

    def boom():
        raise ImportError("No module named 'rapidocr'")

    monkeypatch.setattr(ocr, "_import_rapidocr", boom)
    engine = OcrEngine(model_dir=tmp_path)

    with pytest.raises(OcrUnavailableError) as excinfo:
        engine.preload()

    assert "rapidocr" in str(excinfo.value)


def test_inference_crash_becomes_recognition_error():
    class _Boom:
        def __call__(self, _image):
            raise RuntimeError("onnx 跑炸了")

    engine = OcrEngine(engine_factory=_factory(_Boom()))

    with pytest.raises(OcrRecognitionError) as excinfo:
        engine.recognize(_blank())

    message = str(excinfo.value)
    assert "识别" in message and "onnx 跑炸了" in message


def test_engine_returning_nothing_is_a_recognition_error_not_an_empty_result():
    """引擎不返结果 ≠ 图里没字——后者是"没有识别到文字"，前者必须报故障。"""
    class _Silent:
        def __call__(self, _image):
            return None

    engine = OcrEngine(engine_factory=_factory(_Silent()))

    with pytest.raises(OcrRecognitionError):
        engine.recognize(_blank())


def test_error_detail_is_never_empty():
    """冻结环境里 ImportError 系的 ``str(exc)`` 可能是空串（实测），
    人话不能因此变成"……加载失败（x.onnx）："这种以冒号结尾的空话。"""
    class _SilentFailure(Exception):
        def __str__(self):
            return ""

    def boom(_model_dir, _cpu_threads):
        raise _SilentFailure()

    engine = OcrEngine(engine_factory=boom)

    with pytest.raises(OcrLoadError) as excinfo:
        engine.recognize(_blank())

    message = str(excinfo.value)
    assert not message.rstrip().endswith("："), message
    assert "_SilentFailure" in message, message


def test_failed_load_is_not_retried_on_every_call():
    calls: list = []

    def boom(_model_dir, _cpu_threads):
        calls.append(1)
        raise RuntimeError("加载失败")

    engine = OcrEngine(engine_factory=boom)

    for _ in range(3):
        with pytest.raises(OcrLoadError):
            engine.recognize(_blank())

    assert len(calls) == 1, "已经失败的加载不该在每次调用时重跑一遍"


def test_loader_timeout_is_reported_as_load_error():
    def slow(_model_dir, _cpu_threads):
        time.sleep(5)
        return _FakeEngine()

    engine = OcrEngine(engine_factory=slow, load_timeout=0.2)

    started = time.monotonic()
    with pytest.raises(OcrLoadError) as excinfo:
        engine.preload()
    elapsed = time.monotonic() - started

    assert elapsed < 3, "超时必须真的生效，不能把调用方挂住"
    assert "超时" in str(excinfo.value)


def test_a_timed_out_wait_does_not_poison_the_engine():
    """等超时 ≠ 加载失败：后台线程稍后成功的话，后续调用要能拿到它。"""
    def slow(_model_dir, _cpu_threads):
        time.sleep(0.4)
        return _FakeEngine(text="迟到的引擎")

    engine = OcrEngine(engine_factory=slow, load_timeout=0.1)

    with pytest.raises(OcrLoadError):
        engine.preload()

    deadline = time.monotonic() + 10
    while not engine.loaded and time.monotonic() < deadline:
        time.sleep(0.02)
    assert engine.loaded, "后台加载线程没有在超时后继续跑完"

    blocks = engine.recognize(_blank())
    assert [block.text for block in blocks] == ["迟到的引擎"]


# ------------------------------------------------------ 用完就丢（unload）


def test_unload_releases_the_engine_and_the_next_use_reloads():
    """「用完就丢」的核心契约：释放是真的（loaded → False），且**下次还能用**。"""
    calls: list = []
    engine = OcrEngine(engine_factory=_factory(_FakeEngine(text="第一次"), calls))

    assert [b.text for b in engine.recognize(_blank())] == ["第一次"]
    assert engine.loaded is True
    assert len(calls) == 1

    assert engine.unload() is True

    assert engine.loaded is False
    assert engine._engine is None, "引擎对象必须真的被丢掉，而不是只把标志位翻面"

    assert [b.text for b in engine.recognize(_blank())] == ["第一次"]
    assert len(calls) == 2, "释放之后再次触发必须重新加载，不能变成一次性的"


def test_unload_is_idempotent_when_nothing_is_loaded():
    calls: list = []
    engine = OcrEngine(engine_factory=_factory(_FakeEngine(), calls))

    assert engine.unload() is False, "没加载过就没有东西可丢"
    assert engine.unload() is False
    assert calls == [], "释放不该顺手把模型加载起来"


def test_unload_does_not_resurrect_a_failed_load():
    """失败只试一次是设计约束：一次 unload 不能把它变成「每次点击重试一遍」。"""
    calls: list = []

    def boom(_model_dir, _cpu_threads):
        calls.append(1)
        raise RuntimeError("加载失败")

    engine = OcrEngine(engine_factory=boom)

    with pytest.raises(OcrLoadError):
        engine.recognize(_blank())

    assert engine.unload() is False
    with pytest.raises(OcrLoadError):
        engine.recognize(_blank())

    assert len(calls) == 1


def test_unload_discards_a_load_that_is_still_in_flight():
    """在途加载被释放后必须作废：结果不许写回（否则「已释放」会退回成「有引擎」）。"""
    gate = threading.Event()
    calls: list = []

    def gated(_model_dir, _cpu_threads):
        calls.append(1)
        assert gate.wait(30), "加载闸门没有被放行"
        return _FakeEngine(text="迟到的引擎")

    engine = OcrEngine(engine_factory=gated, load_timeout=0.05)
    with pytest.raises(OcrLoadError):
        engine.preload()
    stale = engine._loader
    assert stale is not None and stale.is_alive(), "这一步的前提是加载线程还在跑"

    assert engine.unload() is True, "在途加载也算「有东西可丢」"

    gate.set()
    stale.join(timeout=30)
    assert not stale.is_alive()

    assert engine.loaded is False, "作废的加载结果不许写回状态"
    assert engine._engine is None


def test_unload_never_cuts_an_inference_that_is_already_running():
    """卸载不许把正在跑的一次识别掐断（那条线程手里的引擎是它自己的强引用）。"""
    engine = OcrEngine(engine_factory=_factory(_FakeEngine(text="在跑", delay=0.3)))
    results: list = []
    errors: list = []

    def worker() -> None:
        try:
            results.append([b.text for b in engine.recognize(_blank())])
        except Exception as exc:  # noqa: BLE001 - 测试要看清到底炸在哪
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 10
    while engine._engine is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine._engine is not None, "识别线程没能在预算内把模型加载起来"

    engine.unload()          # 识别还在跑（假引擎睡 0.3 s）

    thread.join(timeout=30)
    assert not thread.is_alive()
    assert errors == []
    assert results == [["在跑"]], "正在跑的识别必须跑完，不能被卸载掐掉"
    assert engine.loaded is False


def test_release_engine_drops_the_shared_singleton(monkeypatch):
    """模块级释放：单例被摘掉、旧引擎确实释放、下一次 shared_engine() 是新的。"""
    calls: list = []
    first = OcrEngine(engine_factory=_factory(_FakeEngine(text="共享"), calls))
    monkeypatch.setattr(ocr, "_SHARED_ENGINE", first)
    assert ocr.shared_engine() is first
    first.preload()

    assert ocr.release_engine() is True

    assert first.loaded is False
    second = ocr.shared_engine()
    assert second is not first, "释放后必须拿到一份干净的引擎，不能复用半拆的那份"
    assert second.loaded is False, "新单例是懒加载的：没用到不该加载，也不该带上旧的那份"


def test_release_engine_drops_the_singleton_even_after_a_failed_load(monkeypatch):
    """模块级口径：失败**不**跨会话保留。

    与引擎级的 ``test_unload_does_not_resurrect_a_failed_load`` 不矛盾：同一个引擎
    对象里失败仍然只试一次，但会话收口时单例被摘掉，下一次拿到的是新引擎、会重新
    尝试——装坏了的依赖用户重装一次就好，程序不该在整个进程生命周期里都判它死刑。
    """
    calls: list = []

    def boom(_model_dir, _cpu_threads):
        calls.append(1)
        raise RuntimeError("模型坏了")

    engine = OcrEngine(engine_factory=boom)
    monkeypatch.setattr(ocr, "_SHARED_ENGINE", engine)

    for _ in range(2):
        with pytest.raises(OcrLoadError):
            ocr.recognize(_blank())
    assert len(calls) == 1, "同一个引擎对象里失败不许重试"

    assert ocr.release_engine() is False, "失败的对象没有引擎可还"

    fresh = ocr.shared_engine()
    assert fresh is not engine, "单例必须被摘掉，下一次换成新引擎"
    assert fresh.loaded is False
    fresh.unload()


def test_release_engine_is_a_cheap_noop_before_anything_is_loaded(monkeypatch):
    """每次截图收口都会调它：没加载过就必须是零成本（不加载、不建单例）。"""
    monkeypatch.setattr(ocr, "_SHARED_ENGINE", None)

    assert ocr.release_engine() is False
    assert ocr._SHARED_ENGINE is None


# --------------------------------------------------------- 真实引擎（端到端）


@pytest.fixture(scope="module")
def real_engine():
    pytest.importorskip("rapidocr", reason="未安装本地 OCR 依赖（rapidocr）")
    directory = ocr.resolve_model_dir()
    problem = ocr.model_problem(directory)
    assert not problem, (
        f"本地 OCR 模型不可用：{problem}\n"
        f"模型随包放在 {ocr.bundled_model_dir()}；"
        "重新取出的命令见 pet/screen_capture/ocr.py 的模块说明"
    )
    engine = OcrEngine()
    engine.preload()
    return engine


def test_real_engine_sessions_are_cpu_only(real_engine, latin_family):
    """首版禁 GPU：三个 session 的执行提供者里只能有 CPU。

    这条只能从真引擎上验：``SessionOptions`` 没有 getter，所以"线程数/关自旋"
    那两个旋钮只能靠构造时写死（见 ``ocr._new_session``），而**执行提供者**是
    session 自己报得出来的——把它钉住，将来有人顺手打开 use_cuda 会在这里红。
    """
    # 三个子模型是首次调用时才惰性建出来的，所以先真跑一帧（检测/分类/识别都要跑过）。
    real_engine.recognize(_screenshot(latin_family))

    for attribute in ("text_det", "text_cls", "text_rec"):
        ort_session = getattr(real_engine._engine, attribute).session.session
        assert ort_session.get_providers() == ["CPUExecutionProvider"], (
            f"{attribute} 挂上了非 CPU 的执行提供者：{ort_session.get_providers()}"
        )


def test_real_engine_reads_known_latin_lines_in_reading_order(real_engine, latin_family):
    image = _screenshot(latin_family)

    blocks = real_engine.recognize(image)

    joined = " ".join(block.text for block in blocks).lower()
    assert "12345" in joined, f"没读出行 1 的关键词，实际识别：{joined!r}"
    assert "fox" in joined, f"没读出行 2 的关键词，实际识别：{joined!r}"
    assert "2026" in joined, f"没读出行 3 的关键词，实际识别：{joined!r}"

    keywords = ("12345", "fox", "2026")
    positions = [next(i for i, b in enumerate(blocks) if key in b.text.lower()) for key in keywords]
    assert positions == sorted(positions), f"三行的块序不是自上而下：{[(b.text, b.bounds) for b in blocks]}"

    for block in blocks:
        left, top, width, height = block.bounds
        assert 0 < block.score <= 1.0
        assert left >= -1 and top >= -1
        assert left + width <= image.width() + 1
        assert top + height <= image.height() + 1


def test_real_engine_reads_chinese_lines(real_engine, cjk_family):
    image = _screenshot(cjk_family, ("本地离线识别", "快速识屏提取文字"))

    blocks = real_engine.recognize(image)

    joined = "".join(block.text for block in blocks)
    assert "离线" in joined, f"中文识别没对上，实际识别：{joined!r}"
    assert "文字" in joined, f"中文识别没对上，实际识别：{joined!r}"


def test_real_engine_returns_empty_list_for_blank_image(real_engine):
    assert real_engine.recognize(_blank(800, 400)) == []


def test_real_engine_load_never_touches_the_network(monkeypatch):
    """断网可用是硬要求：加载期任何 HTTP 请求都算违规（模型必须随包）。"""
    pytest.importorskip("rapidocr", reason="未安装本地 OCR 依赖（rapidocr）")
    import requests

    def _forbidden(*args, **kwargs):
        raise AssertionError(f"OCR 加载期发起了网络请求：{args[:1]}（模型没有随包？）")

    monkeypatch.setattr(requests, "get", _forbidden)
    monkeypatch.setattr(requests, "post", _forbidden)

    engine = OcrEngine()
    engine.preload()

    assert engine.loaded is True


def test_real_engine_can_be_released_and_loaded_again(real_engine):
    """真机口径：释放后重新加载能再认一次（"用完就丢"不是"丢了就没了"）。"""
    assert real_engine.loaded is True
    assert real_engine.unload() is True
    assert real_engine.loaded is False
    assert real_engine._engine is None

    assert real_engine.recognize(_blank(800, 400)) == []

    assert real_engine.loaded is True, "释放后必须能重新加载"
