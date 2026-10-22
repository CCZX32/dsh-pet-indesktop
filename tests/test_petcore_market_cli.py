from __future__ import annotations

import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from petcore.market import cli, verify


def _make_zip(path: Path, mod_id: str, version: str, payload: str, *, kind="content") -> Path:
    manifest = {
        "schema": 1,
        "id": mod_id,
        "kind": kind,
        "name": mod_id,
        "version": version,
        "api_version": "1",
        "core_requires": ">=0.1.0,<1.0.0",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mod.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("payload.txt", payload)
    return path


def _index(artifacts: dict[str, Path], base_url: str, version: str, mod_id="fun.test") -> bytes:
    entries = []
    for current_version, path in artifacts.items():
        entries.append(
            {
                "version": current_version,
                "size": path.stat().st_size,
                "sha256": verify.sha256_file(path),
                "urls": [f"{base_url}/files/{path.name}"],
            }
        )
    entries.sort(key=lambda item: item["version"], reverse=True)
    document = {
        "schema_version": 1,
        "generated_at": "2026-10-22T00:00:00Z",
        "packages": [
            {
                "id": mod_id,
                "kind": "content",
                "name": mod_id,
                "latest": version,
                "api_version": "1",
                "core_requires": ">=0.1.0,<1.0.0",
                "versions": entries,
            }
        ],
    }
    return json.dumps(document).encode("utf-8")


class _State:
    index_body = b"{}"
    artifacts: dict[str, bytes] = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return None

    def _send(self, status, body, headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/index.json":
            self._send(200, _State.index_body, {"ETag": '"cli-v1"'})
            return
        if self.path.startswith("/files/"):
            body = _State.artifacts.get(self.path.rsplit("/", 1)[-1])
            if body is None:
                self._send(404, b"missing")
                return
            self._send(200, body)
            return
        self._send(404, b"missing")


@pytest.fixture()
def server(tmp_path):
    _State.index_body = b"{}"
    _State.artifacts = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        yield base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_cli_list_install_update_rollback_end_to_end(server, tmp_path, capsys):
    files = tmp_path / "files"
    files.mkdir()
    v1 = _make_zip(files / "fun.test-1.0.0.zip", "fun.test", "1.0.0", "one")
    root = tmp_path / "root"
    _State.artifacts = {"fun.test-1.0.0.zip": v1.read_bytes()}
    _State.index_body = _index({"1.0.0": v1}, server, "1.0.0")

    assert cli.main(["--root", str(root), "--index-url", f"{server}/index.json", "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["packages"][0]["state"] == "available"
    assert listed["stale"] is False

    assert (
        cli.main(
            ["--root", str(root), "--index-url", f"{server}/index.json", "install", "fun.test", "--json"]
        )
        == 0
    )
    installed = json.loads(capsys.readouterr().out)
    assert installed["ok"] is True
    assert (root / "mods" / "fun.test" / "payload.txt").read_text(encoding="utf-8") == "one"

    v2 = _make_zip(files / "fun.test-2.0.0.zip", "fun.test", "2.0.0", "two")
    _State.artifacts = {"fun.test-2.0.0.zip": v2.read_bytes()}
    _State.index_body = _index({"2.0.0": v2}, server, "2.0.0")

    assert (
        cli.main(["--root", str(root), "--index-url", f"{server}/index.json", "update", "--json"])
        == 0
    )
    updated = json.loads(capsys.readouterr().out)
    assert updated[0]["ok"] is True
    assert (root / "mods" / "fun.test" / "payload.txt").read_text(encoding="utf-8") == "two"

    assert cli.main(["--root", str(root), "rollback", "fun.test", "--json"]) == 0
    rolled = json.loads(capsys.readouterr().out)
    assert rolled["ok"] is True
    assert rolled["version"] == "1.0.0"
    assert (root / "mods" / "fun.test" / "payload.txt").read_text(encoding="utf-8") == "one"


def test_cli_offline_uses_the_disk_cache(server, tmp_path, capsys):
    files = tmp_path / "files"
    files.mkdir()
    v1 = _make_zip(files / "fun.test-1.0.0.zip", "fun.test", "1.0.0", "one")
    root = tmp_path / "root"
    _State.artifacts = {"fun.test-1.0.0.zip": v1.read_bytes()}
    _State.index_body = _index({"1.0.0": v1}, server, "1.0.0")
    assert cli.main(["--root", str(root), "--index-url", f"{server}/index.json", "list", "--json"]) == 0
    capsys.readouterr()

    assert cli.main(["--root", str(root), "--offline", "list", "--json"]) == 0
    offline = json.loads(capsys.readouterr().out)
    assert offline["stale"] is True
    assert [item["id"] for item in offline["packages"]] == ["fun.test"]


def test_cli_install_unknown_package_exits_two(server, tmp_path, capsys):
    root = tmp_path / "root"
    assert cli.main(["--root", str(root), "--index-url", f"{server}/index.json", "install", "nope"]) == 2
    assert "unknown package" in capsys.readouterr().out
