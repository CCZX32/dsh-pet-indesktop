from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

SPEC = DOCS / "PETCORE-SPEC.md"
LOG = DOCS / "PETCORE-LOG.md"
LOG_INDEX = DOCS / "PETCORE-LOG-INDEX.md"
README = ROOT / "petcore" / "README.md"
AGENTS = ROOT / "petcore" / "AGENTS.md"
INDEX = DOCS / "INDEX.md"

REQUIRED_DOCS = (SPEC, LOG, LOG_INDEX, README, AGENTS)
_LOG_ID = re.compile(r"^## (L\d{3})\b", re.MULTILINE)
_INDEX_ID = re.compile(r"^\| (L\d{3}) \|", re.MULTILINE)


def test_required_docs_exist_and_are_registered():
    index = INDEX.read_text(encoding="utf-8")
    for path in REQUIRED_DOCS:
        assert path.is_file(), f"缺少文档：{path}"
        relative = path.relative_to(ROOT).as_posix()
        assert relative in index or path.name in index, (
            f"{relative} 未在 docs/INDEX.md 登记"
        )


def test_log_and_log_index_are_in_sync():
    log_ids = _LOG_ID.findall(LOG.read_text(encoding="utf-8"))
    index_ids = _INDEX_ID.findall(LOG_INDEX.read_text(encoding="utf-8"))
    assert log_ids, "PETCORE-LOG.md 没有任何 LNNN 条目"
    assert log_ids == index_ids, (
        "PETCORE-LOG.md 与 PETCORE-LOG-INDEX.md 的编号不一致："
        f"{log_ids} vs {index_ids}"
    )


def test_agent_rules_mention_log_and_menu_settings_contract():
    text = AGENTS.read_text(encoding="utf-8")
    for needle in (
        "PETCORE-LOG.md",
        "PETCORE-LOG-INDEX.md",
        "每次改动",
        "菜单",
        "设置",
        "300",
        "非模态",
    ):
        assert needle in text, f"petcore/AGENTS.md 缺少约定：{needle}"


def test_spec_records_the_final_contract():
    text = SPEC.read_text(encoding="utf-8")
    for needle in (
        "最终形态",
        "菜单/设置一一对应",
        "10%–300%",
        "可插拔 mod",
        "角色包",
        "非目标",
    ):
        assert needle in text, f"PETCORE-SPEC.md 缺少最终契约：{needle}"
