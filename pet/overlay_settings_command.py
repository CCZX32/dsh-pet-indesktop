# -*- coding: utf-8 -*-
"""D12：独立设置进程 → 主进程的「退出子肥鱼」指令通道（零 Qt 纯逻辑）。

设计稿：``.scratch/single-overlay-window/PHASE4_DESIGN.md``（§4 D12 / §5 4.2c）。

问题：子肥鱼是**进程内 sprite**，独立设置进程（``--settings``，
settings.lock 单实例）里点「一键退出子肥鱼」无法跨进程删 sprite；已退役的
旧回退链（runtime 标记/slot 锁 + taskkill 子进程）在进程内形态下找不到任何
目标，按钮必然静默失效。

机制：设置进程把一条指令原子写进配置目录的运行时状态文件，主进程（overlay
壳 / legacy AppShell）经 config 目录 watcher + 定时轮询消费，命中后执行各自的
``clear_spawned_pets`` / ``exit_pet``。4.4b 起**两个拓扑共用这一条通道**（多进程
多宠退役层删除后不再有跨进程子宠；见 modern_settings_dialog._on_clear_spawned_pets）。

第二条指令 ``CMD_APPLY_SETTINGS_RESET``（issue #220 M10）走同一条通道，语义是
「设置页刚把全部设置恢复默认，请做一次重置级运行态对齐」（当前 = 位置回默认落位）：
位置类键 ``rx/ry`` 被重置成 null（没有位置记忆），运行期不跟着对齐的话，本次退出
``save_position()`` 会把重置前的旧位置写回磁盘、重置被静默抵消。

硬约束（本模块承载的纯逻辑部分）：

- **原子写**：临时文件 + ``os.replace``（命名与 ``overlay_spawn_state`` /
  ``Config.save`` 同惯例），读取方永远看到完整 JSON 或旧内容；
- **消费即删**：``consume_command`` 读到内容就摘除文件——包括损坏/未知/陈旧
  指令，否则 3s 轮询会把坏文件永远重放；读失败（被占用/权限）不摘除，留给下
  一轮重试，绝不吞掉用户的一次点击；
- **损坏/未知指令静默跳过**：返回 None + 一行日志，绝不抛给 GUI；
- **陈旧丢弃**：``issued_at`` 超过 ``DEFAULT_MAX_AGE_S`` 的指令视为"桌宠当时
  没在跑"，丢弃并留日志（否则设置页关掉桌宠后再开，会突然清空全部子肥鱼）；
- **身份**：``target`` 为 slot 编号 = 只退那一只；``None`` = 全部子肥鱼。

拓扑门 ``is_overlay_topology`` 也收口在本模块：设置进程必须按拓扑分流，而
``pet/__main__.py --settings`` 禁止导入重量级模块（pet.app / overlay_shell，
会连带素材库/ffmpeg/托盘），所以拓扑读取的唯一实现放在这个零 Qt 模块，
``overlay_shell.is_overlay_topology`` 只做转发（对外入口名不变）。

拓扑输入有两个（T4 落地，Phase A）：

1. ``PET_RENDER_TOPOLOGY`` 显式 env = dev 逃生门，**显式值优先**（测试与开发
   都要能压过用户配置）；
2. 主配置 ``config.json`` 的 ``stream_capture_mode``：勾选「直播捕获兼容」即
   **重启级切换**到 legacy 单窗 PetWindow 路径（overlay 单合成窗不给 OBS
   枚举的窗口）。**进程内快照一次**（T5：启动时定死，不做运行时切换）——
   否则用户在设置页勾上以后，正在跑的这一进程会中途翻拓扑。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from pathlib import Path

# 配置目录口径复用 ``config`` 的既有解析（``app.main`` 的
# ``config_dir = _default_base() / APP_DIR_NAME`` 同源）。模块级导入是有意的：
# 拓扑门要在**测试里**能被钉到临时目录（conftest 的隔离夹具替换本模块的
# ``_default_base``），函数内 ``from .config import ...`` 会绕开这层注入。
# ``config`` 是零 Qt 轻模块，独立设置进程本来就 import 它（``Config``），
# 不会让本模块失去"两侧都能 import"的定位。
from .config import APP_DIR_NAME, _default_base

logger = logging.getLogger(__name__)

# T5：开发期一次性分流 flag（不进 Config/设置页/schema）。显式值优先于配置。
ENV_TOPOLOGY = "PET_RENDER_TOPOLOGY"
TOPOLOGY_OVERLAY = "overlay"

#: T4：持久键 ``stream_capture_mode`` 也是拓扑输入（勾选 = 重启级切到 legacy
#: 单窗路径，OBS 才能枚举到窗口）。键名与 ``config.py`` 的 schema 同字面量。
STREAM_CAPTURE_KEY = "stream_capture_mode"

#: 拓扑判定的配置快照（T5：进程内只读一次）。按**配置文件路径**分键：生产进程
#: 只有 ``<config_dir>/config.json`` 一条路径（等于"进程内快照一次"），测试用
#: 临时目录各自独立、互不污染。清空见 ``reset_topology_snapshot``。
_CAPTURE_SNAPSHOT: dict[Path, bool] = {}

# 指令文件：运行时状态文件，刻意不带 config- 前缀——既不进旧 slot 配置 glob
# （agent_link/config 迁移），也不与 runtime 标记 glob 相撞。与
# overlay-active-pets.json 平级。
COMMAND_FILENAME = "overlay-settings-command.json"
COMMAND_VERSION = 1

# 已知指令：设置页「一键退出子肥鱼」（全部子肥鱼 / 指定 slot 身份）、
# 「恢复默认设置」后的运行态对齐（issue #220 M10：位置回默认落位等，
# 见 pet/settings_reset_defaults.py）。
CMD_EXIT_SPAWNED_PETS = "exit_spawned_pets"
CMD_APPLY_SETTINGS_RESET = "apply_settings_reset"
KNOWN_COMMANDS = frozenset({CMD_EXIT_SPAWNED_PETS, CMD_APPLY_SETTINGS_RESET})

# 指令保鲜窗口：超过即视为"写下时主进程不在跑"。
DEFAULT_MAX_AGE_S = 120.0

_SLOT_INSTANCE_RE = re.compile(r"^slot-(\d+)$")


def _explicit_env_verdict() -> bool | None:
    """显式 env 逃生门的判定：``legacy`` → 非 overlay；其它非空值 → overlay。

    未设置 / 空白 → None（不是判定，只表示"env 没有发话"，交给配置判定）。大小写
    与首尾空白不敏感（历史契约）。
    """
    raw = os.environ.get(ENV_TOPOLOGY, "").strip().lower()
    if not raw:
        return None
    return raw != "legacy"


def env_forces_legacy() -> bool:
    """显式 ``PET_RENDER_TOPOLOGY=legacy``？（dev 逃生门，运行期即时切换）。

    设置页文案要用它区分「本进程就是 legacy，开关即时生效」与「默认路径：开关
    是重启级拓扑输入」（见 ``settings_pet_controls.stream_capture_hint``）。
    """
    return _explicit_env_verdict() is False


def topology_config_path() -> Path:
    """主配置 ``config.json`` 的路径（复用 config 的既有目录解析，不另拼一份）。

    ``app.main`` 的 ``config_dir = _default_base() / APP_DIR_NAME`` 是同一口径。
    取**主配置**而不是当前 instance 的槽位配置：捕获模式是进程级（重启后整个
    进程只起主宠物）的重启级开关，槽位配置里的同名键不参与拓扑判定。
    """
    return _default_base() / APP_DIR_NAME / "config.json"


def _read_stream_capture_mode(path: Path) -> bool:
    """读 ``config.json`` 的捕获开关；文件缺失/损坏/不可读一律 False（overlay）。

    读配置绝不允许拖垮启动：设置目录可能是只读盘、被别的进程占住，或用户手改
    成半截 JSON。布尔清洗复用 ``config._bool_or_default``（手改 ``"true"`` /
    ``"1"`` / ``"on"`` 同样算开启），不另造一套解析。
    """
    from .config import _bool_or_default

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("拓扑门：捕获模式配置不可读，按未开启处理: %s", path,
                     exc_info=True)
        return False
    if not isinstance(data, dict):
        logger.warning("拓扑门：配置不是对象，捕获模式按未开启处理: %s", path)
        return False
    return bool(_bool_or_default(data.get(STREAM_CAPTURE_KEY), False))


def stream_capture_mode_enabled(path: Path | str | None = None) -> bool:
    """主配置是否开启「直播捕获兼容」（True = 本进程应走 legacy 单窗）。

    ``path`` 缺省 = ``topology_config_path()``（生产唯一入参）；显式传入只为
    测试/诊断。首次读取即快照，之后同路径的判定不再回读磁盘（T5）。
    """
    target = Path(path) if path is not None else topology_config_path()
    cached = _CAPTURE_SNAPSHOT.get(target)
    if cached is None:
        cached = _read_stream_capture_mode(target)
        _CAPTURE_SNAPSHOT[target] = cached
    return cached


def reset_topology_snapshot() -> None:
    """清掉拓扑配置快照（仅测试/诊断用；生产进程启动后只读一次就定死）。"""
    _CAPTURE_SNAPSHOT.clear()


def is_overlay_topology() -> bool:
    """当前进程是否 overlay 拓扑（T5：唯一读取实现，启动时定死）。

    判定顺序：

    1. ``PET_RENDER_TOPOLOGY`` 显式值（dev 逃生门，优先）；
    2. 否则读主配置的 ``stream_capture_mode``：开启 → legacy（捕获模式重启级
       切换，T4），关闭/读不到 → overlay（默认拓扑）。

    不做运行时切换：配置判定在首次读取时快照（``stream_capture_mode_enabled``），
    设置页勾选只影响**下一次启动**。
    """
    explicit = _explicit_env_verdict()
    if explicit is not None:
        return explicit
    return not stream_capture_mode_enabled()


def capture_switch_is_restart_level() -> bool:
    """本进程的「重启级」判定：拓扑由主配置捕获开关造成？

    True = 本次启动的（legacy）单窗形态就是 ``config.json`` 的捕获开关造成的，
    所以那个键是**重启级**开关：运行期热切换（``PetWindow.refresh_pet_settings``
    → ``window_screen.set_stream_capture_mode``）不得执行，否则用户在设置页点一下
    就会把正在被 OBS 捕获的窗口当场变回 Tool 窗口（直播断源），与设置页
    「重启后生效」的文案自相矛盾。

    显式 ``PET_RENDER_TOPOLOGY=legacy``（dev 逃生门）下主配置捕获开关为假 →
    False → 保留原有的运行期即时切换语义（那是开发期分流，不是用户开关）。
    默认 overlay 进程同样读 False，但那边本来就没有 PetWindow 消费它。
    """
    return stream_capture_mode_enabled()


def effective_stream_capture_mode(window_value) -> bool:
    """窗口能力该用的捕获开关（主配置压过窗口自己那份配置）。

    ``PetWindow`` 读的是**自己那份** ``Config``：``--slot N`` 启动出来的窗读
    ``config-slot-N.json``（``window.py`` 的窗旗标构造）。而拓扑只看主配置，
    于是"主配置 true + slot 配置 false"会让窗口落在 legacy 单窗形态里却仍是
    Tool 窗口——OBS 依旧枚举不到，正是捕获模式要解决的症状。故主配置开启时
    以它为准（不改写 slot 配置，只影响本次窗口能力的有效值）；主配置关闭时
    按窗口自己那份配置（env 逃生门下仍是逐窗可切）。
    """
    if stream_capture_mode_enabled():
        return True
    return bool(window_value)


def slot_from_instance_id(instance_id) -> int | None:
    """``"slot-3"`` → 3；主身份/非法值 → None（纯逻辑，设置页分流用）。"""
    match = _SLOT_INSTANCE_RE.match(str(instance_id or "").strip())
    if match is None:
        return None
    return int(match.group(1))


def command_path(config_dir: Path | str) -> Path:
    """指令文件路径：``<config_dir>/overlay-settings-command.json``。"""
    return Path(config_dir) / COMMAND_FILENAME


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_target(target) -> int | None:
    """target 合法化：None 或 >=1 的 int；其它（含 bool/字符串）→ None 表示非法。"""
    if target is None:
        return None
    if isinstance(target, bool) or not isinstance(target, int):
        return None
    return target if target >= 1 else None


def write_command(config_dir: Path | str, command: str, *, target=None,
                  now: float | None = None, issuer_pid: int | None = None) -> bool:
    """原子写一条指令（tmp + ``os.replace``）。返回是否落盘成功。

    写失败只返回 False + 留日志，不抛：调用方是设置页按钮回调，环境不可写
    （只读盘/目录被文件占住）不该炸掉设置窗口。
    """
    name = str(command or "")
    if name not in KNOWN_COMMANDS:
        logger.warning("指令通道：拒绝写入未知指令 %r", command)
        return False
    clean_target = _normalize_target(target)
    if target is not None and clean_target is None:
        logger.warning("指令通道：拒绝写入非法 target %r", target)
        return False
    path = command_path(config_dir)
    payload = {
        "version": COMMAND_VERSION,
        "command": name,
        "target": clean_target,
        "issued_at": time.time() if now is None else float(now),
        "issuer_pid": os.getpid() if issuer_pid is None else int(issuer_pid),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        logger.warning("指令通道：写指令文件失败: %s", path, exc_info=True)
        return False
    return True


def _read_text(path: Path) -> str | None:
    """读指令文件正文；缺失返回空串语义（None=读不到，调用方区分处理）。

    返回 ``""`` 表示"文件不存在"（正常常态），返回 None 表示读失败
    （占用/权限/编码）——两者对调用方的处置不同：前者静默，后者保留重试。
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError:
        logger.warning("指令通道：指令文件不可读，留给下一轮重试: %s", path)
        return None


def _parse(raw: str, *, now: float, max_age_s: float) -> dict | None:
    """校验指令正文：损坏/未知/缺字段/陈旧一律 None + 日志（绝不抛）。"""
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("指令通道：指令文件损坏，已跳过")
        return None
    if not isinstance(data, dict):
        logger.warning("指令通道：指令不是对象，已跳过")
        return None
    if data.get("version") != COMMAND_VERSION:
        logger.warning("指令通道：指令版本不匹配 (%r)，已跳过", data.get("version"))
        return None
    name = data.get("command")
    if name not in KNOWN_COMMANDS:
        logger.warning("指令通道：未知指令 %r，已跳过", name)
        return None
    issued_at = _finite(data.get("issued_at"))
    if issued_at is None:
        logger.warning("指令通道：指令缺少合法 issued_at，已跳过")
        return None
    if now - issued_at > float(max_age_s):
        logger.warning("指令通道：陈旧指令已丢弃 (%.1fs 前)",
                       now - issued_at)
        return None
    target = data.get("target")
    if target is not None and _normalize_target(target) is None:
        logger.warning("指令通道：指令 target 非法 (%r)，已跳过", target)
        return None
    return {
        "version": COMMAND_VERSION,
        "command": str(name),
        "target": _normalize_target(target),
        "issued_at": issued_at,
        "issuer_pid": data.get("issuer_pid"),
    }


def read_command(config_dir: Path | str, *, now: float | None = None,
                 max_age_s: float = DEFAULT_MAX_AGE_S) -> dict | None:
    """诊断用读（**不消费**）：返回合法指令 dict，否则 None。"""
    raw = _read_text(command_path(config_dir))
    if not raw:
        return None
    return _parse(raw, now=time.time() if now is None else float(now),
                  max_age_s=max_age_s)


def consume_command(config_dir: Path | str, *, now: float | None = None,
                    max_age_s: float = DEFAULT_MAX_AGE_S) -> dict | None:
    """消费指令：读到内容即摘除文件，返回合法指令 dict（否则 None）。

    摘除在解析**之前**：坏文件也必须在一次消费里消失，否则 3s 轮询会永远重放
    同一份坏内容。摘除失败则本轮不执行（宁可漏一次点击，也不让同一条指令被
    反复执行）。读失败不摘除（下一轮重试）。
    """
    path = command_path(config_dir)
    raw = _read_text(path)
    if not raw:
        return None
    try:
        path.unlink()
    except FileNotFoundError:
        pass  # 已被别的消费者摘走（overlay 只有主进程消费，防御而已）
    except OSError:
        logger.warning("指令通道：指令文件摘除失败，本轮不执行: %s", path)
        return None
    return _parse(raw, now=time.time() if now is None else float(now),
                  max_age_s=max_age_s)
