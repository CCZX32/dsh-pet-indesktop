# -*- coding: utf-8 -*-
"""官方 AI 对话包打包器的拒绝路径与清单形态。

happy path 由 ``test_ai_package_e2e`` 的夹具每次真跑（真打包 → 真事务 → 真宿主），
这里补的是**它拒绝什么**——拒绝路径不做用例就会在真装包时才发现，而且这些判据
（id / 执行形态 / 输出已存在）是"打错了也照样产出一个能验签的包"的防线。

零 Qt：打包脚本与发布门都是纯文件产物。
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = ROOT / "features" / "ai-chat"


@pytest.fixture
def source(tmp_path) -> Path:
    """仓库里那份作者源码树的副本（改坏它不影响仓库）。"""
    target = tmp_path / "src"
    shutil.copytree(PACKAGE_SOURCE, target)
    return target


def _build(source: Path, output: Path):
    from scripts.build_ai_chat_package import build_package

    return build_package(source, output)


# --------------------------------------------------------------- 清单形态


def test_the_built_manifest_is_host_only_with_a_null_worker(tmp_path, source):
    built = _build(source, tmp_path / "out")
    manifest = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_kind"] == "host-only"
    # host-only 的清单**必须**带 worker 键、值恒为 null（少键会被验签层判字段非法）
    assert "worker" in manifest and manifest["worker"] is None
    assert manifest["factory"] == "ai-chat/v1"
    assert manifest["id"] == "official.ai-chat"
    assert manifest["files"], "清单的 files 是空的"
    # 清单覆盖的文件与磁盘上的一致（多一个少一个都是包被改了）
    on_disk = {path.relative_to(built).as_posix() for path in built.rglob("*") if path.is_file()}
    assert on_disk == set(manifest["files"]) | {"manifest.json"}


def test_the_zip_carries_exactly_what_the_directory_does(tmp_path, source):
    built = _build(source, tmp_path / "out")
    with zipfile.ZipFile(built.with_suffix(".zip")) as archive:
        packed = set(archive.namelist())
    on_disk = {path.relative_to(built).as_posix() for path in built.rglob("*") if path.is_file()}
    assert packed == on_disk


# --------------------------------------------------------------- 拒绝路径


def test_a_foreign_id_in_mod_json_is_refused(tmp_path, source):
    mod = json.loads((source / "mod.json").read_text(encoding="utf-8"))
    mod["id"] = "official.screen-understanding"
    (source / "mod.json").write_text(json.dumps(mod, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="mod.json"):
        _build(source, tmp_path / "out")


def test_a_worker_execution_kind_is_refused(tmp_path, source):
    """聊天包是 host-only：源码树里写 host-worker 说明拿错了树，不许打出去。"""
    mod = json.loads((source / "mod.json").read_text(encoding="utf-8"))
    mod["execution_kind"] = "host-worker"
    (source / "mod.json").write_text(json.dumps(mod, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="mod.json"):
        _build(source, tmp_path / "out")


def test_an_existing_output_is_refused_before_writing_anything(tmp_path, source):
    output = tmp_path / "out"
    output.mkdir()
    (output / "keep.txt").write_text("旧的产物", encoding="utf-8")
    with pytest.raises(ValueError, match="already|exists"):
        _build(source, output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "旧的产物"


def test_an_existing_zip_next_to_the_output_is_refused(tmp_path, source):
    output = tmp_path / "out"
    output.with_suffix(".zip").write_bytes(b"stale")
    with pytest.raises(ValueError):
        _build(source, output)
    assert not output.exists()


def test_the_cli_reports_a_refusal_as_a_nonzero_exit_code(tmp_path, source, capsys):
    """``main`` 的退出码是闭集：0 成功、2 打不了包（构建脚本只看码，不解析文案）。"""
    from scripts.build_ai_chat_package import main

    mod = json.loads((source / "mod.json").read_text(encoding="utf-8"))
    mod["id"] = "demo.not-official"
    (source / "mod.json").write_text(json.dumps(mod, ensure_ascii=False), encoding="utf-8")
    assert main([str(tmp_path / "out"), "--source", str(source)]) == 2
    assert "打不了包" in capsys.readouterr().err


def test_the_cli_prints_the_two_products_on_success(tmp_path, source, capsys):
    from scripts.build_ai_chat_package import main

    assert main([str(tmp_path / "out"), "--source", str(source)]) == 0
    printed = capsys.readouterr().out
    assert "created:" in printed and "ZIP:" in printed


# --------------------------------------------------------------- 发布门


def test_the_release_gate_treats_an_official_package_as_reserved(tmp_path, source):
    """发布门（``scripts/verify_feature_package.py``）只管**随包携带**的本地包。

    官方包走 Core 自己的构建入口（本文件上面那条链），所以门看到官方 owner 时
    如实回 ``official_reserved``——不是"验不过"，是"这条门不管它"。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from verify_feature_package import inspect
    except ImportError:  # pragma: no cover - 模块名与 CLI 同名时的兜底
        pytest.skip("发布门没有可导入的 inspect")
    built = _build(source, tmp_path / "out")
    report = inspect(built)
    assert report["reason"] == "official_reserved"
    assert report["ok"] is False
