# -*- coding: utf-8 -*-
"""功能扩展包的门（``scripts/verify_feature_package.py``）——作者自检与构建两道门共用。

门只回答三件事，每一件都要机器可判：

1. **清单**：有界路由读得出 id / version / platforms / execution_kind；
2. **验签**：完整验签链（结构、兼容性、路径边界、逐文件摘要与指纹、祖先快照）；
3. **装前子进程预检**：真起一个子进程把包装一次，读回 ``create_host()`` 的说法。

材料与 D3 同一份：包由 ``scripts.build_mod_example`` 真打（真 manifest、真 SHA-256
清单、真 ZIP），探针那一侧的行为在 ``tests/test_feature_package_preflight.py`` 里另有
分工——这里只看**门会不会用它的结论**、以及门自己的判定。

门是构建管线里的东西，所以这个文件用真子进程跑命令行（与
``tests/test_presentmon_packaging.py`` 同规）：门的退出码与 stdout 就是它与构建脚本
之间的契约，进程内调用看不见那条契约。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._feature_import_package import build, source_tree

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "verify_feature_package.py"
#: 探针的拒绝方向也要能机器读到（门不许把自己包装成"永远说行"）。
OWNER = "demo.hello-local"
_OTHER_PLATFORM = "darwin" if sys.platform != "darwin" else "linux"


def _run(*args: str) -> subprocess.CompletedProcess:
    return _run_in(ROOT, *args)


def _run_in(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(cwd), check=False,
    )


def _json_run(*args: str) -> dict:
    result = _run("--json", *args)
    payload = json.loads(result.stdout)
    payload["_exit"] = result.returncode
    payload["_stderr"] = result.stderr
    return payload


def _only(payload: dict) -> dict:
    assert payload["_exit"] == 0, payload
    assert len(payload["packages"]) == 1, payload
    return payload["packages"][0]


@pytest.fixture
def package(tmp_path: Path) -> tuple[Path, Path]:
    """一份真包（目录 + ZIP）。"""
    return build(tmp_path / "pkg")


# --------------------------------------------------------------------------- 一、正路径


class TestAcceptance:
    def test_directory_package_passes(self, package):
        built, _zip = package
        report = _only(_json_run(str(built)))
        assert report["ok"] is True
        assert report["reason"] is None
        assert report["kind"] == "directory"
        assert report["feature_id"] == OWNER
        assert report["version"] == "1.0.0"
        assert report["execution_kind"] == "host-only"

    def test_zip_package_passes(self, package):
        """导入口给出的本来就是 ZIP：门必须和 D3 那条链看到同一份解包结果。"""
        _built, zip_path = package
        report = _only(_json_run(str(zip_path)))
        assert report["ok"] is True
        assert report["kind"] == "zip"
        assert report["feature_id"] == OWNER

    def test_probe_metadata_is_reported(self, package):
        """预检不是"跑过就算"：它读回 owner / 契约 / 贡献，门要如实写出来。"""
        built, _zip = package
        report = _only(_json_run(str(built)))
        probe = report["probe"]
        assert probe["ok"] is True
        assert probe["metadata"]["owner"] == OWNER
        assert probe["metadata"]["has_runtime"] is True
        assert probe["metadata"]["has_settings"] is True
        assert [item[0] for item in probe["metadata"]["contributions"]] == ["hello"]

    def test_human_output_names_the_verdict(self, package):
        built, _zip = package
        result = _run(str(built))
        assert result.returncode == 0
        assert OWNER in result.stdout

    def test_relative_source_path_is_accepted(self, tmp_path):
        """作者文档与构建脚本给的都是**相对路径**（``.scratch/…``）；验签链要求绝对路径，
        门必须自己归一——否则门在真实用法下对每一份包都报"路径穿越"。"""
        built, _zip = build(tmp_path / "pkg")
        result = _run_in(tmp_path, "--json", built.relative_to(tmp_path).as_posix())
        payload = json.loads(result.stdout)
        assert result.returncode == 0, payload
        assert payload["packages"][0]["feature_id"] == OWNER


class TestBundleRoot:
    """构建脚本按"包根"叫门：根下每一份都要过，一个都不能漏。"""

    def test_every_candidate_is_checked(self, tmp_path):
        root = tmp_path / "release"
        root.mkdir(parents=True)
        built, _zip = build(tmp_path / "work")
        shutil.copytree(built, root / "hello-local")
        (root / "broken").mkdir()
        payload = _json_run("--bundle-root", str(root))
        assert payload["_exit"] == 1
        assert payload["ok"] is False
        by_path = {Path(item["source"]).name: item for item in payload["packages"]}
        assert by_path["hello-local"]["ok"] is True
        assert by_path["broken"]["reason"] == "route_rejected"
        assert any("broken" in problem for problem in payload["problems"])

    def test_zip_candidates_are_included(self, tmp_path):
        root = tmp_path / "release"
        root.mkdir(parents=True)
        _built, zip_path = build(tmp_path / "work")
        target = root / "hello-local.zip"
        shutil.copy2(zip_path, target)
        payload = _json_run("--bundle-root", str(root))
        report = _only(payload)
        assert report["kind"] == "zip"
        assert Path(report["source"]) == target

    def test_an_empty_root_is_a_failure(self, tmp_path):
        """空根不能是"没有坏包所以过"：包根给错了正是要抓的那一种。"""
        root = tmp_path / "empty"
        root.mkdir()
        payload = _json_run("--bundle-root", str(root))
        assert payload["_exit"] == 1
        assert "bundle_empty" in payload["problems"][0]

    def test_the_repo_example_packages_pass(self, tmp_path):
        """仓库自己的示例就是作者照着跑的那一份：它打出来的包必须一直过门。"""
        _built, zip_path = build(tmp_path / "example")
        result = _run("--json", str(zip_path))
        payload = json.loads(result.stdout)
        assert result.returncode == 0, result.stderr
        assert payload["packages"][0]["feature_id"] == OWNER

    def test_author_side_source_tree_is_not_a_package(self):
        """``examples/mods/`` 是**作者侧源码形态**（``mod.json`` + ``host/``）：
        它不是包，门要如实说出来——省得作者把源码目录当成品去分发。"""
        result = _run("--json", "examples/mods/hello-local")
        payload = json.loads(result.stdout)
        assert result.returncode == 1
        assert payload["packages"][0]["reason"] == "route_rejected"


# --------------------------------------------------------------------------- 二、门有牙


class TestRejections:
    def test_missing_source_is_rejected(self, tmp_path):
        payload = _json_run(str(tmp_path / "nope"))
        assert payload["_exit"] == 1
        assert payload["packages"][0]["reason"] == "source_missing"

    def test_missing_manifest_is_rejected(self, tmp_path):
        source = tmp_path / "empty"
        source.mkdir()
        payload = _json_run(str(source))
        assert payload["_exit"] == 1
        assert payload["packages"][0]["reason"] == "route_rejected"

    def test_official_owner_is_rejected(self, tmp_path):
        """官方保留 ID：本地包占不了，门要在装之前说清楚（路由只读清单，够判这一条）。"""
        source = tmp_path / "official"
        source.mkdir()
        (source / "manifest.json").write_text(json.dumps({
            "format_version": 2, "key_id": "local-user",
            "id": "official.ai-chat", "version": "1.0.0", "api_version": "1",
            "core_requires": ">=4.0.0,<6.0.0", "platforms": [sys.platform],
            "capabilities": ["menu.contribute"], "factory": "ai-chat/v1",
            "execution_kind": "host-only", "worker": None, "files": {},
        }), "utf-8")
        payload = _json_run(str(source))
        assert payload["_exit"] == 1
        report = payload["packages"][0]
        assert report["reason"] == "official_reserved"
        assert report["feature_id"] == "official.ai-chat"

    def test_tampered_payload_is_rejected(self, package):
        """打包之后动过字节：路由只看清单，拦不住它，验签那一环必须拦住。"""
        built, _zip = package
        target = built / "host" / "factory.py"
        target.write_text(target.read_text("utf-8") + "\n# tampered\n", "utf-8")
        payload = _json_run(str(built))
        assert payload["_exit"] == 1
        assert payload["packages"][0]["reason"] == "verification_failed"

    def test_platform_mismatch_is_named(self, package):
        """为别的平台声明的包，在目标平台的构建里要有一句能照做的拒绝语。"""
        package_dir, _zip = package
        payload = _json_run(str(package_dir), "--target-platform", _OTHER_PLATFORM)
        assert payload["_exit"] == 1
        report = payload["packages"][0]
        assert report["reason"] == "platform_mismatch"
        assert report["target_platform"] == _OTHER_PLATFORM

    def test_owner_mismatch_is_caught_by_the_probe(self, tmp_path):
        """清单说一个 owner、``create_host()`` 说另一个——只有子进程预检能发现。"""
        tree = source_tree(tmp_path / "src")
        factory = tree / "host" / "factory.py"
        factory.write_text(factory.read_text("utf-8").replace(f'OWNER = "{OWNER}"', 'OWNER = "someone.else"'), "utf-8")
        from scripts.build_mod_example import build_example

        built = build_example(tree, tmp_path / "built")
        payload = _json_run(str(built))
        assert payload["_exit"] == 1
        report = payload["packages"][0]
        assert report["reason"] == "probe_owner_mismatch"
        assert report["probe"]["ok"] is False

    def test_the_probe_can_be_seen_refusing_in_the_human_output(self, tmp_path):
        source = tmp_path / "nope"
        result = _run(str(source))
        assert result.returncode == 1
        assert "source_missing" in result.stderr + result.stdout


# --------------------------------------------------------------------------- 三、门的纪律


class TestGateDiscipline:
    def test_gate_is_read_only(self, package):
        """门在构建管线里只读：跑完之后包目录逐字节不变、不留下任何东西。"""
        built, _zip = package
        before = sorted(
            (path.relative_to(built).as_posix(), path.stat().st_size, path.stat().st_mtime_ns)
            for path in built.rglob("*"))
        assert _run(str(built)).returncode == 0
        after = sorted(
            (path.relative_to(built).as_posix(), path.stat().st_size, path.stat().st_mtime_ns)
            for path in built.rglob("*"))
        assert before == after

    def test_json_output_is_ascii(self, package):
        """构建脚本要解析它：任何代码页下都得是同一串字节。"""
        built, _zip = package
        result = _run("--json", str(built))
        result.stdout.encode("ascii")

    def test_gate_does_not_import_qt(self, package):
        """门跑在构建机上，不该为了两个常量把 PySide6 拉起来。"""
        built, _zip = package
        code = (
            "import sys; sys.modules['PySide6'] = None; sys.argv = ['verify_feature_package.py', '--json', "
            f"{str(built)!r}]; import runpy; runpy.run_path({str(GATE)!r}, run_name='__main__')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=str(ROOT), check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["ok"] is True

    def test_gate_reads_policy_from_the_product_module(self):
        """判据只有一份：门里不许出现第二份能力上限 / API 版本字面量。"""
        text = GATE.read_text(encoding="utf-8")
        assert "from pet.feature_policy import" in text
        assert "local_package_verifier" in text
        assert "FEATURE_CAPABILITIES =" not in text
        assert 'API_VERSION = "' not in text

    def test_usage_error_without_any_source(self):
        result = _run()
        assert result.returncode == 2
        assert "bundle-root" in result.stderr
