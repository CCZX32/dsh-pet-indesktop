# -*- coding: utf-8 -*-
"""DSH 统一状态收敛（纯逻辑，无 Qt/线程/定时器）。

数据源：随桌宠内置的 DSH 桥接插件 ``integrations/dsh-pet-bridge`` 写入的
``<数据基目录>/dsh-pet-bridge/dsh-{pid}.jsonl``（多实例分区写入；消费端
glob ``dsh*.jsonl``，兼容旧版单文件 ``dsh.jsonl``）。

减法后（2026-10）本模块只剩**纯函数/纯类**：唯一的桥接读方是
``pet/agent_link.py`` 的 ``DshMonitor``（一个 DirGlobTailer + 一个轮询线程，
解析一次记录，分发给信号分派与本收敛器两个消费者）。本模块负责把桥接事件
收敛为统一桌宠可见状态：

    offline / idle / thinking / working / waiting_approval / waiting_question /
    success / error

并保证：
- **edge-trigger**：仅当状态真正变化时才产出；同状态重复事件去重。
- **offline 恢复**：DSH 未运行（端口探测，见 ``candidate_ports``）时切
  offline；DSH 恢复后自动回 idle 并继续监听。
- 阻塞型交互锁存：cordis/request-run（当前桥的权威审批请求）与 approval/request
  （旧桥/自定义通道的 UI 级审批事件）进入 waiting_approval、approval/decided 解锁；
  question/requested 进入 waiting_question、question/resolved 解锁。裸
  approval/asked **不参与锁存**（普通工具调用也会被宿主打上这个标记，见
  ``_EVENT_TO_STATE`` 的说明）；锁存超时兜底由 ``tick()`` 完成。

输出以元组列表返回（不直接 emit 信号，Qt 边界全部留在 DshMonitor）：
``("state", from_state, to_state, source_event)`` 与
``("user_message", session_id, text)``；from_state 为 "" 表示首个状态，
source_event 为触发该状态的桥接事件名（探活驱动的基线切换为 ""）。
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from enum import Enum
from typing import Optional

log = logging.getLogger("dsh-pet-standalone")

# 审批锁存兜底：若 approval/decided 长时间未到，强制解除审批态回 working，
# 避免桌宠卡死在 waiting_approval（DSH 异常漏发 decided 的防线）。
APPROVAL_LATCH_TIMEOUT_S = 120.0


class DshState(str, Enum):
    """桌宠可见的 DSH 统一状态。"""
    OFFLINE = "offline"
    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_QUESTION = "waiting_question"
    SUCCESS = "success"
    ERROR = "error"


# AgentStatus 记录的 state 字段 → 统一状态
_AGENT_STATUS_STATE = {
    "idle": DshState.IDLE,
    "working": DshState.WORKING,
    "thinking": DshState.THINKING,
    "waiting_approval": DshState.WAITING_APPROVAL,
    "waiting_question": DshState.WAITING_QUESTION,
    "success": DshState.SUCCESS,
    "error": DshState.ERROR,
}

# 桥接「简单事件」（DSH 原始 session/event 类型）→ 统一状态。
# 事件名来自 DSH dsh-session/known-event-types.js 的真实词汇。
_EVENT_TO_STATE = {
    # 用户提交 / turn 开始 → 思考
    "user/message": DshState.THINKING,
    "turn/start": DshState.THINKING,
    # 工具 / 步骤 / 命令执行 → working
    "assistant/message": DshState.WORKING,
    "tool/call": DshState.WORKING,
    "tool/result": DshState.WORKING,
    "step/start": DshState.WORKING,
    "step/end": DshState.WORKING,
    "command/run": DshState.WORKING,
    "command/done": DshState.WORKING,
    "tool-workflow/run-start": DshState.WORKING,
    "tool-workflow/run-end": DshState.WORKING,
    # 审批（gated 口径，2026-10 修正）：
    # - approval/asked 只是 DSH 的会话/审计信号——普通工具调用也会被宿主打上
    #   这个标记，拿它锁存 waiting_approval 是误报源（桥端注释同款结论），
    #   因此**不收敛**（不在本表，记录被忽略）；
    # - 权威来源是 cordis/request-run（桥只在 requiresApproval 严格布尔 True 时
    #   才写，带 requestId）与旧式 approval/request（旧桥/自定义通道的 UI 级
    #   审批事件）；
    # - approval/decided / cordis/request-run-resolved → WORKING（解锁兼容）。
    "cordis/request-run": DshState.WAITING_APPROVAL,
    "cordis/request-run-resolved": DshState.WORKING,
    "approval/request": DshState.WAITING_APPROVAL,  # 兼容旧一次性审批事件
    "approval/decided": DshState.WORKING,
    # 用户问题（ask_user_question 阻塞交互，与审批同等待遇）
    "question/requested": DshState.WAITING_QUESTION,
    "question/resolved": DshState.WORKING,
    # 完成 / 出错
    "turn/end": DshState.SUCCESS,
    "llm/retry": DshState.ERROR,
    "llm_error": DshState.ERROR,  # API 级错误（errorCode 为真实上游码如 bad_response_status_code）
}


# turn/end 的 reasonKind（新桥接写出）中按「静默收尾」处理的取值：用户主动中止。
_TURN_END_SILENT_REASONS = frozenset({"aborted"})


def map_event_to_state(record: dict) -> Optional[DshState]:
    """把一条桥接记录映射为统一状态；无法识别返回 None（忽略）。

    支持两种记录形态（桥接插件当前实际写出的）：
    - ``{"event": "AgentStatus", "state": "working"}`` —— agent/status 聚合基线；
    - ``{"event": "tool/call", "tool": "..."}`` 等原始事件 —— session/event 转发。
    """
    if not isinstance(record, dict):
        return None
    event = str(record.get("event") or "")
    if event == "AgentStatus":
        return _AGENT_STATUS_STATE.get(str(record.get("state") or "").strip())
    if event == "cordis/request-run":
        # 双保险：桥只在 requiresApproval 严格布尔 True 时写这条记录；对旧桥/
        # 手写桩/自定义通道的平铺形状再核一次，非审批请求不锁存。
        nested = record.get("payload")
        if isinstance(nested, dict) and "requiresApproval" in nested:
            if nested.get("requiresApproval") is not True:
                return None
        elif record.get("requiresApproval") is not True:
            return None
    if event == "turn/end" and str(record.get("reasonKind") or "").strip() in _TURN_END_SILENT_REASONS:
        # 用户中止的回合：回待机、不报完成（无完成气泡/音效）。reasonKind 缺失 =
        # 旧桥接，保持原 SUCCESS 行为。
        return DshState.IDLE
    return _EVENT_TO_STATE.get(event)


# 回合起点标记：live 读到即视为「本会话进入了一个新回合」。
# turn/start 与 user/message 都是桥接真实写出的事件（index.js：前者在
# STATE_EVENT_TYPES 里、后者显式转发），且两者都收敛为 THINKING/新对话。
_TURN_START_EVENTS = ("turn/start", "user/message")

# 会话表容量（身份 token 的有界声明）：每会话只留最新 token，超出按「最久没有
# live 起点」淘汰。桌宠是长跑进程，DSH 每换一次会话就是一个新 sessionId——不设
# 上界就是一条随会话数线性增长的内存。
TURN_TOKEN_MEMORY = 512


class TurnCompletionTracker:
    """live 回合收尾的身份追踪（纯逻辑：无 Qt、无线程、无时钟）。

    判据为什么不放在收敛状态上：``turn/end`` 不带源 ID（不像 ``tool/call`` 有
    callId），收敛器又是 edge-trigger——已停在 SUCCESS 时再收一条收尾零产出，
    而「桌宠中途接上 / 关开联动残留终态 / 聚合 idle 基线先到」这些来向上，呈现
    管线里的上一个状态都不是 busy。此时唯一稳定的事实是**这条 live 记录本身**。

    身份 = ``("turn-end", session_id, step, token)``：

    - ``session_id`` / ``step``：桥接 ``writeStateEvent`` 真实写出的字段
      （step = DSH 的 ``data.step``，桥接在它缺失时回退成 ``turn:<turn>``）；
    - ``token``：**全局单调 generation**——每条 live 起点标记递增一次后记到该会话
      名下。它把「同一回合的重复投递」（没有新起点 → token 不变）与「同一会话的
      下一回合」（接上之后必有 live 起点 → token 变大）分开，并顺带兜住「两回合
      step 取值相同」这一残量。

    token 为什么必须是**全局**计数、而不是「每会话自增 + 只加容量」：消费侧
    （``AgentLinkManager._on_dsh_turn_completed``）按身份去重，身份相同 = 同一回合
    的重复投递 = 直接丢弃。每会话计数在会话被挤出表后会从 1 重来，新回合 step 与
    旧回合相同时身份就撞上**消费者已经见过**的那个，新回合被静默吞掉（无完成气泡、
    无 done 音效）。全局计数在实例生命周期内不复用，因此淘汰只丢「记忆」，不会
    造出假身份。

    有界：会话表 ≤ ``TURN_TOKEN_MEMORY`` 条，且只由 live 起点写入——只见过收尾的
    会话（中途挂载，从没见过起点）token 恒为 0 且**不落表**，身份靠 session + step
    逐条唯一（不按正文造 ID、不写任何持久状态）。``reset()`` 清表但同样不回收全局
    计数（见其文档）。

    两个字段都取不到时退回摄入游标 ``(文件, 文件身份, 行首偏移)``：同一行读两次
    已由摄入账本（``BaseAgentMonitor._event_ledger``）挡住，这里只保证身份唯一。

    追的是 **live** 记录：``ByteOffsetTailer`` 回填之后才读到的字节才会到达
    ``observe``——历史记录到不了这里，所以「返回身份」本身就等于「接上之后真的
    发生了一次回合收尾」。
    """

    def __init__(self) -> None:
        # 全局起点计数（整数，不随会话数占内存）：只增不减（含 reset），保证身份
        # token 在实例生命周期内不复用。
        self._generation = 0
        # 会话 → 该会话最新的起点 token。插入次序 = LRU 次序（起点刷新次序，收尾
        # 只读不刷新——读不该驱动淘汰），淘汰端是最久没有起点的会话。
        self._tokens: OrderedDict[str, int] = OrderedDict()

    def reset(self) -> None:
        """读方重启（监视器 start）时清会话表：上一代次的起点记忆不跨代次存活。

        **全局计数不回收**：回收会让重启后同一会话的下一回合重新拿到旧 token，而
        消费侧的身份记忆（``_dsh_turn_ids``）不随监视器生命周期清空——「关掉再开启
        联动、同一会话继续跑」时那正好把新回合当成重复投递吞掉。清表本身已足以隔离
        代次：没见过起点的会话 token 仍是 0，身份照旧由 session + step 唯一。
        """
        self._tokens.clear()

    def observe(self, record: dict, cursor: Optional[tuple] = None) -> Optional[tuple]:
        """喂一条 live 桥接记录：是回合成功收尾事件时返回其身份，否则 None。"""
        if not isinstance(record, dict):
            return None
        event = str(record.get("event") or "")
        session = str(record.get("sessionId") or record.get("session_id") or "")
        if event in _TURN_START_EVENTS:
            self._generation += 1
            self._tokens.pop(session, None)  # 重入表尾：本会话成为最近使用
            self._tokens[session] = self._generation
            while len(self._tokens) > TURN_TOKEN_MEMORY:
                self._tokens.popitem(last=False)
            return None
        if map_event_to_state(record) is not DshState.SUCCESS:
            return None
        step = str(record.get("step") or "")
        if session or step:
            return ("turn-end", session, step, self._tokens.get(session, 0))
        if cursor is None:
            return None
        return ("turn-end-cursor", str(cursor[0]), cursor[1], int(cursor[2]))


def candidate_ports(port: Optional[int] = None) -> list[int]:
    """待探测的 DSH 端口候选（offline 判定的唯一来源）。

    DSH 可能跑在 3080（web 真实默认）或 38080（桌宠 harness_launcher 启动
    时的避让端口），desktop 桌面端固定在 127.0.0.1:19387，也可能通过
    DSH_PORT 环境变量指定——全部探测，任一在线即视为 DSH 在线（兼容
    「用户自己开的 DSH」与「桌宠一键启动的 DSH」）。
    """
    ports: set[int] = {3080, 38080, 19387}
    if port is not None:
        ports.add(int(port))
    env_port = os.environ.get("DSH_PORT")
    if env_port:
        try:
            ports.add(int(env_port))
        except (TypeError, ValueError):
            pass
    return sorted(ports)


class DshStateConverger:
    """桥接记录 → 统一状态的纯收敛器（无线程/Qt，时钟可注入）。

    由唯一读方 ``DshMonitor`` 在其 worker 线程里驱动：
    - 每条解析后的记录喂给 ``handle_record``；
    - 每次轮询节拍调 ``tick``（锁存超时兜底）；
    - 端口探测结果经 ``set_online`` 灌入（offline/idle 基线）。
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        # 统一状态（edge-trigger）。初始 None，使首个状态（offline/idle）也产出
        self.current_state: Optional[DshState] = None
        # 阻塞型交互锁存（审批 / 用户问题同待遇）：
        # 进入 waiting_approval / waiting_question 后忽略 working/thinking，
        # 直到对应的 decided / resolved 到来解除。
        self._pending_approval = False
        self._approval_since: Optional[float] = None
        self._pending_question = False
        self._question_since: Optional[float] = None

    def reset(self) -> None:
        """读方重启（监视器 start）时清零：状态/锁存回到初始。"""
        self.current_state = None
        self._release_approval()
        self._release_question()

    # ------------------------------------------------------------ 状态推进
    def _transition(self, to_state: DshState, out: list, source: str = "") -> None:
        """edge-trigger 状态切换：同状态去重，真正变化才产出。

        产出为 ("state", from_state, to_state, source_event) 四元组；
        source_event 供消费侧做同源去重（cordis/request-run 与 approval/request
        各有专属常驻气泡，其锁存边沿不再弹通用 attention 气泡）。"""
        if to_state is self.current_state:
            return
        from_state = self.current_state
        self.current_state = to_state
        if from_state is None:
            log.info("[DSH STATE] %s", to_state.value)
        else:
            log.info("[DSH STATE] %s -> %s", from_state.value, to_state.value)
        out.append(("state", "" if from_state is None else from_state.value,
                    to_state.value, source))

    def _release_approval(self) -> None:
        self._pending_approval = False
        self._approval_since = None

    def _release_question(self) -> None:
        self._pending_question = False
        self._question_since = None

    def handle_record(self, record: dict) -> list[tuple]:
        """处理一条桥接记录：阻塞型交互锁存感知的状态推进。

        审批与用户问题（ask_user_question）都是「阻塞 Agent 等待用户输入」的
        交互，统一按锁存处理：进入 waiting_approval / waiting_question 后忽略
        working/thinking，直到对应的 decided / resolved 到来解除。
        """
        out: list[tuple] = []
        event = str(record.get("event") or "")
        state = map_event_to_state(record)
        if state is None:
            return out

        # 真人用户消息：产出 user_message（对话开始的稳定触发点）。
        # agent.inject() 注入上下文（sourceKind=plugin）整体忽略——不进状态机、
        # 不算对话开始，防止每轮 4-5 条 system-reminder/技能目录记录把「对话
        # 开始」触发改成随机的（同 tick 批量应用 + 边沿去重 → 时触时不触）。
        if event == "user/message":
            if str(record.get("sourceKind") or "") == "plugin":
                return out
            out.append((
                "user_message",
                str(record.get("sessionId") or record.get("session_id") or ""),
                str(record.get("text") or record.get("content") or record.get("summary") or ""),
            ))

        # approval/decided / cordis/request-run-resolved：解除审批锁存，
        # 回到 working（agent 仍在 running）
        if event in ("approval/decided", "cordis/request-run-resolved"):
            was_latched = self._pending_approval
            self._release_approval()
            if was_latched:
                self._transition(DshState.WORKING, out)
            return out

        # question/resolved：解除问题锁存，回到 working
        if event == "question/resolved":
            was_latched = self._pending_question
            self._release_question()
            if was_latched:
                self._transition(DshState.WORKING, out)
            return out

        if event == "turn/end" and state is DshState.IDLE:
            # 用户中止的回合：必须带 source 产出，消费侧据此回待机并撤掉完成确认。
            # 放在锁存闸之前：中止会终结整轮，审批/问题锁存一并解除（否则岛一直
            # 等待，超时又被 working 顶回）。
            # 旧 AgentStatus idle 基线可能先到（已是 IDLE），同态去重会吞掉这条
            # 中止——此时仍产出一条 idle→idle 标记，让消费侧撤掉基线排下的确认。
            self._release_approval()
            self._release_question()
            if self.current_state is DshState.IDLE:
                out.append(("state", DshState.IDLE.value, DshState.IDLE.value, event))
            else:
                self._transition(state, out, source=event)
            return out

        # 审批类权威事件（cordis/request-run、旧式 approval/request、显式
        # AgentStatus.waiting_approval）：进入审批锁存
        if state is DshState.WAITING_APPROVAL:
            self._pending_approval = True
            self._approval_since = self._clock()
            self._transition(state, out, source=event)
            return out

        # question/requested：进入问题锁存
        if state is DshState.WAITING_QUESTION:
            self._pending_question = True
            self._question_since = self._clock()
            self._transition(state, out, source=event)
            return out

        # 任一锁存中：忽略一切非阻塞事件（防 waiting_approval / waiting_question
        # 被 working / thinking 顶掉）
        if self._pending_approval or self._pending_question:
            return out

        self._transition(state, out)
        return out

    # ------------------------------------------------------------ 在线基线
    def set_online(self, online: bool) -> list[tuple]:
        """把在线探测结果落到状态机：离线 → offline（清审批锁存），在线且无活动 → idle。"""
        out: list[tuple] = []
        if not online:
            # DSH 未运行：审批/问题锁存一并清除，切 offline
            self._release_approval()
            self._release_question()
            self._transition(DshState.OFFLINE, out)
        else:
            # DSH 在线但没有任何活跃 Agent/事件：基线 idle（含从 None / offline 恢复）
            if self.current_state in (None, DshState.OFFLINE):
                self._transition(DshState.IDLE, out)
        return out

    def tick(self) -> list[tuple]:
        """轮询节拍：阻塞型交互锁存超时兜底（DSH 漏发 decided/resolved 的防线）。"""
        out: list[tuple] = []
        if self._pending_approval and self._approval_since is not None:
            if self._clock() - self._approval_since >= APPROVAL_LATCH_TIMEOUT_S:
                log.warning("DSH 审批锁存超时，强制解除审批态")
                self._release_approval()
                self._transition(DshState.WORKING, out)
        if self._pending_question and self._question_since is not None:
            if self._clock() - self._question_since >= APPROVAL_LATCH_TIMEOUT_S:
                log.warning("DSH 问题锁存超时，强制解除问题态")
                self._release_question()
                self._transition(DshState.WORKING, out)
        return out
