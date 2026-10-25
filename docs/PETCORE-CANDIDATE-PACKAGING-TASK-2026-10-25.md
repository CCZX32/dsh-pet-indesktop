# petcore 候选包构建与隔离验收任务说明

> 执行对象：另一台 Windows 电脑上的弱模型/继任代理
>
> 本文只负责 **PyInstaller/Inno Setup 候选包构建、隔离验收和证据留存**。不要把“候选包验收”写成“公开发布完成”。
>
> 执行日期基线：2026-10-25。仓库路径、Git 安装位置和用户目录可能与本机不同，本文中的 `REPO`、`PY`、`OUT` 都必须在目标机器重新解析，不能照抄本机绝对路径。

## 1. 当前状态与任务目标

### 1.1 代码基线

- 目标分支：`feat/petcore-vpet-architecture`。
- 当前代码基线至少应包含：`254ec8db release(petcore): finalize candidate entrypoint and acceptance evidence`。
- 远端：`origin/feat/petcore-vpet-architecture`。
- 本阶段已有运行时重构、媒体/角色边界、设置与 parity 收口，不需要重新设计产品功能。
- 当前电脑的已知事实：PyInstaller 未安装，因此本机没有候选冻结包验收证据。另一台电脑只需对候选包工作负责，不要把本机历史报告或旧包当成本次证据。

### 1.2 目标

在目标 Windows 电脑上完成以下可验证工作：

1. 为本项目准备一个独立的 Python 3.11 构建环境；
2. 用仓库现有 `scripts/build_petcore.ps1` 构建 `onedir` 候选目录；
3. 在隔离数据目录执行候选程序的 `--check`、启动/退出和基础用户路径探针；
4. 若 Inno Setup 可用，再构建安装器并在全新测试目录安装、启动、卸载；
5. 保存工具版本、命令、原始输出、文件清单、SHA-256、阻断原因和实机观察；
6. 只在证据齐全时标记“候选包本机验收通过”；否则明确标记 `blocked` 或 `unknown`。

### 1.3 不在本任务内

- 不新增业务功能，不重写 `petcore` 架构，不为打包绿灯修改产品默认开关；
- 不上传 GitHub Release、CDN 或扩展 ZIP；
- 不覆盖现有安装，不使用真实账号、API key、钥匙串凭据或真实外部服务；
- 不安装开发证书、不导入信任证书、不关闭 Smart App Control/SmartScreen、不修改系统安全策略；
- 不做 Agent 写入端、灵动岛第二阶段、角色素材远程下载、VPet LPS/PNG、Core 自更新；
- 不重新运行旧 `pet` 实现的整仓测试。后续自动化门禁按用户要求只运行 `petcore` 测试及必要的 petcore 文档/架构门禁；不要运行 `pytest -q` 作为本任务门槛。

## 2. 必读文件

执行前先从仓库根目录读取：

1. `AGENTS.md`；
2. `petcore/AGENTS.md`；
3. `docs/PETCORE-REFACTOR-FINAL-2026-10-25.md` 或实际存在的 `docs/PR-REPORT-PETCORE-REFACTOR-FINAL-2026-10-25.md`；
4. `docs/PETCORE-ROADMAP.md`、`docs/PETCORE-SPEC.md`、`docs/PETCORE-MAIN-PARITY-BACKLOG.md`；
5. `docs/ONEDIR_PACKAGING.md`、`docs/STABLE_BUILDS.md`；
6. `petcore/README.md`；
7. `scripts/build_petcore.ps1`、`scripts/setup_packaging.ps1`、`packaging/petcore.iss`；
8. `docs/PETCORE-EXTENSIONS-RELEASE.md`，确认本任务不执行公开 Release。

若文件名与上面略有不同，以 `docs/INDEX.md` 和仓库实际路径为准；不要自行创建第二套打包流程。

## 3. 不可违反的工作规则

### 3.1 仓库与 Git

- 先运行 `git rev-parse --show-toplevel` 得到本机 `REPO`；不要假设仓库在 `E:\AI\DSH\dshpet`。
- 保留其他人的提交和工作区修改；禁止 `reset --hard`、`clean -fd`、覆盖式复制和 force push。
- 构建输出、日志、安装测试目录放在 `.scratch/petcore-packaging-candidate/<日期-机器名>/`，不要提交二进制、`.cache`、个人配置或凭据。
- 若远端在执行期间新增提交，先 `fetch`，再仅允许 `merge --ff-only`；不能把远端新提交覆盖掉。
- 若只完成探针或构建失败，也要保存原始输出并报告阻断，不要为了“绿”改写证据。

### 3.2 Python 与工具

- 优先使用 Python 3.11；只在项目专用虚拟环境中安装依赖，不修改全局 Python。
- `scripts/setup_packaging.ps1` 默认使用 `<REPO>/.venv/Scripts/python.exe`。若目标机器使用其他虚拟环境，不要偷偷修改脚本；可直接在独立环境安装 PyInstaller，并通过 `-PythonPath` 传给构建脚本。
- PyInstaller 约束：`>=6.10,<7`。记录实际版本，不沿用历史报告中的版本作为本次结果。
- Inno Setup 只使用现有或通过项目脚本安装的便携版本；若下载、SHA-256 或 Smart App Control 阻断，保留证据并标记未验收。
- 不使用真实签名证书。除非目标机器已有明确的开发证书且用户另行授权，不传 `-SignThumbprint`。

### 3.3 测试范围

每次代码、脚本或依赖相关修改后，最少执行：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$petcore = Get-ChildItem -LiteralPath (Join-Path $REPO 'tests') -Filter 'test_petcore_*.py' |
  Sort-Object FullName | ForEach-Object FullName
& $PY -m pytest @petcore -q
& $PY -m pytest tests/test_pr_report_discipline.py -q
& $PY -m ruff check petcore tests scripts
```

PowerShell 不会可靠地把 `tests/test_petcore_*.py` 展开给 pytest，所以使用上面的显式列表。**不要**因为方便改成仓库旧实现的 `pytest -q`。

## 4. 按顺序执行

### A. 环境与分支探针

在 PowerShell 中从仓库根目录运行并保存原始输出：

```powershell
$REPO = (& git rev-parse --show-toplevel).Trim()
Set-Location $REPO
$MACHINE = $env:COMPUTERNAME
$DATE = Get-Date -Format 'yyyy-MM-dd-HHmmss'
$OUT = Join-Path $REPO ".scratch/petcore-packaging-candidate/$DATE-$MACHINE"
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

'=== git ===' | Tee-Object -FilePath (Join-Path $OUT 'baseline.txt')
git status --short --branch | Tee-Object -FilePath (Join-Path $OUT 'baseline.txt') -Append
git rev-parse --show-toplevel | Tee-Object -FilePath (Join-Path $OUT 'baseline.txt') -Append
git log -1 --oneline --decorate | Tee-Object -FilePath (Join-Path $OUT 'baseline.txt') -Append
'=== tools ===' | Tee-Object -FilePath (Join-Path $OUT 'baseline.txt') -Append
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber |
  Out-File -FilePath (Join-Path $OUT 'baseline.txt') -Append
Get-Command git, git.exe, py, python, pwsh -ErrorAction SilentlyContinue |
  Format-List Name,Source,Version | Out-File (Join-Path $OUT 'baseline.txt') -Append
py --list 2>&1 | Tee-Object -FilePath (Join-Path $OUT 'baseline.txt') -Append
python --version 2>&1 | Tee-Object -FilePath (Join-Path $OUT 'baseline.txt') -Append
```

若不在目标分支：

```powershell
git fetch origin feat/petcore-vpet-architecture
git switch feat/petcore-vpet-architecture
```

不要使用 `reset`。检查 `git merge-base --is-ancestor 254ec8db HEAD` 的返回值为 0；若不是，先停止并报告分支基线异常。

记录屏幕和 DPI 探针，不要把单屏结果写成双屏通过：

```powershell
$env:PYTHONUTF8='1'
& $PY -c "from PySide6.QtGui import QGuiApplication; import sys; a=QGuiApplication(sys.argv); print([(s.name(), s.devicePixelRatio(), s.geometry().getRect()) for s in a.screens()])"
```

### B. 建立独立构建环境

优先方案（项目已有 `.venv` 且允许使用）：

```powershell
$PY = Join-Path $REPO '.venv/Scripts/python.exe'
if (-not (Test-Path $PY)) { throw 'missing .venv; use the isolated-venv alternative below' }
& $PY --version
& $PY -m pip install --upgrade pip
& $PY -m pip install -r (Join-Path $REPO 'requirements.txt') pytest ruff 'pyinstaller>=6.10,<7'
& $PY -m PyInstaller --version
```

隔离替代方案（不改全局 Python）：

```powershell
$VENV = Join-Path $REPO '.venv-packaging'
py -3.11 -m venv $VENV
$PY = Join-Path $VENV 'Scripts/python.exe'
& $PY -m pip install --upgrade pip
& $PY -m pip install -r (Join-Path $REPO 'requirements.txt') pytest ruff 'pyinstaller>=6.10,<7'
& $PY -m PyInstaller --version
```

如果使用 `.venv-packaging`，`setup_packaging.ps1` 仍会寻找 `.venv`，不要误以为它已安装成功。可以：

- 只用上面的 PyInstaller 安装，并把 `-PythonPath $PY` 传给 `build_petcore.ps1`；
- Inno Setup 已存在时直接检查 `<REPO>/tools/InnoSetup/ISCC.exe`；
- 只有明确确认脚本会使用正确的项目环境时才运行 `scripts/setup_packaging.ps1`。

依赖安装失败时保存完整 pip 输出。不要修改 `requirements.txt` 来绕过失败。

### C. 只运行 petcore 门禁

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$petcore = Get-ChildItem -LiteralPath (Join-Path $REPO 'tests') -Filter 'test_petcore_*.py' |
  Sort-Object FullName | ForEach-Object FullName
& $PY -m pytest @petcore -q 2>&1 | Tee-Object (Join-Path $OUT 'pytest-petcore.txt')
& $PY -m pytest tests/test_pr_report_discipline.py -q 2>&1 |
  Tee-Object (Join-Path $OUT 'pytest-doc-discipline.txt')
& $PY -m ruff check petcore tests scripts 2>&1 |
  Tee-Object (Join-Path $OUT 'ruff.txt')
& $PY -m petcore --check --root (Join-Path $OUT 'source-check-root') `
  --out (Join-Path $OUT 'source-check.json') 2>&1 |
  Tee-Object (Join-Path $OUT 'source-check.txt')
```

前置门禁失败就先记录并停止构建，不把失败藏在打包错误后面。

### D. 构建 onedir 候选目录

先只构建，不加 `-Installer`：

```powershell
$buildScript = Join-Path $REPO 'scripts/build_petcore.ps1'
& pwsh -NoProfile -ExecutionPolicy Bypass -File $buildScript `
  -Clean `
  -OutputRoot (Join-Path $OUT 'onedir') `
  -PythonPath $PY 2>&1 | Tee-Object (Join-Path $OUT 'build-onedir.txt')
if ($LASTEXITCODE -ne 0) { throw 'onedir build failed; do not continue to installer' }
```

构建脚本会自动执行一次打包后的 `dsh-pet-core.exe --check`，并在 `onedir/check.json` 写结果。仍需使用独立数据根目录复验：

```powershell
$EXE = Join-Path $OUT 'onedir/dist/dsh-pet-core/dsh-pet-core.exe'
if (-not (Test-Path $EXE)) { throw "missing $EXE" }
& $EXE --check --root (Join-Path $OUT 'packaged-check-root') `
  --out (Join-Path $OUT 'packaged-check.json') 2>&1 |
  Tee-Object (Join-Path $OUT 'packaged-check.txt')
if ($LASTEXITCODE -ne 0) { throw 'packaged --check failed' }
```

注意构建脚本的 `-OutputRoot` 会收集 `dist/work/spec/check`；不要把输出指向仓库根目录，也不要覆盖已有安装包。

### E. 候选目录实机冒烟

在不触碰真实配置的前提下：

1. 记录 `onedir/dist/dsh-pet-core` 的文件清单、总大小和每个可执行文件的 SHA-256；
2. 用 `--root <OUT>/packaged-ui-root` 启动候选程序；
3. 观察并记录：窗口/菜单是否出现、设置页能否打开、设置取消是否不写入、退出是否返回码 0；
4. 若本机确有两只合成宠物和提醒扩展测试条件，可在隔离数据根目录验证；没有则写 `not available`，不要模拟成通过；
5. 退出后检查进程和线程没有残留，不要使用 `taskkill /F` 掩盖正常退出问题；
6. 记录 Smart App Control/SmartScreen 的实际提示。被拦截时保留原文并标记阻断，不关闭安全策略。

建议的哈希和清单命令：

```powershell
Get-ChildItem -LiteralPath (Join-Path $OUT 'onedir/dist/dsh-pet-core') -Recurse -File |
  Sort-Object FullName |
  Get-FileHash -Algorithm SHA256 |
  Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $OUT 'onedir-sha256.csv')
Get-ChildItem -LiteralPath (Join-Path $OUT 'onedir/dist/dsh-pet-core') -Recurse -File |
  Select-Object FullName,Length,LastWriteTime |
  Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $OUT 'onedir-files.csv')
```

### F. Inno Setup 安装器（仅在 onedir 通过后）

先确认：

```powershell
$ISCC = Join-Path $REPO 'tools/InnoSetup/ISCC.exe'
if (-not (Test-Path $ISCC)) { 'INNO_NOT_AVAILABLE' | Tee-Object (Join-Path $OUT 'installer.txt'); return }
& $ISCC /? | Tee-Object (Join-Path $OUT 'inno-version.txt')
```

若可用：

```powershell
& pwsh -NoProfile -ExecutionPolicy Bypass -File $buildScript `
  -Clean -Installer `
  -OutputRoot (Join-Path $OUT 'installer') `
  -PythonPath $PY 2>&1 | Tee-Object (Join-Path $OUT 'build-installer.txt')
if ($LASTEXITCODE -ne 0) { throw 'installer build failed' }
```

安装验收必须使用全新目标目录和全新数据根目录：

- 不覆盖现有安装；
- 首次启动后执行 `--check`；
- 观察安装、启动、正常退出、卸载；
- 记录安装器返回码、安装路径、卸载后残留；
- 若 Windows 安全策略阻止，记录证据并停止，不关闭策略、不导入证书。

### G. 证据与结果判定

在 `$OUT` 保存：

- `baseline.txt`；
- Python/PyInstaller/Inno 版本；
- petcore-only pytest、Ruff、`--check` 原始输出；
- onedir/installer 构建输出；
- `check.json`；
- SHA-256 和文件清单；
- 安装/卸载实机记录；
- 进程退出及安全策略结果；
- 最终 `git status --short --branch`。

推荐使用以下矩阵：

| 项目 | 通过条件 | 结果值 |
|---|---|---|
| A 环境 | Python 3.11、Windows、工具版本已记录 | `pass` / `blocked` |
| B petcore 门禁 | petcore 测试、文档纪律、Ruff 均通过 | `pass` / `blocked` |
| C onedir | PyInstaller 构建返回 0，文件齐全 | `pass` / `blocked` |
| D 冻结检查 | 候选 `--check` 返回 0，JSON 可读 | `pass` / `blocked` |
| E 隔离冒烟 | 启动、设置路径、退出无残留 | `pass` / `unknown` / `blocked` |
| F 安装器 | 安装、启动、卸载均成功 | `pass` / `not_available` / `blocked` |
| G 完整性 | SHA、无凭据、无个人配置、无意外超大文件 | `pass` / `blocked` |
| H 平台缺口 | 双屏/其他平台/外部服务只按真实探针填写 | `verified` / `not_available` |

**定义完成**：C、D、G 必须为 `pass`；E 在本机可运行时必须为 `pass`；F 如果 Inno 不可用可为 `not_available`，但不得写“安装器通过”；所有不可用环境都要有命令和原始输出。候选包验收通过仍不等于公开发布。

## 5. 完成后的文档和提交

### 5.1 如果只是探针/打包，未改仓库代码

不要为了写报告修改产品代码。将完整证据保存在 `.scratch/petcore-packaging-candidate/<日期-机器名>/`，把结果回填到交接文件或新建报告后再提交。

### 5.2 如果确实修改了代码或构建脚本

必须先写失败回归，再做最小修复；重新运行本任务的 petcore-only 门禁；在 `docs/PETCORE-LOG.md` 新增下一个 `LNNN`，在 `docs/PETCORE-LOG-INDEX.md` 登记；新增日期报告必须包含：

- `## 修改文件说明`；
- `## 性能分析`；
- `## 实机运行记录`。

构建二进制、安装器、缓存、用户数据和凭据不得提交。

### 5.3 推送规则

```powershell
git status --short --branch
git diff --check
git fetch origin feat/petcore-vpet-architecture
git merge --ff-only FETCH_HEAD
# 仅在文档/脚本和证据归档完成后提交
# 推送时使用当前机器实际配置的 SSH over 443，不要改全局 Git 配置
git push origin HEAD:refs/heads/feat/petcore-vpet-architecture
```

若 `fetch` 后 `merge --ff-only` 失败，停止并报告远端分叉；禁止 force push。若另一台电脑使用不同 Git 路径，使用 `Get-Command git` 找到实际可执行文件即可。

## 6. 最终回传格式

请将以下内容原样或按实际值回传：

```text
机器/OS：
仓库根目录：
分支与 HEAD：
Python：
PyInstaller：
Inno Setup：
屏幕/DPR：
petcore 测试：
Ruff：
源码 --check：
onedir 构建：
候选 --check：
启动/设置/退出：
安装器安装/卸载：
SHA/文件清单：
Smart App Control/SmartScreen：
结果：pass / blocked / partial
证据目录：
是否修改代码：
提交 SHA：
推送结果：
剩余缺口：
```

任何“未执行”“工具缺失”“环境不支持”都必须填真实原因和原始输出，不能用历史报告代替。
