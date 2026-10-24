"""T07：真实候选 ZIP + 本地 file: 索引的安装、升级、回滚与数据保真。

用 T05 的构建器现场产出四个真实 ZIP（不依赖 gitignored 的 dist-extensions/），
再用 `build_index(local=True)` 生成 `file://` 索引，走 CLI + 真实 FeatureManager。
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_petcore_extensions import build_candidates, build_index  # noqa: E402

from petcore.contracts.host import HostPorts  # noqa: E402
from petcore.market import cli, model  # noqa: E402
from petcore.mods import feature as feature_mod  # noqa: E402
from petcore.mods.manifest import load_manifest  # noqa: E402

PACKS = ("fun.divination", "fun.festival", "reminder.todo", "voice.chime")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def candidates(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    manifest = build_candidates(ROOT, out)
    index = build_index(manifest, local=True)
    index_path = out / "local-index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out, index_path, manifest


def _run(capsys, *args) -> tuple[int, dict]:
    code = cli.main([*args, "--json"])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else {}


def test_local_index_lists_four_installable_packages(candidates, tmp_path, capsys):
    _out, index_path, _manifest = candidates
    root = tmp_path / "root"

    code, listing = _run(
        capsys, "--root", str(root), "--index-url", index_path.as_uri(), "list"
    )

    assert code == 0
    assert {item["id"] for item in listing["packages"]} == set(PACKS)
    assert {item["state"] for item in listing["packages"]} == {model.STATE_AVAILABLE}


def test_feature_install_requires_the_flag_and_leaves_no_trace(candidates, tmp_path, capsys):
    _out, index_path, _manifest = candidates
    root = tmp_path / "root"

    code, payload = _run(
        capsys,
        "--root",
        str(root),
        "--index-url",
        index_path.as_uri(),
        "install",
        "reminder.todo",
    )

    assert code == 1
    assert payload["ok"] is False
    assert "功能扩展" in payload["message"]
    mods = root / "mods"
    assert not mods.exists() or list(mods.iterdir()) == []


def test_four_packs_install_by_zip_without_trust_marker(candidates, tmp_path, capsys):
    _out, index_path, _manifest = candidates
    root = tmp_path / "root"

    for pack_id in PACKS:
        code, payload = _run(
            capsys,
            "--root",
            str(root),
            "--index-url",
            index_path.as_uri(),
            "install",
            pack_id,
            "--allow-feature",
        )
        assert code == 0, (pack_id, payload)
        assert payload["ok"] is True, (pack_id, payload)

    for pack_id in PACKS:
        pack = root / "mods" / pack_id
        assert pack.is_dir(), pack_id
        assert not (pack / ".trusted").exists(), pack_id
        manifest, problems = load_manifest(pack)
        assert manifest is not None, (pack_id, problems)
        manager = feature_mod.FeatureManager(HostPorts())
        diagnostics = manager.load(
            pack=pack, owner=manifest.id, entrypoint=manifest.entrypoint, config={}
        )
        assert diagnostics == [], (pack_id, diagnostics)
        manager.stop_owner(manifest.id)

    market = root / "market" / "downloads"
    assert not list(market.glob("*.part"))
    assert not list((root / "market" / "staging").glob("*"))


def _synth_upgrade(out: Path, index_path: Path, pack_id: str, new_version: str) -> None:
    """把候选 ZIP 的真实内容改一个版本号，生成「新版本」并改写本地索引。"""
    document = json.loads(index_path.read_text(encoding="utf-8"))
    entry = next(item for item in document["packages"] if item["id"] == pack_id)
    old = entry["versions"][0]
    source = out / Path(old["urls"][0]).name
    target = out / f"{pack_id}-{new_version}.zip"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            payload = src.read(info.filename)
            if info.filename == "mod.json":
                manifest = json.loads(payload.decode("utf-8"))
                manifest["version"] = new_version
                payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            dst.writestr(info.filename, payload)
    entry["latest"] = new_version
    entry["versions"] = [
        {
            "version": new_version,
            "size": target.stat().st_size,
            "sha256": _sha(target),
            "urls": [target.as_uri()],
        }
    ]
    index_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_upgrade_then_rollback_preserves_user_data(candidates, tmp_path, capsys):
    out, index_path, _manifest = candidates
    root = tmp_path / "root"
    url = index_path.as_uri()

    assert _run(
        capsys, "--root", str(root), "--index-url", url, "install", "reminder.todo", "--allow-feature"
    )[0] == 0
    data = root / "feature-data" / "reminder.todo"
    data.mkdir(parents=True)
    payload = data / "todo-slot-0-v2.json"
    payload.write_text('{"items": [{"id": "keep-me"}]}\n', encoding="utf-8")
    before = _sha(payload)

    _synth_upgrade(out, index_path, "reminder.todo", "1.1.1")
    code, upgraded = _run(
        capsys, "--root", str(root), "--index-url", url, "update", "reminder.todo", "--allow-feature"
    )
    assert code == 0, upgraded
    manifest, _ = load_manifest(root / "mods" / "reminder.todo")
    assert manifest is not None and manifest.version == "1.1.1"
    assert _sha(payload) == before

    code, rolled = _run(capsys, "--root", str(root), "rollback", "reminder.todo")
    assert code == 0, rolled
    manifest, _ = load_manifest(root / "mods" / "reminder.todo")
    assert manifest is not None and manifest.version == "1.1.0"
    assert _sha(payload) == before

    code, again = _run(
        capsys, "--root", str(root), "--index-url", url, "install", "reminder.todo", "--allow-feature"
    )
    assert code == 0, again
    manifest, _ = load_manifest(root / "mods" / "reminder.todo")
    assert manifest is not None and manifest.version == "1.1.1"
    assert _sha(payload) == before


def test_doctor_reports_a_consistent_market_state(candidates, tmp_path, capsys):
    _out, index_path, _manifest = candidates
    root = tmp_path / "root"
    url = index_path.as_uri()
    assert _run(
        capsys, "--root", str(root), "--index-url", url, "install", "voice.chime", "--allow-feature"
    )[0] == 0
    capsys.readouterr()

    code = cli.main(["--root", str(root), "--index-url", url, "doctor"])
    text = capsys.readouterr().out

    assert code == 0
    assert "voice.chime" in text
    lock = json.loads((root / "market" / "market-lock.json").read_text(encoding="utf-8"))
    assert "voice.chime" in lock["packages"]
