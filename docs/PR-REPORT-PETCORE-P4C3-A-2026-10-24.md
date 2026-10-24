# P4-c3 A：整仓质量门禁收口（2026-10-24）

> **状态：A 功能退出门与本批证据收口已完成；保留内存观察/平台缺口，B–E / 分发验收尚未实施。**
> 分支 `feat/petcore-vpet-architecture`；HEAD `729441603525f652b731268dbf0f39ff59effff4`。
> 开始时已有48个未提交文件；本轮保存其内容和差异，未重置、提交、推送或发布。
> 前序：[已有能力质量审查](PR-REPORT-PETCORE-QUALITY-REVIEW-2026-10-24.md)。
> 阶段：[路线图](PETCORE-ROADMAP.md)；[规格](PETCORE-SPEC.md)；[L057](PETCORE-LOG.md)。

## 一、核心特性与范围

本批只关闭进入提醒域之前的质量阻断，不新增提醒、生日、抽签、语音接口或市场条目。
没有调整 Core / mod 版本、最低 Python 版本、Qt 依赖版本、权限默认值、动画素材等级或用户配置格式。
A 的功能退出条件是真正整仓 pytest 完整执行且进程正常退出；选定测试不能替代此条件。

1. **退出崩溃**：`_close_instance_subwindows` 不再用无 QObject context 的
   `QTimer.singleShot(0, dialog.deleteLater)` 二次包裹已经延迟执行的 `deleteLater()`。
   父对象先销毁子窗口时，旧队列仍会尝试调用已销毁的对象，触发原生访问异常。
   直接调用 `deleteLater()`，由 Qt 的对象所有权和 DeferredDelete 队列处理。
2. **旧路径菜单**：大小菜单和逐宠托盘菜单显式 `QMenu(label, parent)` 后加入父菜单；
   子菜单不随局部 Python wrapper 释放，父菜单销毁后仍正常释放；未改样式/动作语义。
3. **Pillow 兼容**：私有 L8 连通块掩膜用 `tobytes()` 读取像素；测试辅助器按 API
   可用性读取像素。Pillow11.2.1 能执行原有断言，未启用挂起的 v4 修复或改动 v5 素材等级。
4. **依赖与编码**：项目已声明 `omegaconf` / `opencv-python-headless`；旧全局环境缺前者、
   OpenCV 发行名不一致。项目内干净 Python3.11 环境恢复声明与实际安装一致，未虚增依赖。
   子进程验证显式 `PYTHONUTF8=1`，不再用本机 cp1252 解码中文输出。
5. **历史门禁**：品牌扫描仅精确放行一份历史报告的两行真实分支引用；历史正文未改。
   新回归锁住文档路径与整行内容，其他报告、用户文案、修改后的引用仍被拒绝。

## 二、修改文件说明

本批修改19个产品/测试/文档文件（其中3个新增，无删除）。下表区分开始快照到当前的本批增删与对HEAD累计差异。
统计命令为 `git diff --no-index --numstat --ignore-cr-at-eol <开始副本或HEAD副本> <当前文件>`；新文件与空文件比较。
普通 `git diff --numstat` 不列未跟踪文件，不能遗漏新增回归/报告。

<!-- FILE_TABLE_BEGIN -->
| 文件 | 本批增删 | 对HEAD累计增删 | 修改内容与原因 |
|---|---:|---:|---|
| `pet/app.py` | +4/−4 | +4/−4 | 对子窗直接安排DeferredDelete，移除已销毁QObject仍可能被调用的零延时回调。 |
| `pet/frameseq_provision.py` | +1/−1 | +1/−1 | L8掩膜使用跨Pillow版本的字节读取；不改变v5等级或v4开关。 |
| `pet/overlay_shell.py` | +2/−1 | +2/−1 | 逐宠托盘QMenu显式绑定父菜单，保持刷新前动作的有效生命周期。 |
| `pet/sprite_menu.py` | +2/−1 | +2/−1 | 大小QMenu显式绑定父菜单，避免局部wrapper释放使子菜单失效。 |
| `tests/pillow_helpers.py`（新增） | +7/−0 | +7/−0 | 新增测试辅助器，保留原像素断言并兼容声明的Pillow版本范围。 |
| `tests/test_settings_exit_lifecycle.py`（新增） | +65/−0 | +65/−0 | 新增真实独立进程回归：父对象先销毁、两种DeleteOnClose、原始两用例顺序与正常退出。 |
| `tests/test_sprite_menu.py` | +19/−0 | +19/−0 | 补充GC/事件循环后动作和父菜单定向销毁回归。 |
| `tests/test_desktop_pet_features.py` | +27/−1 | +27/−1 | 品牌门禁仅精确允许历史报告两行引用；锁住文件、行内容和外溢保护。 |
| `tests/test_frameseq_alpha_floor.py` | +4/−2 | +4/−2 | 使用兼容辅助器，保留alpha floor断言。 |
| `tests/test_frameseq_provision.py` | +3/−1 | +3/−1 | 使用兼容辅助器，保留素材处理断言。 |
| `tests/test_frameseq_unblend.py` | +6/−4 | +6/−4 | 使用兼容辅助器，保留反解像素断言。 |
| `tests/test_frameseq_unblend_v3.py` | +8/−6 | +8/−6 | 使用兼容辅助器，保留v3像素与边界断言。 |
| `tests/test_frameseq_unblend_v4.py` | +15/−13 | +15/−13 | 使用兼容辅助器，保留挂起v4及候选块回归，不删除测试。 |
| `docs/INDEX.md` | +2/−0 | +5/−1 | 登记本批报告并给出适用场景；保留上一轮索引变更。 |
| `docs/PETCORE-LOG.md` | +35/−0 | +120/−0 | 追加L057的范围、根因、证据及阶段断点。 |
| `docs/PETCORE-LOG-INDEX.md` | +2/−0 | +6/−0 | 登记L057，保留L054–L056历史。 |
| `docs/PETCORE-ROADMAP.md` | +12/−3 | +27/−10 | 纠正c3状态为A批执行/验收；提醒和分发不提前记为已实现。 |
| `docs/PETCORE-SPEC.md` | +10/−1 | +18/−1 | 记录新批准的串行边界，区分前序质量审查与本阶段。 |
| `docs/PR-REPORT-PETCORE-P4C3-A-2026-10-24.md`（新增） | +215/−0 | +215/−0 | 新增本报告，逐文件说明、测试原始结果、性能、原生记录和缺口。 |
<!-- FILE_TABLE_END -->

完整工作树还包含上一轮48文件，不能把累计差异都归为本批。开始快照位于
`.scratch/petcore-p4c3/baseline/`（`status.txt`、`diff.txt`、`numstat.txt`、`files.json`、
`current-files/`）；`preserved-baseline.json`记录保留检查：原48文件全部存在、43份逐字节未变，另5份是本批追加的阶段/日志/总索引文档。
新增的探针、安装缓存、环境及原始输出均在被忽略的 `.scratch/petcore-p4c3/` / `.venv/`，不混入产品。

## 三、测试与验证

环境：Windows（build 26100）、CPython3.11.1 x64、PySide6/Qt6.11.1、Pillow11.2.1、
pytest8.3.4、Ruff0.16.6。独立 `.venv` 不继承全局 site-packages。
依赖安装命令：`.venv/Scripts/python.exe -m pip install -r requirements.txt -c .scratch/petcore-p4c3/constraints.txt`；
完整 freeze 见 `environment-freeze.txt`，`pip check` 输出 `No broken requirements found.`。
OCR 关键版本：rapidocr3.10.0 / onnxruntime1.31.0 / omegaconf2.4.0 / OpenCV-headless5.0.0.93 / numpy2.4.6。

原始输出和执行命令：每个 LABEL 均保存 `LABEL.txt` + `LABEL.json`（命令、退出码、耗时），
运行器 `python .scratch/petcore-p4c3/run.py LABEL COMMAND ...`。以下不是历史报告的结果复用。

| 验证 | 原始结果 | 证据 LABEL |
|---|---|---|
| 旧环境失败族（修复前） | 25 failed, 335 passed, 5 skipped | stable-red-global |
| 两项设置顺序复现（修复前） | 原生退出3221225477 / 0xC0000005 | settings-min-red |
| 新销毁/菜单回归（修复前） | 4 failed | lifecycle-new-red |
| 修复后设置/菜单关联族 | 92 passed in31.38s，exit0 | lifecycle-green-global |
| Pillow与文档扫描关联族 | 260 passed in28.96s，exit0 | pillow-copy-green |
| 新环境依赖/OCR族 | 68 passed in32.21s，exit0 | dependencies-green |
| Ruff（最终） | All checks passed!，exit0，0.194s | final-ruff |
| 仓库完整pytest | **9716 passed, 20 skipped, 15 warnings in 1315.19s (0:21:55)，exit0** | full-a-1 / XML |
| 高负载三遍 | 每遍143 passed，分别97.00/100.87/98.81s，全部exit0；20个负载进程、轮前CPU99.6/99.9/99.9% | stress-1/2/3 / summary |
| 可用工具补测 | 5 passed in27.38s，exit0；ffmpeg三项+bash两项 | available-tools-green |
| 最终架构/文档/公共回归门禁 | 387 passed in15.58s，exit0 | final-gates |

### 整仓口径与跳过项

完整命令（没有选择路径、没有排除失败测试）：

```powershell
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -X faulthandler -m pytest -q --tb=short `
 --junitxml=.scratch/petcore-p4c3/full-a-1.xml
```

外层记录耗时1318.501s、exit0；原始stdout/stderr保存在 `full-a-1.txt`，不以尾段测试拼成全量。
产品与测试代码在整仓运行前冻结，之后仅整理文档和scratch证据；因此不为纯文档更新再次重复全仓。
本报告是在该轮运行过程中新增的，新增报告的参数化文档检查由最终387项门禁另跑，不能冒称已包含在该轮初始收集中。
15个warning均为既有Qt的QImage.mirrored/QHoverEvent弃用提示，原文保留于日志，未通过过滤器隐藏；20项skip为仓库已有条件，**本批没有新增skip**。
逐用例名称/理由见 `full-a-skips.json`；本轮环境探针见 `skip-environment-probe.json`。

| 数量 | 原因与覆盖边界 |
|---:|---|
| 3 | Windows非管理员环境不能创建符号链接；未为测试提升权限或修改开发者模式。 |
| 2 | bash不在测试进程PATH；已探测到项目外已有Git自带bash，已用子进程PATH补测2passed，不修改系统PATH。 |
| 3 | ffmpeg不在测试进程PATH；venv内imageio-ffmpeg二进制和测试源素材均存在，已仅在scratch内复制同摘要工具后补测3passed。 |
| 2 | 可选GIF派生素材、完整帧序列素材树不存在；不为本批修复生成/覆盖用户素材。 |
| 3 | offscreen下原生前台窗口2项和桌面截图1项跳过；新的应用窗口原生探针不是这些精确场景的替代。 |
| 3 | macOS/AppKit/Cocoa专属能力在Windows不可测。 |
| 2 | POSIX专属分支在Windows不可测。 |
| 1 | Windows无`time.tzset()`，不能在此测试内切换时区。 |
| 1 | 真实声卡发声需显式`DSH_WINMM_SMOKE=1`；本轮未请求真实音频播放，不启用。 |

最小崩溃复现命令：

```powershell
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -m pytest -q --tb=short `
 tests/test_settings_stale_form_exit.py::test_discarding_the_settings_close_lets_the_pet_exit `
 tests/test_settings_stale_form_exit.py::test_app_quit_waits_for_the_settings_window
```

队列探针 `trace_shots.py` 只观察 Python C-call，不替换 Qt API；记录到失败顺序中唯一
`singleShot` 来源是旧 `pet/app.py:4348`。新独立进程测试覆盖两种 WA_DeleteOnClose 设置，
父对象先销毁、定向 DeferredDelete、事件循环继续处理和下一窗口创建，以及上述两项真实顺序。
新回归正常退出，不用 `os._exit`、全局 Qt 补丁、跳过用例或全局冲刷测试队列掩盖问题。

## 四、性能分析

### 菜单：同环境前后各三轮

命令：`.venv/Scripts/python.exe .scratch/petcore-p4c3/perf_suite.py`；每轮独立进程、预热15秒、
采集60秒、1Hz构造/销毁，前后交错各3轮；测试和CPU负载全部结束后执行。原始逐次样本
`perf-menu-{before|after}-{1|2|3}.json`，命令/正常退出记录`perf-menu-runs.json`。
before只加载HEAD的sprite_menu.py副本，after加载当前实现；其余Python/Qt/机器一致。
旧子菜单本来失效，**不能把本对比当成两份功能都正确的完整交互性能比较**。
CPU为进程user+system CPU时间/墙钟（未除20逻辑核），包括探针GC和资源计数，不是应用空闲CPU。

| 版本/轮次 | 采集秒/次数 | CPU（单核口径） | RSS开始→结束MiB | 构造均值ms | 销毁均值ms | 失效子菜单/遗留菜单 |
|---|---:|---:|---:|---:|---:|---:|
| before/1 | 60.22/60 | 0.908% | 38.36→38.36 | 0.5560 | 0.0692 | 60/0 |
| after/1 | 60.36/60 | 1.061% | 37.70→37.62 | 0.5652 | 0.0673 | 0/0 |
| before/2 | 60.30/60 | 1.062% | 37.50→38.13 | 0.5874 | 0.0782 | 60/0 |
| after/2 | 60.18/60 | 1.142% | 38.03→39.21 | 0.6565 | 0.0744 | 0/0 |
| before/3 | 60.21/60 | 0.882% | 37.51→38.68 | 0.7398 | 0.0909 | 60/0 |
| after/3 | 60.16/60 | 0.961% | 38.44→39.07 | 0.6766 | 0.0954 | 0/0 |

三轮均值：构造0.6277→0.6328ms（+5.04µs），销毁0.07942→0.07904ms；CPU0.951→1.055%。
这个样本不支持宣称“更快”。正确性变化为180/180次旧子菜单失效→0/180次失效；每次销毁后遗留菜单均0。
六轮线程数均4–7、自有QTimer为1；实测read/write次数及字节增量均0，Python connect/getaddrinfo审计事件为0；
Windows I/O other_count均2、other_bytes均0。没有把Python审计当成ETW级系统调用全覆盖。
RSS有上下波动，未承诺长期绝对不增长。

### Pillow内部L8扫描

命令：`.venv/Scripts/python.exe .scratch/petcore-p4c3/pillow_perf.py`；640×360掩膜，
非空bbox36×10，预热30次、测量1000次。均值0.2116ms、中位0.1983ms、P95 0.3180ms；
1块/360像素，线程5→5；文件open、connect、DNS审计均0，全部I/O计数增量0。
旧实现于Pillow11.2.1抛AttributeError，不能伪造有效耗时基线或声称性能提升；此为兼容修复后的绝对成本，
不是替代菜单15s/60s×3门禁。原始`pillow_perf.json`。

### 设置与资源留存


Windows原生设置页（先5轮预热，再30轮）：打开至可见平均878.30ms、中位893.39ms、最大956.67ms；
调用关闭并定向销毁所有者平均143.01ms、中位142.27ms、最大167.22ms。此为修复后绝对耗时；
旧故障路径会崩溃，不能据此宣称退出性能提升。

设置页扩展检查：30轮后 RSS143.88→152.97MiB；继续独立100轮为144.84→182.25MiB，
存活 QWidget 恒0、有效 Qt wrapper 恒423。不能把这些数据说成零增长或已排除泄漏。
追加 tracemalloc 60轮，RSS177.47→159.86MiB；主要 Python 留存约342KiB落在既有设置页
QWidget 构造行（`modern_settings_dialog.py:1746/1750`、`settings_widgets.py:1554`），
没有对应的活窗口数量增长。RSS与分配器/Qt缓存有关，当前不能把全部 RSS 差额归因为新补丁或证明长期无泄漏。
只据实记录，不为未定位的原因重写设置架构；详细 samples / allocations 在 native-legacy-*-a/result.json。

路径成本说明：源码差异没有新增业务采样、网络请求、常驻线程、配置写盘或独立OS调用路径；
Qt本身的创建/销毁和探针读取进程计数仍会进入系统API，未做系统级逐调用跟踪。菜单父对象绑定只在
菜单创建时执行；销毁修复少排一个零延时回调；L8字节提取只在内部候选掩膜非空时执行，
对应 v4 业务链仍默认关闭。测试辅助器只影响测试，不进入运行时。

## 五、实机运行记录

所有记录均为本机新的 `QT_QPA_PLATFORM=windows` 进程，隔离配置位于本轮 scratch 子目录；
没有使用真实账号、上传截图、修改安装或系统安全策略。旧设置页的自启控件仅读取当前状态，
未改动该控件；系统写入的“值变化”分支未触发。源码正常退出与用户正常退出均不等同于系统关机测试。

| 探针 | 实际结果 | 输出 |
|---|---|---|
| 旧菜单+真实设置页30轮 | 子菜单显示、130%动作生效；父对象先销毁后下一窗口能打开；顶层窗归零；exit0 | native-legacy-run / native-legacy-a |
| 同路径100轮 | 无原生崩溃；Qt活对象数量不增长；RSS增长如上记录；exit0 | native-legacy-extended-run |
| petcore源码 | 菜单13子菜单GC后有效；托盘可见；设置取消恢复0.72、保存0.85；双宠0.85/0.5隔离 | native-core-run |
| 隐藏/折叠/停用 | 展开折叠network段后网络采样停止；隐藏后系统与网络采样停止；停用后岛不可见 | native-core-a/native-result.json |
| 资源循环与退出 | 托盘刷新30轮仅2个子菜单；菜单/岛开关30轮结束0个遗留菜单；退出后Python线程仅MainThread，exit0 | 同上 |

命令：`.venv/Scripts/python.exe -X faulthandler .scratch/petcore-p4c3/native_legacy.py`，
`native_legacy_extended.py`、`native_legacy_memory.py`、`native_core.py` 同目录。
主代理查看了本轮设置页、大小子菜单及 petcore 菜单截图：菜单项/勾选/设置内容可见；
截图只裁自应用自身窗口，不含用户桌面或真实账号。自动动作与断言不是用户人工验收。
源码探针用了真实系统采样；没有为此接入真实外部服务。

## 六、限制、阶段状态与后续

- B 通用接口、C 待办、D 节日生日、E 48签、扩展清单/ZIP、Core0.2.0及mod版本更新均尚未实施；
  没有候选产物，不存在“可发布”结论。本轮不提交、推送或上传 Release。
- 当前只验证Python3.11.1；没有把上一轮Python3.12 stdlib冒烟当成本次全套验证。
  双屏、macOS/Linux、真实外部TTS、安装包及远程Release下载仍未验收。
- 内存留存观察尚不能给出长期无增长保证；以上对象计数与 tracemalloc 证据须保留。
- 下一步是B通用端口，不是发布：先声明slot配置/展示交付，再建立真实播放结束与取消回归；
  用户已经批准这条顺序，无需重开方向决策。执行摘要在 `.scratch/petcore-p4c3/PLAN.md`，
  准确断点见 `.scratch/petcore-p4c3/HANDOFF.md`。
- 回滚本批代码不迁移用户配置或mod数据；不要用 reset 清除上一轮48文件修复。
  若选择撤回，仅针对本报告逐文件差异，先比对开始快照。


## 2026-10-24 C–E后续记录

以上内容保留本批完成时的状态/原始结果；随后C待办、D节日生日、E48签已实施，最新联合门禁与验证缺口请读[E报告](PR-REPORT-PETCORE-P4C3-E-2026-10-24.md)。不把早期“尚未实施”当作当前状态，也不以本批选定用例替代后续完整全仓。
