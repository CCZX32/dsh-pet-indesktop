# -*- coding: utf-8 -*-
"""Personal Agent v0.5：受控写/编辑工具（工作区内原子写 + 备份 + 撤销）。

测试口径对齐 SPEC-v05-write.md：

- 默认关：``chat_agent_write_enabled`` 默认 False，运行环境不装配写工具；
- 路径围栏：realpath + 工作区内 + 设备名/保留名，``..`` 与目录链接逃逸拒绝；
- 原子写：替换前失败不得留下半截目标文件；
- 备份/撤销：``.feiyu-backup`` 下按 UTC 时间戳命名，撤销本身也备份当前状态；
- 审计：content / new_text 只留长度，写结果与错误都过不可信标记。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from pet.chat import agent_write
from pet.chat.agent_tools import (
    UNTRUSTED_END,
    UNTRUSTED_HEAD,
    AgentAuditLog,
    agent_registry,
    build_agent_runtime,
    build_registry,
)
from pet.config import Config

WRITE_TOOL_NAMES = {"fs_write", "fs_edit", "fs_undo"}


def _config(tmp_path, *, enabled=True, root=None) -> Config:
    cfg = Config(base=tmp_path / "cfg")
    cfg.set("chat_agent_tools", True)
    cfg.set("chat_agent_write_enabled", enabled)
    if root is not None:
        cfg.set("chat_agent_write_root", str(root))
    return cfg


def _runtime(tmp_path, *, enabled=True, root=None):
    runtime = build_agent_runtime(_config(tmp_path, enabled=enabled, root=root), "")
    assert runtime is not None
    return runtime


def _registry(tmp_path, *, enabled=True, root=None, audit=None):
    runtime = _runtime(tmp_path, enabled=enabled, root=root)
    return agent_registry(runtime, audit=audit)


def _make_dir_link(link: Path, target: Path) -> None:
    """优先 symlink；Windows 无权限时退回 junction（mklink /J 不需要管理员）。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        pytest.skip("当前环境不允许创建目录链接")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"无法创建 junction：{result.stdout}{result.stderr}")


def _remove_dir_link(link: Path) -> None:
    try:
        link.unlink()
    except OSError:
        try:
            link.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------- 配置 / 装配

def test_write_tools_default_off_and_default_workspace(tmp_path):
    cfg = Config(base=tmp_path / "cfg")

    assert cfg.get("chat_agent_write_enabled") is False
    root = Path(cfg.get("chat_agent_write_root"))
    assert root.is_absolute()
    assert root.name == "肥鱼工作区"


def test_dirty_string_false_does_not_enable_writes(tmp_path):
    cfg = Config(base=tmp_path / "dirty")
    cfg.set("chat_agent_write_enabled", "false")
    assert cfg.data["chat_agent_write_enabled"] is False
    cfg.set("chat_agent_write_enabled", "yes")
    assert cfg.data["chat_agent_write_enabled"] is True


def test_default_off_registers_no_write_tools(tmp_path):
    runtime = _runtime(tmp_path, enabled=False, root=tmp_path / "workspace")

    assert runtime.write_root is None
    names = set(agent_registry(runtime).names)
    assert not (WRITE_TOOL_NAMES & names), f"默认关却挂了写工具：{names}"


def test_enabled_registers_three_write_tools(tmp_path):
    root = tmp_path / "workspace"
    cfg = _config(tmp_path, enabled=True, root=root)

    runtime = build_agent_runtime(cfg, "")
    assert runtime is not None
    assert runtime.write_root == Path(os.path.realpath(str(root)))

    registry = agent_registry(runtime)
    assert WRITE_TOOL_NAMES <= set(registry.names)

    # build_registry（聊天 worker 的实际装配点）同样要带上写工具
    cfg.agent = runtime
    assert WRITE_TOOL_NAMES <= set(build_registry(cfg).names)


def test_tool_descriptions_state_workspace_only_and_tell_user(tmp_path):
    registry = _registry(tmp_path, root=tmp_path / "workspace")
    specs = {tool.name: tool for tool in registry.tools}

    write_desc = specs["fs_write"].description
    assert "只能写工作区目录" in write_desc
    assert "写之前不用问" in write_desc
    assert "告诉用户你写了什么" in write_desc
    for name in WRITE_TOOL_NAMES:
        assert "工作区" in specs[name].description


# ---------------------------------------------------------------- fs_write

def test_fs_write_creates_parent_dirs_and_reports_bytes(tmp_path):
    root = tmp_path / "workspace"
    target = root / "notes" / "hello.txt"
    registry = _registry(tmp_path, root=root)

    outcome = registry.run("fs_write", {"path": "notes/hello.txt", "content": "你好"})

    assert outcome.ok, outcome.text
    assert target.read_text(encoding="utf-8") == "你好"
    assert "已写入" in outcome.text
    assert "6" in outcome.text  # UTF-8: 你好 = 6 字节
    assert ".feiyu-backup" not in outcome.text


def test_fs_write_backup_naming_and_undo_round_trip(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old", encoding="utf-8")
    registry = _registry(tmp_path, root=root)

    outcome = registry.run("fs_write", {"path": "note.txt", "content": "new"})
    assert outcome.ok, outcome.text

    backups = list((root / ".feiyu-backup").rglob("note.txt.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old"
    assert re.fullmatch(r"note\.txt\.\d{8}T\d{12}Z\.bak", backups[0].name)
    assert str(backups[0]) in outcome.text

    undo = registry.run("fs_undo", {"path": "note.txt"})
    assert undo.ok, undo.text
    assert target.read_text(encoding="utf-8") == "old"
    assert "当前状态备份" in undo.text

    # 撤销本身也备份当前状态：再撤销一次即可回到 new（可逆）
    redo = registry.run("fs_undo", {"path": "note.txt"})
    assert redo.ok, redo.text
    assert target.read_text(encoding="utf-8") == "new"


def test_fs_undo_without_backup_reports_code(tmp_path):
    registry = _registry(tmp_path, root=tmp_path / "workspace")

    outcome = registry.run("fs_undo", {"path": "missing.txt"})

    assert outcome.ok is False
    assert outcome.code == "fs_no_backup"


def test_fs_write_atomic_replace_failure_keeps_old_file(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "atomic.txt"
    target.write_text("old", encoding="utf-8")
    registry = _registry(tmp_path, root=root)

    real_replace = os.replace

    def fail_target_replace(src, dst):
        if Path(dst) == target:
            raise OSError("simulated crash before replace")
        return real_replace(src, dst)

    monkeypatch.setattr(agent_write.os, "replace", fail_target_replace)
    outcome = registry.run("fs_write", {"path": "atomic.txt", "content": "new"})

    assert outcome.ok is False
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(root.rglob("*.tmp")), "失败后不得留下临时文件"


@pytest.mark.parametrize("content,code", [
    pytest.param("a" * (agent_write.WRITE_MAX_BYTES + 1), "fs_write_too_large", id="oversize"),
    pytest.param("a\x00b", "fs_binary", id="binary"),
])
def test_fs_write_rejects_oversize_and_binary(tmp_path, content, code):
    registry = _registry(tmp_path, root=tmp_path / "workspace")

    outcome = registry.run("fs_write", {"path": "x.txt", "content": content})

    assert outcome.ok is False
    assert outcome.code == code


# ---------------------------------------------------------------- fs_edit

def test_fs_edit_unique_replacement_reports_line_and_context(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "text.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    registry = _registry(tmp_path, root=root)

    outcome = registry.run(
        "fs_edit", {"path": "text.txt", "old_text": "beta", "new_text": "BETA"}
    )

    assert outcome.ok, outcome.text
    assert target.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
    assert "第 2 行" in outcome.text
    assert "alpha" in outcome.text and "gamma" in outcome.text
    assert len(list((root / ".feiyu-backup").rglob("text.txt.*.bak"))) == 1


def test_fs_edit_zero_matches_hints_nearest_line(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "text.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    registry = _registry(tmp_path, root=root)

    outcome = registry.run(
        "fs_edit", {"path": "text.txt", "old_text": "delta", "new_text": "x"}
    )

    assert outcome.ok is False
    assert outcome.code == "fs_ambiguous_edit"
    assert "第 2 行" in outcome.text


def test_fs_edit_multiple_matches_requires_more_context(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "text.txt").write_text("x\nx\n", encoding="utf-8")
    registry = _registry(tmp_path, root=root)

    outcome = registry.run(
        "fs_edit", {"path": "text.txt", "old_text": "x", "new_text": "y"}
    )

    assert outcome.ok is False
    assert outcome.code == "fs_ambiguous_edit"
    assert "2" in outcome.text


def test_fs_edit_old_and_new_are_size_limited(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "text.txt").write_text("x", encoding="utf-8")
    registry = _registry(tmp_path, root=root)
    oversized = "a" * (agent_write.EDIT_TEXT_MAX_BYTES + 1)

    old_out = registry.run(
        "fs_edit", {"path": "text.txt", "old_text": oversized, "new_text": "y"}
    )
    new_out = registry.run(
        "fs_edit", {"path": "text.txt", "old_text": "x", "new_text": oversized}
    )

    assert old_out.code == "fs_write_too_large"
    assert new_out.code == "fs_write_too_large"


def test_fs_edit_counts_overlapping_matches_as_ambiguous(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "text.txt").write_text("aaa", encoding="utf-8")
    registry = _registry(tmp_path, root=root)

    outcome = registry.run(
        "fs_edit", {"path": "text.txt", "old_text": "aa", "new_text": "b"}
    )

    assert outcome.ok is False
    assert outcome.code == "fs_ambiguous_edit"


def test_fs_edit_rejects_nul_in_new_text(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "text.txt").write_text("x", encoding="utf-8")
    registry = _registry(tmp_path, root=root)

    outcome = registry.run(
        "fs_edit", {"path": "text.txt", "old_text": "x", "new_text": "a\x00b"}
    )

    assert outcome.ok is False
    assert outcome.code == "fs_binary"


# ---------------------------------------------------------------- 路径围栏

@pytest.mark.parametrize("path", ["../outside.txt", "sub/../../outside.txt"])
def test_fs_write_rejects_parent_escape(tmp_path, path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    registry = _registry(tmp_path, root=root)

    outcome = registry.run("fs_write", {"path": path, "content": "x"})

    assert outcome.ok is False
    assert outcome.code == "fs_outside_workspace"
    assert not outside.exists()


def test_fs_write_rejects_absolute_outside_path(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    registry = _registry(tmp_path, root=root)

    outcome = registry.run("fs_write", {"path": str(outside), "content": "x"})

    assert outcome.ok is False
    assert outcome.code == "fs_outside_workspace"
    assert not outside.exists()


@pytest.mark.parametrize("path", ["CON.txt", "sub/NUL"])
def test_fs_write_rejects_device_names_as_escape(tmp_path, path):
    registry = _registry(tmp_path, root=tmp_path / "workspace")

    outcome = registry.run("fs_write", {"path": path, "content": "x"})

    assert outcome.ok is False
    assert outcome.code == "fs_outside_workspace"


@pytest.mark.parametrize("path", ["bad. ", "bad."])
def test_fs_write_rejects_trailing_dot_or_space(tmp_path, path):
    registry = _registry(tmp_path, root=tmp_path / "workspace")

    outcome = registry.run("fs_write", {"path": path, "content": "x"})

    assert outcome.ok is False
    assert outcome.code == "fs_invalid_name"


def test_fs_write_rejects_directory_link_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "escape"
    _make_dir_link(link, outside)
    try:
        registry = _registry(tmp_path, root=root)
        outcome = registry.run("fs_write", {"path": "escape/pwn.txt", "content": "x"})
    finally:
        _remove_dir_link(link)

    assert outcome.ok is False
    assert outcome.code == "fs_outside_workspace"
    assert not (outside / "pwn.txt").exists()


def test_workspace_root_falls_back_for_system_directories_and_files(tmp_path):
    default = tmp_path / "default-workspace"
    fallback = Path(os.path.realpath(str(default)))
    windows_dir = os.environ.get("WINDIR")
    protected = Path(windows_dir) if windows_dir else Path(Path.home().anchor)

    assert agent_write.resolve_workspace_root(str(protected), default=default) == fallback
    assert agent_write.resolve_workspace_root("", default=default) == fallback

    not_a_dir = tmp_path / "a-file"
    not_a_dir.write_text("x", encoding="utf-8")
    assert agent_write.resolve_workspace_root(str(not_a_dir), default=default) == fallback

    roaming = os.environ.get("APPDATA")
    if roaming:
        assert agent_write.resolve_workspace_root(roaming, default=default) == fallback


# ---------------------------------------------------------------- 审计

def test_write_audit_stores_lengths_not_secret_body(tmp_path):
    root = tmp_path / "workspace"
    secret = "TOPSECRET-BODY"
    audit_path = tmp_path / "audit.jsonl"
    audit = AgentAuditLog(audit_path)
    registry = _registry(tmp_path, root=root, audit=audit)

    outcome = registry.run("fs_write", {"path": "secret.txt", "content": secret})

    assert outcome.ok, outcome.text
    assert outcome.text.startswith(UNTRUSTED_HEAD)
    assert UNTRUSTED_END in outcome.text
    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["tool"] == "fs_write"
    assert record["args"]["content_chars"] == len(secret)
    assert "content" not in record["args"]
    assert secret not in audit_path.read_text(encoding="utf-8")


def test_write_error_goes_through_audit_and_untrusted_wrapper(tmp_path):
    secret = "TOPSECRET-BODY"
    audit_path = tmp_path / "audit-error.jsonl"
    audit = AgentAuditLog(audit_path)
    registry = _registry(tmp_path, root=tmp_path / "workspace", audit=audit)

    outcome = registry.run("fs_write", {"path": "../escape.txt", "content": secret})

    assert outcome.ok is False
    assert outcome.code == "fs_outside_workspace"
    assert outcome.text.startswith(UNTRUSTED_HEAD)
    assert UNTRUSTED_END in outcome.text
    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["code"] == "fs_outside_workspace"
    assert record["args"]["content_chars"] == len(secret)
    assert secret not in audit_path.read_text(encoding="utf-8")
