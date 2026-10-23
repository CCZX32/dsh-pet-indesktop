# P4-c1 补充交付：系统缩放（DPI）适配（2026-10-23）

> 紧接 `PR-REPORT-PETCORE-P4C1-2026-10-23.md`。那条报告里已经修掉「窗口抓图按
> DPR 二次缩放、150% 下 100% 失败」的问题；本批把**其余受缩放影响的链路**统一到
> 一条口径，并把规则写进 `docs/PETCORE-SPEC.md` §27 与 `petcore/AGENTS.md`。

## 1. 修改文件说明

| 文件 | 增/删 | 做了什么 & 为什么 |
|---|---|---|
| `petcore/contracts/screen.py` | +22 | 新 `VISION_MAX_EDGE = 1024` 与 `ScreenPort.shrink_for_vision(png, max_edge=1024)`：**送多模态模型的图按物理像素封顶**。此前「看看屏幕」直接把 1920×1200 的整屏 PNG 发出去，2x 屏上会翻到 3840×2160——费用、延迟、失败率都随缩放上升。 |
| `petcore/platform/screenshot.py` | +28 | `shrink_png()`：等比缩放 + 重新编码；空数据/坏图/未超限原样返回（不制造额外失败）。 |
| `petcore/platform/screenshot.py` | +26 | `capture_desktop()`：Windows 抓**虚拟桌面**（所有显示器并集，物理像素），非 Windows 退回主屏。此前「看看屏幕」只抓宠物所在屏，多屏/混合 DPI 下会漏掉用户正在看的那块。 |
| `petcore/ui/ports.py` | +8 | `QtScreenPort.shrink_for_vision()` 让 mod 不必 import Qt；`capture()` 改走 `capture_desktop()`。 |
| `examples/petcore-mods/ai.chat/host/runtime.py` | +32/−8 | `_vision_bytes()`；「看看屏幕」「主动识屏」「截图提问」「提取文字/翻译的 AI 兜底」四处模型输入统一先过封顶。**本地 OCR 与「复制图像」仍用原图**。`_start_vision` 接受 `messages` 工厂函数，缩放+base64 移到请求线程（`shrink_png` 实测 61 ms，不再占 GUI 线程）。 |
| `petcore/ui/icons.py` | +40/−12 | `icon()` / `file_icon()` / `icon_from_spec()` 接受 `dpr`：按 `screen_dpr()` 用物理尺寸绘制并写回 DPR（36→54/72 像素）。此前 36×36 位图在 1.5x/2x 菜单里被放大 = 糊。 |
| `petcore/ui/menu_actions.py` | +18/−5 | 动画缩略图按 `physical_side(64, screen_dpr(window))` 解码，回调里写回 DPR；2x 屏从 64px 源图变成 128px 源图。 |
| `tests/test_petcore_screenshot.py` | +45 | 封顶尺寸/未超限原样/坏图原样/「同一图在 1x、1.5x、2x 下封顶结果一致」。 |
| `tests/test_petcore_menu.py` | +28 | 图标 `availableSizes` 在 1x/1.5x/2x 下分别 36/54/72；文件图标同理。 |
| `tests/test_petcore_ai_mod.py` | +40 | 截图提问的模型载荷确实经过端口封顶（原图 base64 不出现）；端口缺失时回退原图。 |
| 文档 | — | SPEC §27（逻辑 vs 物理口径）、MOD-FORMAT §14、`petcore/AGENTS.md` DPI 红线、LOG `L051` + 索引。 |

## 2. 性能分析

环境：本机 150% 缩放（逻辑 1280×800 / 物理 1920×1200）；
`QT_QPA_PLATFORM=offscreen`；每样本独立计时（中位/最差）。

| 路径 | 样本 | 实测 |
|---|---|---|
| `shrink_png` 1920×1200 → 1024 | 20 | 中位 **61.4 ms**，最差 71.7 ms（在请求线程里执行，不占 GUI） |
| `icon(36, dpr=2.0)` 绘制 | 20 | 中位 **0.09 ms**（每张菜单图标一次） |
| 整屏 PNG → 模型输入 | 1 | 1920×1200 / 287,978 B → 1024×640 / 165,675 B（**−42%**） |
| 前台窗口抓图 | 1 | 1920×1128 → 768×451 / 111,419 B |

- **稳态开销**：菜单图标/缩略图只在构建菜单时生成一次；`shrink_png` 只发生在用户
  触发「看看屏幕/截图提问」或主动识屏真正发请求时，且已移出 GUI 线程。
- **新增系统调用/线程/磁盘**：无。纯内存缩放。
- **内存**：缩放期间多一张目标 `QImage`（1024 长边 ≈ 2.6 MB @RGB32），随即释放；
  不给缩略图/图标新增缓存项（缩略图缓存键里已经带了物理边长）。

## 3. 实机运行记录

### 3.1 真实桌面探针（`.scratch/probe_dpi.py`）

```
screen: TM140VDXP02 logical 1280 x 800 dpr 1.5
full screen png: 1920 x 1200 287978 bytes
model input after cap: 1024 x 640 165675 bytes
foreground window: QQ.exe physical rect (0, 0, 1920, 1128) -> png 768 x 451 111419 bytes
selection logical 400x200 at dpr 1.5 -> device (150, 120, 600, 300)
```

### 3.2 门禁

```
ruff check pet/ tests/ petcore/ examples/petcore-mods   → All checks passed
pytest tests/test_petcore_*.py tests/test_architecture.py \
       tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
                                                        → 1353 passed（0 skipped）
python -m petcore --check                               → exit 0, diagnostics []
```

上一批唯一 skip 的 `tool.ocr` 真实引擎用例本机已恢复：用户关闭火绒相关监测后，
`shapely/_geos*.pyd` 不再被 WinError 4551 拦截（同一时刻 `VerifiedAndReputablePolicyState`
仍为 1，说明拦截来自第三方监控而不是 SAC 本身）。

### 3.3 打包与安装

- 最终构建：`dsh-pet-core.exe` 14,969,376 B / `dsh-pet-core-setup.exe`
  261,554,392 B，签名 `Valid`（`CN=DSH Pet Core Dev`）；setup 冒烟 `--check` exit 0。
- 静默升级安装到 `E:\dsh-pet-core`（用户此前已装过，`UsePreviousAppDir` 生效），
  安装后 exe 时间戳 19:37，与构建产物一致。
- 安装版以隔离 `%APPDATA%` 启动 70 秒（`ai_proactive_dry_run=true`、白名单记事本）：
  `--check` exit 0、`diagnostics: []`、9 个 mod；日志两条 dry-run 记录（见 P4-c1 报告
  §3.4），说明冻结后的 exe 里 GDI 采样/指纹链路可用。
- 高 DPI 交互项（菜单图标清晰度、框选对齐）未做逐像素截图比对，见 §4。

## 4. 未验证 / 风险

1. 菜单对勾图（14px QSS 资源）未做 @2x：Qt 对 QSS `url()` 的高 DPI 变体支持随版本
   而异，未实机核对；只是略软，不影响功能。
2. 混合 DPI 多屏只在逻辑层与单元测试覆盖（`ScreenLayout` 的 dpr 不参与矩形换算），
   未在真机双屏复核。
3. 模型图封顶用**物理像素**口径（与主分支一致），代价是高 DPI 屏上送去的逻辑内容
   更少；若视觉模型对小字不稳，可改为逻辑像素口径。
4. `capture_screen()` 本身仍返回整屏物理像素（框选冻结帧需要原图），只在进模型前
   封顶；第三方 mod 若自己把 `capture.png` 直接发出去，需要自己调
   `shrink_for_vision()`。
