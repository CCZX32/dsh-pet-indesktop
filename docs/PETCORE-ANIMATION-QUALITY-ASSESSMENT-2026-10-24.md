# petcore 动画画质评估与串行执行计划

> **状态：评估已记录，产品实现尚未开始。** 本次授权仅写文档，不是执行下面的实现任务。
> **日期 / 分支**：2026-10-24 / `feat/petcore-vpet-architecture`。
> **本地调查基线**：`7ab09683bec459d18fe2a18c983484c7bf5b8a81`。
> **对方源码基线**：`yshuang722-spec/xiaoxiao-zhuochong` 的 v1.0.4 标签在调查时解析为
> `9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93`。后续引用固定 SHA，不能重新取移动标签代替。
> **适用对象**：用户确认的「当前 petcore 分支、同一个蓝毛角色」；不是旧 `pet` 发布版的修复任务。
> **执行方式**：未来获得实现授权后，由一个执行者按 T00→T06 串行推进，不默认委派子代理。

关联入口：[动画 backlog](PETCORE-ANIMATION-BACKLOG.md)、[素材流水线](ASSET-PIPELINE.md)、
[v5 透明修正报告](PR-REPORT-FRAMESEQ-ALPHA-FLOOR-2026-10-16.md)、
[petcore 工作约定](../petcore/AGENTS.md)、[日志索引](PETCORE-LOG-INDEX.md)、[总索引](INDEX.md)。
本文是上述日期的调查快照和待执行任务书，不取代现行编码档位、素材几何或发布规范。

## 1. 结论、证据等级与边界

**推荐保留 Qt，先修复动画 DPR，再独立比较编码档位。不整体移植对方播放器。**
“移植”在本计划中指在现有 Qt 架构内采用正确的像素尺寸处理；旧 `pet` overlay 已有
可参考规则。对方的首帧就绪切换和停滞恢复仅记为后续议题，不属于本轮实现。

### 1.1 已验证事实

以下是前一轮会话通过只读源码调查和本机探针得到的结果；此次文档落盘没有重跑这些实验。
原始完整工具输出在该会话中，没有已归档的独立日志文件。后继执行者须按 T00/T04 生成自己的日志，
不能把下面的历史数字写成自己的新验收。

| 编号 | 观察 / 实测 | 可支持的结论与限制 |
|---|---|---|
| E01 | 本地蓝毛 106 段 WebM 中，105 段的 Git blob SHA-1 与对方 `characters/main/animations/` 匹配；103 段同名，2 段改名 | 大多数动作并没有更高清的另一份源文件；不代表已核验对方发行 ZIP 内的文件 |
| E02 | 两段改名为本地 `左转奔跑` / `漂浮踏步`，对方为 `原地左转奔跑` / `原地漂浮踏步`；仅 `深度思考碎碎念.webm` 内容不同 | 不把文件名差异当成素材质量差异，也不把 105/106 写成全部一致 |
| E03 | 本机 Windows 11 build 26200、Python 3.12.10、Qt 6.12.0、Qt 平台 `windows`；屏 `TM140VDXP02`，逻辑 1280×800，DPR=1.5 | 这些是调查进程实际输出；历史日志中的 Python/Qt/显示器可能不同，执行前必须重测 |
| E04 | 蓝毛待机 WebM 为 VP9、640×360、24fps、10.04s；强制 `libvpx-vp9` 解码得到 alpha | 该样本源分辨率固定，增加 DPR 不能生成源文件不存在的细节 |
| E05 | `frame_pixmap(image, 461, 259)` 输出 460×259、DPR=1、逻辑尺寸 460×259 | `KeepAspectRatio` 导致宽为 460；当前链路先缩到逻辑尺寸，再由高 DPI 绘制放大，丢掉了可保留的源细节 |
| E06 | 默认 `auto` 的待机实际选中 `frameseq/idle/待机呼吸休闲.gdeb965d05a85`，241 帧，meta 为 `libwebp lossy q70 (bgra straight, unblend-white-v5)` | 此处确实使用有损 Q70，并非旧模块注释所说的“无损帧序列” |
| E07 | 待机首帧：对原 WebM 解码结果执行同一 `unblend_v3`，再与现有首帧 WebP 比较；参考 alpha≥250 的 35,807 像素，RGB MAE=4.3791065/255，PSNR=32.4386352dB，整帧 alpha 最大差=0 | 证明该样本再编码改变 RGB；这是近不透明区域的单帧统计，不能代替整段主观评价 |

微基准 E08：原始待机首帧转 QPixmap 后，执行 `scaled(..., KeepAspectRatio,
SmoothTransformation)` 并写 DPR；每档 5 组、每组 200 次，组内均值再取中位数。
没有测解码、QPixmap 初次构造、实际上屏、CPU/GPU 利用率或整体内存。

| 目标 DPR | 输出物理尺寸 | 单次缩放中位数 |
|---|---|---|
| 1 | 460×259 | 0.1965 ms |
| 1.25 | 576×324 | 0.3025 ms |
| 1.5 | 689×388 | 0.4785 ms |
| 2 | 920×518 | 0.8037 ms |

这些尺寸来自当时直接将目标框乘 DPR 后 `KeepAspectRatio` 的实验，不是未来实现的精确尺寸契约；
T02 规定先确定逻辑适配尺寸，再计算物理尺寸，避免二次取整改变逻辑布局。

### 1.2 推断与尚未验证

- **强线索**：DPR 缺口很可能贡献了用户所见的发虚；其代码路径和低分辨率中间帧已确认，
  但没有双方程序同帧上屏证据，不能量化它占整体观感差异的多少。
- **待实验**：Q70 可能影响细线、眼睛和发丝；透明修正也会改变轮廓。不能为追求锐利直接撤销 v5。
- **未验证**：对方 ZIP 实际源码对应关系、两程序 CPU/GPU/RSS、硬件解码启用情况、双屏混合 DPI、
  macOS/Linux 实机画质。不能把浏览器合成推导成 VP9 alpha 必然硬解或性能更好。
- Release 页面缓存曾显示另一短提交 `816fdb7`，API 标签调查得到上述 `9ce91ec8`；本报告固定后者，
  不宣称已完成发布页、标签和发行二进制的三方一致性核验。

### 1.3 不可自行扩大的范围

- 不换 Electron、Qt WebEngine、Qt Quick 或 GPU 渲染后端；不增依赖、配置键或后台线程。
- 不改窗口逻辑尺寸、移动/碰撞坐标、位置持久化、角色 `body_box` 或素材帧号/速度语义。
- 不修改 `pet/` 产品代码来适配 petcore；旧路径只读参考，保持分层约束。
- 不修改 `ENCODER_DESC`、`UNBLEND_MARK`、生产 Q70、v5 算法、构建门或现有帧序列。
- 不下载并运行对方 EXE、不导入其新增角色、不提交、推送、合并、构建发布包或发布 Release。
- T05 仅实验、T06 仅记录建议。生产改档及播放恢复需要独立任务，不能因实验看起来更好就顺带实施。

## 2. 架构对照与采纳决定

对方明确说明集成改动在实际发布用 JavaScript，直接重编保留的 TypeScript 会覆盖这些改动。
因此调查以 `lib/` 和 `runtime/` 为准，而不是只读 `src/`。

| 层 | 小小桌宠 | 当前 petcore | 决定 |
|---|---|---|---|
| 宿主 | Electron 控制端启动 Node standalone 服务；桌面 helper 为宠物创建透明 BrowserWindow | Python/Qt 应用与宠物窗口，媒体经 `PetClip` 适配 | 保留 Qt；跨技术栈整体移植无已证实收益 |
| 媒体 | HTML video 直接播放透明 WebM | `ClipLibrary` 按模式选 `FrameSeqClip` 或 `WebMClip`；后者经 ffmpeg 解码 | 保留现有后端选择与回退 |
| 切换 | 双 video，`loadeddata` 后交换前后台，旧 video 暂停；CSS 0.18s 淡化 | 切换 clip，等待新帧时保留已有 pixmap；同 clip 续圈 | 不把淡化当清晰度提升；本轮不新增双播放器 |
| 缩放 | Chromium 视频合成；Windows 有全局 device scale factor 与页面 zoom 补偿 | `renderer.frame_pixmap` 当前只按逻辑尺寸缩帧；旧 overlay 已按 DPR 处理 | 在 petcore 内修复 DPR，不照搬对方全局 DPI 策略 |
| 恢复 | 加载 10s 超时；每秒检测进度，持续约 6s 不前进触发恢复，含状态豁免 | `PetClip` 透传错误，窗口错误处理；完整停滞场景本轮未验证 | 记录后续可靠性议题，不纳入画质修复 |
| 素材 | 蓝毛多数源文件与我们一致 | 帧序列额外经过 v5 + Q70 | 分离缩放问题与再编码问题 |

固定来源：

- [项目说明](https://github.com/yshuang722-spec/xiaoxiao-zhuochong/blob/9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93/README.md)
- [客户端服务](https://github.com/yshuang722-spec/xiaoxiao-zhuochong/blob/9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93/client/service.cjs)
- [透明窗口宿主](https://github.com/yshuang722-spec/xiaoxiao-zhuochong/blob/9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93/dsh-pet/runtime/electron-helper/main.js)
- [桌面播放器](https://github.com/yshuang722-spec/xiaoxiao-zhuochong/blob/9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93/dsh-pet/runtime/electron-helper/sprite.js)
- [播放守卫](https://github.com/yshuang722-spec/xiaoxiao-zhuochong/blob/9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93/dsh-pet/runtime/electron-helper/playback-guard.js)
- [DPI 规则](https://github.com/yshuang722-spec/xiaoxiao-zhuochong/blob/9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93/dsh-pet/runtime/electron-helper/dpi-linearization.js)
- [许可证](https://github.com/yshuang722-spec/xiaoxiao-zhuochong/blob/9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93/LICENSE)：MIT，保留原作者声明；若将来复制源码需保留声明，本计划不复制其播放器代码或素材。

## 3. 后继执行者操作规则

本节及以下命令均为**未来实现任务**。仅编写本文不执行它们。先读根 AGENTS、petcore AGENTS、
本文以及上面的关联文档；涉及 ffmpeg 派生时额外读
[Windows 会话结束约束](ISSUE-111-WINDOWS-SESSION-END-FFMPEG-2026-09-12.md)。

将未来证据放在 `.scratch/petcore-animation-quality/`；恢复时先读其中 `HANDOFF.md`。
只有已获实现授权才创建该目录、测试或探针。保留用户已有修改，不 reset/checkout 覆盖脏文件。
每个任务完成立即更新进度；失败记录真实输出，不修改测试期望来掩盖失败。

PowerShell 执行约定：项目根目录运行，Python 固定 `.venv/Scripts/python.exe -X utf8`。
测试日志用 `2>&1 | Tee-Object -FilePath <日志>`，紧接着检查 `$LASTEXITCODE`；非零即停止当前步骤。
每条命令单独执行，不依赖前一条命令失败后 shell 自动中止。`QT_SCALE_FACTOR` 与
`QT_QPA_PLATFORM` 仅设置在专用子进程环境或临时测试 shell，结束恢复原值；不改系统显示设置。
表格中的 `not_started` 是初始状态，不是已经验收。

### T00：核对基线与保留证据（not_started）

**前置**：获得产品实现授权，工作树可用；先处理写集冲突，不能覆盖他人修改。

**只读入口**：`petcore/ui/renderer.py:frame_pixmap`、`ui/pet_window.py:_on_frame/paintEvent/set_scale/shutdown`、
`media/library.py:ClipLibrary._create`、`media/images.py:screen_dpr`；旧 `pet/pet_sprite.py:_scaled_size/_rebuild_pixmap`
仅作参考。查看 `petcore/ui/app.py` 已有屏幕信号接线，避免重复订阅。

**步骤 / 命令**：

```powershell
git status --short
git rev-parse HEAD
git diff 7ab09683bec459d18fe2a18c983484c7bf5b8a81 -- petcore/ui/renderer.py petcore/ui/pet_window.py petcore/media
rg -n "frame_pixmap|DevicePixelRatioChange|screenChanged|logicalDotsPerInchChanged" petcore/ui
.venv/Scripts/python.exe -X utf8 -c "import sys,platform,PySide6; print(sys.version); print(platform.platform()); print(PySide6.__version__)"
```

1. 保存 SHA、工作树状态、版本、屏幕名称/逻辑尺寸/DPR、目标动画和 frameseq meta；不要读出用户密钥。
2. 使用真实 `QApplication` 的 `screens()` 读取屏幕。没有原生桌面时明确写 offscreen，不能称实机上屏。
3. 用附录 A 复核素材身份；网络失败保留历史结论标签，不能猜新 SHA。
4. 保存修改前缩放探针、真实帧和原实现供后续同进程 A/B 基准使用；不能改运行中的源码来切换版本。

**预期**：确认是否仍为“逻辑尺寸 pixmap + DPR=1”，确定实际后端及素材摘要。
**停止条件**：已存在 DPR 修复、函数契约变化、依赖缺失或目标文件有冲突。先报告基线变化；不要重复实现、
降级依赖或重建 `.venv`。历史 Python/Qt 数字不构成改环境指令。

### T01：先建立会失败的回归（not_started；依赖 T00）

**写集**：新增 `tests/test_petcore_animation_dpr.py`，需要窗口夹具时参考
`tests/test_petcore_window_smoke.py`；此步不改产品。

**步骤**：

1. 创建真实 QApplication 与非方形 QImage：不对称色块、单像素条纹、透明区域和半透明边缘。
   在公开 `frame_pixmap` seam 验证输出物理尺寸、DPR、镜像方向、原始输入未改变。
2. 参数化 DPR=1/1.25/1.5/2；缺省 DPR 保持原调用可用。DPR=1 要与旧版逐像素一致。
3. 在独立进程中设置 `QT_QPA_PLATFORM=offscreen`、`QT_SCALE_FACTOR=1.5`；从真实 Qt 查询有效 DPR，
   建立窗口并驱动真实帧回调。断言显示所用帧没有先被压到逻辑分辨率，不能只测试新增参数存在。
4. 用源帧直接缩放到目标物理分辨率作为参考，比较条纹及指定主体 ROI；透明背景不计入质量评分。
   不把旧低分辨率输出生成的快照当正确参考。
5. 同步靠信号/事件循环条件，给独立进程 60s 超时；禁止固定 sleep 猜测帧是否已到。

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_petcore_animation_dpr.py -q
```

**预期**：旧版出现预期红灯（新 `dpr` 参数缺失，以及原窗口高 DPI 输出不足的行为断言）。
**停止条件**：只有导入/环境错误、全部意外通过或未覆盖真实窗口链。先纠正测试，不进入产品修改。

### T02：实现最小 DPR 修复（not_started；依赖 T01 已记录红灯）

**写集**：`petcore/ui/renderer.py`、`petcore/ui/pet_window.py`；默认不改其他产品模块。
如果必须扩大写集，先在 HANDOFF 写出不能在这两个文件解决的证据，暂停扩大范围。

**固定接口**：`frame_pixmap(frame, width, height, *, mirrored=False, dpr=1.0)`。
`width/height` 永远是逻辑像素；输出为带 DPR 的 QPixmap。空帧语义不变。

**固定实现步骤**：

1. renderer 内将 DPR 转为有限正数，非法值回退 1；不要改变全局图片 helper 的契约。
2. 先依据源宽高和逻辑目标框用 `KeepAspectRatio` 算出逻辑适配尺寸，不生成中间缩小图；
   例如源 640×360、目标 461×259，逻辑适配为 460×259。
3. 物理尺寸为逻辑适配宽高分别乘 DPR、`round` 并钳到至少 1；直接从原始帧平滑缩放一次到该尺寸。
   已确定目标宽高后使用 `IgnoreAspectRatio`，只吸收物理整数取整误差，不再二次适配宽高比。
4. 镜像不叠加第二次缩放；在最终 QPixmap 上显式设置 DPR，包括经过 QImage 镜像转换的分支。
   不给输入 QImage/QPixmap 原地修改 DPR。
5. 窗口提取只负责重建显示帧的 `_refresh_frame_pixmap()`；从保存的原始 `_image` 和实际
   `screen_dpr(self)` 生成 pixmap 并请求 update。`_on_frame` 仍只在真正到帧时调用移动推进。
6. 屏幕或 DPR 刷新只调用重建 helper，不能调用 `_on_frame(0)` 来假造一帧或改变移动位置。
7. 绘制使用与第 2 步一致的逻辑目标尺寸；不要把物理 `pixmap.width()/height()` 当作窗口尺寸。
   对整数取整产生的不足一物理像素误差使用明确逻辑目标矩形处理，正常画面仍左上对齐，保留原布局。
8. 原始 `_image` 继续供 `is_transparent_at` 采样；不替换成物理缩放缓存，不改变阈值和命中逆变换。

**验证**：重复 T01 命令，应绿；DPR=1、非镜像/镜像输出均保持兼容。抽查最终 diff 无额外功能。
**停止条件**：需要修改几何/碰撞/配置、修改原始帧或 Qt 对象跨线程；这些不属于本修复。

### T03：屏幕变化、镜像和生命周期（not_started；依赖 T02）

**写集**：同 T02 与新回归测试；窗口的 `start/shutdown/event` 是主要接线点。

**步骤**：

1. 窗口建立 native handle 后连接一次 `QWindow.screenChanged`，切屏重建当前帧。
2. 处理 `QEvent.Type.DevicePixelRatioChange`；初始化期间事件可能早于 `_image`，必须检查就绪状态；
   继续正常调用基类事件处理。Qt 版本不支持该事件时，记录探针并暂停兼容方案，不使用私有 API 猜测。
3. 同屏缩放还通过当前 QScreen 的 `logicalDotsPerInchChanged` 请求重建；换屏先断旧屏再连新屏，
   关闭时断开自有连接。已有 app 广播不再额外新增第二套全局监听器。
4. 需要等待 Qt 更新 DPR 的屏幕通知，只排队一次 GUI 线程重建；回调检查窗口仍存活/未 shutdown。
   不新增常驻轮询。帧到达也重新读取当前 DPR，作为播放期间的自然刷新。
5. 测试镜像两次、调整大小、暂停帧刷新、重复 start/关闭、关闭前已排队通知；确认没有新解码器、
   虚假 frameChanged、移动推进或持久化写入。
6. 回归旋转、Q 弹和透明命中；OS 屏幕变更边界可注入，但绘制与事件循环必须使用真实 Qt。
   无第二块真实屏时注明跨屏实机未验，不以注入测试替代。

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_petcore_animation_dpr.py tests/test_petcore_window_smoke.py tests/test_petcore_images.py tests/test_petcore_motion.py tests/test_petcore_edge_probe.py tests/test_petcore_screens.py -q
```

**预期**：全部通过；刷新当前帧后逻辑大小不变，关闭后无迟到回调访问已销毁对象。
**停止条件**：出现漂移、穿透错位、原生崩溃或重复信号。修复本步，不转去性能或编码实验。

### T04：性能与实机 A/B（not_started；依赖 T03）

**写集**：仅 scratch 探针/日志/截图及实现报告；不为凑数字继续改播放器。

**探针契约**：由执行者创建 `bench_render.py`，命令入口如下；这些文件现在尚不存在。

```powershell
.venv/Scripts/python.exe -X utf8 .scratch/petcore-animation-quality/bench_render.py --samples 200 --repeats 5 --dprs 1 1.25 1.5 2
.venv/Scripts/python.exe -X utf8 -m petcore --root .scratch/petcore-animation-quality/run-dpr --character shenshen --scale 0.72 --frameseq auto
```

1. 探针加载 T00 保留的旧实现与新实现，同一进程交错 A/B；同源、同镜像状态、同目标逻辑尺寸。
   每档先预热 20 次，再 5×200 次；报告组内均值、组间中位数、p95 和所有原始组值。
2. 分开测纯缩放与完整帧准备；不要将 E08 的纯缩放数值与新端到端耗时直接相减。
3. 默认尺寸之外增加 scale=0.5/1/3 的边界检查。统计 pixmap 物理像素数；宽×高×4 只能标为
   单缓冲理论字节量，不能冒充 RSS 或显存实测。
4. 1/4/8 宠，分别 WebM 回退和帧序列；15s 预热后 30s×3 轮，统计进程树 CPU、RSS、线程/子进程数、
   帧间隔与切换首帧延迟。持续 5 分钟另查缓存是否增长；固定动画池和配置，记录活跃后端。
5. 用隔离数据根在原生 Windows 150% 屏幕比较旧/新实现的相同源帧、相同物理显示大小，白/灰/黑背景。
   静帧用于画质，真实播放用于节拍；不能拿不同时间的动画截图算 PSNR。
6. 记录新增路径成本与触发频率、稳态成本、系统调用/磁盘/网络/线程和内存。DPR 缓冲增大是预期成本，
   不写“零成本”。修复本身不应引入新 I/O、线程、进程或随播放时长增长的帧缓存。

**验收**：没有逻辑大小/动作/命中回归；原生高 DPI 展示与直接从源帧生成的参考一致；
单宠默认尺寸完整帧准备 p95 小于 24fps 的 41.67ms 帧预算。多宠帧间隔 p95 若超过基线 10%，
同环境再复测一轮，仍超则记录为性能未通过并停止扩大实施；不自动以跳帧或改编码掩盖。
该 10% 是本任务建议门槛，不是既有产品保证。无原生显示时只交付自动验证，明确实机验收未完成。

### T05：编码质量实验（not_started；依赖 T04，无生产改档）

**前置阅读**：v5 透明修正报告、`pet/frameseq_provision.py:unblend_v3/WEBP_QUALITY/WEBP_METHOD`。
**写集**：`.scratch/petcore-animation-quality/encoding/` 和评估结果；不写 assets 或用户缓存。

**步骤**：

1. 从 idle/click/move/drag 各按相对路径排序取首个 WebM，再取本地存在的
   `鲸鱼吐泡泡特效.webm`，共 5 段；某段缺失则停止选样并记录，不静默换样。
2. 每段取第 0、`N//2`、`N-1` 个源帧（N 用实际解码帧数）；固定 `libvpx-vp9` 保留 alpha。
   依现有会话结束约束创建/关闭 ffmpeg；不得遗留进程。
3. 每个源帧只执行一次当前 `unblend_v3` 作为共同参考，在 scratch 编码 Q70/Q85/Q90/无损。
   lossy 的 `method` 取当前 `WEBP_METHOD`；lossless 使用 Pillow `lossless=True, method=6`。
   记录 Pillow/libwebp/ffmpeg 版本，不修改生产常量。
4. 每档记录 15 帧总体积、编码耗时；解码读入内存后各 100 次×5 轮，另列磁盘冷读，不能混合。
5. 参考 alpha≥250 的主体统计 RGB MAE/PSNR；0<alpha<250 的边缘单列；白/灰/黑背景合成图另算误差。
   alpha 逐像素比较。无损只要求非透明像素颜色与 alpha 精确保留，alpha=0 的隐藏 RGB 不计观感。
6. 输出 15 帧的局部放大和同物理尺寸对照；记录脸、发丝与特效观察。PSNR 高不自动等于主观更好。

**未来命令入口**（执行者先按以上契约创建脚本）：

```powershell
.venv/Scripts/python.exe -X utf8 .scratch/petcore-animation-quality/compare_encoding.py --output .scratch/petcore-animation-quality/encoding
```

**预期**：可复现的四档比较与推荐，不更改默认 Q70。15 帧体积不是完整包体，必须明确样本量。
**停止条件**：alpha 异常、样本不对齐、需要覆盖生产帧或需要撤销 v5。不得生成“改档已完成”结论。

### T06：验证、交接和独立改档建议（not_started；依赖 T01–T05 的真实结果）

**未来实现批次**需要新增符合模板的 PR 报告，给出修改文件说明（numstat）、性能分析、实机运行记录，
并同步总索引、petcore 日志及索引。纯文档落盘批次不需要冒充实现报告。

按顺序运行：先 T01 聚焦、再 T03 相关、再以下全量与门禁。Qt 测试使用专用 offscreen shell。

```powershell
.venv/Scripts/python.exe -X utf8 -m ruff check petcore/ pet/ tests/
.venv/Scripts/python.exe -X utf8 -m pytest -q
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_petcore_docs.py tests/test_pr_report_discipline.py -q
git diff --check
git diff --numstat
```

- 因涉及窗口事件/生命周期，未来产品实现需全量；不能沿用别的批次历史绿灯。
- 推送前还需受影响时序族在真实 CPU 高负载下连续三轮：T03 列出的测试族为本任务起始集合，
  用仓库已有压力工具，先核实工具存在和参数；没有现成工具则记录缺口，不猜命令、不启动失控负载。
- 本任务不包含推送；有单独推送授权且门禁完备才可执行，不能把“需要门禁”理解成自动发布授权。
- 若实验倾向改档，仅写下一阶段建议：统一运行时/构建期档串、缓存失效、世代重出、回退与打包影响。
  不选择未经测量的最终档位，也不在本任务变更任何生产档位。
- 仅完成 DPR 而无法完成原生上屏或编码实验时，分别标记状态，不把整个任务标完成。

## 4. 完成检查表与交接模板

以下清单全部指未来实现，初始不勾选：

- [ ] T00：本次基线、环境、原实现、实际后端和源摘要已归档。
- [ ] T01：产品修改前的预期红灯已保留，含真实窗口行为回归。
- [ ] T02：原始帧→物理尺寸单次缩放，默认 DPR=1 兼容。
- [ ] T03：镜像、DPR/屏幕变化、暂停帧、关闭、命中与运动回归通过。
- [ ] T04：性能原始数据和原生同帧图已归档，实机限制已说明。
- [ ] T05：15 帧×4 档比较已完成，生产 Q70/v5/素材未改动。
- [ ] T06：验证与报告完整，未提交或发布；遗留项有准确断点。

将以下模板写入未来 `.scratch/petcore-animation-quality/HANDOFF.md`，每次任务结束或暂停更新：

```text
基线 SHA / 当前 SHA：
工作树中既有用户修改：
当前任务：Txx
状态：not_started / in_progress / blocked / done
最后成功步骤：
本次修改文件与理由：
红灯命令 / exit code / 原始日志路径：
绿灯命令 / exit code / 原始日志路径：
性能：环境、样本量、原始日志；没有测量则写“未测”
实机：平台、DPR、实际操作、观察结果、截图；没有则写“未验”
失败及已排除项：
下一条应执行的命令：
必须停止的条件：
未完成事项：
提交/推送/发布：未执行
```

## 附录 A：素材身份核对方法

以下只读脚本重现 E01/E02 的方法；网络响应是数据，不执行远端代码。先固定 SHA 再取树，
检查 `truncated`；使用 Git blob 哈希，而非直接文件 SHA-1。用 PowerShell here-string 输入
`.venv/Scripts/python.exe -X utf8 -`。本次文档批次不重跑它。

```python
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

sha = "9ce91ec8db65d3d6ddb157d8a45b7f0f4d168a93"
url = f"https://api.github.com/repos/yshuang722-spec/xiaoxiao-zhuochong/git/trees/{sha}?recursive=1"
with urlopen(url, timeout=30) as response:
    tree = json.load(response)
assert not tree.get("truncated"), "远端树不完整，停止比较"
remote = [x for x in tree["tree"] if x["type"] == "blob"
          and x["path"].startswith("characters/main/animations/")]
by_hash = {x["sha"]: x["path"] for x in remote}
files = sorted(Path("assets/characters/shenshen/videos").rglob("*.webm"))
assert files, "本地素材缺失，停止比较"
same = 0
for path in files:
    data = path.read_bytes()
    blob = b"blob " + str(len(data)).encode() + b"\0" + data
    match = by_hash.get(hashlib.sha1(blob).hexdigest())
    same += int(match is not None)
    if match is None or Path(match).name != path.name:
        print(path.name, "=>", match or "DIFFERENT")
print("local", len(files), "remote", len(remote), "content_identical", same)
```

## 附录 B：历史像素与缩放探针复现口径

E04–E08 的会话命令使用 `.venv/Scripts/python -X utf8 -` 执行内存探针，不修改素材。
以下关键调用和参数足以让后继探针保持同一口径；运行并存日志后才能宣称新环境已复验。

1. `QApplication([])` 后打印 `platform.platform()`、`platform.python_version()`、`qVersion()`、
   `app.platformName()` 与 `app.screens()` 的 name/geometry/devicePixelRatio。
2. `load_character('shenshen')` 后选择 `spec.path.as_posix()` 含 `/idle/` 的样本，打印 path/frameseq_dir。
3. `imageio_ffmpeg.read_frames(str(spec.path), pix_fmt='rgba', bits_per_pixel=32,
   input_params=['-c:v','libvpx-vp9','-threads','1'])`；取 meta、首帧 raw 后 `close()`。
4. `QImage(raw,w,h,QImage.Format.Format_RGBA8888).copy()` 后调用原 `frame_pixmap(image,461,259)`，
   打印像素宽高、DPR、`deviceIndependentSize()`；raw 生命周期不能短于 QImage 拷贝。
5. E08 从 `QPixmap.fromImage(image)` 开始，每档执行 `scaled(round(461*dpr), round(259*dpr),
   KeepAspectRatio, SmoothTransformation)` 与 `setDevicePixelRatio(dpr)`，5×200 次。
   历史探针没有单列预热，T04 新探针增加预热后必须用新旧实现配对重测，不直接拼历史结果。
6. E07 参考为 `numpy.array(unblend_v3(Image.frombytes('RGBA',(w,h),raw))).astype(float)`，
   对照为 `frameseq_dir` 中按名字排序首个 WebP 的 RGBA 浮点数组。
   mask=`reference[:,:,3]>=250`；MAE 和 MSE 仅取 RGB 的 mask 区域，
   PSNR=`10*log10(255**2/MSE)`；另算整帧 alpha 绝对差最大值。MSE=0 时记无穷，不伪造有限值。

## 5. 本次文档落盘记录

本批仅新增本文和维护文档互链、索引、L063 日志，不创建 T01 测试或 T04/T05 探针，不运行产品实验。
文档校验及逐文件增删见 [L063](PETCORE-LOG.md#l063--2026-10-24--动画画质评估与串行执行任务书)。
纯文档不改变运行行为，因此本批不运行全量 pytest、性能或 GUI 验收；此豁免不延伸到未来 DPR 实现。
