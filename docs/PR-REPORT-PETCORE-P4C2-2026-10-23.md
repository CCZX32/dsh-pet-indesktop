# P4-c2 交付：Agent 联动 `ai.agent` 扩展（2026-10-23）

> 把主分支 `pet/agent_link.py`（6303 行）的**只读联动**那半边，按本分支的
> core + mod 架构重做成一个可卸载扩展。Core 只加三条通用接缝，不认识任何 Agent。
> 行为口径写在 `docs/PETCORE-SPEC.md` §28；写方协议仍是
> `docs/AGENT_LINK_PROTOCOL.md` §2。

## 1. 修改文件说明

| 文件 | 增/删 | 做了什么 & 为什么 |
|---|---|---|
| `petcore/contracts/host.py` | +3 | `StoragePort.data_root()`、`PresentationPort.visible()`、`PetHandle.animations()`。没有它们，mod 拿不到事件目录、判不了隐藏态、也拿不到角色动作名（只能硬编码动作名，换角色包就哑）。 |
| `petcore/ui/ports.py` | +18 | `StorageAdapter.data_root()` 返回数据根；`PetHandleImpl.animations()` 走 `catalog.names_for(GraphType.ACT)`（异常吞掉返回空，不影响桌面）。 |
| `petcore/ui/app.py` | +5 | `_PresentationAdapter.visible()` = 目标窗口 `isVisible()`；隐藏态据此跳过联动动画。 |
| `petcore/ui/icons.py` | +9 | 新增 `agent` 图标（机器人头），菜单与设置页共用；未知图标名会退化成圆点，所以必须补。 |
| `petcore/config.py` | +70 | 13 个 `ai_agent_*` 全局键：`GLOBAL_CONFIG_KEYS` + `DEFAULTS` + `_normalize()`；新增 `_agent_links()/_agent_link_key()` 清洗自定义条目（key 正则、去重、≤8、保留 `dsh`）。 |
| `petcore/menu_templates/petcore-default-v1.json` | +1 | `ai.agent:enabled` 插在 `ai.chat:proactive` 之后。 |
| `petcore/ui/menu_layout.py` | +1 | `BUILTIN_DEFAULT_LAYOUT` 同步（打包丢数据文件时的兜底副本，两份必须一致）。 |
| `examples/petcore-mods/ai.agent/mod.json` | +21 | v1.0.0 / host-only / 能力：`files.read`、`settings.read`、`settings.write`、`speech.present`、`sound.play`。 |
| `examples/petcore-mods/ai.agent/host/protocol.py` | +197 | 纯解析：`state` 优先、`event` 查表（Claude hooks + DSH 事件 + 裸状态名）、`turn/end` 带 `aborted/blocked/max_tokens/unknown` 收敛 idle、BOM、4KB 行上限、工具名文案表。 |
| `examples/petcore-mods/ai.agent/host/tailer.py` | +139 | `ByteTailer`：首次见到**已存在**的文件跳到末尾（不回放历史），监视开始后**新出现**的文件从头读；单次 64KB、半行缓冲 ≤8KB、截断/轮转重读一代。`GlobTailer`：`dsh*.jsonl`，启动快照判历史，按 mtime 最多 8 个。 |
| `examples/petcore-mods/ai.agent/host/links.py` | +253 | `LinkEngine`：多写者折叠、去抖 + 2 s 节流、800 ms 完成确认（窗口内回到忙碌即静默取消）、5 s 完成冷却、错误回合报「这轮好像没能跑完」、动作池 `写代码/吃Token` 交替 + 每 3 次插播摸鱼 + 关键词回退、过程气泡 10/8/60 s、三档音效带冷却、隐藏态不切动画。 |
| `examples/petcore-mods/ai.agent/host/runtime.py` | +371 | `Runtime` 协议（`start/stop/close`）：唯一轮询线程 1.5 s，配置每轮现读（来源签名变了就重建 tailer），解析结果经 `scheduler.call_later(0, …)` 回 GUI；关闭期间继续推进偏移（重新开启不回放）；`commands={"agent_toggle"}`。 |
| `examples/petcore-mods/ai.agent/host/settings_page.py` | +453 | H2 + 5×H3（总开关 / 事件来源 / 动画与气泡 / 音效 / 诊断）；控件改动即时写全局配置，`discard_changes()` 从打开时快照回滚；诊断面板列来源目录 + 最近一行事件，「发送测试事件」写 demo 事件走完整链路。 |
| `examples/petcore-mods/ai.agent/host/__init__.py` | +44 | 入口：`settings_page` 贡献 + 菜单 `ai.agent:enabled`（`checked` 读 `ai_agent_enabled`）。 |
| `packaging/petcore.iss` | +3/−1 | `mod_agent` 任务（`Flags: unchecked`）+ `{app}\mods\ai.agent` + `.trusted`；顺手修掉「以下 5 个官方 feature」的过期注释。 |
| `tests/test_petcore_agent_mod.py` | +854 | 70 条：协议映射/坏行、tailer 增量/半行/轮转/上限/glob、状态机（去抖、完成确认、抖动取消、冷却、错误回合、多写者、音效、隐藏态）、runtime（统一目录、DSH 桥、关闭期间推进偏移、来源重建、自定义文件、内置音、toggle、诊断上限）、设置页（分组、实时写、回滚、诊断）、配置归一化。 |
| `tests/test_petcore_installer.py` | +1 | 可选任务表加 `("ai.agent", "agent")`。 |
| `tests/test_petcore_menu_layout.py` | +1 | 默认模板顶层顺序加 `ai.agent:enabled`。 |
| 文档 | — | SPEC §28（键表/六态/线程/行为口径）、MOD-FORMAT §15、ARCHITECTURE §25、ROADMAP §27（含 c2.1 待办）、PARITY、AGENT_LINK_PROTOCOL §7（本分支范围对照）、`petcore/AGENTS.md` 联动红线、`examples/petcore-mods/README.md`（8 → 9 个包）、LOG `L052` + 索引、本报告 + `docs/INDEX.md`。 |

## 2. 性能分析

环境：Windows 10、150% 缩放、`QT_QPA_PLATFORM=offscreen`、`.venv` Python 3.12；
样本在同一进程内连续计时（`.scratch/probe_agent.py`）。

| 路径 | 样本 | 实测 |
|---|---|---|
| `parse_line()`（典型 DSH 记录） | 20 000 行 | 57.1 ms → **35 万行/秒**，**2.86 µs/行** |
| `LinkEngine.handle()`（含节流判定） | 20 000 事件 | 83.8 ms → **4.19 µs/事件** |
| `ByteTailer.read_lines()`（追加 10 行） | 1 次 | **0.18 ms**（790 字节） |
| `petcore.mods.loader` 导入 | 1 次 | 95 ms（进程启动一次性） |

结论与预算：

- 轮询线程 1.5 s 一拍，稳态实际开销 = 「stat + 读新增字节」，空转接近 0；即使一个
  会话一秒写 200 条事件，一拍内解析 + 状态机也只要 ≈1.4 ms，远低于 1.5 s 预算。
- 单次读取封顶 64KB（≈800 条典型记录），最坏一拍解析 ≈2.3 ms；**不会**因为事件文件
  长期不轮转而越读越多。
- 状态机与呈现全部在 GUI 线程，但只在**真的有待处理行**时才 `call_later(0, …)`；
  一条事件的处理量是微秒级，不会挤掉动画帧。
- 关闭联动时仍推进偏移（不做解析、不回调），重新开启不会补播关闭期间的历史。

## 3. 实机运行记录

**A. 门禁（本机实跑）**

```
$ .venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods/
All checks passed!

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
    tests/test_petcore_*.py tests/test_architecture.py \
    tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
1426 passed in 54.76s          # 基线 1356，本轮 +70

$ .venv/Scripts/python -m petcore --check
exit 0，menu_template=json
```

**B. 真实 loader + 真实 Config（隔离 root，不动用户数据）**

```
$ .venv/Scripts/python -m petcore --root .scratch/agent-root --portable \
    mods install examples/petcore-mods/ai.agent
installed ai.agent 1.0.0 -> .scratch\agent-root\mods\ai.agent

# 默认 allow_feature_mods=false，如实报禁用：
diagnostics: ["ai.agent: feature mods disabled"]

# 打开开关后：
mods: [{"id": "ai.agent", "kind": "feature", "version": "1.0.0", "enabled": true}]
diagnostics: []
```

**C. 源码树端到端（真实 `Config` + 真实 `QtScheduler` + 真实文件 + 真实 mod 包）**

`.scratch/probe_agent_e2e.py`：offscreen QApplication，写入三条事件，跑 9 秒事件循环。

```
# 1.6s  UserPromptSubmit      → 联动动作
# 2.6s  PreToolUse(tool=bash) → 过程气泡
# 5.2s  state=idle            → 800 ms 后完成通知
animations: ['写代码']
bubbles:    [('正在跑命令', False), ('干完活啦', True)]
recent:     thinking → working → idle（三条都在，agent=demo）
states:     {'demo': 'idle'}
```

（`thinking → working` 间隔 1 s，被 `ai_agent_min_interval_seconds=2.0` 正常节流，
所以只切了一次动作——与主分支一致。）

**D. 真机 GUI 冒烟（源码树，隔离数据根）**

```
$ .venv/Scripts/python -m petcore --root .scratch/agent-root --portable     --allow-feature-mods --verbose      # 15 秒后终止
[ai.agent] agent=demo writer=default state=thinking event=UserPromptSubmit tool=
[ai.agent] agent=demo writer=default state=working  event=PreToolUse     tool=bash
[ai.agent] agent=demo writer=default state=working  event=tool/call      tool=read
[ai.agent] agent=demo writer=default state=idle     event=
# 无 ERROR / 无 Traceback / 无 "animations() failed"
```

这一轮抓到两个**只在真机才暴露**的问题，都已修复并补回归：

1. `AgentLinkRuntime._log()` 没有 `level` 参数——单元测试的 ctx 替身没走这条路径。
2. `PetHandleImpl.animations()` 用了**不存在**的 `GraphType.ACT`，异常被端口吞掉后
   mod 拿到空动作池 → 联动永远不切动作。改成 `GraphType.DEFAULT`（与行为链 `act()`
   同池，实测该角色 89 个动作里包含 `写代码`/`吃Token`），并补两条用真实
   `GraphCatalog` 的回归测试。

**未做真机视觉验收**：本批只改源码树与安装器脚本，未重打 PyInstaller/Inno 产物；
GUI 呈现（气泡位置、动作观感）由用户在实际运行中确认——设置页
「扩展管理 → Agent 联动 → 诊断 → 发送测试事件」一键即可复现上面这条链路。


## 2026-10-24 补充：测试范围口径

保留上文原始执行记录。上文「全量」应理解为命令中列出的 `test_petcore_*.py`
及公共门禁文件的选定测试，不是仓库全量 `python -m pytest -q`。不能用这些历史
数字代表本轮验收；本轮环境、整仓失败/崩溃、实机与限制见
[已有能力质量审查](PR-REPORT-PETCORE-QUALITY-REVIEW-2026-10-24.md)。
