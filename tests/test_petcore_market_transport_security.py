"""市场逐跳传输加固（T02）：206 对齐、416 语义、读流预算、跳转收敛与响应释放。

全部网络边界用 loopback ``ThreadingHTTPServer``，不访问外网；时序用 Event，
不用 sleep 猜。每个用例对应当前实现的一处已知缺陷（旧行为见 ``red-*`` 证据）。
"""

from __future__ import annotations

import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from petcore.contracts.archive import ArchiveLimits, BudgetExceeded
from petcore.contracts.http import TransferSpec
from petcore.market.errors import TransferCancelled
from petcore.net import errors, http, market
from petcore.net import market_transport

PAYLOAD = bytes(range(256)) * 4  # 1024 字节，可区分前缀
BIG_PAYLOAD = bytes(range(256)) * 256  # 65536 字节
BUDGET_PAYLOAD = b"z" * 4096
STREAM_PAYLOAD = b"s" * 8192


# --------------------------------------------------------------------------- 服务端


class _ServerState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.hits: dict[str, int] = {}
        self.requests: list[tuple[str, str]] = []
        self.release = threading.Event()
        self.port = 0

    def hit(self, path: str, range_header: str) -> None:
        with self.lock:
            self.hits[path] = self.hits.get(path, 0) + 1
            self.requests.append((path, range_header))

    def count(self, path: str) -> int:
        with self.lock:
            return self.hits.get(path, 0)

    def ranges(self, path: str) -> list[str]:
        with self.lock:
            return [value for name, value in self.requests if name == path]


def _range_start(value: str) -> int | None:
    if not value.startswith("bytes="):
        return None
    try:
        return int(value[len("bytes=") :].split("-", 1)[0])
    except ValueError:
        return None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args):  # noqa: D401 - 测试静音
        return None

    def _send(self, status: int, body: bytes = b"", headers=None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except OSError:
                self.close_connection = True

    def _stream(self, chunks: list[bytes], *, content_length: int | None) -> None:
        self.send_response(200)
        if content_length is not None:
            self.send_header("Content-Length", str(content_length))
        self.end_headers()
        try:
            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            self.close_connection = True

    def do_GET(self):  # noqa: N802
        state: _ServerState = self.server.state  # type: ignore[attr-defined]
        path = self.path.split("?", 1)[0]
        range_header = self.headers.get("Range", "")
        state.hit(path, range_header)

        if path == "/artifact.bin":
            start = _range_start(range_header)
            if start is None:
                self._send(200, PAYLOAD)
            elif start >= len(PAYLOAD):
                self._send(416, b"", {"Content-Range": f"bytes */{len(PAYLOAD)}"})
            else:
                self._send(
                    206,
                    PAYLOAD[start:],
                    {"Content-Range": f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"},
                )
            return
        if path == "/range-wrong-start.bin":
            self._send(
                206,
                PAYLOAD,
                {"Content-Range": f"bytes 0-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"},
            )
            return
        if path == "/range-missing-header.bin":
            start = _range_start(range_header)
            if start is None:
                self._send(200, PAYLOAD)
            else:
                self._send(206, PAYLOAD[start:])
            return
        if path == "/range-malformed.bin":
            start = _range_start(range_header)
            if start is None:
                self._send(200, PAYLOAD)
            else:
                self._send(
                    206,
                    PAYLOAD[start:],
                    {"Content-Range": f"bytes {start}-"},
                )
            return
        if path == "/range-total-mismatch.bin":
            start = _range_start(range_header) or 0
            self._send(
                206,
                PAYLOAD[start:],
                {"Content-Range": f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD) + 1}"},
            )
            return
        if path == "/unsatisfied-match.bin":
            self._send(416, b"", {"Content-Range": f"bytes */{len(PAYLOAD)}"})
            return
        if path == "/unsatisfied-mismatch.bin":
            if range_header:
                self._send(416, b"", {"Content-Range": f"bytes */{len(PAYLOAD) + 5}"})
            else:
                self._send(200, PAYLOAD)
            return
        if path == "/unsatisfied-always.bin":
            self._send(416, b"", {"Content-Range": f"bytes */{len(PAYLOAD) + 5}"})
            return
        if path == "/budget.bin":
            self._send(200, BUDGET_PAYLOAD)
            return
        if path == "/budget-pre.bin":
            self._send(200, BUDGET_PAYLOAD)
            return
        if path == "/big.bin":
            self._send(200, BIG_PAYLOAD)
            return
        if path == "/stream-no-length.bin":
            self._stream(
                [STREAM_PAYLOAD[index : index + 1024] for index in range(0, len(STREAM_PAYLOAD), 1024)],
                content_length=None,
            )
            return
        if path == "/redirect-cross-host":
            self._send(
                302,
                b"",
                {"Location": f"http://localhost:{state.port}/target.bin"},
            )
            return
        if path == "/target.bin":
            self._send(200, PAYLOAD)
            return
        if path == "/redirect-same-host":
            self._send(302, b"", {"Location": "/artifact.bin"})
            return
        if path == "/redirect-loop":
            self._send(302, b"", {"Location": "/redirect-loop"})
            return
        if path == "/rate-limited.bin":
            self._send(429, b"", {"Retry-After": "1"})
            return
        if path == "/slow.bin":
            state.release.wait(5)
            self._send(200, PAYLOAD)
            return
        self._send(404, b"not found")


@pytest.fixture()
def loopback():
    state = _ServerState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.state = state  # type: ignore[attr-defined]
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _base(state: _ServerState) -> str:
    return f"http://127.0.0.1:{state.port}"


def _http_spec(url: str, **kwargs) -> TransferSpec:
    return TransferSpec(urls=(url,), allowed_schemes=("http",), **kwargs)


def _part(tmp_path: Path, url: str) -> Path:
    name = Path(url.rsplit("/", 1)[-1]).name
    return tmp_path / f"{name}.part"


# --------------------------------------------------------------------------- 206 对齐


def test_206_matching_start_resumes_from_part(loopback, tmp_path):
    url = f"{_base(loopback)}/artifact.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD[:100])

    report = market_transport.fetch_artifact(
        _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
    )

    assert report.bytes_read == len(PAYLOAD)
    assert report.resumed_from == 100
    assert report.redirects == 0
    assert Path(report.path).read_bytes() == PAYLOAD
    assert not part.exists()
    assert loopback.ranges("/artifact.bin") == ["bytes=100-"]


def test_206_wrong_start_discards_part_and_restarts(loopback, tmp_path):
    url = f"{_base(loopback)}/range-wrong-start.bin"
    part = _part(tmp_path, url)
    part.write_bytes(b"X" * 100)

    report = market_transport.fetch_artifact(
        _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
    )

    assert Path(report.path).read_bytes() == PAYLOAD
    assert report.bytes_read == len(PAYLOAD)
    assert report.resumed_from == 0  # 没有真正续传
    assert loopback.ranges("/range-wrong-start.bin") == ["bytes=100-", ""]


def test_206_missing_content_range_restarts(loopback, tmp_path):
    url = f"{_base(loopback)}/range-missing-header.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD[:100])

    report = market_transport.fetch_artifact(
        _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
    )

    assert Path(report.path).read_bytes() == PAYLOAD
    assert report.resumed_from == 0
    assert loopback.ranges("/range-missing-header.bin") == ["bytes=100-", ""]


def test_206_malformed_content_range_restarts(loopback, tmp_path):
    url = f"{_base(loopback)}/range-malformed.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD[:100])

    report = market_transport.fetch_artifact(
        _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
    )

    assert Path(report.path).read_bytes() == PAYLOAD
    assert report.resumed_from == 0
    assert loopback.ranges("/range-malformed.bin") == ["bytes=100-", ""]


def test_206_total_mismatch_restarts(loopback, tmp_path):
    url = f"{_base(loopback)}/range-total-mismatch.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD[:100])

    report = market_transport.fetch_artifact(
        _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
    )

    assert Path(report.path).read_bytes() == PAYLOAD
    assert report.resumed_from == 0
    assert loopback.ranges("/range-total-mismatch.bin") == ["bytes=100-", ""]


# --------------------------------------------------------------------------- 416


def test_416_with_matching_total_completes_and_closes(loopback, tmp_path, monkeypatch):
    closed: list[int] = []
    original = urllib.error.HTTPError.close

    def tracking_close(self):
        closed.append(int(getattr(self, "code", 0) or 0))
        return original(self)

    monkeypatch.setattr(urllib.error.HTTPError, "close", tracking_close, raising=False)

    url = f"{_base(loopback)}/unsatisfied-match.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD)

    report = market_transport.fetch_artifact(_http_spec(url), tmp_path)

    assert Path(report.path).read_bytes() == PAYLOAD
    assert report.bytes_read == len(PAYLOAD)
    assert report.resumed_from == len(PAYLOAD)
    assert closed == [416]
    assert loopback.count("/unsatisfied-match.bin") == 1


def test_416_with_local_length_equal_expected_size_completes(loopback, tmp_path):
    url = f"{_base(loopback)}/unsatisfied-match.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD)

    report = market_transport.fetch_artifact(
        _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
    )

    assert report.bytes_read == len(PAYLOAD)
    assert report.resumed_from == len(PAYLOAD)
    assert loopback.count("/unsatisfied-match.bin") == 1


def test_416_with_mismatched_total_restarts_once(loopback, tmp_path):
    url = f"{_base(loopback)}/unsatisfied-mismatch.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD[:100])

    report = market_transport.fetch_artifact(
        _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
    )

    assert Path(report.path).read_bytes() == PAYLOAD
    assert report.resumed_from == 0
    assert loopback.ranges("/unsatisfied-mismatch.bin") == ["bytes=100-", ""]


def test_416_that_never_matches_retries_only_once(loopback, tmp_path):
    url = f"{_base(loopback)}/unsatisfied-always.bin"
    part = _part(tmp_path, url)
    part.write_bytes(PAYLOAD[:100])

    with pytest.raises(errors.HttpStatusError) as caught:
        market_transport.fetch_artifact(
            _http_spec(url, expected_size=len(PAYLOAD)), tmp_path
        )

    assert caught.value.status == 416
    assert loopback.count("/unsatisfied-always.bin") == 2
    assert not part.exists()  # 重下一次仍失败，不留坏 .part


# --------------------------------------------------------------------------- 读流预算


def test_stream_budget_exceeded_mid_read_and_drops_part(loopback, tmp_path):
    url = f"{_base(loopback)}/budget.bin"
    limits = ArchiveLimits(1024, 1 << 20, 100)

    with pytest.raises(BudgetExceeded) as caught:
        market_transport.fetch_artifact(_http_spec(url), tmp_path, limits=limits)

    assert caught.value.kind == "compressed"
    assert caught.value.limit == 1024
    assert caught.value.actual > 1024
    assert not (tmp_path / "budget.bin").exists()
    assert not (tmp_path / "budget.bin.part").exists()
    assert loopback.count("/budget.bin") == 1


def test_stream_budget_does_not_trust_content_length(loopback, tmp_path):
    """无 Content-Length 的流也必须按实际读到字节截停。"""
    url = f"{_base(loopback)}/stream-no-length.bin"
    seen: list[int] = []

    with pytest.raises(BudgetExceeded) as caught:
        market_transport.fetch_artifact(
            _http_spec(url),
            tmp_path,
            limits=ArchiveLimits(1024, 1 << 20, 100),
            progress=lambda done, total: seen.append(done),
        )

    # 旧实现在下载完成后才复核，actual 会是整段 8192；读流截停只多读 1 字节。
    assert caught.value.actual == 1025
    assert all(done <= 1024 for done in seen)
    assert not (tmp_path / "stream-no-length.bin.part").exists()


def test_budget_rejects_oversized_existing_part_without_request(loopback, tmp_path):
    url = f"{_base(loopback)}/budget-pre.bin"
    part = _part(tmp_path, url)
    part.write_bytes(b"x" * 2048)

    with pytest.raises(BudgetExceeded) as caught:
        market_transport.fetch_artifact(
            _http_spec(url), tmp_path, limits=ArchiveLimits(1024, 1 << 20, 100)
        )

    assert caught.value.actual == 2048
    assert not part.exists()
    assert loopback.count("/budget-pre.bin") == 0


# --------------------------------------------------------------------------- 跳转收敛


def test_cross_host_redirect_rejected_without_target_hit(loopback, tmp_path):
    url = f"{_base(loopback)}/redirect-cross-host"

    with pytest.raises(errors.NetworkError) as caught:
        market_transport.fetch_artifact(_http_spec(url), tmp_path)

    assert caught.value.reason == errors.PROTOCOL
    assert "跨主机" in str(caught.value)
    assert loopback.count("/target.bin") == 0
    assert loopback.count("/redirect-cross-host") == 1
    assert not (tmp_path / "redirect-cross-host.part").exists()


def test_same_host_redirect_followed_and_counted(loopback, tmp_path):
    url = f"{_base(loopback)}/redirect-same-host"

    report = market_transport.fetch_artifact(_http_spec(url), tmp_path)

    assert Path(report.path).read_bytes() == PAYLOAD
    assert report.redirects == 1
    assert report.url.endswith("/artifact.bin")
    assert loopback.count("/redirect-same-host") == 1
    assert loopback.count("/artifact.bin") == 1


def test_redirect_limit_is_enforced(loopback, tmp_path):
    url = f"{_base(loopback)}/redirect-loop"

    with pytest.raises(errors.NetworkError) as caught:
        market_transport.fetch_artifact(
            _http_spec(url, max_redirects=3), tmp_path
        )

    assert caught.value.reason == errors.PROTOCOL
    assert "跳转超过" in str(caught.value)
    assert loopback.count("/redirect-loop") == 4


def test_http_url_is_rejected_by_default_https_spec(loopback, tmp_path):
    # 非回环主机：默认 spec 只允许 https，http 在连接前就被拒。
    url = "http://market.example.invalid/artifact.bin"

    with pytest.raises(errors.NetworkError) as caught:
        market_transport.fetch_artifact(TransferSpec(urls=(url,)), tmp_path)

    assert caught.value.reason == errors.PROTOCOL
    assert "协议" in str(caught.value)
    assert loopback.count("/artifact.bin") == 0


def test_https_to_http_downgrade_is_rejected():
    policy = market.TransportPolicy(max_redirects=3, allowed_schemes=("https", "http"))

    with pytest.raises(errors.NetworkError) as caught:
        market.validate_redirect(
            "https://example.invalid/a.zip",
            "http://example.invalid/a.zip",
            policy,
            1,
        )

    assert caught.value.reason == errors.PROTOCOL
    assert "降级" in str(caught.value)


def test_redirect_to_file_scheme_is_rejected():
    policy = market.TransportPolicy(max_redirects=3, allowed_schemes=("http",))

    with pytest.raises(errors.NetworkError) as caught:
        market.validate_redirect(
            "http://example.invalid/a.zip",
            "file:///C:/Windows/win.ini",
            policy,
            1,
        )

    assert caught.value.reason == errors.PROTOCOL
    assert "file" in str(caught.value)


def test_github_release_hop_requires_explicit_allow_list():
    """github.com → objects.githubusercontent.com 只有显式列出目标主机才放行。"""
    strict = market.TransportPolicy(max_redirects=3, allowed_schemes=("https",))
    with pytest.raises(errors.NetworkError) as caught:
        market.validate_redirect(
            "https://github.com/owner/repo/releases/download/v1/pack.zip",
            "https://objects.githubusercontent.com/blob/pack.zip",
            strict,
            1,
        )
    assert caught.value.reason == errors.PROTOCOL
    assert "跨主机" in str(caught.value)

    allowed = market.TransportPolicy(
        max_redirects=3,
        allowed_schemes=("https",),
        allowed_hosts=("objects.githubusercontent.com",),
    )
    market.validate_redirect(
        "https://github.com/owner/repo/releases/download/v1/pack.zip",
        "https://objects.githubusercontent.com/blob/pack.zip",
        allowed,
        1,
    )


def test_transfer_spec_rejects_blank_allowed_hosts():
    with pytest.raises(ValueError):
        TransferSpec(urls=("https://example.invalid/a.zip",), allowed_hosts=("  ",))


# --------------------------------------------------------------------------- 取消


def test_cancel_keeps_part_for_resume(loopback, tmp_path):
    url = f"{_base(loopback)}/big.bin"
    part = _part(tmp_path, url)
    cancelled = threading.Event()

    def progress(done, _total):
        if done >= 2048:
            cancelled.set()

    with pytest.raises(TransferCancelled):
        market.download_to(
            url,
            part,
            expected_size=len(BIG_PAYLOAD),
            chunk_size=1024,
            progress=progress,
            cancel=cancelled.is_set,
        )

    assert part.exists()
    written = part.read_bytes()
    assert 0 < len(written) < len(BIG_PAYLOAD)
    assert BIG_PAYLOAD.startswith(written)


# --------------------------------------------------------------------------- 响应释放与错误分类


class _TrackedResponse:
    def __init__(self, response) -> None:
        self._response = response
        self.closed = False

    def read(self, *args):
        return self._response.read(*args)

    def close(self) -> None:
        self.closed = True
        self._response.close()

    @property
    def status(self):
        return getattr(self._response, "status", 200)

    @property
    def headers(self):
        return self._response.headers

    def geturl(self):
        return self._response.geturl()


@pytest.fixture()
def tracked_responses(monkeypatch):
    created: list[_TrackedResponse] = []
    real = http.urlopen

    def wrapper(request, **kwargs):
        tracked = _TrackedResponse(real(request, **kwargs))
        created.append(tracked)
        return tracked

    monkeypatch.setattr(http, "urlopen", wrapper)
    return created


def test_success_closes_response(loopback, tmp_path, tracked_responses):
    url = f"{_base(loopback)}/artifact.bin"

    market_transport.fetch_artifact(_http_spec(url), tmp_path)

    assert tracked_responses
    assert all(item.closed for item in tracked_responses)


def test_read_failure_closes_response(tmp_path):
    class _BrokenResponse:
        status = 200
        headers = {"Content-Length": "16"}

        def __init__(self) -> None:
            self.closed = False

        def read(self, _amt=None):
            raise ConnectionResetError("boom")

        def close(self) -> None:
            self.closed = True

    response = _BrokenResponse()

    def factory(_use_proxy, _context=None):
        class _Opener:
            def open(self, _request, **_kwargs):
                return response

        return _Opener()

    with pytest.raises(errors.NetworkError):
        market.download_to(
            "http://127.0.0.1:9/artifact.bin",
            tmp_path / "broken.part",
            opener=factory,
        )

    assert response.closed


def test_timeout_is_classified(loopback, tmp_path):
    url = f"{_base(loopback)}/slow.bin"

    with pytest.raises(errors.NetworkTimeout):
        market_transport.fetch_artifact(
            _http_spec(url, timeout=0.3), tmp_path
        )

    loopback.release.set()
    assert not (tmp_path / "slow.bin.part").exists()


def test_rate_limit_keeps_retry_after_and_does_not_retry(loopback, tmp_path):
    url = f"{_base(loopback)}/rate-limited.bin"

    with pytest.raises(errors.RateLimitError) as caught:
        market_transport.fetch_artifact(_http_spec(url), tmp_path)

    assert caught.value.status == 429
    assert caught.value.retry_after == 1.0
    assert loopback.count("/rate-limited.bin") == 1


def test_loopback_http_is_allowed_by_default_and_can_be_switched_off(tmp_path, loopback):
    url = f"{_base(loopback)}/artifact.bin"

    relaxed = TransferSpec(urls=(url,))  # 默认 allowed_schemes 只有 https
    report = market_transport.fetch_artifact(relaxed, tmp_path / "relaxed")
    assert report.bytes_read == len(PAYLOAD)

    strict = TransferSpec(urls=(url,), allow_loopback_http=False)
    with pytest.raises(errors.NetworkError) as caught:
        market_transport.fetch_artifact(strict, tmp_path / "strict")

    assert caught.value.reason == errors.PROTOCOL
    assert loopback.count("/artifact.bin") == 1
