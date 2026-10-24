"""分发契约（T01）：预算、传输描述、来源与授信标记。"""

from __future__ import annotations

import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from petcore.contracts.archive import (
    MARKET_ARCHIVE_LIMITS,
    ArchiveLimits,
    BudgetExceeded,
)
from petcore.contracts.http import ResumePolicy, TransferReport, TransferSpec
from petcore.contracts.market import PackageOrigin, writes_trusted_marker
from petcore.market import install as market_install
from petcore.market import model, verify
from petcore.net.market_transport import fetch_artifact


def test_archive_limits_reject_non_positive_and_bool():
    for field in ("compressed_bytes", "expanded_bytes", "entries"):
        kwargs = {"compressed_bytes": 1, "expanded_bytes": 1, "entries": 1}
        kwargs[field] = 0
        with pytest.raises(ValueError):
            ArchiveLimits(**kwargs)
        kwargs[field] = -5
        with pytest.raises(ValueError):
            ArchiveLimits(**kwargs)
        kwargs[field] = True
        with pytest.raises(TypeError):
            ArchiveLimits(**kwargs)


def test_market_limits_are_the_documented_values_and_allows_is_inclusive():
    assert MARKET_ARCHIVE_LIMITS.compressed_bytes == 64 * 1024 * 1024
    assert MARKET_ARCHIVE_LIMITS.expanded_bytes == 256 * 1024 * 1024
    assert MARKET_ARCHIVE_LIMITS.entries == 10_000
    limits = ArchiveLimits(10, 20, 3)
    assert limits.allows(compressed=10, expanded=20, entries=3)
    assert not limits.allows(compressed=11, expanded=20, entries=3)
    assert not limits.allows(compressed=10, expanded=21, entries=3)
    assert not limits.allows(compressed=10, expanded=20, entries=4)


def test_budget_exceeded_names_kind_limit_and_actual():
    error = BudgetExceeded("expanded", 100, 101)
    assert (error.kind, error.limit, error.actual) == ("expanded", 100, 101)
    assert "expanded" in str(error) and "101" in str(error) and "100" in str(error)


def test_transfer_spec_rejects_empty_urls_and_bad_numbers():
    with pytest.raises(ValueError):
        TransferSpec(urls=())
    with pytest.raises(ValueError):
        TransferSpec(urls=("https://example.invalid/a.zip",), max_redirects=-1)
    with pytest.raises(ValueError):
        TransferSpec(urls=("https://example.invalid/a.zip",), expected_size=-1)
    with pytest.raises(ValueError):
        TransferSpec(urls=("https://example.invalid/a.zip",), timeout=0)


def test_transfer_spec_defaults_are_https_only_and_resume_if_match():
    spec = TransferSpec(urls=("https://example.invalid/a.zip",))
    assert spec.allowed_schemes == ("https",)
    assert spec.resume is ResumePolicy.RESUME_IF_MATCH
    assert spec.max_redirects == 3
    report = TransferReport(url="https://example.invalid/a.zip", bytes_read=4)
    assert report.path == "" and report.resumed_from == 0


def test_package_origin_only_bundled_may_write_trusted():
    for origin in (PackageOrigin.MARKET, PackageOrigin.LOCAL_DIR, PackageOrigin.LOCAL_ZIP):
        assert not writes_trusted_marker(origin)
    assert writes_trusted_marker(PackageOrigin.BUNDLED)
    assert not writes_trusted_marker("not-an-origin")


class _Handler(BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):  # noqa: A003
        pass


@pytest.fixture()
def loopback():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/artifact.zip"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fetch_artifact_writes_file_and_reports_bytes(tmp_path, loopback):
    _Handler.payload = b"x" * 4096
    spec = TransferSpec(
        urls=(loopback,), expected_size=4096, allowed_schemes=("http",)
    )
    report = fetch_artifact(spec, tmp_path)
    assert report.bytes_read == 4096
    assert Path(report.path).read_bytes() == _Handler.payload
    assert not (tmp_path / "artifact.zip.part").exists()


def test_fetch_artifact_enforces_compressed_budget_and_drops_part(tmp_path, loopback):
    _Handler.payload = b"y" * 2048
    spec = TransferSpec(urls=(loopback,), allowed_schemes=("http",))
    with pytest.raises(BudgetExceeded) as caught:
        fetch_artifact(spec, tmp_path, limits=ArchiveLimits(1024, 8192, 10))
    assert caught.value.kind == "compressed"
    assert not (tmp_path / "artifact.zip").exists()
    assert not (tmp_path / "artifact.zip.part").exists()


def _manifest(mod_id: str, kind: str, version: str) -> dict:
    document = {
        "schema": 1,
        "id": mod_id,
        "kind": kind,
        "name": mod_id,
        "version": version,
        "api_version": "1",
        "core_requires": ">=0.1.0,<1.0.0",
    }
    if kind == "feature":
        document["entrypoint"] = "host/factory.py:create"
        document["execution"] = "host-only"
    return document


def _make_zip(root: Path, manifest: dict, *, marker: bool) -> Path:
    path = root / "artifact.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mod.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("payload.txt", "one")
        if manifest.get("kind") == "feature":
            archive.writestr("host/factory.py", "def create(host):\n    return None\n")
        if marker:
            archive.writestr(".trusted", "")
    return path


def _package(artifact: Path, mod_id: str, version: str, kind: str = "content"):
    entry = {
        "id": mod_id,
        "kind": kind,
        "name": mod_id,
        "latest": version,
        "api_version": "1",
        "core_requires": ">=0.1.0,<1.0.0",
        "execution": "host-only",
        "versions": [
            {
                "version": version,
                "size": artifact.stat().st_size,
                "sha256": verify.sha256_file(artifact),
                "urls": ["https://mirror.invalid/artifact.zip"],
            }
        ],
    }
    index, problems = model.parse_index(
        {"schema_version": 1, "packages": [entry]}
    )
    assert index is not None, problems
    package = index.packages[0]
    resolved = model.latest_version(package)
    assert resolved is not None
    return package, resolved


class _Fetcher:
    def __init__(self, artifact: Path):
        self.artifact = artifact

    def download(self, url, part_path, *, expected_size=None, timeout=15.0, progress=None, cancel=None):
        part_path.write_bytes(self.artifact.read_bytes())
        return part_path.stat().st_size


@pytest.mark.parametrize(
    ("origin", "expect_marker", "note"),
    [
        (PackageOrigin.MARKET, False, True),
        (PackageOrigin.LOCAL_ZIP, False, True),
        (PackageOrigin.BUNDLED, True, False),
    ],
)
def test_install_package_trust_marker_follows_origin(tmp_path, origin, expect_marker, note):
    artifact = _make_zip(tmp_path, _manifest("fun.marker", "content", "1.0.0"), marker=True)
    package, version = _package(artifact, "fun.marker", "1.0.0")
    outcome = market_install.install_package(
        tmp_path, package, version, fetcher=_Fetcher(artifact), origin=origin
    )
    assert outcome.ok, outcome.message
    marker = tmp_path / "mods" / "fun.marker" / ".trusted"
    assert marker.exists() is expect_marker
    assert ("已移除" in outcome.message) is note
