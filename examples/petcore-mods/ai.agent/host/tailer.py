"""有界增量读取：按字节偏移 tail 事件文件，不回放历史。

两条不变量（协议 §1）：

* **不回放**：首次打开只读当时末尾之后追加的内容；
* **有界**：单次读取 ≤ ``MAX_READ_BYTES``，半行缓冲有上限，文件轮转/截断只重读一代。
"""

from __future__ import annotations

from pathlib import Path

from .protocol import MAX_LINE_BYTES

#: 单次读取上限（协议 §1 的 64KB）。
MAX_READ_BYTES = 64 * 1024
#: 半行缓冲上限：超过说明这行畸形（或被拼接），直接丢弃，等下一个换行。
MAX_BUFFER_BYTES = MAX_LINE_BYTES * 2
#: 同时监视的文件数上限（DSH 多实例桥文件按 mtime 淘汰）。
MAX_FILES = 8


class ByteTailer:
    """单个文件的字节偏移 tailer。"""

    def __init__(
        self,
        path: Path | str,
        *,
        max_read: int = MAX_READ_BYTES,
        prime_to_end: bool = True,
    ) -> None:
        self.path = Path(path)
        self.max_read = int(max_read)
        self._offset = 0
        self._buffer = b""
        self._identity: tuple[int, int] | None = None
        # 首次见到已存在的文件时跳到末尾：协议要求不回放历史。文件在监视开始后
        # 才出现的（例如新会话写入新文件）仍从 0 读。
        self._prime_to_end = bool(prime_to_end)
        # 构造时就存在的文件才需要「跳到末尾」：监视开始后才出现的文件是**新**
        # 事件，必须从头读，否则会漏掉首轮状态。
        self._prime_pending = self._prime_to_end and self.path.is_file()
        self._primed = False

    @property
    def offset(self) -> int:
        return self._offset

    def reset(self) -> None:
        self._offset = 0
        self._buffer = b""
        self._identity = None
        self._primed = False

    def read_lines(self) -> list[bytes]:
        """返回本次新增的完整行（不含换行符）；不完整的一行留在缓冲里。"""
        try:
            stat = self.path.stat()
        except OSError:
            self.reset()
            return []
        identity = (int(stat.st_dev), int(stat.st_ino))
        if not self._primed:
            self._primed = True
            if self._prime_pending:
                self._offset = int(stat.st_size)
            self._prime_pending = False
        if self._identity is not None and (
            identity != self._identity or stat.st_size < self._offset
        ):
            # 轮转或截断：旧偏移已无意义，从头读一代。
            self._offset = 0
            self._buffer = b""
        self._identity = identity
        if stat.st_size <= self._offset:
            return []
        try:
            with self.path.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read(self.max_read)
        except OSError:
            return []
        if not data:
            return []
        self._offset += len(data)
        self._buffer += data
        parts = self._buffer.split(b"\n")
        self._buffer = parts.pop()
        if len(self._buffer) > MAX_BUFFER_BYTES:
            # 畸形长行：丢掉整个半行，避免常驻内存。
            self._buffer = b""
        return [line for line in parts if line.strip()]


class GlobTailer:
    """目录里按模式匹配多个文件（DSH 桥目录：多实例各写一份）。"""

    def __init__(
        self,
        directory: Path | str,
        pattern: str = "*.jsonl",
        *,
        limit: int = MAX_FILES,
    ) -> None:
        self.directory = Path(directory)
        self.pattern = pattern
        self.limit = max(1, int(limit))
        self._tailers: dict[Path, ByteTailer] = {}
        # 启动时就存在的文件视为「历史」，跳到末尾；之后出现的文件从头读。
        try:
            self._initial = {path for path in self.directory.glob(self.pattern)}
        except OSError:
            self._initial = set()

    def paths(self) -> list[Path]:
        try:
            entries = [path for path in self.directory.glob(self.pattern) if path.is_file()]
        except OSError:
            return []
        entries.sort(key=_mtime, reverse=True)
        return entries[: self.limit]

    def read_lines(self) -> list[tuple[Path, bytes]]:
        """按「较旧的文件先读」返回 ``(path, line)``，保证跨文件的顺序稳定。"""
        current = self.paths()
        keep = set(current)
        for stale in [path for path in self._tailers if path not in keep]:
            self._tailers.pop(stale, None)
        result: list[tuple[Path, bytes]] = []
        for path in reversed(current):
            tailer = self._tailers.get(path)
            if tailer is None:
                tailer = ByteTailer(path, prime_to_end=path in self._initial)
                self._tailers[path] = tailer
            for line in tailer.read_lines():
                result.append((path, line))
        return result


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def agent_key_for(path: Path | str, *, default: str = "") -> str:
    """从文件名推断 agent 标识：``dsh-1234.jsonl`` → ``dsh``，``claude.jsonl`` → ``claude``。"""
    stem = Path(path).stem.strip().lower()
    if not stem or stem.startswith("."):
        return default
    if stem.startswith("dsh"):
        return "dsh"
    return stem
