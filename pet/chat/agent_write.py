# -*- coding: utf-8 -*-
"""Personal Agent v0.5：仅限工作区的受控写 / 定点编辑 / 撤销。

设计稿：``.scratch/personal-agent/SPEC-v05-write.md``。本模块是纯逻辑层，
**不 import Qt**，跑在聊天 worker 线程里；工具注册与审计收口复用
``pet/chat/agent_tools.py``。

四条边界：

1. **默认关**：只有 ``chat_agent_write_enabled=True`` 时，装配点才会把工作区
   根交给这里并注册 ``fs_write`` / ``fs_edit`` / ``fs_undo``。
2. **唯一工作区根**：写面与只读白名单严格分离；所有路径都经 realpath +
   ``_within`` + 设备名/保留名校验，``..``、目录联接/符号链接逃逸一律拒绝。
3. **原子写 + 备份**：同目录临时文件 + flush + ``os.replace``；目标已存在时先
   把旧内容复制到 ``<工作区>/.feiyu-backup/<相对路径>.<UTC 时间戳>.bak``。
4. **可撤销**：撤销恢复该路径最新一份备份，并先备份当前状态，所以再撤销一次
   可以回到撤销前（可逆）。
"""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .agent_tools import _DEVICE_NAMES, ToolError, ToolOutcome, ToolSpec

#: 单文件上限 / 单次编辑文本上限（SPEC §工具语义）。
WRITE_MAX_BYTES = 256 * 1024
EDIT_TEXT_MAX_BYTES = 8 * 1024
#: 兼容更直白的旧名（测试与调用方都能一眼对上 spec）。
FS_WRITE_MAX_BYTES = WRITE_MAX_BYTES
FS_EDIT_TEXT_MAX_BYTES = EDIT_TEXT_MAX_BYTES

BACKUP_DIR_NAME = ".feiyu-backup"
WORKSPACE_DIR_NAME = "肥鱼工作区"
_BACKUP_STAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"

_INVALID_FILENAME_CHARS = frozenset('<>:"|?*')
_STRICT_TREE_ENV = ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")


def _fallback_default_root() -> Path:
    """Qt 不可用 / 未传默认值时的兜底：家目录下的桌面/肥鱼工作区。"""
    return Path.home() / "Desktop" / WORKSPACE_DIR_NAME


def _real(path) -> Path:
    """解析 ``..``、符号链接与 Windows junction（与 v0 只读路径同一口径）。"""
    return Path(os.path.realpath(str(path)))


def _norm(path) -> str:
    return os.path.normcase(str(path))


def _within(target: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([_norm(target), _norm(root)]) == _norm(root)
    except ValueError:  # 不同盘符 / 混合绝对相对：无从比较
        return False


def _is_dir(path) -> bool:
    try:
        return Path(path).is_dir()
    except OSError:
        return False


def _device_name(path) -> bool:
    stem = str(getattr(path, "name", path)).split(".")[0].upper()
    return stem in _DEVICE_NAMES


def _device_part(part: str) -> bool:
    return part.split(".")[0].upper() in _DEVICE_NAMES


def _invalid_part(part: str) -> bool:
    """Windows 文件名/目录名黑名单：尾点/尾空格、非法字符、NUL。"""
    if part in ("", ".", ".."):
        return False
    if part.endswith((" ", ".")):
        return True
    if any(char in _INVALID_FILENAME_CHARS for char in part):
        return True
    return "\x00" in part


def _device_in_path(path: Path) -> bool:
    return any(_device_part(part) for part in path.parts[1:])


def _invalid_absolute_path(path: Path) -> bool:
    return any(_invalid_part(part) for part in path.parts[1:])


def _check_parts(parts) -> None:
    for part in parts:
        if _device_part(part):
            raise ToolError("Windows 设备名不能作为文件名", code="fs_outside_workspace")
        if _invalid_part(part):
            raise ToolError("文件名/目录名不合法（尾点、尾空格或非法字符）", code="fs_invalid_name")


def _protected_dirs() -> tuple[Path, ...]:
    """拒绝列表：系统目录、盘符根、用户目录根 / AppData 根（精确命中）。"""
    values: list[Path] = [Path.home(), Path.home().parent]
    for key in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                "APPDATA", "LOCALAPPDATA"):
        raw = os.environ.get(key)
        if raw:
            values.append(Path(raw))
    values.append(Path.home() / "AppData")
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            try:
                if drive.exists():
                    values.append(drive)
            except OSError:
                continue
    else:
        values.extend(Path(item) for item in ("/", "/usr", "/etc", "/var", "/bin", "/sbin", "/boot"))
    return tuple(_real(path) for path in values)


def _is_protected(path: Path) -> bool:
    for protected in _protected_dirs():
        if _norm(path) == _norm(protected):
            return True
    # Windows/Program Files 的**子目录**同样是系统目录；AppData 同理，但放行
    # 系统临时目录（CI/测试的 tmp_path 就在 AppData\Local\Temp 下）。
    for key in _STRICT_TREE_ENV:
        raw = os.environ.get(key)
        if raw and _within(path, _real(Path(raw))):
            return True
    roaming = os.environ.get("APPDATA")
    if roaming and _within(path, _real(Path(roaming))):
        return True
    local = os.environ.get("LOCALAPPDATA")
    if local and _within(path, _real(Path(local))):
        try:
            temp_root = _real(Path(tempfile.gettempdir()))
        except OSError:
            temp_root = None
        if temp_root is None or not _within(path, temp_root):
            return True
    return False


def resolve_workspace_root(raw, *, default=None) -> Path:
    """把配置里的工作区根归一为真实路径；非法/系统目录回落默认（fail-closed）。"""
    default_path = _fallback_default_root() if default is None else Path(default)
    fallback = _real(default_path)
    if not isinstance(raw, str) or not raw.strip():
        return fallback
    text = raw.strip().strip('"\'')
    candidate = Path(os.path.expandvars(text)).expanduser()
    if not candidate.is_absolute():
        candidate = Path.home() / candidate
    try:
        resolved = _real(candidate)
    except OSError:
        return fallback
    if (_is_protected(resolved) or _device_in_path(resolved)
            or _invalid_absolute_path(resolved)):
        return fallback
    if resolved.exists() and not _is_dir(resolved):
        return fallback
    ancestor = resolved
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if not _is_dir(ancestor):
        return fallback
    return resolved


def _workspace_root(root) -> Path:
    path = _fallback_default_root() if root is None else Path(root)
    if not path.is_absolute():
        path = Path.home() / path
    return _real(path)


def _outside_message(root: Path) -> str:
    return f'这个位置不在肥鱼工作区里（只能写工作区目录：{root}）'


def resolve_workspace_path(raw, root=None) -> Path:
    """把模型给的路径解析到工作区内；任何逃逸/保留名都抛 ``fs_outside_workspace``。"""
    workspace = _workspace_root(root)
    text = str(raw or "").strip().strip('"\'')
    if not text:
        raise ToolError("没有给出路径", code="fs_no_path")
    if text.endswith(("/", "\\")):
        raise ToolError("这是目录路径，写文件需要给到文件名", code="fs_is_directory")
    candidate = Path(os.path.expandvars(text)).expanduser()
    if candidate.is_absolute():
        _check_parts(candidate.parts[1:])
        target_candidate = candidate
    else:
        _check_parts(candidate.parts)
        target_candidate = workspace / candidate
    target = _real(target_candidate)
    if _device_name(target) or _device_in_path(target):
        raise ToolError("Windows 设备名不能作为文件名", code="fs_outside_workspace")
    if _invalid_absolute_path(target):
        raise ToolError("文件名/目录名不合法（尾点、尾空格或非法字符）", code="fs_invalid_name")
    if _norm(target) == _norm(workspace):
        raise ToolError("这是一个目录，不能当文件写", code="fs_is_directory")
    if not _within(target, workspace):
        raise ToolError(_outside_message(workspace), code="fs_outside_workspace")
    backup_root = _real(workspace / BACKUP_DIR_NAME)
    if _within(target, backup_root):
        raise ToolError("备份区不能直接写入", code="fs_outside_workspace")
    return target


def _ensure_parent(target: Path, root: Path) -> None:
    """创建父目录并再次校验 realpath（防创建目录期间被联接点带出工作区）。"""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolError(f"创建目录失败（{type(exc).__name__}）", code="fs_write_failed") from exc
    real_target = _real(target)
    if not _within(real_target, root) or _norm(real_target) == _norm(root):
        raise ToolError(_outside_message(root), code="fs_outside_workspace")
    if _within(real_target, _real(root / BACKUP_DIR_NAME)):
        raise ToolError("备份区不能直接写入", code="fs_outside_workspace")


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """同目录临时文件 + flush/fsync + os.replace；失败清理临时文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    fd, temp_name = handle
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _atomic_copy(source: Path, target: Path) -> None:
    """流式复制到同目录临时文件再 replace（大文件备份不整份进内存）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as out, open(source, "rb") as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _ensure_backup_root(root: Path) -> Path:
    backup_root = root / BACKUP_DIR_NAME
    if backup_root.exists() and not _is_dir(backup_root):
        raise ToolError("备份目录被同名文件占用，无法写入", code="fs_write_failed")
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolError(f"创建备份目录失败（{type(exc).__name__}）", code="fs_write_failed") from exc
    real_backup = _real(backup_root)
    if not _within(real_backup, root) or _norm(real_backup) == _norm(root):
        raise ToolError(_outside_message(root), code="fs_outside_workspace")
    return real_backup


def _backup_path(target: Path, root: Path) -> Path:
    try:
        relative = target.relative_to(root)
    except ValueError:
        relative = Path(target.name)
    backup_root = _ensure_backup_root(root)
    base = backup_root / relative
    base.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime(_BACKUP_STAMP_FORMAT)
    candidate = base.with_name(f"{base.name}.{stamp}.bak")
    counter = 0
    while candidate.exists() or candidate.is_symlink():
        counter += 1
        candidate = base.with_name(f"{base.name}.{stamp}-{counter}.bak")
    return candidate


def _backup_existing(target: Path, root: Path) -> Path | None:
    if not target.exists():
        return None
    if target.is_dir():
        raise ToolError("这是一个目录，不能当文件写", code="fs_is_directory")
    backup = _backup_path(target, root)
    try:
        _atomic_copy(target, backup)
    except OSError as exc:
        raise ToolError(f"备份失败（{type(exc).__name__}）", code="fs_write_failed") from exc
    return backup


def _write_file(target: Path, data: bytes, root: Path) -> Path | None:
    _ensure_parent(target, root)
    backup = _backup_existing(target, root)
    try:
        _atomic_write_bytes(target, data)
    except OSError as exc:
        raise ToolError(f"写入失败（{type(exc).__name__}）", code="fs_write_failed") from exc
    return backup


def _latest_backup(target: Path, root: Path) -> Path | None:
    backup_root = root / BACKUP_DIR_NAME
    if not _is_dir(backup_root):
        return None
    try:
        relative = target.relative_to(root)
    except ValueError:
        relative = Path(target.name)
    base = backup_root / relative
    parent = base.parent
    if not _is_dir(parent):
        return None
    prefix = f"{base.name}."
    candidates: list[Path] = []
    try:
        entries = list(parent.iterdir())
    except OSError:
        return None
    real_backup_root = _real(backup_root)
    if not _within(real_backup_root, root) or _norm(real_backup_root) == _norm(root):
        return None
    for entry in entries:
        if not entry.name.startswith(prefix) or not entry.name.endswith(".bak"):
            continue
        if entry.is_symlink() or not entry.is_file():
            continue
        try:
            if not _within(_real(entry), real_backup_root):
                continue
        except OSError:
            continue
        candidates.append(entry)

    def _order(path: Path) -> tuple[str, int]:
        stem = path.name[:-4] if path.name.endswith(".bak") else path.name
        base, separator, tail = stem.rpartition("-")
        if separator and tail.isdigit():
            return base, int(tail)
        return stem, 0

    return max(candidates, key=_order) if candidates else None


def _restore_backup(target: Path, backup: Path, root: Path) -> Path | None:
    _ensure_parent(target, root)
    current_backup = _backup_existing(target, root)
    try:
        _atomic_copy(backup, target)
    except OSError as exc:
        raise ToolError(f"撤销失败（{type(exc).__name__}）", code="fs_write_failed") from exc
    return current_backup


def _text_arg(args: dict, key: str) -> str:
    value = args.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ToolError(f"{key} 必须是文本", code="fs_invalid_argument")
    return value


def _encode_text(text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ToolError("文本不是合法的 UTF-8", code="fs_decode") from exc


def _read_text_file(target: Path) -> str:
    if not target.exists():
        raise ToolError("文件不存在", code="fs_not_found")
    if target.is_dir():
        raise ToolError("这是一个目录，请用 fs_list 查看", code="fs_is_directory")
    try:
        with open(target, "rb") as handle:
            data = handle.read(WRITE_MAX_BYTES + 1)
    except OSError as exc:
        raise ToolError(f"读取失败（{type(exc).__name__}）") from exc
    if len(data) > WRITE_MAX_BYTES:
        raise ToolError(f"文件超过 {WRITE_MAX_BYTES // 1024} 千字节上限，没有编辑", code="fs_write_too_large")
    if b"\x00" in data:
        raise ToolError("这不是文本文件（含二进制内容），没有编辑", code="fs_binary")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError("无法按 UTF-8 解码，没有编辑", code="fs_decode") from exc


def _nearest_line(text: str, needle: str) -> tuple[int, str] | None:
    lines = text.splitlines()
    if not lines:
        return None
    probe = needle.strip().splitlines()[0] if needle.strip() else needle
    best_line = 1
    best_ratio = -1.0
    for number, line in enumerate(lines, 1):
        ratio = difflib.SequenceMatcher(None, probe, line).ratio()
        if ratio > best_ratio:
            best_line, best_ratio = number, ratio
    return best_line, lines[best_line - 1]


def _count_occurrences(text: str, needle: str) -> int:
    """按**重叠**口径计数：``aa`` 在 ``aaa`` 里算 2 次（唯一性判定要保守）。"""
    count = 0
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return count
        count += 1
        start = index + 1


def fs_write(args: dict, root=None) -> ToolOutcome:
    """创建/覆写工作区内的 UTF-8 文本文件（原子写 + 旧内容备份）。"""
    workspace = _workspace_root(root)
    target = resolve_workspace_path(args.get("path"), workspace)
    content = _text_arg(args, "content")
    data = _encode_text(content)
    if len(data) > WRITE_MAX_BYTES:
        raise ToolError(
            f"内容超过 {WRITE_MAX_BYTES // 1024} 千字节上限，没有写入",
            code="fs_write_too_large",
        )
    if b"\x00" in data:
        raise ToolError("这不是文本内容（含二进制内容），没有写入", code="fs_binary")
    status = (f"✍️ 正在写入：{target}",)
    backup = _write_file(target, data, workspace)
    body = f"已写入：{target}\n字节数：{len(data)}"
    if backup is not None:
        body += f"\n原内容备份：{backup}"
    return ToolOutcome(body, True, status)


def fs_edit(args: dict, root=None) -> ToolOutcome:
    """定点替换：old_text 必须恰好出现一次，再走与 fs_write 相同的原子写通道。"""
    workspace = _workspace_root(root)
    target = resolve_workspace_path(args.get("path"), workspace)
    old_text = _text_arg(args, "old_text")
    new_text = _text_arg(args, "new_text")
    if not old_text:
        raise ToolError("old_text 不能为空", code="fs_empty_old_text")
    for label, value in (("old_text", old_text), ("new_text", new_text)):
        if len(_encode_text(value)) > EDIT_TEXT_MAX_BYTES:
            raise ToolError(
                f"{label} 超过 {EDIT_TEXT_MAX_BYTES // 1024} 千字节上限，没有编辑",
                code="fs_write_too_large",
            )

    text = _read_text_file(target)
    occurrences = _count_occurrences(text, old_text)
    if occurrences == 0:
        hint = _nearest_line(text, old_text)
        if hint is None:
            message = "没有找到要替换的文本（文件是空的）"
        else:
            line_no, snippet = hint
            message = f"没有找到要替换的文本。最接近的是第 {line_no} 行：{snippet[:80]}"
        raise ToolError(message, code="fs_ambiguous_edit")
    if occurrences > 1:
        raise ToolError(
            f"要替换的文本出现了 {occurrences} 次，请提供更长的上下文让它唯一",
            code="fs_ambiguous_edit",
        )

    index = text.index(old_text)
    line_no = text.count("\n", 0, index) + 1
    new_content = text[:index] + new_text + text[index + len(old_text):]
    data = _encode_text(new_content)
    if len(data) > WRITE_MAX_BYTES:
        raise ToolError(
            f"编辑后文件超过 {WRITE_MAX_BYTES // 1024} 千字节上限，没有写入",
            code="fs_write_too_large",
        )
    if b"\x00" in data:
        raise ToolError("这不是文本内容（含二进制内容），没有写入", code="fs_binary")
    backup = _write_file(target, data, workspace)

    lines = text.splitlines()
    before = lines[line_no - 2] if line_no >= 2 and line_no - 2 < len(lines) else ""
    end_line = text.count("\n", 0, index + len(old_text)) + 1
    after = lines[end_line] if end_line < len(lines) else ""
    body = (
        f"已在 {target} 替换第 {line_no} 行。\n"
        f"上下文：\n{_clip(before, 100)}\n{_clip(after, 100)}"
    )
    if backup is not None:
        body += f"\n原内容备份：{backup}"
    return ToolOutcome(body, True, (f"✂️ 正在编辑：{target}",))


def fs_undo(args: dict, root=None) -> ToolOutcome:
    """恢复该路径最新一份备份；当前状态同样先备份，所以撤销可逆。"""
    workspace = _workspace_root(root)
    target = resolve_workspace_path(args.get("path"), workspace)
    backup = _latest_backup(target, workspace)
    if backup is None:
        raise ToolError("这个路径没有可撤销的备份", code="fs_no_backup")
    current_backup = _restore_backup(target, backup, workspace)
    body = f"已撤销：{target}\n恢复自：{backup}"
    if current_backup is not None:
        body += f"\n当前状态备份：{current_backup}"
    else:
        body += "\n原文件此前不存在，没有当前状态备份"
    return ToolOutcome(body, True, (f"↩️ 正在撤销：{target}",))


def _clip(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"


def write_tools(root) -> list:
    """装配三个写工具；``root`` 是唯一工作区根（调用方已做配置校验）。"""
    workspace = _workspace_root(root)
    root_text = str(workspace)
    workspace_rule = (
        f"只能写工作区目录：{root_text}。写之前不用问，但要在回复里告诉用户你写了什么。"
    )
    return [
        ToolSpec(
            "fs_write",
            "在工作区目录内创建或覆写一个 UTF-8 文本文件（同目录原子写入，"
            "目标已存在时自动把旧内容备份到 .feiyu-backup）。"
            f"{workspace_rule}单文件上限 256 KB；不允许二进制。",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内的文件路径（相对工作区或绝对路径）"},
                    "content": {"type": "string", "description": "要写入的完整 UTF-8 文本"},
                },
                "required": ["path", "content"],
            },
            lambda args: fs_write(args, workspace),
        ),
        ToolSpec(
            "fs_edit",
            "在工作区目录内定点替换一段文本：old_text 必须恰好出现一次，"
            "替换后走与 fs_write 相同的原子写与备份通道。"
            f"{workspace_rule}old_text / new_text 各上限 8 KB；出现 0 次或多次都会报错。",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内的文件路径"},
                    "old_text": {"type": "string", "description": "要替换的原文（必须唯一）"},
                    "new_text": {"type": "string", "description": "替换后的新文本"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            lambda args: fs_edit(args, workspace),
        ),
        ToolSpec(
            "fs_undo",
            "撤销工作区内某个文件最近一次写入/编辑：恢复最新一份 .feiyu-backup 备份，"
            "并先把当前状态也备份一份，所以再撤销一次可以回到撤销前。"
            f"{workspace_rule}没有备份时会明确报错。",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内要撤销的文件路径"},
                },
                "required": ["path"],
            },
            lambda args: fs_undo(args, workspace),
        ),
    ]


#: 兼容可能的调用方命名；与 :func:`write_tools` 同一实现。
fs_write_tools = write_tools
