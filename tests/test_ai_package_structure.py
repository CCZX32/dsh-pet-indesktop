# -*- coding: utf-8 -*-
"""AI 对话包的结构守卫：它是**可插拔形态**，不是把内置聊天搬出去。

本片的口径（见 ``docs/modding/PORT-STATUS.md`` §九）是"两套聊天实现并存、不合并"，
所以有两件事必须机器可判，而不是靠 review 记得：

1. **包不 import 内置聊天**（`pet/chat/`）。包是自洽的：自己的 models / providers /
   session_store / service / widgets。一旦它开始 `from pet.chat import ...`，
   包就不再能被独立分发，"可插拔形态"当场退化成"内置聊天的第二个入口"；
2. **包的目录形态是官方 host 包**（`mod.json` + `host/`），没有 ``worker-src/``
   ——聊天包是 ``host-only``，声明里不许有 Worker，目录里也不该出现 Worker 入口话术。

这两条都是**源码级**判据（零 Qt、零导入、纯读文件），所以它们不依赖包被装载过。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "features" / "ai-chat"
BUILTIN_CHAT = ROOT / "pet" / "chat"

_PET_CHAT_IMPORT = re.compile(r"^\s*(?:from\s+pet\.chat[\w.]*\s+import|import\s+pet\.chat\b)", re.MULTILINE)


def _package_sources() -> list[Path]:
    return sorted(path for path in PACKAGE.rglob("*") if path.is_file() and "__pycache__" not in path.parts)


def test_the_package_tree_is_the_official_host_only_shape():
    assert (PACKAGE / "mod.json").is_file()
    assert (PACKAGE / "host" / "__init__.py").is_file()
    assert (PACKAGE / "host" / "chat" / "__init__.py").is_file()
    # host-only：没有 worker 源码树，也没有 common/（那是识屏包 worker 共享层的形态）
    assert not (PACKAGE / "worker-src").exists()
    assert not (PACKAGE / "common").exists()
    # 聊天窗的样式表随包分发（缺了界面就散架）
    assert (PACKAGE / "host" / "chat" / "modern_styles.qss").is_file()
    assert (PACKAGE / "host" / "chat" / "legacy_styles.qss").is_file()


def test_the_manifest_declares_the_closed_official_identity():
    mod = json.loads((PACKAGE / "mod.json").read_text(encoding="utf-8-sig"))
    from pet.official_features import AI_FEATURE_ID, official_feature

    registration = official_feature(AI_FEATURE_ID)
    assert mod["id"] == AI_FEATURE_ID
    assert mod["factory"] == registration.factory
    assert mod["execution_kind"] == registration.execution_kind == "host-only"
    # 目录名与 owner 的末段一致（与识屏包同一约定：features/<name>/）
    assert PACKAGE.name == AI_FEATURE_ID.rsplit(".", 1)[-1]


def test_the_package_never_imports_the_builtin_chat():
    """包是自洽的：一旦它 import ``pet.chat``，两套实现就合并了（本片明确禁止）。"""
    offenders = [
        f"{path.relative_to(ROOT)}:{match.group(0).strip()}"
        for path in _package_sources()
        if path.suffix == ".py"
        for match in [_PET_CHAT_IMPORT.search(path.read_text(encoding="utf-8"))]
        if match is not None
    ]
    assert offenders == [], "包里出现了对内置聊天的依赖：" + "; ".join(offenders)


def test_the_package_and_the_builtin_chat_do_not_share_module_names_by_accident():
    """包内自带一套同名模块（models/providers/session_store/service/widgets）是**有意**的。

    这条守卫把"有意"钉成事实：同名文件两边都在，但它们是两份实现（内容不同源），
    谁都不是谁的别名。若哪天包内那份变成 `from pet.chat.x import *` 的转发壳，
    上一条守卫会红、这条会提醒不要顺手把包内实现换成 import。
    """
    packaged = {path.name for path in (PACKAGE / "host" / "chat").glob("*.py")}
    builtin = {path.name for path in BUILTIN_CHAT.glob("*.py")}
    shared = {"models.py", "providers.py", "session_store.py", "service.py", "widgets.py"} & packaged & builtin
    assert shared == {"models.py", "providers.py", "session_store.py", "service.py", "widgets.py"}
    for name in sorted(shared):
        packaged_text = (PACKAGE / "host" / "chat" / name).read_text(encoding="utf-8")
        assert "from pet.chat" not in packaged_text


def test_every_package_module_is_python_or_a_known_asset():
    """包根里只许有 ``.py`` / ``.json`` / ``.qss``——多出来的字节要能解释。"""
    unexpected = [str(path.relative_to(PACKAGE)) for path in _package_sources() if path.suffix not in {".py", ".json", ".qss"}]
    assert unexpected == []


@pytest.mark.parametrize("name", ["config.py", "runtime.py", "runtime_mount.py", "contributions.py", "factory.py", "contribution_settings.py"])
def test_the_host_face_files_the_repo_wires_against_exist(name):
    """宿主接线点（``attach_official`` / ``GenericModMounts`` / 设置面板）指向的文件。

    这几条路径是 Core 侧的**契约**：改名就要同步改 Core 与打包脚本，所以钉在这里，
    免得改名后只在运行期才发现。
    """
    assert (PACKAGE / "host" / name).is_file()
