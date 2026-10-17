# 冻结包构建与官方包随包投递（4B-5 前半；5A Setup 受阻登记）

> 分支：`dlc/mod-center-port`；阶段 1–3 报告见同目录。
> 环境：Windows 11，Python 3.12.10，PyInstaller 6.22.3，16 核。
> **结论先说**：4B-5 的「冻结 Worker + onedir 随包携带官方包 + 冻结入口分流」已在本机真实构建并取证；
> 5A 的 Inno Setup 选装器**未做**——本机没有 `ISCC.exe`，且未做正式签名密钥，按计划停在
> 「可交付的一半」，不声称 Setup 已验收。

## 一、修改文件说明

### 新增文件（`wc -l`）

| 文件 | 行数 | 改了什么 / 为什么 |
|---|---:|---|
| `scripts/build_screen_worker.py` | 79 | 用 PyInstaller 把官方识屏包的 `worker-src/entry.py` 冻成单文件 exe；显式列运行期惰性 import 的 Core 模块（租约/识屏运行时/vision/协议/诊断），排除 PySide6/shiboken6。 |

### 修改文件（`git diff --numstat`）

| 文件 | +/− | 改了什么 / 为什么 |
|---|---:|---|
| `scripts/build_screen_package.py` | +17/−2 | 新增 `--worker-exe`：把冻结 Worker 复制成 `worker/entry.exe`（POSIX 为 `worker/entry`），写入清单 `worker.path` 与逐文件摘要；不传时保持源码态 `worker/entry.py`。 |
| `scripts/verify_feature_package.py` | +27/−6 | 新增 `--official`：官方闭集校验（能力上限取 `OFFICIAL_FEATURES` 登记），默认本地口径继续拒绝官方保留 ID；包根级问题纳入失败判定与 JSON。 |
| `scripts/build_onedir.ps1` | +9/−3 | 新增 `-OfficialFeaturePackages`：源码侧/产物侧两道门按官方闭集校验，其余复制/布局不变。 |

## 二、性能分析

```text
冻结 Worker（PyInstaller onefile）: 19.4 s；产物 32,268,517 bytes
官方包（含冻结 Worker）构建:       2.1 s（两个包）
onedir 三端构建（Windows）:        约 130 s（含 PyInstaller Analysis/COLLECT，本机）
冻结 Worker 裸跑（无交接）:        3.8 s 后 exit 77（fail-closed）
冻结入口 --worker 未知 id:         0.5 s 后 exit 2（未拉起 UI）
```

- **稳态开销**：新增脚本只在构建期跑；产品运行期没有新增代码路径（`worker_command` 的冻结分支原本就存在，只是第一次有真实 exe 可指）。
- **新增路径成本与频率**：每次发版多一次 Worker 冻结（19 s）与一次包重建（2 s）；`<app>/features/` 的校验仍是构建期一次。
- **新的系统调用 / 网络 / 磁盘 / 线程**：构建期新增 PyInstaller 子进程与文件写入；运行期无新增。
- **内存**：Worker exe 32 MB 磁盘占用；不进入主进程内存。

## 三、实机运行记录

```text
$ .venv/Scripts/python.exe scripts/build_screen_worker.py .scratch/stage4-worker
... Build complete! ...
worker: .scratch/stage4-worker/entry.exe        # 32,268,517 bytes

$ ./.scratch/stage4-worker/entry.exe </dev/null
EXIT=77                                       # 无交接 token，fail-closed

$ .venv/Scripts/python.exe scripts/build_screen_package.py \
    .scratch/stage4-packages-frozen/screen-understanding --worker-exe .scratch/stage4-worker/entry.exe
$ .venv/Scripts/python.exe scripts/verify_feature_package.py \
    --bundle-root .scratch/stage4-packages-frozen --target-platform win32 --official
...
OK: 2 份包全部通过（清单完整性 + 摘要校验 + 装前子进程预检）
screen-understanding 清单摘要 sha256:298c6f8d5d242029df083bc976a55f3bb876ee2f8e01ee20c47fd03542326208

$ pwsh -File scripts/build_onedir.ps1 -FeaturePackages .scratch/stage4-packages-frozen \
    -OfficialFeaturePackages -SkipZip
...
[features] bundle carries verified feature packages under features\
[3/3] Done. onedir dir: E:\Work\dsh-pet\dsh-pet-indesktop\dist-onedir\dsh-pet-standalone-webm-chat

$ ls dist-onedir/dsh-pet-standalone-webm-chat/features
ai-chat  screen-understanding
$ ls dist-onedir/dsh-pet-standalone-webm-chat/features/screen-understanding/worker
entry.exe  entry.py

$ "dist-onedir/.../dsh-pet-standalone-webm-chat.exe" --worker not-a-worker
unknown worker: not-a-worker
EXIT=2                                        # 冻结入口在 import pet.app 之前分流
```

- **真实构建**：上述命令在本机真实执行；不是 mock、不是只读 spec。
- **全量分片门（最终）**：`python scripts/ci_shards.py --include-isolated --jobs 6` → **21/21 分片通过**（墙钟 554.0s；日志 `.scratch/final-full-shards-5.log`）。
- **未验证项**：① 冻结 Worker 的**完整交接链路**（有 token、真租约、真握手）没有跑——裸跑只证明了 fail-closed；完整链路需要已安装的官方识屏包 + 宿主租约，属产品内安装后的实机验收。② 未启动桌面 GUI 做人工观感验收（本会话无可交互桌面）。③ Setup 未编译（见下）。
- **构建环境注意**：`build_onedir.ps1` 调的是 PATH 上的 `python`；本次用 `.venv/Scripts` 前置 PATH 才满足 `edge-tts>=7.3.1` 的构建期门。这是构建机的既有前提，不是本片新增。

## 四、5A Setup / 签名：部分接线，编译受阻（未验收）

- **已接线的安装器脚本**（本机无 ISCC，未编译）：
  - `packaging/dsh-pet.iss` 新增两个可选 Task：`official_ai_chat` / `official_screen`，默认不勾选；
  - 基础 `[Files]` 用 `Excludes` 把两个官方包从整目录复制中排除，改为按 Task 的 `Source` 条目安装到 `{app}\features\...`，并带 `skipifsourcedoesntexist`（不带包的构建仍可编译）；
  - `[Code]` 的 `CurStepChanged(ssPostInstall)` 写 `startup-receipt.json`（`dsh-pet-startup-receipt/v1` + 两个 Task 的布尔值）——只写回执，不执行包代码、不写安装状态；
  - 结构判据 `tests/test_setup_optional_features.py` 5 条（BOM/UTF-8、Task、Excludes、Task-scoped Source、回执）全绿。
- **仍未做**：本机没有 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`，**无法编译安装包**，因此装/卸/升级、首启回执的实际消费、显式便携模式均未验证；没有正式发布签名密钥，Ed25519 发布清单与签名验证路径未做。文档与构建口径仍是 `local_user`（显式用户信任，不声称发布者认证），**不会伪造签名产物**。
- 已具备的前置：构建脚本能把官方包随 onedir 携带并双门校验；`<app>/features/` 的真实读取链（`official_package_source`）在阶段 3 已落地。5A 的下一步：在装有 Inno Setup 的机器上编译并做安装/卸载/升级人工验收，再决定便携模式与签名基线。

## 五、边界

- 冻结 Worker 只覆盖官方识屏包（host-worker）；AI 对话包是 host-only，不需要 Worker。
- `<app>/features/` 是随包投递的**只读来源**；安装仍走 Core 事务链与权威安装状态，没有第二份安装真相。
- 没有把 PySide6 打进 Worker（`--exclude-module PySide6/shiboken6`），Worker 只背视觉/协议/租约依赖。
