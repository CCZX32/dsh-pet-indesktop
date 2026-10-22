from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from petcore.market.errors import TransferCancelled
from petcore.net import errors
from petcore.net import market

INDEX_BODY = json.dumps(
    {"schema_version": 1, "generated_at": "2026-10-22T00:00:00Z", "packages": []}
).encode("utf-8")
ARTIFACT = b"0123456789abcdef" * 64
ETAG = '"market-v1"'


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):  # noqa: D401 - 测试静音
        return None

    def _send(self, status: int, body: bytes, *, headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/index.json":
            if self.headers.get("If-None-Match") == ETAG:
                self._send(304, b"", headers={"ETag": ETAG})
                return
            self._send(200, INDEX_BODY, headers={"ETag": ETAG})
            return
        if self.path == "/github/index.json":
            payload = {
                "encoding": "base64",
                "content": base64.b64encode(INDEX_BODY).decode("ascii"),
            }
            self._send(200, json.dumps(payload).encode("utf-8"))
            return
        if self.path in ("/artifact.bin", "/artifact-norange.bin"):
            range_header = self.headers.get("Range", "")
            if self.path.endswith("norange.bin") or not range_header.startswith("bytes="):
                self._send(200, ARTIFACT)
                return
            start = int(range_header.split("=", 1)[1].split("-", 1)[0] or 0)
            chunk = ARTIFACT[start:]
            self._send(
                206,
                chunk,
                headers={"Content-Range": f"bytes {start}-{len(ARTIFACT) - 1}/{len(ARTIFACT)}"},
            )
            return
        self._send(404, b"not found")


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_fetch_index_returns_body_and_etag(server):
    result = market.fetch_index(f"{server}/index.json")

    assert result.not_modified is False
    assert result.body == INDEX_BODY
    assert result.etag == ETAG


def test_fetch_index_reports_not_modified(server):
    result = market.fetch_index(f"{server}/index.json", etag=ETAG)

    assert result.not_modified is True
    assert result.body == b""


def test_fetch_index_decodes_github_contents_api(server):
    result = market.fetch_index(f"{server}/github/index.json")

    assert result.body == INDEX_BODY


def test_fetch_index_maps_http_errors(server):
    with pytest.raises(market.IndexFetchError):
        market.fetch_index(f"{server}/missing")


def test_download_writes_full_artifact_and_reports_progress(server, tmp_path):
    part = tmp_path / "artifact.zip.part"
    progress: list[tuple[int, int]] = []

    size = market.download_to(
        f"{server}/artifact.bin",
        part,
        expected_size=len(ARTIFACT),
        progress=lambda done, total: progress.append((done, total)),
    )

    assert size == len(ARTIFACT)
    assert part.read_bytes() == ARTIFACT
    assert progress[-1] == (len(ARTIFACT), len(ARTIFACT))


def test_download_resumes_from_part_with_range(server, tmp_path):
    part = tmp_path / "artifact.zip.part"
    part.write_bytes(ARTIFACT[:100])
    progress: list[tuple[int, int]] = []

    size = market.download_to(
        f"{server}/artifact.bin",
        part,
        expected_size=len(ARTIFACT),
        progress=lambda done, total: progress.append((done, total)),
    )

    assert size == len(ARTIFACT)
    assert part.read_bytes() == ARTIFACT
    assert progress[0][0] > 100


def test_download_restarts_when_server_ignores_range(server, tmp_path):
    part = tmp_path / "artifact.zip.part"
    part.write_bytes(b"stale-prefix")

    size = market.download_to(
        f"{server}/artifact-norange.bin", part, expected_size=len(ARTIFACT)
    )

    assert size == len(ARTIFACT)
    assert part.read_bytes() == ARTIFACT


def test_download_maps_http_errors(server, tmp_path):
    with pytest.raises(errors.HttpStatusError):
        market.download_to(f"{server}/missing", tmp_path / "x.part")


def test_download_can_be_cancelled(server, tmp_path):
    part = tmp_path / "artifact.zip.part"

    with pytest.raises(TransferCancelled):
        market.download_to(f"{server}/artifact.bin", part, cancel=lambda: True)

    assert part.exists()


def test_http_fetcher_exposes_both_protocols(server, tmp_path):
    fetcher = market.HttpFetcher()

    assert fetcher.fetch_index(f"{server}/index.json").body == INDEX_BODY
    size = fetcher.download(f"{server}/artifact.bin", tmp_path / "a.part")
    assert size == len(ARTIFACT)
