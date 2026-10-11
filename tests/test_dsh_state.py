# -*- coding: utf-8 -*-
"""DSH 统一状态收敛（dsh_state.DshStateConverger）单元测试。

减法后（2026-10）dsh_state 只剩纯逻辑：不建 Qt 对象、不读文件、不探端口——
直接驱动收敛器的 handle_record / set_online / tick，验证 edge-trigger 去重、
离线恢复与审批/问题锁存。读方（DshMonitor）与消费侧的接线回归见
tests/test_agent_link_subtraction.py 的单读方/审批收敛测试族。
"""
from __future__ import annotations

from pet import dsh_state
from pet.dsh_state import (
    APPROVAL_LATCH_TIMEOUT_S,
    DshState,
    DshStateConverger,
    TurnCompletionTracker,
    candidate_ports,
)


def _records_for(*events):
    """把事件名序列转为 AgentStatus(working/idle) 或原始事件记录。"""
    out = []
    for ev in events:
        if ev in ("idle", "working", "thinking", "waiting_approval", "waiting_question",
                  "success", "error"):
            out.append({"event": "AgentStatus", "state": ev})
        else:
            out.append({"event": ev})
    return out


def _feed(conv, *records):
    out = []
    for rec in records:
        out.extend(conv.handle_record(rec))
    return out


def _states(outputs):
    return [to for kind, _f, to, *_src in outputs if kind == "state"]


def test_offline_when_dsh_down(caplog):
    conv = DshStateConverger()
    with caplog.at_level("INFO"):
        out = conv.set_online(False)
    assert conv.current_state is DshState.OFFLINE
    assert _states(out) == ["offline"]
    assert any("[DSH STATE] offline" in r.getMessage() for r in caplog.records)


def test_online_goes_idle(caplog):
    conv = DshStateConverger()
    with caplog.at_level("INFO"):
        out = conv.set_online(True)
    assert conv.current_state is DshState.IDLE
    # DSH 一开始就在线：首个状态直接是 idle（from 为空，不是 offline -> idle）
    assert _states(out) == ["idle"]
    assert any("[DSH STATE] idle" in r.getMessage() for r in caplog.records)


def test_offline_then_online_idle(caplog):
    """先 offline，DSH 上线后切 idle：日志体现 offline -> idle。"""
    conv = DshStateConverger()
    conv.set_online(False)
    assert conv.current_state is DshState.OFFLINE
    with caplog.at_level("INFO"):
        out = conv.set_online(True)
    assert conv.current_state is DshState.IDLE
    assert _states(out) == ["idle"]
    assert any("[DSH STATE] offline -> idle" in r.getMessage() for r in caplog.records)


def test_edge_trigger_dedup():
    """同状态重复事件不重复产出。"""
    conv = DshStateConverger()
    conv.set_online(True)  # -> idle
    out = _feed(conv, *(_records_for("user/message") * 2))  # thinking ×2
    assert conv.current_state is DshState.THINKING
    assert _states(out) == ["thinking"]  # 只有一次 thinking 转换


def test_full_pipeline():
    """完整生命周期：thinking -> working -> waiting_approval -> working -> success -> idle。

    审批锁存的权威触发是 cordis/request-run（requiresApproval 严格 True）；
    解锁用 cordis/request-run-resolved（approval/decided 同款兼容路径另测）。
    """
    conv = DshStateConverger()
    conv.set_online(True)  # idle
    out = _feed(conv, *(_records_for("user/message", "tool/call")))
    out += _feed(conv, {"event": "cordis/request-run", "requestId": "r-1",
                        "payload": {"requiresApproval": True}})
    out += _feed(conv, {"event": "cordis/request-run-resolved", "requestId": "r-1"})
    out += _feed(conv, *(_records_for("turn/end", "idle")))
    assert _states(out) == [
        "thinking", "working", "waiting_approval", "working", "success", "idle",
    ]
    assert conv.current_state is DshState.IDLE


def test_approval_asked_does_not_latch():
    """H1 钉住：裸 approval/asked（普通工具调用也会被宿主打标的审计信号）
    绝不收敛为 waiting_approval——它是误报源，不是权威审批事件。"""
    conv = DshStateConverger()
    conv.set_online(True)  # idle
    out = _feed(conv, {"event": "approval/asked", "tool": "pwsh"})
    assert _states(out) == []
    assert conv.current_state is DshState.IDLE
    assert conv._pending_approval is False


def test_cordis_request_run_requires_strict_true():
    """cordis/request-run 只在 requiresApproval 严格布尔 True 时锁存审批态。"""
    conv = DshStateConverger()
    conv.set_online(True)
    # 平铺 False / 缺失 / 字符串 "true" 都不锁存
    _feed(conv, {"event": "cordis/request-run", "requestId": "r-a",
                 "payload": {"requiresApproval": False}})
    _feed(conv, {"event": "cordis/request-run", "requestId": "r-b"})
    _feed(conv, {"event": "cordis/request-run", "requestId": "r-c",
                 "payload": {"requiresApproval": "true"}})
    assert conv.current_state is DshState.IDLE
    # 嵌套 True 才锁存
    out = _feed(conv, {"event": "cordis/request-run", "requestId": "r-d",
                       "payload": {"requiresApproval": True}})
    assert _states(out) == ["waiting_approval"]
    assert conv.current_state is DshState.WAITING_APPROVAL


def test_approval_decided_releases_latch_for_compat():
    """approval/decided 保留为解锁兼容路径（旧桥/自定义通道的 approval 对）。"""
    conv = DshStateConverger()
    conv.set_online(True)
    _feed(conv, {"event": "approval/request", "approvalId": "ap-1"})  # 旧式审批事件
    assert conv.current_state is DshState.WAITING_APPROVAL
    out = _feed(conv, {"event": "approval/decided", "approvalId": "ap-1"})
    assert _states(out) == ["working"]
    assert conv.current_state is DshState.WORKING


def test_approval_latch_ignores_working():
    """审批锁存期间 working 事件被忽略，直到 cordis/request-run-resolved。"""
    conv = DshStateConverger()
    conv.set_online(True)
    # waiting_approval 后，即便又来 working（agent 仍在跑），也不被顶掉
    _feed(conv, {"event": "cordis/request-run", "requestId": "r-1",
                 "payload": {"requiresApproval": True}})
    _feed(conv, *(_records_for("tool/call", "working")))
    assert conv.current_state is DshState.WAITING_APPROVAL

    _feed(conv, {"event": "cordis/request-run-resolved", "requestId": "r-1"})
    assert conv.current_state is DshState.WORKING


def test_offline_force_overrides_work():
    """DSH 被强制关闭时切 offline，不崩。"""
    conv = DshStateConverger()
    conv.set_online(True)
    _feed(conv, *(_records_for("working")))
    assert conv.current_state is DshState.WORKING

    conv.set_online(False)
    assert conv.current_state is DshState.OFFLINE


def test_question_latch_ignores_working():
    """问题锁存期间 working 事件被忽略，直到 question/resolved。"""
    conv = DshStateConverger()
    conv.set_online(True)
    _feed(conv, {"event": "question/requested", "questions": [
        {"id": "q1", "question": "要执行哪个方案？",
         "options": [{"label": "方案 A"}, {"label": "方案 B"}]}]})
    _feed(conv, *(_records_for("tool/call", "working")))
    assert conv.current_state is DshState.WAITING_QUESTION

    _feed(conv, {"event": "question/resolved"})
    assert conv.current_state is DshState.WORKING


def test_question_pipeline():
    """完整生命周期：thinking -> working -> waiting_question -> working -> success -> idle。"""
    conv = DshStateConverger()
    conv.set_online(True)  # idle
    out = []
    out.extend(_feed(conv, *(_records_for("user/message", "tool/call"))))
    out.extend(_feed(conv, {"event": "question/requested", "questions": [
        {"id": "q1", "question": "选 A 还是 B？", "options": [{"label": "A"}, {"label": "B"}]}]}))
    out.extend(_feed(conv, {"event": "question/resolved"}))
    out.extend(_feed(conv, *(_records_for("turn/end", "idle"))))
    assert _states(out) == [
        "thinking", "working", "waiting_question", "working", "success", "idle",
    ]
    assert conv.current_state is DshState.IDLE


def test_offline_releases_question_latch():
    """DSH 离线时问题锁存一并清除，且离线后不再被残留 resolved 顶成 working。"""
    conv = DshStateConverger()
    conv.set_online(True)
    _feed(conv, {"event": "question/requested", "questions": [{"id": "q", "question": "?"}]})
    assert conv.current_state is DshState.WAITING_QUESTION

    out = conv.set_online(False)
    assert conv.current_state is DshState.OFFLINE
    assert _states(out) == ["offline"]

    # 残留 resolved 不再把 offline 顶成 working（map 得 working，但读方在离线时
    # 不喂记录；即便防御性喂入，resolved 也只是解除一个已清的锁存）
    out = _feed(conv, {"event": "question/resolved"})
    assert conv.current_state is DshState.OFFLINE


def test_recovery_after_restart():
    """DSH 重启后自动回 idle 并继续消费事件。"""
    conv = DshStateConverger()
    conv.set_online(True)
    conv.set_online(False)
    assert conv.current_state is DshState.OFFLINE

    conv.set_online(True)
    assert conv.current_state is DshState.IDLE

    _feed(conv, *(_records_for("turn/start")))
    assert conv.current_state is DshState.THINKING


def test_user_message_plugin_source_ignored():
    """agent.inject() 注入上下文（sourceKind=plugin）不触发对话开始、不进状态机。

    每轮 DSH 会注入 4-5 条 system-reminder/技能目录等 user/message,必须与真人
    消息区分,否则「对话开始」被注入文案污染。
    """
    conv = DshStateConverger()
    conv.set_online(True)  # idle
    out = _feed(conv, {"event": "user/message", "sourceKind": "plugin",
                       "text": "<system-reminder> 技能目录……", "sessionId": "s1"})
    assert [o for o in out if o[0] == "user_message"] == []
    assert conv.current_state is DshState.IDLE


def test_user_message_real_emits_output():
    """真人消息（sourceKind=user）产出 user_message(session, text) 并收敛 thinking。"""
    conv = DshStateConverger()
    conv.set_online(True)  # idle
    out = _feed(conv, {"event": "user/message", "sourceKind": "user",
                       "text": "看看还有没有这个事件", "sessionId": "s1"})
    assert [o for o in out if o[0] == "user_message"] == [("user_message", "s1", "看看还有没有这个事件")]
    assert conv.current_state is DshState.THINKING


def test_user_message_legacy_record_keeps_output():
    """旧版桥接记录无 sourceKind：按真人消息兼容处理，绝不静默丢事件。"""
    conv = DshStateConverger()
    conv.set_online(True)  # idle
    out = _feed(conv, {"event": "user/message", "text": "hi", "sessionId": "s2"})
    assert [o for o in out if o[0] == "user_message"] == [("user_message", "s2", "hi")]
    assert conv.current_state is DshState.THINKING


def test_unknown_event_ignored():
    conv = DshStateConverger()
    conv.set_online(True)
    _feed(conv, {"event": "some/unknown", "foo": 1})
    assert conv.current_state is DshState.IDLE


def test_llm_error_record_enters_error_state():
    """桥接真实写的是 llm_error（index.js），状态机必须认它——否则 ERROR 态不可达。

    桥接在 bad_response_status_code（API 级错误）分支写 ``event: "llm_error"``；
    旧键名 "llm/error" 与它只差一个分隔符，导致 API 错误永远进不了 ERROR。
    """
    conv = DshStateConverger()
    conv.set_online(True)  # idle
    out = _feed(conv, {"event": "tool/call"},  # working
                {
                    "event": "llm_error", "errorCode": "bad_response_status_code",
                    "errorMessage": "404", "errorKind": "api",
                })
    assert conv.current_state is DshState.ERROR
    assert _states(out) == ["working", "error"]


def test_success_edge_needs_a_real_transition():
    """``turn/end`` 的 success 是边沿触发：已是 SUCCESS 时再来一条不产出。

    中途挂载场景：回填跳过 ``turn/start`` 之后，同一会话的 ``turn/end`` 是收敛器
    唯一能看到的那条记录——它能产出 success，靠的是「接上时收敛器已被探活基线
    推到 idle」这一次真实转换，不是「turn/end 每条都产出」。反过来，重复的
    ``turn/end``（同状态帧）必须零产出，否则完成提醒会被重复调度。
    """
    conv = DshStateConverger()
    conv.set_online(True)  # idle（接上时的基线转换）
    out = _feed(conv, {"event": "turn/end"})
    assert conv.current_state is DshState.SUCCESS
    assert _states(out) == ["success"]

    out = _feed(conv, {"event": "turn/end"}, {"event": "turn/end"})
    assert conv.current_state is DshState.SUCCESS
    assert _states(out) == [], "已 SUCCESS 时重复的 turn/end 不得再产出"


def test_dead_event_keys_removed_from_state_map():
    """状态表不得保留桥接从不写的事件键。

    index.js 明确不转发流式 assistant/chunk，plan/mode 也只在 DSH 内部词汇里
    出现——留着这两条只会让状态表看起来覆盖了并不存在的事件。
    """
    from pet.dsh_state import _EVENT_TO_STATE

    assert "llm_error" in _EVENT_TO_STATE
    assert "llm/error" not in _EVENT_TO_STATE, "桥接实际写 llm_error，旧键名匹配不到"
    assert "assistant/chunk" not in _EVENT_TO_STATE
    assert "plan/mode" not in _EVENT_TO_STATE


def test_approval_latch_timeout_releases_to_working():
    """审批锁存超时兜底：DSH 漏发 approval/decided 时 tick() 强制回 working。"""
    clock = [1000.0]
    conv = DshStateConverger(clock=lambda: clock[0])
    conv.set_online(True)
    _feed(conv, {"event": "tool/call"})
    _feed(conv, {"event": "cordis/request-run", "requestId": "r-1",
                 "payload": {"requiresApproval": True}})
    assert conv.current_state is DshState.WAITING_APPROVAL

    clock[0] += APPROVAL_LATCH_TIMEOUT_S - 1
    assert conv.tick() == [], "未到超时点不得解除锁存"
    assert conv.current_state is DshState.WAITING_APPROVAL

    clock[0] += 2.0
    out = conv.tick()
    assert _states(out) == ["working"]
    assert conv.current_state is DshState.WORKING


def test_candidate_ports_include_desktop_host():
    """端口候选必须含 desktop 桌面端硬编码端口 19387（web 3080 / 避让 38080 之外）。"""
    ports = candidate_ports()
    assert 3080 in ports
    assert 38080 in ports
    assert 19387 in ports, "desktop 桌面端 host 在 127.0.0.1:19387，漏探会把桌面端误判 offline"


# ---------------------------------------------------------------------------
# live 回合收尾身份（TurnCompletionTracker）：完成提醒的判据
# ---------------------------------------------------------------------------
#
# 判定为什么不能挂在收敛状态上：``turn/end`` 不带源 ID、收敛器是 edge-trigger
# （已停在 SUCCESS 时再收一条收尾零产出），而「中途挂载 / 聚合 idle 基线先到 /
# 关开联动残留终态」这些来向上呈现管线里的上一个状态都不是 busy。唯一稳定的事实
# 是这条 live 记录本身——它的身份由本模块构造，消费侧只按身份去重（见
# tests/test_dsh_mid_attach_done.py 的真 tailer + 真 monitor 链路用例）。
#
# 身份 = (session_id, step, token)：
# - session_id / step：桥接真实写出的字段（桥缺 step 时回退 ``turn:<n>``）；
# - token：**全局单调 generation**，每条 live 起点标记（turn/start / user/message）
#   递增一次后记到该会话名下。全局计数是硬要求，不是实现细节：消费侧按身份去重，
#   token 一旦复用就会被当成「同一回合的重复投递」而吞掉新回合。「每会话自增 +
#   只加容量」的朴素修法在会话被挤出后正好撞身份，对照实现见
#   .scratch/product-dsh-tracker-bound-20261011/probe_naive_lru_collision.py。
#
# 会话表有界（``dsh_state.TURN_TOKEN_MEMORY``），且只由 live 起点写入：只见过
# 收尾的会话（中途挂载）token 恒为 0、不落表——身份靠 session + step 逐条唯一。


def test_turn_completion_identity_from_turn_end():
    tracker = TurnCompletionTracker()
    end = {"event": "turn/end", "sessionId": "s-1", "step": "turn:3"}
    identity = tracker.observe(end)
    assert identity == ("turn-end", "s-1", "turn:3", 0)
    # 同一回合的重复投递（另一个文件的游标）身份相同 → 消费侧据此只提醒一次
    assert tracker.observe(end, ("dsh-b.jsonl", (1, 2), 7)) == identity


def test_turn_completion_token_separates_successive_turns():
    """同会话连续回合靠 live 起点 token 分开；两回合 step 取值相同也不撞。"""
    tracker = TurnCompletionTracker()
    assert tracker.observe({"event": "turn/start", "sessionId": "s", "step": "5"}) is None
    first = tracker.observe({"event": "turn/end", "sessionId": "s", "step": "5"})
    assert tracker.observe({"event": "user/message", "sessionId": "s"}) is None
    second = tracker.observe({"event": "turn/end", "sessionId": "s", "step": "5"})
    assert first != second, "同一会话的下一回合必须有不同身份"
    assert first[:3] == second[:3] == ("turn-end", "s", "5"), "差异只能来自起点 token"
    assert second[3] > first[3], "后一个起点的 token 必须严格更大（token 只增不重用）"
    # 另一会话的起点不影响本会话 token（身份按会话独立）
    tracker.observe({"event": "turn/start", "sessionId": "other"})
    assert tracker.observe({"event": "turn/end", "sessionId": "s", "step": "5"}) == second


def test_turn_completion_session_table_is_bounded():
    """会话表有界：1000 个不同会话的 live 起点不得把表撑成 1000 条。

    长期运行的实例会看过成千上万个会话（DSH 每换一次会话就是一个新 sessionId），
    表随会话数增长即无界内存——修复前实测 1000 个会话 → 1000 条
    （.scratch/product-dsh-tracker-bound-20261011/01-probe-RED-prefix.txt）。
    不变量：条数 ≤ ``TURN_TOKEN_MEMORY``，且淘汰从最久没有起点的那一端开始。
    """
    tracker = TurnCompletionTracker()
    for i in range(1000):
        tracker.observe({"event": "turn/start", "sessionId": f"s-{i}"})
    limit = dsh_state.TURN_TOKEN_MEMORY
    assert len(tracker._tokens) <= limit, f"会话表必须有界：{len(tracker._tokens)} 条 > {limit}"
    assert "s-999" in tracker._tokens, "最近的会话必须在表内"
    assert "s-0" not in tracker._tokens, "最久没有起点的会话应被淘汰"


def test_turn_completion_evicted_session_next_turn_gets_fresh_identity():
    """被容量挤出的会话：同 session + 同 step 的新回合必须拿到**不同**身份。

    这是 token 必须全局单调（而非每会话自增）的原因——消费侧按身份去重，身份重用
    = 新回合被当成重复投递吞掉（无完成气泡、无 done 音效）。「只加容量、token 语义
    不变」的修法在本用例下必红（对照实现见 scratch 的 probe_naive_lru_collision.py：
    驱逐后新旧身份同为 ``("turn-end", "s-x", "turn:1", 1)``）。
    """
    tracker = TurnCompletionTracker()
    end = {"event": "turn/end", "sessionId": "s-x", "step": "turn:1"}
    tracker.observe({"event": "turn/start", "sessionId": "s-x", "step": "turn:1"})
    first = tracker.observe(end)
    assert first is not None

    for i in range(dsh_state.TURN_TOKEN_MEMORY + 8):
        tracker.observe({"event": "turn/start", "sessionId": f"flood-{i}"})
    assert "s-x" not in tracker._tokens, "前提：s-x 已被容量淘汰"

    tracker.observe({"event": "turn/start", "sessionId": "s-x", "step": "turn:1"})
    second = tracker.observe(end)
    assert second is not None
    assert second != first, "驱逐后同一会话的新回合不得沿用旧身份"
    assert first[:3] == second[:3] == ("turn-end", "s-x", "turn:1")


def test_turn_completion_end_only_sessions_do_not_grow_the_table():
    """中途挂载（从没见过 live 起点）的会话：收尾照常出身份，但**不落表**。

    表只能由 live 起点驱动——否则任意 sessionId 的收尾帧都能往里塞行，等于把无界
    增长从「起点表」挪到「收尾表」。这类会话 token 恒为 0（= 从未见过起点），身份
    仍靠 session + step 逐条唯一，不按正文造 ID、不写任何持久状态。
    """
    tracker = TurnCompletionTracker()
    identities = [
        tracker.observe({"event": "turn/end", "sessionId": f"attach-{i}", "step": "turn:1"})
        for i in range(1000)
    ]
    assert len(tracker._tokens) == 0, "只收尾的会话不得落表"
    assert all(identity is not None for identity in identities)
    assert len(set(identities)) == 1000, "同 step 的不同会话必须各自身份唯一"
    assert {identity[3] for identity in identities} == {0}, "无起点会话的 token 恒为 0"


def test_turn_completion_end_identity_stable_across_other_sessions():
    """同一回合的重复投递身份不变——别的会话的起点不得动摇本会话的 token。

    全局 generation 是「给起点发号」，不是「拿当前号当身份」：本会话的 token 只在自己
    的起点上更新。若身份跟着全局计数走，同一回合的重复帧会被算成新回合而重复提醒。
    """
    tracker = TurnCompletionTracker()
    tracker.observe({"event": "turn/start", "sessionId": "s-r", "step": "turn:1"})
    end = {"event": "turn/end", "sessionId": "s-r", "step": "turn:1"}
    identity = tracker.observe(end)
    assert identity is not None
    for i in range(64):
        tracker.observe({"event": "turn/start", "sessionId": f"noise-{i}"})
        assert tracker.observe(end, ("dsh-other.jsonl", (1, 1), i)) == identity


def test_turn_completion_ignores_non_completion_records():
    tracker = TurnCompletionTracker()
    for record in ({"event": "tool/call", "sessionId": "s"},
                   {"event": "llm/retry", "sessionId": "s"},
                   {"event": "llm_error", "sessionId": "s"},
                   {"event": "execution/failed", "sessionId": "s"},
                   {"event": "AgentStatus", "state": "working"},
                   {"event": "AgentStatus", "state": "error"},
                   {"event": "cordis/request-run", "sessionId": "s",
                    "payload": {"requiresApproval": True}}):
        assert tracker.observe(record) is None, record


def test_turn_completion_accepts_any_success_shaped_record():
    """任何收敛为 success 的记录形状都算收尾（含旧式 AgentStatus 基线）。

    ``AgentStatus`` 不带 sessionId/step（桥接的聚合基线形状），此时身份退回摄入
    游标——注意**不能**退化成「同代次所有无会话收尾都是同一个身份」，那会把两条
    不同的收尾压成一次提醒。
    """
    assert TurnCompletionTracker().observe(
        {"event": "AgentStatus", "state": "success"}, ("dsh.jsonl", (1, 1), 0)) == \
        ("turn-end-cursor", "dsh.jsonl", (1, 1), 0)
    assert TurnCompletionTracker().observe(
        {"event": "turn/end", "session_id": "s-2"}) == ("turn-end", "s-2", "", 0)


def test_turn_completion_cursor_fallback_and_reset():
    """无 session/step 时退回摄入游标；连游标都没有时给不出身份（消费侧不排定）。"""
    assert TurnCompletionTracker().observe(
        {"event": "turn/end"}, ("dsh.jsonl", (9, 9), 42)) == \
        ("turn-end-cursor", "dsh.jsonl", (9, 9), 42)
    assert TurnCompletionTracker().observe({"event": "turn/end"}) is None

    tracker = TurnCompletionTracker()
    tracker.observe({"event": "turn/start", "sessionId": "s"})
    tracker.observe({"event": "turn/end", "sessionId": "s", "step": "turn:1"})
    tracker.reset()
    assert tracker.observe({"event": "turn/end", "sessionId": "s", "step": "turn:1"}) == \
        ("turn-end", "s", "turn:1", 0), "重启后起点记忆不得跨代次存活（清表 → token 回 0）"


def test_turn_completion_reset_clears_table_but_never_reuses_tokens():
    """reset 清会话表、**不回收**全局计数：跨代次 token 不复用。

    消费侧的身份记忆（``AgentLinkManager._dsh_turn_ids``）不随监视器生命周期清空，
    所以「关掉再开启联动、同一会话继续跑」时若 token 从头重来，新回合会撞上旧身份被
    当成重复吞掉。清表已足够隔离代次（未见起点的会话 token 回 0，既有断言不变），
    计数不回收则再堵住这条真实路径。
    """
    tracker = TurnCompletionTracker()
    end = {"event": "turn/end", "sessionId": "s", "step": "turn:1"}
    tracker.observe({"event": "turn/start", "sessionId": "s", "step": "turn:1"})
    before = tracker.observe(end)
    tracker.reset()
    assert tracker.observe(end) == ("turn-end", "s", "turn:1", 0), "清表后 token 回 0"
    tracker.observe({"event": "turn/start", "sessionId": "s", "step": "turn:1"})
    after = tracker.observe(end)
    assert after != before, "跨代次（关开联动）同会话同 step 的新回合不得撞旧身份"
    assert after is not None and after[3] > before[3]


# ---- 用户中止的回合静默收尾（桥接 turn/end 携带 reasonKind）----

def test_aborted_turn_end_maps_to_idle_not_success():
    from pet.dsh_state import map_event_to_state
    assert map_event_to_state({"event": "turn/end", "reasonKind": "aborted"}) is DshState.IDLE
    assert map_event_to_state({"event": "turn/end", "reasonKind": "completed"}) is DshState.SUCCESS
    # 旧桥接：无 reasonKind → 保持原 SUCCESS 行为
    assert map_event_to_state({"event": "turn/end"}) is DshState.SUCCESS


def test_aborted_turn_end_yields_no_completion_identity():
    from pet.dsh_state import TurnCompletionTracker
    tr = TurnCompletionTracker()
    tr.observe({"event": "turn/start", "sessionId": "s1"})
    assert tr.observe({"event": "turn/end", "sessionId": "s1", "step": "1",
                       "reasonKind": "aborted"}) is None
    tr.observe({"event": "turn/start", "sessionId": "s1"})
    assert tr.observe({"event": "turn/end", "sessionId": "s1", "step": "2",
                       "reasonKind": "completed"}) is not None


def test_aborted_turn_end_transition_carries_source():
    """中止 turn/end 收敛为 idle 时必须带 source_event（消费侧据此回待机/撤确认）。"""
    conv = DshStateConverger()
    conv.handle_record({"event": "turn/start", "sessionId": "s"})
    out = conv.handle_record({"event": "turn/end", "sessionId": "s", "reasonKind": "aborted"})
    assert out == [("state", "thinking", "idle", "turn/end")], out


def test_aborted_turn_end_after_idle_baseline_still_emits_marker():
    """旧 AgentStatus idle 基线先到时，中止 turn/end 不得被同态去重吞掉。"""
    conv = DshStateConverger()
    conv.handle_record({"event": "turn/start", "sessionId": "s"})
    conv.handle_record({"event": "AgentStatus", "state": "idle"})
    assert conv.current_state is DshState.IDLE
    out = conv.handle_record({"event": "turn/end", "sessionId": "s", "reasonKind": "aborted"})
    assert out == [("state", "idle", "idle", "turn/end")], out


def test_aborted_turn_end_releases_approval_and_question_latch():
    """锁存（审批/问题）期间用户中止：中止终结整轮，锁存解除并回 idle，不得被吞。"""
    for req in ({"event": "approval/request", "sessionId": "s"},
                {"event": "question/requested", "sessionId": "s"}):
        conv = DshStateConverger()
        conv.handle_record({"event": "turn/start", "sessionId": "s"})
        conv.handle_record(req)
        out = conv.handle_record({"event": "turn/end", "sessionId": "s", "reasonKind": "aborted"})
        assert conv.current_state is DshState.IDLE, (req, out)
        assert out and out[-1][2:] == ("idle", "turn/end"), out
        # 锁存已解除：后续 working 正常推进
        assert conv.handle_record({"event": "tool/call", "sessionId": "s", "tool": "bash"})
