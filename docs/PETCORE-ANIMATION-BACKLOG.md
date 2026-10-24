# petcore 动画与性能 backlog

> 基线：`feat/petcore-vpet-architecture`，2026-10-20。这里只列**刻意延后**的动画/
> 性能项、依赖与验收；已经完成的交互动画见 `PETCORE-ROADMAP.md` §11。

> **2026-10-24 待执行专项**：[动画画质评估与串行执行计划](PETCORE-ANIMATION-QUALITY-ASSESSMENT-2026-10-24.md)。
> 比较小小桌宠与当前 petcore；先修动画 DPR，再独立评估 Q70 编码损失。
> 目前仅完成调查与任务书，未实施；改动画缩放、屏幕 DPR 或筹划改编码档位前必读。

## 已完成（P2-A，本轮）

| 项 | 入口 | 验收 |
|---|---|---|
| 点击 Q 弹 | `ui/effects.py` + `engine/squash.py` | 220ms、底部居中、旋转/探头叠加、命中逆变换 |
| 黄金回旋 | `ui/effects.py` + `engine/spin.py` | 点击触发/直连、连击累计圈数、逐圈加速 |
| 探头击飞旋转 | `ui/effects.py` | 探头激活被甩飞时头部跟随速度；低速碰边/停稳恢复 |
| 弹弓形变/轨迹 | `ui/slingshot.py` + `engine/physics.py` | 拉拽距离/形变/轨迹点/发射 |
| 投喂吃动画 | `ui/feeding.py` + `engine/feeding.py` | 文件统计预算、吃动画选择、气泡反馈 |
| 碰撞 Q 弹 | `engine/collision.py` + `ui/pet_manager.py` | 两宠弹开、低速只分离、连续 3 tick 强制分离 |
| 播放速率/动作等待间隔 | `ui/pet_window.py` | 0.5x–2.0x、0–3600s；点击/拖拽立即打断 |
| 移动朝向/位移同步 | `engine/motion.py` + `ui/pet_window.py` | 方向先设 facing；curve 静态帧不位移；末拍到位 |
| 待机掷骰/可调概率 | `ui/pet_window.py` + `engine/behavior.py` | 待机一圈 = 掷骰时机；四项权重归一化，设置可调（默认 30/10/40/20） |
| 事件动画（余额 6 档） | `engine/catalog.py` + `ui/pet_window.py` | `events/<group>` 独立于随机动作池，`play_event()` 按名字/索引触发 |

## 可导入 mod 示例（P2-B2 / examples）

| 项 | 依赖 | 验收 |
|---|---|---|
| ~~音乐唱歌动画~~ | `media.music` 的 SMTC 检测 | **P4-b 完成**：检测到播放 → `play_animation(loop=True)`；静音 grace 后 `release_loop()` |
| ~~歌词对齐/多歌手~~ | 同上 | **P4-b 完成**：歌词气泡节流（≥2s/行），`lyric_align` 循环偏移；多歌手仍未做 |
| ~~语音报时动画/口型~~ | `voice.chime` | **P4-b 完成（口型除外）**：报时走 `SpeechPort`；口型主分支也未实现 |
| 节日/待办提醒动画 | `fun.festival` / `reminder.todo` | **未实现的验收目标**：到期提醒可见、可完成/忽略、跨午夜宽限；当前只有清单 CRUD / 公历查询，不在本轮补功能 |

## P4（P3 之后）

| 项 | 为什么延后 | 计划 |
|---|---|---|
| 共享解码 broker | 多宠/多窗共享帧缓存，先等 P2 多宠稳定 | 每角色每动画单解码器 + LRU；内存/帧率实测 |
| 预测预热 | 依赖行为机与播放链稳定 | 预测 idle/move 首帧；交互让路时取消 |
| WebM→WebP 全量 | 首跑供给已跑通，全量耗时/磁盘策略未定 | `petcore provision --all`、世代 GC、失败诊断 |
| VPet PNG 序列后端 | 只留 `Clip` 接口 | `PNGAnimationClip`，按文件名尾数计时；不承诺 LPS |
| Agent 联动动画 | P4-c2 `ai.agent` | 只读六态映射已实现；真实外部写方验收与安装未做 |
| 灵动岛 | 独立 Core UI 域（ROADMAP §28） | P5-a1 胶囊/系统网络指标/展开卡片已实现；果冻/碰撞等第二阶段未做 |
| `head_box` 精细探头 | 当前曝光只用 `body_box` 投影 | 用 head_box 算“只露头”锚点，body_box 兜底 |

## 明确不做

- 跨进程碰撞 IPC、每屏多宠、overlay `ScreenHost`；
- Core 自更新、签名/分发；
- 兼容 VPet LPS 素材格式。

> P6 起 `keyring` 不再是「不做」：API 密钥由 `petcore/api/credentials.py` 存系统
> 钥匙串（不可用时退内存），构建脚本已收集 keyring 的 Windows 后端。
