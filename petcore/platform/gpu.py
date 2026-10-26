"""GPU 占用数据源（零 Qt、零线程、零新依赖）：Windows PDH 的「最忙引擎」占用。

移植自主分支 ``pet/gpu_monitor.py``，口径与失败面原样保留。本模块只回答"此刻最忙的
那个 GPU 引擎占用多少、在哪块适配器上"；采样节拍归 :mod:`petcore.platform.gpu_monitor`。
本模块**不建线程**，也**不在导入 / 构造期碰 PDH**：没有第一次 :meth:`GpuReader.read`
就没有 query（GPU 段没被订阅时，``pdh.dll`` 一次都不该被装载）。

口径（每一条都是主分支探针实测结论，本批只做移植不改口径）
--------------------------------------------------------------------------------
1. **引擎身份是 ``(luid, phys, eng)``，不是 engtype**。实例名文法
   ``pid_<pid>_luid_<hi>_<lo>_phys_<n>_eng_<n>_engtype_<名字>``，``engtype`` 含空格
   （``Compute 0`` / ``Video Codec 0``），只能是行尾捕获组。探针实测同一
   ``(luid,phys)`` 下 17 个不同引擎共用 engtype ``3D``——按 engtype 聚合会把 17 个
   独立硬件引擎混成一条，所以聚合键必须是引擎序数。
2. **三级聚合，量纲各不相同**：引擎级 = 同一 ``(luid,phys,eng)`` 跨 pid **求和**并夹紧
   [0,100]；适配器级 = 该适配器全部引擎取 **max**；跨适配器取 **max**。引擎各有独立
   计时器，跨引擎相加的算术上界是 17×100%，所以那个数**不是百分比**。本模块报的是
   "最忙 GPU 引擎占用"，**不是总算力百分比**（见 :data:`UNIT_FULL`）。
3. **首拍只建基线**：速率型计数器注册后第一拍没有参照区间
   （``PDH_CSTATUS_INVALID_DATA``），报 ``sampling`` 而不是伪造 0。**长停恢复同样重建
   基线**：query 句柄留着（重建要再付一次注册成本），但超过 :data:`MAX_SAMPLE_GAP_SECONDS`
   的第一拍只建基线——窗口平均不等于"此刻"。
4. **不可用一定是非 0 语义**：``percent=None`` + 具体 ``error_reason``，绝不报 0。
   ``PDH_NO_DATA``（采集在跑但没数据）与"本机没有这个计数器对象"是两个失败面，分别
   映射到 ``unknown`` 与 ``error``；非 Windows 平台明确 ``unsupported``。
5. **无名字的适配器按真实 LUID 标识，不猜名字**：DXGI 与 PDH 的适配器身份不保证一致
   （实测 DXGI 5 个 / PDH 4 个，交集 3 个）。名字只从 DXGI 来，拿不到就如实显示 LUID。
   **DXGI 失败不影响读数**：不剔除任何适配器、不改任何数值，只把原因记进
   ``detail["names_error"]``。软件适配器只在 DXGI 明确告知时才剔除。
6. **有界**：数组读取两段式（先问尺寸再取数据），两次调用之间实例数可能增长，按新
   尺寸**有界重试**；条数与字节双上限，绝不为来路不明的尺寸分配缓冲区。**不用线程超时
   去"取消"系统 API**：PDH 调用在调用线程里同步做完，超时只会制造"还在跑的调用 + 已经
   放弃的调用方"这种更坏的组合。

线程纪律
--------
query 在**第一次 :meth:`GpuReader.read` 的调用线程**里创建，跨线程读会被明确拒绝
（返回 ``error`` 样本、不碰 PDH）——"别在 GUI 线程建 query"的机器化守卫。唯一的例外
是 owner 线程**已经退出**：那时句柄没有任何可能的并发使用者，新线程直接接管并重建
基线（:meth:`GpuReader.read` 的选择见其文档）；否则 :class:`~petcore.platform.sampling.SamplingLoop`
没有线程退出钩子，每一次 stop/start 都会把上一代的 query 永久留在手里。

两个已登记在案的"静默出 0"陷阱在这里没有可乘之机：通配计数器只走数组 API（标量读在
多实例计数器上命中哪个实例不确定），数组项一律按 ``szName`` 建键（raw/formatted 两个
数组下标可能错序，按下标 zip 会把 A 引擎的原始值配到 B 引擎上）。
"""

from __future__ import annotations

import ctypes
import logging
import math
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 口径常量
#: 计数器路径。``PdhAddEnglishCounterW`` 用英文名，不受系统语言影响。
COUNTER_PATH = r"\GPU Engine(*)\Utilization Percentage"
#: 计数器对象名（仅用于诊断文案；**不做**全表枚举，实测 0.56s）。
OBJECT_NAME = "GPU Engine"
#: 卡片的说明口径——**防误读**：这个数不是总算力。
UNIT_FULL = "最忙 GPU 引擎占用（非总算力）"
SOURCE_TEXT = "PDH \\GPU Engine(*)\\Utilization Percentage"
#: 最坏宽度样本：读数夹紧在 0–100，所以 ``100%`` 就是真的最坏样本。
MAX_TEXT = "100%"
#: 无读数时的占位文案（与 ``island.segments.UNKNOWN_TEXT`` 同一口径）。
UNKNOWN_TEXT = "--"

#: 段状态词表（与 ``island.segments.STATES`` 逐字一致；本层不 import 下游业务域）。
STATE_OK = "ok"
STATE_SAMPLING = "sampling"
STATE_UNKNOWN = "unknown"
STATE_ERROR = "error"
STATE_UNSUPPORTED = "unsupported"
STATES = frozenset({STATE_OK, STATE_SAMPLING, STATE_UNKNOWN, STATE_ERROR, STATE_UNSUPPORTED})
#: 词表外的状态一律降到它——契约违约必须被看见，不能被当成可信读数。
STATE_FALLBACK = STATE_ERROR

#: 一次数组读取最多接受的实例条数。本机实测 430 条；留 10 倍余量仍越界，说明数据源
#: 已经不是"每引擎每进程一条"，此时宁可报错也不分配那块缓冲区。
MAX_ENGINE_ITEMS = 4096
#: 数组缓冲区的字节上限（条目上限 × 每条 64 字节的宽裕估法：真身 24 字节）。
#: 条数与字节**两个都要卡**：只卡条数的话，"条数很小、尺寸很大"的应答照样能撑爆内存。
MAX_ARRAY_BYTES = MAX_ENGINE_ITEMS * 64
#: 两段式读取的重试上限（缓冲区竞态：问完尺寸之后实例数又涨了）。
MAX_ARRAY_RETRIES = 3
#: 单个实例名的字符上限（实测名字约 60 字符）：到上限还没终止符就判为不可信。
MAX_INSTANCE_NAME_CHARS = 512
#: 采样间隔超过它就算"长停"：恢复后的第一拍只重建基线，不当即时读数报出去。
MAX_SAMPLE_GAP_SECONDS = 5.0

# ---------------------------------------------------------------- PDH 状态码
PDH_CSTATUS_VALID_DATA = 0x00000000
PDH_CSTATUS_NEW_DATA = 0x00000001
PDH_CSTATUS_NO_INSTANCE = 0x800007D1
PDH_MORE_DATA = 0x800007D2
PDH_NO_DATA = 0x800007D5
PDH_CSTATUS_NO_OBJECT = 0xC0000BB8
PDH_CSTATUS_NO_COUNTER = 0xC0000BB9
PDH_CSTATUS_INVALID_DATA = 0xC0000BBA
PDH_INVALID_HANDLE = 0xC0000BBC

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOSCALE = 0x00001000
#: 显式不封顶：默认行为是把百分比封顶在 100，显式传 NOCAP100 之后"要不要夹紧、在哪里
#: 夹紧"就是我们自己写在代码里可测的决策，而不是 PDH 的隐式默认。
PDH_FMT_NOCAP100 = 0x00008000
_FORMAT = PDH_FMT_DOUBLE | PDH_FMT_NOSCALE | PDH_FMT_NOCAP100

_STATUS_NAMES = {
    PDH_CSTATUS_VALID_DATA: "PDH_CSTATUS_VALID_DATA",
    PDH_CSTATUS_NEW_DATA: "PDH_CSTATUS_NEW_DATA",
    PDH_CSTATUS_NO_INSTANCE: "PDH_CSTATUS_NO_INSTANCE",
    PDH_MORE_DATA: "PDH_MORE_DATA",
    PDH_NO_DATA: "PDH_NO_DATA",
    PDH_CSTATUS_NO_OBJECT: "PDH_CSTATUS_NO_OBJECT",
    PDH_CSTATUS_NO_COUNTER: "PDH_CSTATUS_NO_COUNTER",
    PDH_CSTATUS_INVALID_DATA: "PDH_CSTATUS_INVALID_DATA",
    PDH_INVALID_HANDLE: "PDH_INVALID_HANDLE",
}

#: 实例名文法（实测 430/430 全部匹配）。``pid`` 只用于区分实例，不进聚合键；
#: ``engtype`` 可能含空格，必须是行尾捕获组。
_ENGINE_INSTANCE_RE = re.compile(
    r"^pid_\d+_luid_(0x[0-9A-Fa-f]+)_(0x[0-9A-Fa-f]+)"
    r"_phys_(\d+)_eng_(\d+)_engtype_(.+)$",
)


class GpuUnavailable(RuntimeError):
    """GPU 采集不可用（平台不支持 / 系统 API 失败）——读数不可用，**不是** 0。"""


class PdhError(GpuUnavailable):
    """PDH 调用返回非零 ``PDH_STATUS``。"""

    def __init__(self, status: int, message: str = ""):
        self.status = int(status) & 0xFFFFFFFF
        super().__init__(message or _status_name(self.status))


class DxgiUnavailable(GpuUnavailable):
    """DXGI 适配器枚举失败（名字不可用）。**不影响 PDH 读数**，只影响标签。"""


def _status_name(status: int) -> str:
    return _STATUS_NAMES.get(int(status) & 0xFFFFFFFF, "0x%08X" % (int(status) & 0xFFFFFFFF))


def _platform_supported() -> bool:
    """本模块的数据源只在 Windows 上存在（PDH / DXGI）。测试按此分支打桩。"""
    return sys.platform == "win32"


def normalize_state(value: Any) -> str:
    """状态串归一；**词表外的值一律不算 ``ok``**（降为 :data:`STATE_FALLBACK`）。

    下游用同一份词表渲染（``ok`` 才有真读数，其余画同宽 ``--``）。把未知串原样传下去
    会让呈现层与判定层对"这拍可不可信"得出不同结论，所以在数据类型上就钉死。
    """
    text = "" if value is None else str(value).strip().lower()
    return text if text in STATES else STATE_FALLBACK


def _finite(value: Any) -> float | None:
    """有限浮点；NaN / ±inf / 非数字一律 None（**不当作 0 计入**）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_name(address: Any, base: int, end: int) -> str | None:
    """读数缓冲区里的一个实例名指针 → 字符串；**不可信就返回 None**（绝不越界解引用）。

    PDH 把实例名写进我们分配的那同一块缓冲区（名字区紧跟条目数组之后）。所以这里的
    边界与终止符检查不是对合法用法设卡：真 PDH 的名字永远在界内。落到界外或没有终止符，
    说明读数缓冲区的契约已经不成立（并发改写 / 内存损坏 / 不是真 PDH），此时解引用就是
    在读别人的内存。

    名字是 UTF-16LE（Windows 的 ``wchar_t`` 恰好 2 字节），所以按**字节**读固定长度再
    自己解码，不用 ``ctypes.wstring_at``——后者按**本平台的** ``wchar_t`` 读，同一块
    缓冲区在 POSIX 语义下会把相邻两个 UTF-16 码元拼成一个越界码点。
    """
    try:
        start = int(address or 0)
    except (TypeError, ValueError):
        return None
    if start < base or start + 2 > end:  # 连一个宽字符都放不下
        return None
    limit = min((end - start) // 2, MAX_INSTANCE_NAME_CHARS)
    text = ctypes.string_at(start, limit * 2).decode("utf-16-le", "surrogatepass")
    terminator = text.find("\0")
    return text[:terminator] if terminator >= 0 else None


# ---------------------------------------------------------------- 身份与快照
def canonical_luid(high: Any, low: Any) -> str:
    """LUID 两半 → ``0xHHHHHHHH_0xLLLLLLLL``（8 位十六进制，大小写稳定）。

    这是**唯一的规范化实现**：同一块显卡在 PDH 与 DXGI 里格式化得不一样（大小写 /
    前导零 / 两半顺序），就会出现"一块卡两个键"的静默错配。
    """
    try:
        return "0x%08X_0x%08X" % (int(high) & 0xFFFFFFFF, int(low) & 0xFFFFFFFF)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"LUID 两半必须是整数：{high!r} / {low!r}") from exc


@dataclass(frozen=True, order=True)
class EngineKey:
    """硬件引擎身份：**适配器 LUID + 物理序数 + 引擎序数**（不是 engtype）。"""

    luid: str
    phys: int = 0
    eng: int = 0


@dataclass(frozen=True)
class EngineReading:
    """一个硬件引擎的占用（跨进程求和后的结果）。

    ``samples`` 是参与求和的进程条数；``clamped`` 标记这次求和是否被夹到 100
    （浮点毛刺或驱动重复计数时会出现，如实留痕以便排查）。
    """

    key: EngineKey
    percent: float
    engtype: str = ""
    samples: int = 1
    clamped: bool = False


@dataclass(frozen=True)
class AdapterInfo:
    """DXGI 侧的适配器身份（**只有名字与软件标志**；利用率一律来自 PDH）。"""

    luid: str
    name: str = ""
    is_software: bool = False


@dataclass(frozen=True)
class AdapterReading:
    """一块适配器的占用 = 它全部引擎里的 **max**（引擎各有独立计时器，不能相加）。"""

    luid: str
    percent: float = 0.0
    busiest: EngineReading | None = None
    name: str = ""
    is_software: bool | None = None


@dataclass(frozen=True)
class GpuSample:
    """一个采样周期的结果快照（GUI 侧只读它，不做任何 syscall）。

    ``state`` 用段契约的词表：``ok`` 才有真读数；其余状态一律 ``percent=None``
    （呈现层画同宽的 ``--``），原因在 ``error_reason`` 与 ``detail`` 里，**绝不伪造 0**。
    这些不变量在 :meth:`__post_init__` 里钉死：构造一个自相矛盾的样本（``ok`` 却没有
    有限读数、非 ``ok`` 却带着读数、词表外的状态串、非 ``ok`` 却没有原因）会被就地
    归一，不让它流到呈现层。
    """

    percent: float | None
    sampled_at: float
    state: str = STATE_OK
    error_reason: str = ""
    #: 最忙的适配器（``percent`` 就是它）；降级样本为 None。
    adapter: AdapterReading | None = None
    #: 全部适配器（被 DXGI 明确判为软件的已剔除）。
    adapters: tuple[AdapterReading, ...] = ()
    #: 卡片 B 区的行素材（``unit_full``/``source``/``detail``，失败时加 ``error_reason``，
    #: DXGI 名字不可用时加 ``names_error``）。
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        state = normalize_state(self.state)
        reason = "" if self.error_reason is None else str(self.error_reason)
        percent = self.percent
        if state == STATE_OK:
            number = _finite(percent)
            if number is None:
                # ok + 没有有限读数 = 自相矛盾的样本：宁可按不可用报，也不放一个 0 出去。
                logger.warning("GPU 样本：ok 状态却缺少有限读数，已降级为 error")
                state = STATE_ERROR
                reason = reason or "ok 样本缺少有限读数"
                percent = None
            else:
                percent = min(100.0, max(0.0, number))
        else:
            percent = None
            if not reason and state != STATE_SAMPLING:
                reason = "读数不可用（数据源未给出原因）"
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "percent", percent)
        object.__setattr__(self, "error_reason", reason)


def format_gpu(percent: Any) -> str:
    """GPU 占用 → ``"24%"``；无读数 / 非数字 / 非有限 → ``"--"``（不伪造 0）。"""
    number = _finite(percent)
    return UNKNOWN_TEXT if number is None else f"{number:.0f}%"


def adapter_label(adapter: AdapterReading | None) -> str:
    """适配器 → 呈现标签（``"<名字> · <引擎>"``）。

    **没有名字就用真实 LUID**（DXGI 未列举该 luid 是实测存在的情况），绝不编一个
    "GPU 1" 之类会被读成真实设备名的标签——机器的谎话比"未命名"更坏。
    """
    if adapter is None:
        return ""
    head = adapter.name or f"{adapter.luid}(未命名适配器)"
    engine = adapter.busiest.engtype if adapter.busiest is not None else ""
    return f"{head} · {engine}" if engine else head


# ---------------------------------------------------------------- 纯聚合
def parse_engine_instance(name: Any) -> tuple[EngineKey, str] | None:
    """实例名 → ``(EngineKey, engtype)``；不认识的名字返回 ``None``（不猜）。"""
    if not isinstance(name, str):
        return None
    match = _ENGINE_INSTANCE_RE.match(name)
    if match is None:
        return None
    high, low, phys, eng, engtype = match.groups()
    try:
        key = EngineKey(canonical_luid(int(high, 16), int(low, 16)), int(phys), int(eng))
    except ValueError:
        return None
    return key, engtype


def group_engines(items) -> tuple[EngineReading, ...]:
    """① 引擎级：``(实例名, 读数)`` → 按 ``(luid,phys,eng)`` 跨 pid **求和**并夹紧 [0,100]。

    - 读数是**顺序无关**的：输出按 :class:`EngineKey` 定序；同一键上出现冲突的
      ``engtype``（实测 0 冲突，但不赌它永远不发生）取字典序最小的那个。
    - NaN / ±inf / 非数字 / 解析不了的实例名一律跳过：跳过是"这一项没有有效数据"，
      计成 0 会把"读不到"洗成"GPU 空闲"。
    """
    totals: dict[EngineKey, float] = {}
    counts: dict[EngineKey, int] = {}
    types: dict[EngineKey, set[str]] = {}
    for item in items or ():
        try:
            name, value = item
        except (TypeError, ValueError):
            continue
        parsed = parse_engine_instance(name)
        if parsed is None:
            continue
        key, engtype = parsed
        number = _finite(value)
        if number is None:
            continue
        totals[key] = totals.get(key, 0.0) + number
        counts[key] = counts.get(key, 0) + 1
        types.setdefault(key, set()).add(engtype)
    readings = []
    for key in sorted(totals):
        raw = totals[key]
        readings.append(EngineReading(
            key=key,
            percent=min(100.0, max(0.0, raw)),
            engtype=min(types[key]),
            samples=counts[key],
            clamped=raw > 100.0,
        ))
    return tuple(readings)


def adapter_readings(engines, *, known: Mapping[str, AdapterInfo] | None = None,
                     ) -> tuple[AdapterReading, ...]:
    """②③ 适配器级取 **max over engines**；``known`` 里的软件适配器**才**被剔除。

    ``known`` 是 DXGI 给的 ``luid → AdapterInfo``；``None`` = 名字与软件标志**都不可用**
    （DXGI 失败）。此时一块适配器都不剔、一个数值都不改，``is_software`` 保持"不知道"
    ——拿不到名字就按 0 / 按"正常"处理，正是要避免的那种静默降级。

    luid 在 PDH 有、在 DXGI 没有（实测存在）：保留，``name=""``、``is_software=None``，
    由 :func:`adapter_label` 按 LUID 如实标识。
    """
    grouped: dict[str, list[EngineReading]] = {}
    for engine in sorted(engines or (), key=lambda item: item.key):
        grouped.setdefault(engine.key.luid, []).append(engine)
    readings = []
    for luid in sorted(grouped):
        info = None if known is None else known.get(luid)
        if info is not None and info.is_software:
            continue  # 软件适配器不是一块 GPU——只因为 DXGI 明确说了才剔除
        busiest = max(grouped[luid], key=lambda item: item.percent)  # 同分取引擎序数最小
        readings.append(AdapterReading(
            luid=luid,
            percent=busiest.percent,
            busiest=busiest,
            name=info.name if info is not None else "",
            is_software=None if info is None else bool(info.is_software),
        ))
    return tuple(readings)


def busiest_adapter(adapters) -> AdapterReading | None:
    """④ 跨适配器取 **max**（不是求和、不是平均）；同分取 luid 最小者，结果确定。"""
    best = None
    for adapter in adapters or ():
        if best is None or adapter.percent > best.percent:
            best = adapter
    return best


def _detail(*, reason: str = "", label: str = "", names_error: str = "",
            adapter: AdapterReading | None = None) -> dict:
    """卡片 B 区的行素材（键与 ``island_segments`` 的 detail 口径一致）。"""
    detail = {"unit_full": UNIT_FULL, "source": SOURCE_TEXT, "detail": label}
    if adapter is not None:
        detail["adapter_luid"] = adapter.luid
        detail["adapter_name"] = adapter.name
        detail["engine"] = adapter.busiest.engtype if adapter.busiest is not None else ""
    if reason:
        detail["error_reason"] = reason
    if names_error:
        detail["names_error"] = names_error
    return detail


def _degraded(state: str, reason: str, now: float, *, names_error: str = "") -> GpuSample:
    """降级样本：``percent=None`` + 原因（呈现层画 ``--``，卡片写原因）。"""
    return GpuSample(percent=None, sampled_at=now, state=state, error_reason=reason,
                     detail=_detail(reason=reason, names_error=names_error))


def _reason_for_status(status: int) -> tuple[str, str]:
    """PDH 状态码 → ``(段状态, 人话原因)``。

    三个失败面必须分开：**速率计数器还没基线**是 ``sampling``（再来一拍就有）；
    **采集在跑但当前没数据**是 ``unknown``；**对象/计数器不存在**是 ``error``。
    """
    if status == PDH_CSTATUS_INVALID_DATA:
        return STATE_SAMPLING, "第一拍只建立采样基线，还没有可用的差分区间"
    if status in (PDH_NO_DATA, PDH_CSTATUS_NO_INSTANCE):
        return STATE_UNKNOWN, "GPU 计数器当前没有数据（没有实例在活动）"
    if status == PDH_CSTATUS_NO_OBJECT:
        return STATE_ERROR, f"本机没有 {OBJECT_NAME} 计数器对象（没有可用的 GPU 计数来源）"
    if status == PDH_CSTATUS_NO_COUNTER:
        return STATE_ERROR, f"{OBJECT_NAME} 上找不到 Utilization Percentage 计数器"
    if status == PDH_MORE_DATA:
        return STATE_ERROR, (f"读数数组在 {MAX_ARRAY_RETRIES} 次重试内仍未稳定"
                             "（缓冲区竞态：实例数持续增长）")
    return STATE_ERROR, f"PDH 返回 0x{int(status) & 0xFFFFFFFF:08X}（{_status_name(status)}）"


# ---------------------------------------------------------------- Windows PDH 薄封装
#: 进程内唯一的 PDH 绑定。**惰性**：没有采样请求就一次都不装载。
#: 装载失败是粘性的（:data:`_pdh_error` 非空后不再重试），失败原因照样要能被报出来。
_pdh: WindowsPdh | None = None
_pdh_error = ""
_pdh_lock = threading.Lock()


def _load_pdh():
    """加载并绑定 ``pdh.dll`` 的五个函数（每进程一次）。只在 Windows 上被调用。"""
    dll = ctypes.WinDLL("pdh", use_last_error=True)
    handle = ctypes.c_void_p
    dword = ctypes.c_uint32
    dll.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t,
                                  ctypes.POINTER(handle)]
    dll.PdhOpenQueryW.restype = dword
    dll.PdhAddEnglishCounterW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_size_t,
                                          ctypes.POINTER(handle)]
    dll.PdhAddEnglishCounterW.restype = dword
    dll.PdhCollectQueryData.argtypes = [handle]
    dll.PdhCollectQueryData.restype = dword
    dll.PdhGetFormattedCounterArrayW.argtypes = [handle, dword, ctypes.POINTER(dword),
                                                 ctypes.POINTER(dword), ctypes.c_void_p]
    dll.PdhGetFormattedCounterArrayW.restype = dword
    dll.PdhCloseQuery.argtypes = [handle]
    dll.PdhCloseQuery.restype = dword
    return dll


def pdh_api() -> WindowsPdh | None:
    """进程内唯一的 PDH 封装；不可用返回 ``None``（原因见 :func:`pdh_error`）。"""
    global _pdh, _pdh_error
    if _pdh is not None:
        return _pdh
    if _pdh_error:
        return None
    with _pdh_lock:
        if _pdh is not None:
            return _pdh
        if _pdh_error:
            return None
        if not _platform_supported():
            _pdh_error = "PDH 只在 Windows 上可用"
            return None
        try:
            _pdh = WindowsPdh(_load_pdh())
        except Exception as exc:  # noqa: BLE001 - 装载失败只降级，不炸导入链
            _pdh_error = f"{type(exc).__name__}: {exc}"
            logger.warning("GPU 采集：PDH 装载失败：%s", _pdh_error)
    return _pdh


def pdh_error() -> str:
    """PDH 不可用的原因（可用时为空串）。"""
    return _pdh_error


class _FmtCounterValue(ctypes.Structure):
    """``PDH_FMT_COUNTERVALUE`` 里我们唯一要用的成员（默认对齐下 double 落在偏移 8）。"""

    _fields_ = [("CStatus", ctypes.c_uint32), ("doubleValue", ctypes.c_double)]


class _FmtCounterValueItemRaw(ctypes.Structure):
    """``PDH_FMT_COUNTERVALUE_ITEM_W``，但 ``szName`` 保持**裸指针**。

    刻意不用 ``c_wchar_p``：它会在取字段的那一刻就替我们把指针解引用成字符串，于是
    "这个指针在不在我给的缓冲区内、有没有终止符"就再也检查不了了——那是把一个必须
    自己判断的安全边界交给 ctypes 的隐式行为。布局与 C 结构一致（指针 + CStatus +
    对齐 + double = 24 字节）。
    """

    _fields_ = [("szName", ctypes.c_void_p), ("FmtValue", _FmtCounterValue)]


class WindowsPdh:
    """PDH 的 ctypes 薄封装：句柄进出，**不含任何聚合**（聚合是纯函数，与平台无关）。

    方法集就是 :class:`GpuReader` 真正会调的五个；替身在单测里实现同一组签名。
    """

    def __init__(self, dll=None):
        self._dll = dll

    def _api(self):
        if self._dll is None:
            self._dll = _load_pdh()
        return self._dll

    def open_query(self):
        api = self._api()
        query = ctypes.c_void_p()
        status = api.PdhOpenQueryW(None, 0, ctypes.byref(query))
        if status != 0:
            raise PdhError(status)
        return query

    def add_counter(self, query, path):
        api = self._api()
        counter = ctypes.c_void_p()
        status = api.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter))
        if status != 0:
            raise PdhError(status)
        return counter

    def collect(self, query):
        api = self._api()
        status = api.PdhCollectQueryData(query)
        if status != 0:
            raise PdhError(status)

    def counter_array(self, counter, size=None):
        """两段式数组读取的**单次**调用；重试与上限在 :meth:`GpuReader._read_items` 里。

        ``size=None`` 只问尺寸（返回 ``PDH_MORE_DATA`` 时第二个出参给出所需**字节数**）；
        给出 ``size`` 时按它开缓冲取数据，返回 ``(状态, 最新尺寸, 项数, [(名字, CStatus, 值)…])``。

        **解引用之前的每一层都有界**：① 条目数 ≤ 全局上限；② 条目数 ≤ 申报尺寸装得下的
        条数（``count × sizeof(item)`` 可能远大于实际分配——只卡全局条数不够）；③ 每个
        名字指针都必须落在缓冲区内且以 ``\\0`` 结尾。任一条不成立就不去读那块内存，也
        不把读到的脏字节当成一个合法读数。
        """
        api = self._api()
        declared = 0 if size is None else int(size)
        size_c = ctypes.c_uint32(declared)
        count_c = ctypes.c_uint32(0)
        buffer = None if size is None else ctypes.create_string_buffer(declared)
        status = int(api.PdhGetFormattedCounterArrayW(
            counter, _FORMAT, ctypes.byref(size_c), ctypes.byref(count_c), buffer))
        items: list[tuple[str, int, float]] = []
        if status == 0 and buffer is not None:
            limit = min(int(count_c.value), MAX_ENGINE_ITEMS,
                        declared // ctypes.sizeof(_FmtCounterValueItemRaw))
            base = ctypes.addressof(buffer)
            end = base + declared
            array = ctypes.cast(buffer, ctypes.POINTER(_FmtCounterValueItemRaw))
            dropped = 0
            for index in range(max(0, limit)):
                item = array[index]
                name = _safe_name(item.szName, base, end)
                if name is None:
                    dropped += 1
                    name = ""
                items.append((name, int(item.FmtValue.CStatus),
                              float(item.FmtValue.doubleValue)))
            if dropped:
                logger.warning(
                    "GPU 采集：%d 个实例名的指针越界或没有终止符，已按无名字丢弃"
                    "（不解引用越界内存）", dropped)
        return status, int(size_c.value), int(count_c.value), items

    def close_query(self, query):
        api = self._api()
        status = int(api.PdhCloseQuery(query))
        if status != 0:
            raise PdhError(status)


# ---------------------------------------------------------------- Windows DXGI 薄封装
class _Guid(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, d1, d2, d3, d4):
        super().__init__(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))


class _Luid(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]


class _DxgiAdapterDesc1(ctypes.Structure):
    """``DXGI_ADAPTER_DESC1``：末位多一个 ``Flags``（软件适配器标志在这里）。"""

    _fields_ = [("Description", ctypes.c_wchar * 128),
                ("VendorId", ctypes.c_uint32), ("DeviceId", ctypes.c_uint32),
                ("SubSysId", ctypes.c_uint32), ("Revision", ctypes.c_uint32),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", _Luid), ("Flags", ctypes.c_uint32)]


#: ``IID_IDXGIFactory1``。**必须**按我们真正要调的方法所属的接口取工厂：
#: ``EnumAdapters1`` 是 ``IDXGIFactory1`` 的方法（虚表槽 12）。请求父接口再跨槽调子接口
#: 的方法，是"碰巧能跑"的未定义行为——拿到哪个接口由实现决定，不该靠运气。
_IID_IDXGIFACTORY1 = _Guid(0x770AAE78, 0xF26F, 0x4DBA,
                           (0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
#: COM 虚表槽位（``IUnknown.Release`` / ``IDXGIFactory1::EnumAdapters1`` /
#: ``IDXGIAdapter1::GetDesc1``）。``Release`` 在**每个**接口上都是 2。
_SLOT_RELEASE = 2
_SLOT_ENUM_ADAPTERS1 = 12
_SLOT_GET_DESC1 = 10
DXGI_ADAPTER_FLAG_SOFTWARE = 0x2
#: ``EnumAdapters1`` 用它表示"没有更多适配器了"——是**正常结束**，不是失败。
DXGI_ERROR_NOT_FOUND = 0x887A0002
MAX_DXGI_ADAPTERS = 16


def _com_release(vtable):
    """从**该对象自己的**虚表取 ``IUnknown::Release``。

    ``Release`` 的槽位号在每个接口上都是 2，但函数指针是**每个对象一份**：拿 factory
    的 Release 去放 adapter，在真机上不会报错（同一个槽位、同一个 this 偏移），只会
    错放对象——这是 COM 互操作最经典的静默误用，必须按对象取。
    """
    return ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_SLOT_RELEASE])


def dxgi_adapters() -> dict[str, AdapterInfo]:
    """DXGI 适配器表 ``luid → AdapterInfo``（名字 + 软件标志）。

    **只枚举 + Release**：不创建设备、不改显示模式、不弹窗。

    **失败一律抛 :class:`DxgiUnavailable`，不返回半张表**：``EnumAdapters1`` 只有
    ``DXGI_ERROR_NOT_FOUND`` 是"没有更多适配器"的正常结束；``GetDesc1`` 失败同样不能
    跳过——半张表会让调用方把"我们没读到名字的适配器"当成"DXGI 本来就不认识它"，于是
    无名字 luid 与真故障再也分不开。
    """
    if not _platform_supported():
        raise DxgiUnavailable("DXGI 只在 Windows 上可用")
    try:
        dxgi = ctypes.WinDLL("dxgi")
    except OSError as exc:
        raise DxgiUnavailable(f"加载 dxgi.dll 失败：{exc}") from exc
    dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(_Guid),
                                        ctypes.POINTER(ctypes.c_void_p)]
    dxgi.CreateDXGIFactory1.restype = ctypes.c_long
    factory = ctypes.c_void_p()
    code = dxgi.CreateDXGIFactory1(ctypes.byref(_IID_IDXGIFACTORY1), ctypes.byref(factory))
    if code != 0 or not factory:
        raise DxgiUnavailable("CreateDXGIFactory1 失败：0x%08X" % (code & 0xFFFFFFFF))
    try:
        table = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release_factory = _com_release(table)          # factory 自己的 Release
        enum_adapters1 = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p))(table[_SLOT_ENUM_ADAPTERS1])
        adapters: dict[str, AdapterInfo] = {}
        for index in range(MAX_DXGI_ADAPTERS):
            adapter = ctypes.c_void_p()
            code = enum_adapters1(factory, index, ctypes.byref(adapter)) & 0xFFFFFFFF
            if code == DXGI_ERROR_NOT_FOUND:
                break                                   # 正常结束：没有更多适配器
            if code != 0:
                raise DxgiUnavailable("EnumAdapters1(%d) 失败：0x%08X" % (index, code))
            slot = ctypes.cast(
                adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            release_adapter = _com_release(slot)        # adapter **自己**的 Release
            try:
                get_desc1 = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p,
                    ctypes.POINTER(_DxgiAdapterDesc1))(slot[_SLOT_GET_DESC1])
                desc = _DxgiAdapterDesc1()
                if get_desc1(adapter, ctypes.byref(desc)) != 0:
                    raise DxgiUnavailable(
                        "IDXGIAdapter1::GetDesc1 失败（第 %d 个适配器）：拿不到它的身份"
                        "与软件标志，残缺的表不许当成结果缓存" % index)
                luid = canonical_luid(desc.AdapterLuid.HighPart, desc.AdapterLuid.LowPart)
                adapters[luid] = AdapterInfo(
                    luid=luid, name=desc.Description or "",
                    is_software=bool(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE))
            finally:
                release_adapter(adapter)
        return adapters
    finally:
        release_factory(factory)


# ---------------------------------------------------------------- 线程身份
def _thread_alive(ident: int | None) -> bool:
    """该线程 id 是否还有活着的线程（线程退出后它会从 ``enumerate`` 里消失）。

    不用 ``threading._active``（私有结构）。系统会复用 ident：退出的 owner 被误判为
    存活时按"拒绝"处理——宁可少采一拍，也不在两个线程之间共享一个句柄。
    """
    if ident is None:
        return False
    return any(thread.ident == ident for thread in threading.enumerate())


# ---------------------------------------------------------------- 读数器
class GpuReader:
    """GPU 占用读数器：**惰性 query、单线程、无后台线程**。

    生命周期契约（:class:`~petcore.platform.gpu_monitor.GpuMonitor` 按它接线）：

    - **构造 / 导入期零系统调用**：不装载 ``pdh.dll``、不建 query、不枚举 DXGI。
      第一次 :meth:`read` 才建（那一次要付 provider 装载成本，所以它**必须**发生在
      采样线程里，绝不在 GUI 线程）。
    - **query 属于创建它的线程**：跨线程 ``read``/``close`` 被明确拒绝（``read`` 返回
      ``error`` 样本、``close`` 返回 ``False``，都不碰 PDH）。唯一例外是 owner 线程
      **已经退出**：此时句柄没有任何可能的并发使用者，:meth:`read` 直接接管它并重建
      基线（理由见模块 docstring 的"线程纪律"）。
    - **无订阅时只是不 collect**：句柄留着，宿主停采不必销毁重建（重建要再付一次注册
      成本）；但**恢复后的第一拍仍然只建基线**（见 :data:`MAX_SAMPLE_GAP_SECONDS`）。
    - **``close`` 的成败必须被看见**：重复调用是 no-op，但"没关掉"和"关掉了"是两件事
      ——原生 ``PdhCloseQuery`` 返回错误码时句柄状态**未知**，所以那种情况不报"已关闭"：
      句柄留在手里、``closed`` 保持 False、原因进 :attr:`release_error`，等 owner 线程
      明确再试一次（一次 ``close`` 恰好一次原生调用，这里不做重试循环）。
    """

    def __init__(self, *, api=None,
                 adapter_provider: Callable[[], Mapping[str, AdapterInfo]] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 counter_path: str = COUNTER_PATH,
                 max_gap_seconds: float = MAX_SAMPLE_GAP_SECONDS):
        self._api = api
        self._adapter_provider = adapter_provider
        self._clock = clock
        self._counter_path = counter_path
        self._max_gap = float(max_gap_seconds)
        self._lock = threading.RLock()
        self._query = None
        self._counter = None
        self._owner_thread: int | None = None
        self._primed = False
        self._closed = False
        self._last_collect_at: float | None = None
        self._adapters: Mapping[str, AdapterInfo] | None = None
        self._names_error = ""
        self._adapters_resolved = False
        self._release_error = ""

    # ------------------------------------------------------------ 状态
    @property
    def opened(self) -> bool:
        """是否持有已注册的 PDH query（无订阅的时段里它就是 False）。

        释放失败过（:attr:`release_error` 非空）时它**仍然是 True**：那只句柄没被确认
        收掉，既可能已经失效也可能还有效——这里如实报"还在手上"。
        """
        return self._query is not None

    @property
    def closed(self) -> bool:
        """句柄是否**已确认**放掉（此时再 ``read`` 会重新建 query）。"""
        return self._closed

    @property
    def primed(self) -> bool:
        """当前是否已经有过一次可用的采样基线（首拍为 False）。"""
        return self._primed

    @property
    def owner_thread(self) -> int | None:
        """创建 query 的线程 id（未创建时为 None）。"""
        return self._owner_thread

    @property
    def release_error(self) -> str:
        """上一次释放失败的原因（没有失败时为 ``""``）。

        非空 = 手里还留着一个没确认收掉的 query，只有 owner 线程再试一次 ``close``
        才能把这笔账结掉。诊断用途：宿主能在日志里看见"这条采样链收口没成功"，而不是
        拿到一个假的成功。
        """
        return self._release_error

    # ------------------------------------------------------------ 释放
    def close(self) -> bool:
        """释放 query。返回**句柄是不是真的放掉了**——调用方必须看这个返回值。

        - **幂等**：重复调用、从没读过就调用都是 no-op，返回 ``True``；
        - **守 owner 线程契约**：只有创建它的线程能关闭它。别的线程来 close 时**不碰
          那个句柄**、返回 ``False`` 并记一条 warning——"替别人关掉正在用的 query"
          比"没关掉"危险得多，而默默返回成功会让调用方以为收口完成了；
        - **释放失败如实返回 False**：句柄留在手里、``closed`` 保持 False、原因进
          :attr:`release_error`（原生失败面没有承诺句柄/内存已经收干净）；
        - **有界**：一次调用恰好一次原生尝试，没有内部重试循环；
        - 本方法**不做任何线程 join / 超时强关**：关在 owner 线程里同步完成，用超时去
          "取消"一个正在跑的收尾只会制造"句柄不知道关没关"的第三种状态。
        """
        ident = threading.get_ident()
        with self._lock:
            query = self._query
            if query is not None and self._owner_thread != ident:
                logger.warning(
                    "GPU 采集：close 被非 owner 线程调用（当前 %d，owner %s），"
                    "已拒绝关闭——query 必须由创建它的线程收口",
                    ident, self._owner_thread)
                return False
            if query is None:
                self._release_error = ""
                self._closed = True
                return True
            # 基线/计数器状态先作废（这一代 query 要走了）；**句柄在释放确认前不动**。
            self._counter = None
            self._primed = False
            self._last_collect_at = None
        error = self._release(query)
        with self._lock:
            if error:
                self._release_error = error
                self._closed = False
                return False
            self._query = None
            self._owner_thread = None
            self._release_error = ""
            self._closed = True
            return True

    def __enter__(self) -> GpuReader:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def refresh_adapters(self) -> None:
        """让下一次 ``read`` 重新枚举 DXGI 适配器（名字缓存只在这之前有效）。"""
        with self._lock:
            self._adapters = None
            self._names_error = ""
            self._adapters_resolved = False

    # ------------------------------------------------------------ 读数
    def read(self) -> GpuSample:
        """采样一拍。**只许在采样线程里调用**（query 的创建线程就是采样线程）。

        任何失败都收成一个**带原因**的样本返回，不抛穿调用方——采样线程拿到的是
        "这一拍没有可信读数"，而不是一条炸掉的线程。

        **owner 线程已经退出时接管那只 query**（:func:`_thread_alive`）：句柄是进程级
        资源，退出线程不会回收它；拒绝这里只会让"停采再恢复"永久失效或把句柄永久泄漏。
        接管时基线作废（跨代的时间差没有意义），这一拍按首拍规则只重建基线。

        **上一次释放失败过（:attr:`release_error` 非空）时直接拒绝采样**：手里那只句柄
        状态未知，既不能拿它当"没关掉、接着采"用，也不能在这里重开一只新的把它"覆盖
        丢弃"（那就真的泄露了）。账结清之后 ``read`` 恢复原语义。
        """
        now = float(self._clock())
        api = self._ensure_api()
        if api is None:
            if not _platform_supported():
                return _degraded(STATE_UNSUPPORTED, "GPU 采集只在 Windows 上可用（PDH）", now)
            return _degraded(STATE_ERROR,
                             f"PDH 不可用：{_pdh_error or '未知原因'}", now)
        ident = threading.get_ident()
        with self._lock:
            if self._release_error:
                return _degraded(
                    STATE_ERROR,
                    "上一只 PDH query 释放失败（%s）：句柄状态未知，"
                    "先由 owner 线程重试 close 再采样" % self._release_error,
                    now, names_error=self._names_error)
            owner = self._owner_thread
            if self._query is not None and owner != ident:
                if _thread_alive(owner):
                    return _degraded(
                        STATE_ERROR,
                        "PDH query 只能在创建它的线程里使用（当前线程 %d，创建线程 %s）"
                        % (ident, owner), now)
                logger.info(
                    "GPU 采集：接管已退出线程（%s）留下的 PDH query，基线重建", owner)
                self._owner_thread = ident
                self._primed = False
                self._last_collect_at = None
                self._closed = False
            try:
                query, counter = self._ensure_query(api)
            except PdhError as exc:
                state, reason = _reason_for_status(exc.status)
                return _degraded(state, reason, now)
            except Exception as exc:  # 平台/装载级失败：如实报原因，不报 0
                logger.debug("GPU 采集：建立 query 失败", exc_info=True)
                return _degraded(STATE_ERROR, f"{type(exc).__name__}: {exc}", now)
            try:
                api.collect(query)
            except PdhError as exc:
                # 采样基线不可信：宁可少报一拍，也不拿旧基线算出一个像样的数
                self._primed = False
                state, reason = _reason_for_status(exc.status)
                return _degraded(state, reason, now, names_error=self._names_error)
            except Exception as exc:
                self._primed = False
                logger.debug("GPU 采集：collect 失败", exc_info=True)
                return _degraded(STATE_ERROR, f"{type(exc).__name__}: {exc}", now)
            return self._after_collect(api, counter, now)

    # ------------------------------------------------------------ 内部
    def _ensure_api(self):
        """惰性取 API：注入的替身优先；生产路径走进程内唯一的 PDH 绑定。"""
        if self._api is not None:
            return self._api
        if not _platform_supported():
            return None
        api = pdh_api()
        if api is not None:
            self._api = api
        return api

    def _ensure_query(self, api):
        """惰性建 query + counter；**失败时把半开的 query 收掉**（异常释放）。"""
        if self._query is not None:
            return self._query, self._counter
        query = None
        try:
            query = api.open_query()
            counter = api.add_counter(query, self._counter_path)
        except BaseException:
            if query is not None:
                self._cleanup_query(query)
            raise
        self._query, self._counter = query, counter
        self._owner_thread = threading.get_ident()
        self._primed = False
        self._last_collect_at = None
        self._closed = False
        self._release_error = ""
        return query, counter

    def _cleanup_query(self, query) -> None:
        """异常路径上收掉刚开出来的 query；**收不掉就把它记在手上**，不静默丢句柄。"""
        error = self._release(query)
        if not error:
            return
        self._query = query
        self._counter = None
        self._owner_thread = threading.get_ident()
        self._primed = False
        self._last_collect_at = None
        self._closed = False
        self._release_error = error

    def _release(self, query) -> str:
        """放掉一个 query；返回释放失败的原因（成功为 ``""``）。收口路径不许再抛。"""
        api = self._api
        if api is None:
            return ""
        try:
            api.close_query(query)
        except Exception as exc:  # noqa: BLE001 - 收口失败要变成原因，不是异常
            logger.warning("GPU 采集：关闭 PDH query 失败，句柄未确认释放", exc_info=True)
            return f"{type(exc).__name__}: {exc}"
        return ""

    def _after_collect(self, api, counter, now: float) -> GpuSample:
        previous, self._last_collect_at = self._last_collect_at, now
        gap = None if previous is None else now - previous
        if not self._primed or (gap is not None and gap > self._max_gap):
            # 首拍 / 长停恢复：这一拍只重建基线。窗口平均不等于"此刻"的占用，
            # 拿它当即时读数报出去就是把一段历史说成现状。
            self._primed = True
            return _degraded(STATE_SAMPLING, "", now, names_error=self._names_error)
        state, reason, items = self._read_items(api, counter)
        if state != STATE_OK:
            # 不因为这一拍读不出来就丢掉基线：上一次 collect 已经发生，下一拍就有
            # 有效差分区间（"还在采样"是自愈的，不需要额外重建基线）。
            return _degraded(state, reason, now, names_error=self._names_error)
        engines = group_engines(items)
        if not engines:
            # 没有任何有效实例：这是"没有数据"，不是"GPU 占用 0"（后者是合法读数）。
            return _degraded(STATE_UNKNOWN, "GPU 计数器没有返回任何有效实例", now,
                             names_error=self._names_error)
        known, names_error = self._adapter_infos()
        adapters = adapter_readings(engines, known=known)
        if not adapters:
            return _degraded(STATE_UNKNOWN,
                             "只有软件适配器在报数（如 Microsoft Basic Render Driver）",
                             now, names_error=names_error)
        busiest = busiest_adapter(adapters)
        return GpuSample(
            percent=busiest.percent,
            sampled_at=now,
            state=STATE_OK,
            adapter=busiest,
            adapters=adapters,
            detail=_detail(label=adapter_label(busiest), names_error=names_error,
                           adapter=busiest),
        )

    def _read_items(self, api, counter) -> tuple[str, str, list[tuple[str, float]]]:
        """两段式读数组 + **有界**重试，返回 ``(状态, 原因, [(名字, 值)…])``。

        两段式之间实例数可能增长（别的进程起来又开了引擎）——那时第二次调用仍然回
        ``PDH_MORE_DATA``，并给出更大的尺寸。**必须按新尺寸重取**，绝不能读那块半截
        缓冲；重试用尽即报错，不无限重试，也不为来路不明的尺寸分配内存。
        """
        try:
            status, size, count, _ = api.counter_array(counter, None)
        except PdhError as exc:
            state, reason = _reason_for_status(exc.status)
            return state, reason, []
        except Exception as exc:  # noqa: BLE001 - 读数失败只降级
            logger.debug("GPU 采集：读取数组尺寸失败", exc_info=True)
            return STATE_ERROR, f"{type(exc).__name__}: {exc}", []
        if status == PDH_CSTATUS_VALID_DATA:
            # 问尺寸却没拿到 MORE_DATA：这条路径不该有数据，如实按"没有实例"处理。
            return STATE_UNKNOWN, "GPU 计数器当前没有实例（没有引擎在活动）", []
        for _ in range(MAX_ARRAY_RETRIES):
            if status != PDH_MORE_DATA:
                state, reason = _reason_for_status(status)
                return state, reason, []
            if count <= 0:
                return STATE_UNKNOWN, "GPU 计数器当前没有实例（没有引擎在活动）", []
            if count > MAX_ENGINE_ITEMS:
                return STATE_ERROR, (f"实例条数 {count} 超过上限 {MAX_ENGINE_ITEMS}"
                                     "（拒绝为不确定的尺寸分配缓冲区）"), []
            if size <= 0:
                return STATE_ERROR, f"PDH 给出的数组尺寸异常（{size} 字节）", []
            if size > MAX_ARRAY_BYTES:
                return STATE_ERROR, (f"数组尺寸 {size} 字节超过上限 {MAX_ARRAY_BYTES}"
                                     "（拒绝为不确定的尺寸分配缓冲区）"), []
            try:
                status, size, count, raw = api.counter_array(counter, size)
            except PdhError as exc:
                state, reason = _reason_for_status(exc.status)
                return state, reason, []
            except Exception as exc:  # noqa: BLE001
                logger.debug("GPU 采集：读取数组失败", exc_info=True)
                return STATE_ERROR, f"{type(exc).__name__}: {exc}", []
            if status == 0:
                return STATE_OK, "", [
                    (name, value) for name, cstatus, value in raw
                    if cstatus in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA)
                ]
        state, reason = _reason_for_status(PDH_MORE_DATA)
        return state, reason, []

    def _adapter_infos(self) -> tuple[Mapping[str, AdapterInfo] | None, str]:
        """DXGI 适配器表（每实例只枚举一次）；失败返回 ``(None, 原因)``。

        ``known=None`` 的语义是"**不知道**"，不是"没有适配器"：一块都不剔、一个数
        都不改，只把原因记进 ``detail["names_error"]``。
        """
        with self._lock:
            if not self._adapters_resolved:
                self._adapters_resolved = True
                provider = self._adapter_provider or dxgi_adapters
                try:
                    self._adapters = dict(provider())
                    self._names_error = ""
                except Exception as exc:  # noqa: BLE001 - 名字不可用不影响读数
                    logger.debug("GPU 采集：适配器名字不可用", exc_info=True)
                    self._adapters = None
                    self._names_error = f"{type(exc).__name__}: {exc}"
            return self._adapters, self._names_error
