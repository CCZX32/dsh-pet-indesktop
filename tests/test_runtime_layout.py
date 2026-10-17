# -*- coding: utf-8 -*-
"""显式便携模式的布局解析（portable.json）。

便携只认 exe 同目录的 ``portable.json`` 一个身份；标记存在但内容/路径/文件系统
不满足时**必须报错**，不许静默回退平台数据目录（那会把用户数据写回 %APPDATA%，
用户却以为自己在用便携包）。
"""

import json
import zipfile
from pathlib import Path

import pytest

from pet import runtime_layout


def _write_marker(root: Path, payload, *, name: str = "portable.json") -> Path:
    path = root / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _layout(root: Path):
    return runtime_layout.read_portable_layout(root)


def test_no_marker_means_installed_layout(tmp_path):
    assert _layout(tmp_path) is None


def test_valid_marker_resolves_relative_data_dir(tmp_path):
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})

    layout = _layout(tmp_path)

    assert layout is not None
    assert layout.data_dir == (tmp_path / "data").resolve()
    assert layout.data_dir.is_dir()


def test_nested_relative_data_dir_is_accepted(tmp_path):
    _write_marker(
        tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "user data/dsh-pet"}
    )

    layout = _layout(tmp_path)

    assert layout is not None
    assert layout.data_dir == (tmp_path / "user data" / "dsh-pet").resolve()


def test_existing_data_dir_is_reused_without_touching_contents(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    marker = data_dir / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})

    layout = _layout(tmp_path)

    assert layout is not None
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "data",
    ["", "   ", ".", "..", "../escape", "data/../../escape", "/absolute", "C:\\\\absolute"],
)
def test_unsafe_data_paths_are_rejected(tmp_path, data):
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": data})

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '"data"',
        {"data": "data"},
        {"schema": "dsh-pet-portable/v0", "data": "data"},
        {"schema": runtime_layout.PORTABLE_SCHEMA},
        {"schema": runtime_layout.PORTABLE_SCHEMA, "data": 3},
    ],
)
def test_invalid_marker_payload_is_rejected(tmp_path, payload):
    _write_marker(tmp_path, payload)

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_marker_directory_is_rejected_instead_of_ignored(tmp_path):
    (tmp_path / "portable.json").mkdir()

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_data_dir_that_is_a_file_is_rejected(tmp_path):
    (tmp_path / "data").write_text("not a directory", encoding="utf-8")
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_reparse_point_marker_is_rejected(tmp_path, monkeypatch):
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})
    monkeypatch.setattr(
        runtime_layout,
        "_is_reparse_point",
        lambda path: Path(path).name == runtime_layout.PORTABLE_MARKER,
    )

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_reparse_point_data_dir_is_rejected(tmp_path, monkeypatch):
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})
    monkeypatch.setattr(
        runtime_layout, "_is_reparse_point", lambda path: Path(path).name == "data"
    )

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_non_ntfs_volume_is_rejected_on_windows(tmp_path, monkeypatch):
    if __import__("sys").platform != "win32":
        pytest.skip("NTFS gate is Windows-only")
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})
    monkeypatch.setattr(runtime_layout, "_filesystem_name", lambda path: "exFAT")

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_unreadable_volume_information_is_rejected_on_windows(tmp_path, monkeypatch):
    """查不到卷信息也必须拒绝，不能当成"大概是 NTFS"放行。"""
    if __import__("sys").platform != "win32":
        pytest.skip("NTFS gate is Windows-only")
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})
    monkeypatch.setattr(runtime_layout, "_filesystem_name", lambda path: "")

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_unwritable_data_dir_is_rejected(tmp_path, monkeypatch):
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})

    def _deny(*args, **kwargs):
        raise OSError(13, "denied")

    monkeypatch.setattr(runtime_layout.tempfile, "mkstemp", _deny)

    with pytest.raises(runtime_layout.PortableLayoutError):
        _layout(tmp_path)


def test_app_data_dir_uses_portable_dir_directly(tmp_path, monkeypatch):
    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})
    monkeypatch.setattr(runtime_layout, "executable_dir", lambda: tmp_path)
    runtime_layout.reset_layout_cache()
    try:
        assert runtime_layout.app_data_dir(tmp_path / "os-base") == (tmp_path / "data").resolve()
    finally:
        runtime_layout.reset_layout_cache()


def test_app_data_dir_keeps_platform_layout_without_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_layout, "executable_dir", lambda: tmp_path)
    runtime_layout.reset_layout_cache()
    try:
        from pet.config import APP_DIR_NAME

        assert runtime_layout.app_data_dir(tmp_path) == tmp_path / APP_DIR_NAME
    finally:
        runtime_layout.reset_layout_cache()


def test_config_dir_follows_portable_root(tmp_path, monkeypatch):
    from pet.config import Config

    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})
    monkeypatch.setattr(runtime_layout, "executable_dir", lambda: tmp_path)
    runtime_layout.reset_layout_cache()
    try:
        config = Config()
        assert config.dir == (tmp_path / "data").resolve()
    finally:
        runtime_layout.reset_layout_cache()


def test_absence_of_marker_is_cached_too(tmp_path, monkeypatch):
    """安装态没有标记也必须缓存：否则每个热路径调用都付一次 exists()。

    负结果缓存是这里最容易回归的一处（`None` 不能同时表示"没算过"与"没有标记"）。
    """
    calls: list[int] = []

    def _exe_dir():
        calls.append(1)
        return tmp_path

    monkeypatch.setattr(runtime_layout, "executable_dir", _exe_dir)
    runtime_layout.reset_layout_cache()
    try:
        assert runtime_layout.portable_layout() is None
        assert runtime_layout.portable_layout() is None
    finally:
        runtime_layout.reset_layout_cache()
    assert len(calls) == 1


def test_settings_process_reads_the_portable_config(tmp_path, monkeypatch):
    from pet import overlay_settings_command as cmd

    _write_marker(tmp_path, {"schema": runtime_layout.PORTABLE_SCHEMA, "data": "data"})
    monkeypatch.setattr(runtime_layout, "executable_dir", lambda: tmp_path)
    runtime_layout.reset_layout_cache()
    try:
        assert cmd.topology_config_path() == (tmp_path / "data" / "config.json").resolve()
    finally:
        runtime_layout.reset_layout_cache()


def test_invalid_marker_fails_config_instead_of_falling_back(tmp_path, monkeypatch):
    from pet.config import Config

    _write_marker(tmp_path, {"schema": "dsh-pet-portable/v0", "data": "data"})
    monkeypatch.setattr(runtime_layout, "executable_dir", lambda: tmp_path)
    runtime_layout.reset_layout_cache()
    try:
        with pytest.raises(runtime_layout.PortableLayoutError):
            Config()
    finally:
        runtime_layout.reset_layout_cache()


def test_canonical_marker_text_is_accepted(tmp_path):
    marker_text = runtime_layout.canonical_marker_text()
    (tmp_path / runtime_layout.PORTABLE_MARKER).write_text(marker_text, encoding="utf-8")

    layout = _layout(tmp_path)
    assert layout is not None
    assert layout.data_dir == (tmp_path / "data").resolve()


def test_marker_script_appends_marker_to_portable_zip(tmp_path):
    import subprocess
    import sys

    zip_path = tmp_path / "portable.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("dsh-pet.exe", b"stub")
    script = Path(__file__).resolve().parents[1] / "scripts" / "write_portable_marker.py"

    result = subprocess.run(
        [sys.executable, str(script), "--zip", str(zip_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(zip_path) as archive:
        assert runtime_layout.PORTABLE_MARKER in archive.namelist()

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    with zipfile.ZipFile(zip_path) as archive:
        archive.extract(runtime_layout.PORTABLE_MARKER, app_dir)

    layout = _layout(app_dir)
    assert layout is not None
    assert layout.data_dir == (app_dir / "data").resolve()

    again = subprocess.run(
        [sys.executable, str(script), "--zip", str(zip_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert again.returncode == 0, again.stderr
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.namelist().count(runtime_layout.PORTABLE_MARKER) == 1
