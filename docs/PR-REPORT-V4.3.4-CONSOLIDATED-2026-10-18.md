# v4.3.4 成体系修复：两个模型盲审 + 逐条红绿

> 分支 `release/v4.3.3`（发布前改版本号为 4.3.4），基线 v4.3.3 = `a4c8b7f`。
> 触发原因：v4.3.3 发布数小时内两位用户报告仍无声（#307 及另一位），用户明确要求
> 「从 4.3.0 到这次任务的修复都过一遍，不想再出一点小问题修一点」。

## 一、方法：先归纳模式，再找全部实例

盲审由两个独立模型执行（`gpt-6-astra` 全面审查 + `Agents-A1` 复核），均为**只读**、
基于 `git log v4.3.0..HEAD` 与代码取证。第二轮的任务不是复述第一轮，而是核对
「每条是否真修好」并**继续找同一模式的漏网实例**。

最终归纳出七类模式：

| 模式 | 本批修复的实例 |
|---|---|
| **读写作用域分裂**（每宠键用主配置读） | 点击朗读判据、音频通道生命周期、主宠 `cfg`、chat 会话角色、灵动岛名、主动识屏 `pet_name`、托盘角色勾选 |
| **运行态与持久态两套身份** | 拖到副屏后 `home_screen` 更新但 `screen_name`／待写归属没更新 |
| **输入范围扩张、通知范围没扩张** | 刷新率取数枚举全部屏，但只订阅窗口自己那块屏 |
| **「调用成功」冒充「交付成功」** | 待办/报时/节日的气泡返回 False 却被当成已送达 |
| **缓存键不是实际计算输入的指纹** | 台词纯文本键（换音色永不更新）、报时键用配置原音色而非 resolved 音色 |
| **单飞防重变丢更新、开启门没有运行期撤销** | 预缓存合成期间保存被丢弃、关开关不停止后续句子 |
| **测试按内部捷径验证** | 跨屏持久化绕过鼠标拖拽；缓存 expected 复用错误配置；作用域测试抹平 slot/global |

## 二、修改文件说明

产品代码（净改动）：

| 文件 | 改了什么 + 为什么 |
|---|---|
| `pet/overlay_shell.py` | `cfg` 改回**主宠每宠视图**（点击朗读/台词池/角色都读它）；新增 `_mixed_dpr()`，混合缩放时 `_desktop_bounds` 退化为家屏可用区（一张窗只能一个 DPR）；`_activity_rects` 同步只留家屏；拖拽收尾补记屏幕归属并**松手即落盘**（且只在原归属屏仍在线时算有意换屏，拔屏的临时承载不动归属）；`move_sprite_to_screen` 改按活动区判定；全屏订阅 `refreshRateChanged` 并接/摘一致 |
| `pet/app.py` | `_self_talk_speak_wanted` 改读每宠视图；`_self_talk_voice_configs` 修正底层表名（`_instances`）与测试桩容错；`_sync_chat_sessions` 的角色走 `_identity_config()`；`_identity_config()` 新增，供灵动岛/托盘/识屏取当前呈现身份 |
| `pet/todo_reminder.py` | 气泡返回 False 时改道系统通知（不再吞掉）；`_daily_due` 枚举昨天/今天/明天，跨午夜宽限窗生效 |
| `pet/window.py` | legacy `show_bubble` 返回布尔，与 overlay 同契约 |
| `pet/voice_chime_service.py` | 气泡被占时不再静默；缓存键改用 attempt 的 resolved `provider+values`；设置页抑制期的直写抽成 `_bubble_in_slot` |
| `pet/festival_service.py` | 与报时同型修复 |
| `pet/self_talk_voice.py` | 缓存键加 `provider.flavor(values)`；经典文本 wav 降为兼容来源；`_pending_run` 支持补跑与取消 |
| `pet/voice_chime.py` | `cache_key` 接受 `values=`（三处调用共用同一份 resolved attempt） |
| `pet/dynamic_island.py` / `pet/proactive.py` / `pet/multi_window_shared.py` | 角色身份经 provider 取，不再读全局 `character` |
| `pet/modern_settings_dialog.py` / `pet/settings_interaction.py` | 点击内容设置（文本/配图目录/概率/时长）改为「周期或点击任一开启」即显示；节奏项仍只跟周期 |

测试：新增 `tests/test_process_service_identity.py`；改写两条把 bug 写成契约的断言
（`test_precache_worker_uses_resolved_voice` 用旧 `_cfg` 造 expected；
`test_click_self_talk_rows_follow_their_own_toggle` 断言「只开点击时内容项隐藏」）；
新增约 25 条回归，全部先红后绿。

## 三、性能分析

| 路径 | 开销 | 触发频率 |
|---|---|---|
| 拖拽收尾多一次几何自存 | 中位 3.4 ms（一次性原子写） | 用户每次拖拽结束 |
| `_mixed_dpr()` | 每屏一次 `devicePixelRatio()` 比较 | 建壳 + 几何同步（非每拍） |
| 台词点击查找 | 0.071 → 0.265 ms（flavor 解析 0.038 ms，且不再读钥匙串；磁盘侧由整目录 glob 变 ≤3 次精确 stat） | 每次点击 |
| `_attempts` 每轮解析 | 0.7–1.6 ms | 每次预缓存批次（一次，非每句） |
| `refreshRateChanged` 接线 | 每块屏一条信号连接 | 改刷新率/插拔屏 |

无新增线程、定时器、网络请求；常驻内存无增长路径。

## 四、实机运行记录

- 本机双屏（主屏 2560×1440 avail 1392 @170Hz + 左侧副屏 1920×1080 avail 1032 @60Hz，
  DPR 均为 1.0）：部署 v4.3.3 后实测合成窗 `(-1920,0,4480,1392)`、tick 6ms、帧序列
  106 段，跨屏拖拽/探头/设置说明均正常（用户当场确认「用起来正常了」）。
- 台词语音：用用户真实配置（slot0 档案 22 句）跑预缓存 → **22 句全成、0 失败**，
  26.5 s；`cached_audio` 命中验证通过。
- SAPI 线程 COM：修复前后台线程 `WinError -2147221008`，修复后同线程取到 3 个音色、
  真合成 60 872 字节 wav。
- 混合缩放 / 150% DPI（#307 问题一、#286）：**本机不具备**（两屏同 DPR、100%），
  只做到代码级退化路径与自动化用例，未声称实机验证。

## 五、已知未修（如实）

- **#286**（150% DPI 下点不到、legacy 拖不动）需要该缩放环境 + 现场探针；报告者的
  「活跃清单启动不注册」经核为代码注释写明的有意设计（启动期不替用户改盘）。
- `VoiceChimeService.apply_config()` 不中止**已起飞**的合成：已提交的句子用旧音色
  播完属可接受契约，未改。
- 待办 fire 的「每档一次」戳语义未改：气泡+通知双不通时只留 warning，不无限重试。
- 混合 DPI 下跨屏不可用（窗口退化），未做按 DPR 分组拆窗。
