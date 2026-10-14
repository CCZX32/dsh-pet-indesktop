# -*- coding: utf-8 -*-
"""功能包的分发链：作者侧构建入口 + 三端构建脚本接线。

与 ``tests/test_feature_package_gate.py`` 的分工：那边验**门自己的判定**，这边验
**这条链有没有接上**——构建入口能不能一条命令产出可导入的包、自检会不会真跑预检、
三个平台的构建脚本有没有把门接在正确的位置上。接线只能由源码文本断言（行为测试
看不到"有没有接上"），与 ``tests/test_presentmon_packaging.py`` 同规。

两条纪律在这里机器化：

* **判据只有一份**：能力上限 / API 版本 / 验签器装配都在 ``pet/feature_policy.py``，
  构建入口与门都不许抄第二份（曾经的 ``scripts/build_mod_example.py`` 就是第二份）；
* **门有两道**（照 presentmon 先例）：PyInstaller 之前验源包根、产物里再验一次
  ——拷贝截断/漏件同样致命，而运行期看不出来。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_mod_example.py"
GATE = ROOT / "scripts" / "verify_feature_package.py"
POLICY = ROOT / "pet" / "feature_policy.py"
WINDOWS_BUILD = ROOT / "scripts" / "build_onedir.ps1"
SHELL_BUILDS = {
    "linux": (ROOT / "scripts" / "build_linux.sh", "linux"),
    "macos": (ROOT / "scripts" / "build_macos.sh", "darwin"),
}
ONEDIR_DOC = ROOT / "docs" / "ONEDIR_PACKAGING.md"
MODDING_README = ROOT / "docs" / "modding" / "README.md"
PORT_STATUS = ROOT / "docs" / "modding" / "PORT-STATUS.md"
HANDOFF_PLAN = ROOT / "docs" / "modding" / "MOD-CENTER-IMPLEMENTATION-PLAN-2026-10-10.md"
#: 产物里随包携带的包根（= 设计文档里"旁置 packages 根"在 onedir 树的落法）。
ARTIFACT_ROOT = "features"
#: 门的命令行片段（注释里提到脚本名不算接线——只数真正的**调用**）。
CALL = "verify_feature_package.py --bundle-root"


def _call_positions(text: str) -> list[int]:
    """每次真实调用的起点（逐次 `find`，注释里提到脚本名不算调用）。"""
    positions, start = [], 0
    while (index := text.find(CALL, start)) >= 0:
        positions.append(index)
        start = index + 1
    return positions


def _run_builder(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, cwd=str(ROOT), check=False,
    )


# --------------------------------------------------------------------------- 一、作者侧构建入口


class TestBuildEntry:
    """``scripts/build_mod_example.py`` 是作者的一条命令入口，不是测试材料。"""

    def test_builds_a_directory_and_a_zip_from_the_repo_example(self, tmp_path):
        result = _run_builder(str(BUILDER), "examples/mods/hello-local", str(tmp_path / "out"))
        assert result.returncode == 0, result.stderr
        built = tmp_path / "out"
        assert (built / "manifest.json").is_file()
        assert (built / "host" / "factory.py").is_file()
        archive = tmp_path / "out.zip"
        assert archive.is_file()
        with zipfile.ZipFile(archive) as zipped:
            names = sorted(zipped.namelist())
        assert names == ["host/__init__.py", "host/factory.py", "host/settings.py", "manifest.json"]

    def test_manifest_inventory_covers_every_shipped_byte(self, tmp_path):
        """清单里的 files 就是包的全部字节：多一个少一个都会被校验链拒。"""
        assert _run_builder(str(BUILDER), "examples/mods/hello-local", str(tmp_path / "out")).returncode == 0
        manifest = json.loads((tmp_path / "out" / "manifest.json").read_text("utf-8"))
        listed = set(manifest["files"])
        on_disk = {path.relative_to(tmp_path / "out").as_posix() for path in (tmp_path / "out").rglob("*") if path.is_file()}
        assert listed | {"manifest.json"} == on_disk
        assert manifest["platforms"] == [sys.platform]

    def test_check_runs_the_preflight_probe(self, tmp_path):
        """``--check`` 是发布前自检：清单完整性 + 摘要校验 + 装前子进程预检，一条命令。"""
        assert _run_builder(str(BUILDER), "examples/mods/hello-local", str(tmp_path / "out")).returncode == 0
        result = _run_builder(str(BUILDER), str(tmp_path / "out"), "--check")
        assert result.returncode == 0, result.stderr
        assert "demo.hello-local" in result.stdout

    def test_check_refuses_a_package_whose_factory_disagrees(self, tmp_path):
        """自检必须有牙：owner 对不上的包，--check 非零退出。"""
        from tests._feature_import_package import source_tree

        tree = source_tree(tmp_path / "src")
        factory = tree / "host" / "factory.py"
        factory.write_text(factory.read_text("utf-8").replace('OWNER = "demo.hello-local"', 'OWNER = "someone.else"'), "utf-8")
        assert _run_builder(str(BUILDER), str(tree), str(tmp_path / "built")).returncode == 0
        result = _run_builder(str(BUILDER), str(tmp_path / "built"), "--check")
        assert result.returncode == 1
        assert "probe_owner_mismatch" in result.stdout + result.stderr

    def test_existing_output_is_refused_without_a_traceback(self, tmp_path):
        """文档里那条命令是给作者敲的：撞上已存在的输出要给一句话，不是 traceback。"""
        output = tmp_path / "out"
        assert _run_builder(str(BUILDER), "examples/mods/hello-local", str(output)).returncode == 0
        result = _run_builder(str(BUILDER), "examples/mods/hello-local", str(output))
        assert result.returncode != 0
        assert "Traceback" not in result.stderr
        assert "already exists" in result.stderr

    def test_missing_manifest_is_refused_without_a_traceback(self, tmp_path):
        source = tmp_path / "src"
        source.mkdir()
        result = _run_builder(str(BUILDER), str(source), str(tmp_path / "out"))
        assert result.returncode != 0
        assert "Traceback" not in result.stderr
        assert "mod.json" in result.stderr

    def test_direct_path_invocation_works(self, tmp_path):
        """文档里写的是 ``python scripts/build_mod_example.py``（不是 ``-m``）——
        直接给路径时 ``sys.path[0]`` 是 ``scripts/``，脚本必须自己把仓库根放上去。"""
        result = _run_builder(str(BUILDER), "examples/mods/hello-local", str(tmp_path / "out"))
        assert result.returncode == 0, result.stderr
        assert "No module named 'pet'" not in result.stderr


class TestSingleTruthPolicy:
    def test_policy_module_holds_the_only_definitions(self):
        text = POLICY.read_text(encoding="utf-8")
        assert "FEATURE_CAPABILITIES = frozenset" in text
        assert 'API_VERSION = "' in text
        assert "def local_package_verifier(" in text

    @pytest.mark.parametrize("path", [BUILDER, GATE])
    def test_consumers_do_not_restate_the_policy(self, path):
        text = path.read_text(encoding="utf-8")
        assert "from pet.feature_policy import" in text
        assert "FEATURE_CAPABILITIES =" not in text
        assert 'API_VERSION = "' not in text

    def test_host_runtime_uses_the_same_policy(self):
        """宿主侧那一半也走这份装配：两条路必须回答同一个"兼容上限"。"""
        text = (ROOT / "pet" / "feature_management.py").read_text(encoding="utf-8")
        assert "local_package_verifier" in text
        assert "FEATURE_CAPABILITIES =" not in text
        assert 'API_VERSION = "' not in text

    def test_policy_module_is_qt_free(self):
        """门要在最小构建机环境跑：策略模块沾上 Qt 就等于把 GUI 依赖塞进构建管线。"""
        architecture = (ROOT / "tests" / "test_architecture.py").read_text(encoding="utf-8")
        assert '"feature_policy.py"' in architecture


# --------------------------------------------------------------------------- 二、Windows 构建接线


class TestWindowsBuildWiring:
    def _text(self) -> str:
        return WINDOWS_BUILD.read_text(encoding="utf-8")

    def test_carries_a_package_root_only_when_asked(self):
        assert "[string]$FeaturePackages" in self._text()

    def test_source_side_gate_runs_before_pyinstaller(self):
        text = self._text()
        assert CALL in text
        assert text.index(CALL) < text.index("python -m PyInstaller")

    def test_artifact_side_gate_runs_after_the_build(self):
        text = self._text()
        assert text.count(CALL) == 2, "源码侧 + 产物侧，两道"
        assert text.index("python -m PyInstaller") < text.rindex(CALL)

    def test_packages_are_copied_into_the_artifact(self):
        text = self._text()
        assert "Join-Path $appDir 'features'" in text
        assert "Copy-Item $FeaturePackages $featuresDir -Recurse" in text

    def test_gate_failure_aborts_the_build(self):
        text = self._text()
        for call in (f"{CALL} $FeaturePackages",
                     f"{CALL} (Join-Path $appDir 'features')"):
            index = text.index(call)
            block = text[index:text.index("\n", text.index("throw", index))]
            assert "$LASTEXITCODE" in block and "throw" in block

    def test_target_platform_is_the_build_platform(self):
        """门按**目标平台**判兼容性，不是按跑构建的机器。"""
        assert "--target-platform win32" in self._text()


# --------------------------------------------------------------------------- 三、POSIX 构建接线


class TestShellBuildWiring:
    @pytest.mark.parametrize("name", sorted(SHELL_BUILDS))
    def test_accepts_a_package_root(self, name):
        text = SHELL_BUILDS[name][0].read_text(encoding="utf-8")
        assert "--feature-packages)" in text
        assert "FEATURE_PACKAGES=" in text

    @pytest.mark.parametrize("name", sorted(SHELL_BUILDS))
    def test_two_gates_around_pyinstaller(self, name):
        path, platform = SHELL_BUILDS[name]
        text = path.read_text(encoding="utf-8")
        assert text.count(CALL) == 2, "源码侧 + 产物侧，两道"
        assert text.index(CALL) < text.index("-m PyInstaller") < text.rindex(CALL)
        assert f"--target-platform {platform}" in text
        assert f"/{ARTIFACT_ROOT}" in text

    @pytest.mark.parametrize("name", sorted(SHELL_BUILDS))
    def test_gate_failure_aborts_the_build(self, name):
        text = SHELL_BUILDS[name][0].read_text(encoding="utf-8")
        for index in _call_positions(text):
            assert "exit 1" in text[index:index + 300], "门没过就必须中止出包"

    @pytest.mark.parametrize("name", sorted(SHELL_BUILDS))
    def test_unknown_option_still_fails_loudly(self, name):
        assert "未知参数" in SHELL_BUILDS[name][0].read_text(encoding="utf-8")


# --------------------------------------------------------------------------- 四、文档


class TestDocsTellTheTruth:
    def test_packaging_doc_registers_the_gate(self):
        text = ONEDIR_DOC.read_text(encoding="utf-8")
        assert "verify_feature_package.py" in text
        assert ARTIFACT_ROOT in text

    def test_modding_docs_no_longer_deny_that_the_builder_exists(self):
        """D1 那批基线头写的是"打包脚本不存在"——D2/D3/D4 之后这句是假话。"""
        for stale in ("`scripts/build_mod_example.py`", ):
            for path in sorted((ROOT / "docs" / "modding").glob("*.md")):
                text = path.read_text(encoding="utf-8")
                assert f"{stale}、`scripts/build_character_mod_example.py` 都不存在" not in text, path.name

    def test_readme_states_what_the_self_check_does(self):
        text = MODDING_README.read_text(encoding="utf-8")
        assert "verify_feature_package.py" in text
        assert "--check" in text

    def test_port_status_records_the_slice(self):
        text = PORT_STATUS.read_text(encoding="utf-8")
        assert "D4" in text
        assert "verify_feature_package.py" in text

    def test_implementation_plan_points_at_the_builder(self):
        text = HANDOFF_PLAN.read_text(encoding="utf-8")
        assert "scripts/build_mod_example.py` 都已存在" in text


class TestTheChainDoesNotClaimPublisherAuthentication:
    """本地包是**显式用户信任**（Phase 5A）：分发链的文字不许说自己在"验签"。

    这条链（门 + 三端构建脚本 + 作者侧打包入口）对一份本地包做的是清单完整性、摘要校验
    与装前预检；``manifest.sig`` 在本口径下被忽略。写成"验签"会让作者读成发布者已认证。
    """

    #: 门自己的那句话（构建脚本与作者入口都照抄它）。
    CLAIM = "清单完整性 + 摘要校验 + 装前子进程预检"

    def _chain(self) -> dict[str, Path]:
        return {
            "gate": GATE,
            "builder": BUILDER,
            "windows": WINDOWS_BUILD,
            **{name: path for name, (path, _platform) in SHELL_BUILDS.items()},
        }

    def test_every_link_states_what_the_gate_really_does(self):
        for name, path in self._chain().items():
            # 强调标记（``**``）不算文案的一部分——判据是那句话本身在不在。
            text = path.read_text(encoding="utf-8").replace("**", "")
            assert self.CLAIM in text, name
            assert "验签" not in text, f"{name} 仍在声称验签（本地口径不做发布者认证）"

    def test_the_gate_reports_the_trust_path_and_the_ignored_signature(self):
        text = GATE.read_text(encoding="utf-8")
        assert "SIGNATURE_IGNORED" in text
        assert "未做发布者认证" in text

    def test_the_author_facing_docs_say_the_same(self):
        for path in (MODDING_README, ROOT / "docs" / "modding" / "AUTHORING-HANDBOOK.md"):
            text = path.read_text(encoding="utf-8")
            assert "不做发布者认证" in text, path.name
