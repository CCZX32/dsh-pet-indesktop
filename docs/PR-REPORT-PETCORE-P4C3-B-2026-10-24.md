# P4-c3 B：提醒交付与共享语音端口（2026-10-24）

> **状态：B已实现；本批整仓及高负载自动化通过；Windows隔离源码通过。真实TTS、物理通知点击与候选包仍未验证。**
> 前序：[A质量门禁](PR-REPORT-PETCORE-P4C3-A-2026-10-24.md)。
> 边界：[规格](PETCORE-SPEC.md)、[路线图](PETCORE-ROADMAP.md)、[L058](PETCORE-LOG.md)。

## 一、核心特性与范围

本批提供增量兼容端口，不在Core放待办/历法/签池业务。保留原48项修复与A批修复，无提交、发布或真实账号操作。
- PetHandle声明现有config；Presentation支持for_slot及真实交付bool。目标关闭后不转移到其他宠物。
- 隐藏宠物/设置抑制气泡时使用可用的原生托盘通知；不可用明确记录。通知回调有slot/owner代次保护。
- 免打扰将自动提醒暂存至128项有界队列，每只宠物跨扩展汇总一次；不补播语音。原手动force反馈兼容，不作为自动提醒绕过入口。
- 共享语音队列默认16项，单worker保留阻塞合成所有权；on_done保持合成/启动播放含义，on_finished仅真实媒体结束触发。
- token/owner/slot取消、关闭代次与可撤销让位规则；宠物关闭、扩展停用和进程退出取消待交付任务。
- 真实QMediaPlayer在异步Loading期间立即play/stop会在本环境阻塞；改为LoadedMedia后排队播放，未开始播放时不调用stop。独立进程回归覆盖两次实际EndOfMedia、立即取消、加载中重复请求及失效来源重试，未使用全局Qt补丁。
- Core/API版本尚未调整；需要新增接口的扩展升版时一并声明Core0.2.0/API1。

## 二、修改文件说明

统计口径：本批开始时62个dirty文件保存在`.scratch/petcore-p4c3/baseline-b/files`。
与该快照（未变文件取HEAD）比较；新增文件与空文件比较。累计差异另列，不覆盖A的历史统计。

<!-- FILE_TABLE_BEGIN -->
| 文件 | 本批增删 | 对HEAD累计增删 | 修改内容与原因 |
|---|---:|---:|---|
| `petcore/contracts/host.py` | +13/−2 | +13/−2 | 声明现有宠物配置、slot绑定展示和有返回值的提醒交付协议。 |
| `petcore/contracts/speech.py` | +13/−1 | +13/−1 | 增量声明实际播放完成、owner/slot/token取消及可撤销让位，不破坏on_done旧语义。 |
| `petcore/ui/speech_channel.py`（新增） | +249/−0 | +249/−0 | 有界单worker语音队列、播放结束等待、取消代次及队列拒绝回调抑制。 |
| `petcore/ui/reminders.py`（新增） | +82/−0 | +82/−0 | 有界DND暂存、同宠跨扩展单摘要、通知降级与取消保护。 |
| `petcore/ui/ports.py` | +87/−126 | +87/−125 | 复用新语音通道；真实QMediaPlayer结束/错误、LoadedMedia启动门控、QuietMode订阅。 |
| `petcore/ui/app.py` | +55/−20 | +63/−22 | 绑定目标宠物、真实展示返回值、系统托盘出口及退出释放服务。 |
| `petcore/ui/pet_window.py` | +3/−2 | +3/−2 | 隐藏窗口不宣称气泡展示成功，显示路径返回真实状态。 |
| `petcore/ui/pet_manager.py` | +5/−0 | +5/−0 | 关宠取消对应语音和暂存提醒，保持其他宠物。 |
| `petcore/mods/feature.py` | +7/−8 | +7/−8 | 停用扩展统一取消该owner资源后停止runtime。 |
| `tests/test_petcore_reminder_ports.py`（新增） | +308/−0 | +308/−0 | 新增9项真实Qt/线程及独立媒体进程回归，覆盖单通道、晚回调、DND、slot、加载重入、失效来源重试和结束。 |
| `tests/test_petcore_p5.py` | +1/−0 | +10/−5 | 手动force反馈测试显式展示真实窗口，锁住原兼容语义。 |
| `docs/INDEX.md` | +2/−0 | +7/−1 | 登记B报告。 |
| `docs/PETCORE-LOG.md` | +9/−0 | +129/−0 | 追加L058范围、验证及后续断点。 |
| `docs/PETCORE-LOG-INDEX.md` | +2/−0 | +8/−0 | 登记L058。 |
| `docs/PETCORE-ROADMAP.md` | +7/−0 | +34/−10 | 分别记录B实现/验证和C–E后续状态。 |
| `docs/PETCORE-SPEC.md` | +7/−0 | +25/−1 | 记录B增量接口与剩余提醒业务边界。 |
| `docs/PR-REPORT-PETCORE-P4C3-B-2026-10-24.md`（新增） | +100/−0 | +100/−0 | 本批逐文件、性能、原生和真实测试证据及缺口。 |
| `docs/PETCORE-MOD-FORMAT.md` | +15/−0 | +15/−0 | 补充slot绑定、提醒交付结果、真实播放完成与取消/让位的API 1增量协议。 |
<!-- FILE_TABLE_END -->

### 行为回归与真实输出

最终无过滤`full-b-2`：**9729passed、20skipped、14warnings、1755.57s，pytest进程exit0**。XML与JSON已完整保存。外层scratch运行器随后在回显中文警告时遇到cp1252编码错误、返回1；这不是pytest失败/崩溃。运行器已显式UTF-8回显，原始输出不改写，后续文档门禁验证其正常返回。

运行器：`.venv/Scripts/python.exe .scratch/petcore-p4c3/run.py LABEL COMMAND ...`，原始输出与JSON在同目录。
- `b-ports-red`：4failed；`b-ports-green`：24passed。
- `b-delivery-red`：2failed；`b-delivery-green4`：26passed。中间原生子进程timeout记录保留，不能计为通过。
- `b-petcore`：1333passed/1failed；旧手动force用例修正后`b-ports-final`：66passed/7.74s。
- `b-rejected-red`：1failed；队列拒绝回调取消后迟到已用代次修复。
- `b-mixed-summary-red`：1failed（同宠两个扩展产生两份摘要）；`b-mixed-summary-green`：7passed/2.60s。
- `b-related-final`曾引用不存在测试文件，无测试执行；保留原始记录，不算通过。
- `b-stress`：20个自有CPU负载进程，98.1/99.9/100.0%下三遍各30passed，14.27/15.28/14.59秒、exit0；均已回收。混合摘要新断言在最终门禁补跑。
- `b-repeat-red`：1failed，同一URL仍Loading时重复请求提前play；`b-repeat-green`：67passed。启动回调再次检查媒体状态。
- `b-invalid-red`/`b-invalid-red2`：重复InvalidMedia来源无结束/错误通知，分别立即断言失败/真实事件循环10秒超时失败；改为清空该失效来源后重新加载，保留重试恢复能力。
- `b-audio-final`：68passed/9.81s/exit0，为两项修复后的关联回归；最终高负载及整仓使用`b-stress-final`、`full-b-2`。
- 无过滤整仓`full-b-1`：9727passed、20skipped、15warnings、1267.69s、exit0。开始后发现上述媒体问题，因此仅为中间快照；`full-b-2`才覆盖最终音频实现，不沿用A结果。
- 最终`b-stress-final`：20负载进程、CPU100.0/100.0/99.9%，三遍各32passed（28.38/17.92/18.72s）、exit0；负载进程全部回收。首次stress记录保存在`b-stress-initial`，不覆盖历史证据。

## 三、性能分析

环境同A：Windows、项目内CPython3.11.1、PySide6/Shiboken6.11.1。脚本`b_perf.py`使用真实Qt调度与线程，合成和音频边界使用本地确定性替身，不测外网TTS耗时。
每个场景15秒预热、60秒采样，前后各3遍；每秒一次语音作业。记录CPU、RSS、线程、定时器、I/O、网络审计和启动回调耗时。每遍61次作业；每遍新增读写字节/次数0、network事件0、系统other I/O 62次（包括GUI/计时器等，不推断每次具体系统调用）。

| 场景/遍次 | 采样秒数 | CPU | RSS字节 | 线程min–max | 启动回调均值ms | 遗留调度器timer最大 |
|---|---:|---:|---:|---:|---:|---:|
| before/1 | 60.015 | 0.703% | 44511232→44253184 | 4–7 | 1.622 | 0 |
| before/2 | 60.253 | 0.752% | 44503040→44220416 | 4–7 | 1.551 | 0 |
| before/3 | 60.274 | 0.596% | 44527616→44756992 | 4–7 | 1.667 | 0 |
| after/1 | 60.292 | 0.700% | 43831296→44302336 | 5–8 | 1.491 | 0 |
| after/2 | 60.082 | 0.780% | 43814912→44466176 | 5–8 | 1.576 | 0 |
| after/3 | 60.300 | 0.622% | 43974656→44441600 | 5–8 | 1.470 | 0 |

数据为冻结语音代码后的重采集；期间有短暂DND相关单元探针及文件读取，不是独占机器或硬实时基准。该路径差异不作为“更快”的结论。

稳态：未排队语音不保留工作线程；有待播作业最多一个合成worker。新增有限队列/取消状态，媒体播放使用Qt原生后端自身线程，不声称总线程永远只有一个。
新增成本：每个语音作业一个GUI调度请求，真实播放额外媒体加载/结束事件；DND仅有待汇总时启用1秒定时器。端口本身不新增磁盘写入/外部请求；合成由已有SpeechService负责。远端服务未实测。
资源循环见下节，不把短期RSS稳定等同于排除长期泄漏。

## 四、实机运行记录

命令：`.venv/Scripts/python.exe .scratch/petcore-p4c3/native_b.py`。隔离目录`native-core-b`，Qt windows平台；合成文本/配置，不使用真实账号。
`b-native`：exit0，14.9秒；应用剩余Python线程仅MainThread。
- 菜单GC后13子菜单有效，托盘、设置保存/取消、双宠配置隔离通过。
- 隐藏子宠交付返回notification；托盘支持与可见性真实探测通过。通过messageClicked信号验证回到slot1，**未验证操作系统通知的实际鼠标点击**。
- 三条DND提醒汇总为一条，取消30轮pending0；关宠后绑定展示返回False。
- 托盘30轮RSS216059904→216059904字节，线程23恒定、子菜单2；菜单/岛开关30轮RSS206172160→206176256，线程22恒定，菜单遗留0。
- 实际系统采样、岛展开后network折叠停采样、隐藏停止采样与退出通过。截图在隔离证据目录。
- 测试独立进程生成44100Hz、1秒、音量0的合成PCM，真实媒体两次EndOfMedia后立即取消第三次重播，正常退出；不是TTS或人工听音验收。

修复后的`b-native-final`再次通过，exit0、外层11.799秒，剩余Python线程MainThread：同样覆盖双宠、菜单、通知路由、DND、设置及退出。托盘30轮RSS214228992→214929408字节、线程23、QMenu2；菜单/岛30轮RSS205713408→205721600、线程22、QMenu0。两次记录均保留，不能用首次RSS完全不变掩盖复测的小幅增长。

### 限制与下一步

其他Python、macOS/Linux、双屏、真实TTS、真实通知鼠标点击及候选安装包尚未验证。通知平台不提供逐条消息ID，托盘点击路由到最新有效可点击提醒。
B门禁收口，继续C待办，再D节日生日、E48签；不发布、不扩大角色/Agent/灵动岛范围。


## 2026-10-24 C–E后续记录

以上内容保留本批完成时的状态/原始结果；随后C待办、D节日生日、E48签已实施，最新联合门禁与验证缺口请读[E报告](PR-REPORT-PETCORE-P4C3-E-2026-10-24.md)。不把早期“尚未实施”当作当前状态，也不以本批选定用例替代后续完整全仓。
