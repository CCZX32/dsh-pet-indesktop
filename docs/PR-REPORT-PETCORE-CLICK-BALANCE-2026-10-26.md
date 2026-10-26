# PR 报告：点击显示余额验收与构建冒烟等待修复（2026-10-26）

> 关联日志：`docs/PETCORE-LOG.md` L095。关联产物：
> `rel-balance-2026-10-26/dsh-pet-core-setup.exe`（不在版本库内）。

## 0 结论先行

1. **「点击显示余额」不是没做，而是用户手上的 setup 旧**。该特性自 P5（`ce8c67fb`，
   2026-10-26 00:35）就已在源码里端到端实现；用户本机 `dist/dsh-pet-core-setup.exe`
   构建于 **2026-10-23 19:39**，早于 P5 三个多小时，所以设置页与点击行为里都没有它。
2. 本轮**不改产品代码**，补了 4 例点击链路回归测试，保住这条已经实现的通路。
3. 重建候选包时发现**构建门本身是假绿**：`--check --strict` 冒烟对 `-Windowed`（GUI 子系统）
   的 exe 用 `& $exe` 调用，PowerShell 根本不等待进程退出（实测 52ms 返回、
   `$LASTEXITCODE` 为空、`check.json` 还没落盘），于是这道门要么读到上一份报告、要么直接
   抛「路径不存在」。已改为 `Start-Process -Wait -PassThru` 并按真实退出码判红。
4. 修复后重跑构建：`check: menu_template=json characters=1 builtin_images=24 strict=True`，
   exe 与 setup 签名 `Valid`，`dsh-pet-core-setup.exe` 268,491,704 B。

## 1 修改文件说明

> 说明：工作树里另有上一轮审计修复（L088–L094，91 个文件）尚未提交，下列
> `git diff --numstat` 是相对 `1c1507f1` 的**文件级**口径；「本轮」列只描述本次改动。

| 文件 | 本轮改了什么 | 为什么 | 行数（本轮 / 相对 HEAD） |
|---|---|---|---|
| `tests/test_petcore_click_balance.py`（新增） | 4 例：点击按被点那只的 slot 请求余额；关掉选项一次都不请求；余额端口抛错不打断点击动画与监听者；飞行中（`motion.thrown`）不消费点击故不请求 | 原先只有「设置页勾选能落盘」的测试，点击这一跳完全没被钉住 | +130 / 新增文件 |
| `scripts/build_petcore.ps1` | 冒烟改 `Start-Process -FilePath $exe -ArgumentList @("--check --strict","--out",…) -Wait -PassThru`，按 `$smoke.ExitCode` 判红；新增「报告必须存在」「报告必须本次新写（`LastWriteTimeUtc` 前进）」两条断言；构建成功后打印 `menu_template/characters/builtin_images/strict` 摘要；不新增任何 `Remove-Item`（保持「脚本不删目录」约定） | GUI 子系统 exe 用 `&` 不阻塞，`$LASTEXITCODE` 是上一条 Python 命令的残留值，构建门实际没有校验任何东西 | +20/−6 / +90/−10 |
| `tests/test_petcore_candidate_packaging.py` | 新增 `test_smoke_waits_for_the_windowed_exe`：断言 `Start-Process -FilePath $exe` 与 `-Wait -PassThru` 存在，且旧的 `& $exe --check` 不再出现 | 把「必须等待」变成脚本结构断言，防止下次被改回去 | +19 / +78 |
| `petcore/AGENTS.md` | 「打包工具」红线补一段：`-Windowed` 冒烟必须 `Start-Process -Wait`，不许用删除旧文件绕开 | AGENTS 描述的行为变了，必须同步，否则下一个人会重写回 `& $exe` | +6 / +61（含审计批次） |
| `docs/PETCORE-LOG.md` / `docs/PETCORE-LOG-INDEX.md` | 追加 L095 与索引一行 | 仓库硬要求 | +221/−0、+12/−0（含审计批次） |

产品代码（`petcore/` 运行时）**本轮 0 行改动**。

## 2 性能分析

- **运行时开销：0**。本轮没有碰 `petcore/` 任何运行路径，新增文件只有测试。
- **构建路径实测**（本机 E:\Work\dsh-pet-0，Windows，pwsh 7.6.6，`.venv` Python 3.12.10）：

  | 阶段 | 实测 |
  |---|---|
  | PyInstaller（含 `--clean`，onedir） | 91.2 s |
  | Inno Setup（`Compress=lzma2`，压 256 MB dist） | 115.7 s（ISCC 自报 `Successful compile (115.719 sec)`） |
  | 打包后 `--check --strict` 冒烟 | 0.7 s（同机计时探针 `elapsed_ms=698`） |
  | 整次 `-Clean -Installer` 构建 | 216.8 s（后台任务墙钟） |

  冒烟这一跳从「52 ms 假返回」变成「真实等待约 0.7 s」：这是**新增的门禁成本**，
  换来的是每次构建都能真实判红。
- **新增系统调用/线程/网络**：无。`Start-Process -Wait` 只是在同一个 pwsh 进程里同步等待
  子进程句柄。
- **磁盘**：`rel-balance-2026-10-26/` 内 dist 256 MB + setup 268,491,704 B（上版 261,554,392 B，
  +6.9 MB，来自 P5/审计阶段新增的代码、菜单模板、内置素材与 OCR/天气等扩展）。
- **内存**：未测（GUI 应用冷启内存不属于本轮改动面；本轮不引入常驻结构）。

## 3 实机运行记录

### 3.1 根因探针（同一台机器、同一个已签名未改动 exe）

```text
$ .\dsh-pet-core.exe --check --out <path> | Out-Null     # 管道 → PowerShell 等待
elapsed_ms=698 exists_now=True  exit=0

$ .\dsh-pet-core.exe --check --strict --out <path>       # 无管道 → 不等 GUI 进程
elapsed_ms=52  exists_now=False exit=(空)
```

52 ms 就是「启动器起来了又立刻返回」，所以首轮构建在 dist 已生成的情况下报
`找不到路径 …\rel-balance-2026-10-26\check.json`，而该文件在 14:01:40 才由子进程写出。

### 3.2 修复后的完整构建

```text
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 `
  -Clean -Installer -SignThumbprint 217337C099EC8624AC481BFC9F3E1664D0A442E1 `
  -OutputRoot 'rel-balance-2026-10-26'
```

关键日志（`.scratch/build-l095-b.log`）：

```text
signed: ...\rel-balance-2026-10-26\dsh-pet-core\dsh-pet-core.exe (CN=DSH Pet Core Dev, O=DSH Pet, C=CN)
check: menu_template=json characters=1 builtin_images=24 strict=True
Successful compile (115.719 sec). Resulting Setup program filename is: ...\dsh-pet-core-setup.exe
signed: ...\rel-balance-2026-10-26\dsh-pet-core-setup.exe (CN=DSH Pet Core Dev, O=DSH Pet, C=CN)
installer: ...\rel-balance-2026-10-26\dsh-pet-core-setup.exe
```

签名复验：

```text
status=Valid       signer=CN=DSH Pet Core Dev, O=DSH Pet, C=CN   (setup)
exe_status=Valid                                                  (dsh-pet-core.exe)
```

产物体检：

```text
268,491,704  rel-balance-2026-10-26/dsh-pet-core-setup.exe
sha256 472b2f8d9cd5c5e25bd6d7203834dcd8db1834c3f9f31c744982b9364ab97011
check.json: "click_show_balance": false      # 包内配置 schema 已含该键（默认关）
```

### 3.3 测试与静态检查（都是本轮真实输出）

| 命令 | 结果 |
|---|---|
| `pytest tests/test_petcore_click_balance.py -q` | 4 passed |
| `pytest tests/test_petcore_candidate_packaging.py -q` | 10 passed |
| `pytest -q $(ls tests/test_petcore*.py)`（全量） | **1713 passed in 131.57s，exit 0** |
| `pytest tests/test_petcore_docs.py tests/test_pr_report_discipline.py -q` | 301 passed |
| `ruff check tests/test_petcore_click_balance.py tests/test_petcore_candidate_packaging.py` | All checks passed |

### 3.4 无法自动验证的部分（用户需在真机手测）

- **双击安装全流程**：本机 Smart App Control 仍是强制模式
  （`VerifiedAndReputablePolicyState=1`），签名 `Valid` 不等于 SAC 放行；安装器可能被 3077 拦。
  若被拦，请用旧版已安装目录 + 新 `dsh-pet-core/` 覆盖的方式验证，或临时关 SAC。
- **真实余额数字**：需要在「设置 → API 与账户」里配置一个支持余额协议的服务（如 DeepSeek），
  勾上「点击显示余额」后再点桌宠；未配置时点击只会提示「没有配置余额服务」。

## 4 仍未做完 / 风险

1. SAC 环境下新 setup 的直接双击安装未验证（同上）；这是环境限制，不是代码问题。
2. 冒烟等待的回归只有脚本结构断言——PowerShell 对 GUI 子系统的等待语义无法在单测里复现，
   真实证据靠每次构建日志。
3. 「点击显示余额」的**反馈样式**仍是 petcore 版（气泡一行 `余额 ¥x`，灵动岛同步刷新），
   与主分支的余额气泡副标题/峰谷提示不完全一致；主分支差异记在
   `docs/PETCORE-MAIN-PARITY-BACKLOG.md`，本轮未改。
4. 工作树中上一轮审计修复（L088–L094）仍未提交，等用户决定提交方式。
