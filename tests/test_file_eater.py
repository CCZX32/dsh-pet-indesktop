# -*- coding: utf-8 -*-
"""“吃垃圾文件”拖放模拟功能测试：只记录，绝不真删/移动文件。"""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QWidget

from pet.file_eater import FileEaterDropHandler, format_bytes
from pet.window_optional_services import WindowFeatureGateMixin


class _FakePet(QWidget):
    def __init__(self, config_dir):
        super().__init__()
        self.cfg_dir = config_dir
        self.acts = ["待机", "吃Token", "吃西瓜"]
        self.anim_requests = []
        self.bubbles = []

    @property
    def cfg(self):
        class _Cfg:
            pass

        obj = _Cfg()
        obj.dir = self.cfg_dir
        return obj

    def request_link_anim(self, name):
        self.anim_requests.append(name)

    def show_bubble(self, text, duration_ms=3200, subtitle=None):
        self.bubbles.append((text, subtitle))


def _qapp():
    return QApplication.instance() or QApplication([])


def _make_pet(tmp_path):
    _qapp()
    return _FakePet(tmp_path)


class _FakePetWindow(QWidget, WindowFeatureGateMixin):
    def __init__(self, config_dir):
        super().__init__()
        self.acts = ["待机", "吃Token"]
        self.cfg = type("Cfg", (), {"dir": config_dir})()


def test_install_file_eater_is_idempotent_and_accepts_drops(tmp_path):
    _qapp()
    pet = _FakePetWindow(tmp_path)
    assert pet._file_eater is None

    first = pet.install_file_eater()
    assert pet.acceptDrops() is True
    assert first is pet._file_eater
    assert pet.install_file_eater() is first


def test_eat_paths_records_stats_plays_eat_animation_and_keeps_files(tmp_path):
    pet = _make_pet(tmp_path)
    first = tmp_path / "junk-a.log"
    first.write_text("0123456789", encoding="utf-8")
    second = tmp_path / "junk-b.bin"
    second.write_text("x" * 2048, encoding="utf-8")
    folder = tmp_path / "junk-dir"
    folder.mkdir()
    inner = folder / "inner.tmp"
    inner.write_text("y" * 512, encoding="utf-8")

    handler = FileEaterDropHandler(pet)
    result = handler.eat_paths([str(first), str(second), str(folder)])

    # 文件只是“被吃”，真实内容不能动。
    assert first.read_text(encoding="utf-8") == "0123456789"
    assert second.stat().st_size == 2048
    assert inner.read_text(encoding="utf-8") == "y" * 512

    # 动画优先选更贴近“吃数字垃圾”的吃Token。
    assert pet.anim_requests == ["吃Token"]
    assert len(pet.bubbles) == 1
    assert "文件没有删除或移动" in pet.bubbles[0][1]

    stats_path = tmp_path / "file_eaten_stats.json"
    assert stats_path.is_file()
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert stats["feed_count"] == 1
    assert stats["file_count"] == 2
    assert stats["folder_count"] == 1
    assert stats["item_count"] == 3
    assert stats["total_bytes"] == 10 + 2048 + 512

    # 再吃一个文件，累计统计继续增加。
    third = tmp_path / "junk-c.tmp"
    third.write_text("z" * 100, encoding="utf-8")
    handler.eat_paths([str(third)])
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert stats["feed_count"] == 2
    assert stats["file_count"] == 3
    assert stats["total_bytes"] == 10 + 2048 + 512 + 100
    assert result["stats"]["total_bytes"] == 10 + 2048 + 512


def test_drag_and_drop_events_are_accepted_and_fed(tmp_path):
    pet = _make_pet(tmp_path)
    target = tmp_path / "drop.txt"
    target.write_text("drop", encoding="utf-8")

    handler = FileEaterDropHandler(pet)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(target))])

    drag = QDragEnterEvent(
        QPoint(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert handler.eventFilter(pet, drag) is True
    assert drag.isAccepted()

    pet.anim_requests.clear()
    drop = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert handler.eventFilter(pet, drop) is True
    assert drop.isAccepted()
    assert pet.anim_requests == ["吃Token"]
    assert (tmp_path / "file_eaten_stats.json").is_file()


def test_format_bytes_has_human_readable_units():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1023) == "1023 B"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(3 * 1024 * 1024) == "3.0 MB"
    assert format_bytes(4 * 1024 * 1024 * 1024) == "4.0 GB"


def test_petinstance_build_window_wires_file_eater(tmp_path, monkeypatch):
    """回归：PR73 在 _build_window 里接线 install_file_eater()，#76 重构时被
    丢掉——真实建窗路径必须把文件投喂 handler 挂到每只桌宠上。

    用记录替身窗锁定 app 层 seam（install_file_eater 幂等/acceptDrops 的
    mixin 行为由 test_install_file_eater_is_idempotent_and_accepts_drops
    单独覆盖）。
    """
    import pet.app as app_mod
    from pet.app import AppShell
    from pet.config import Config
    from tests.test_predictive_prewarm import FakeLibrary

    app = _qapp()

    class _SpyWindow:
        def __init__(self, *args, **kwargs):
            self.file_eater_install_calls = 0
            self.file_interpret_install_calls = 0

        def install_file_eater(self):
            self.file_eater_install_calls += 1

        def install_file_interpreter(self):
            self.file_interpret_install_calls += 1

        def show(self):
            pass

    real_petwindow = app_mod.PetWindow
    monkeypatch.setattr(app_mod, "PetWindow", _SpyWindow)
    try:
        cfg = Config(tmp_path)
        cfg.set("todo_reminder_enabled", False)
        cfg.set("collision_enabled", False)
        cfg.set("click_sound_enabled", False)
        cfg.set("collision_sound_enabled", False)
        shell = AppShell(app, cfg, enable_chat=False)
        spy = shell.instance._build_window("shenshen", lib=FakeLibrary(), build_tray=False)
        assert spy.file_eater_install_calls == 1, "建窗路径必须调用 install_file_eater()（PR73 接线，#76 后丢失）"
        assert spy.file_interpret_install_calls == 1, "建窗路径必须调用 install_file_interpreter()（拖文件解读接线）"
    finally:
        monkeypatch.setattr(app_mod, "PetWindow", real_petwindow)


def test_eat_paths_forwards_interpret_offer(tmp_path):
    """接缝：吃完后把拖入路径原样转发给注入的解读入口（getattr 防御，未注入不炸）。"""
    _qapp()
    pet = _make_pet(tmp_path)
    handler = FileEaterDropHandler(pet)
    note = tmp_path / "note.md"
    note.write_text("内容", encoding="utf-8")

    # 未注入解读入口：正常吃完不炸
    handler.eat_paths([str(note)])

    offers = []
    handler.interpret_offer = lambda paths: offers.append(list(paths))
    handler.eat_paths([str(note)])

    assert offers == [[str(note)]]


# ---------------------------------------------------------------- B03：扫描预算
def _big_dir(tmp_path, name, count):
    folder = tmp_path / name
    folder.mkdir()
    for i in range(count):
        (folder / f"f{i:05d}.bin").write_text("x" * 10, encoding="utf-8")
    return folder


def test_small_drop_reports_no_truncation(tmp_path):
    """小目录/散文件不触预算：旧口径（文件数/文件夹数/字节数）一个不少。"""
    pet = _make_pet(tmp_path)
    folder = tmp_path / "small-dir"
    folder.mkdir()
    (folder / "inner.bin").write_text("x" * 7, encoding="utf-8")
    loose = tmp_path / "loose.bin"
    loose.write_text("y" * 3, encoding="utf-8")

    result = FileEaterDropHandler(pet).eat_paths([str(folder), str(loose)])

    assert result["files"] == 1
    assert result["folders"] == 1
    assert result["bytes"] == 10
    assert result["truncated"] is False
    assert result["scanned"] == 2
    assert "只统计了前" not in pet.bubbles[0][0]


def test_eat_paths_stops_at_file_budget(tmp_path, monkeypatch):
    """B03：文件数预算——触上限即停扫，统计/气泡用真实口径（不是全量数）。"""
    import pet.file_eater as file_eater

    monkeypatch.setattr(file_eater, "SCAN_FILE_LIMIT", 3)
    pet = _make_pet(tmp_path)
    folder = _big_dir(tmp_path, "big-dir", 6)

    result = FileEaterDropHandler(pet).eat_paths([str(folder)])

    assert result["truncated"] is True
    assert result["scanned"] == 3, "计数停在预算内"
    assert result["folders"] == 1
    assert result["bytes"] == 30, "只累计已统计的 3 个文件（每个 10 字节）"
    assert "只统计了前 3 项" in pet.bubbles[0][0], "气泡如实提示截断"
    stats = json.loads((tmp_path / "file_eaten_stats.json").read_text(encoding="utf-8"))
    assert stats["total_bytes"] == 30


def test_eat_paths_stops_at_time_budget(tmp_path, monkeypatch):
    """B03：耗时预算（mock monotonic）——每 512 个文件查一次钟，越预算即停扫。"""
    import pet.file_eater as file_eater

    folder = _big_dir(tmp_path, "slow-dir", 520)
    calls = {"n": 0}

    def slow_clock():
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 1e6  # 建预算时正常，之后时间已越过预算

    monkeypatch.setattr(file_eater, "_SCAN_CLOCK", slow_clock)
    pet = _make_pet(tmp_path)

    result = FileEaterDropHandler(pet).eat_paths([str(folder)])

    assert result["truncated"] is True
    assert result["scanned"] == 512, "512 个文件一次耗时检查，检查即停"
    assert result["bytes"] == 512 * 10
    assert "只统计了前 512 项" in pet.bubbles[0][0]


def test_eat_paths_budget_covers_dropped_file_list(tmp_path, monkeypatch):
    """预算按整批记账：拖进来的一串散文件同样在预算内截断。"""
    import pet.file_eater as file_eater

    monkeypatch.setattr(file_eater, "SCAN_FILE_LIMIT", 2)
    pet = _make_pet(tmp_path)
    paths = []
    for i in range(4):
        p = tmp_path / f"loose{i}.bin"
        p.write_text("x" * 5, encoding="utf-8")
        paths.append(str(p))

    result = FileEaterDropHandler(pet).eat_paths(paths)

    assert (result["files"], result["bytes"]) == (2, 10)
    assert result["truncated"] is True
    assert result["scanned"] == 2
