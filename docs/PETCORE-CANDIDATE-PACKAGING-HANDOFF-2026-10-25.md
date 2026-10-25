# petcore 候选包构建交接文档

> 交给另一台 Windows 电脑上的弱模型执行。详细步骤见 [`PETCORE-CANDIDATE-PACKAGING-TASK-2026-10-25.md`](PETCORE-CANDIDATE-PACKAGING-TASK-2026-10-25.md)。

## 1. 交接结论

本机已完成 petcore 重构代码、自动化回归和文档收口；**未在本机安装 PyInstaller，也未构建或验收候选包**。下一台电脑只负责候选包构建与隔离验收，不要重新设计产品功能。

候选包验收通过不等于公开发布；本任务不上传 GitHub Release/CDN，不使用真实账号，不覆盖现有安装，不调整 Windows 安全策略。

## 2. 基线与仓库规则

- 目标分支：`feat/petcore-vpet-architecture`。
- 代码基线至少包含：`254ec8db`。
- 目标远端：`origin/feat/petcore-vpet-architecture`。
- 目标电脑先运行 `git rev-parse --show-toplevel`，不要使用本机 `E:\AI\DSH\dshpet` 路径。
- 不得 `reset --hard`、`clean -fd`、force push 或覆盖远端新提交。
- 构建产物和用户数据放在 `.scratch/petcore-packaging-candidate/<日期-机器名>/`，不要提交二进制、缓存、凭据或个人配置。

## 3. 可以复用的已验证结果

| 项目 | 当前证据 |
|---|---|
| petcore 测试 | 显式展开 `tests/test_petcore_*.py`：1479 passed in 132.94s |
| petcore 专项门禁 | 架构、文档、设置覆盖、PR 纪律：302 passed in 4.03s |
| Ruff | `All checks passed!` |
| 源码检查 | `python -m petcore --check` 默认根和隔离根均返回 0 |
| 高负载时序 | 受影响族 3 轮，每轮 136 passed |
| 本机环境缺口 | 单屏/DPR 1.0；PyInstaller 未安装；无候选冻结包证据 |

这些结果不替代目标电脑的候选包证据，也不能推出双屏、其他平台、真实 TTS/CDN 或公开发布已通过。

## 4. 继任模型执行顺序

1. 读取根 `AGENTS.md`、`petcore/AGENTS.md`、`docs/PETCORE-CANDIDATE-PACKAGING-TASK-2026-10-25.md`、`docs/ONEDIR_PACKAGING.md`、`docs/STABLE_BUILDS.md` 和 `scripts/build_petcore.ps1`。
2. 记录 OS、Python、Git、屏幕/DPR、Smart App Control/SmartScreen 状态；确认分支包含 `254ec8db`。
3. 使用项目专用 Python 3.11 venv 安装 `PyInstaller>=6.10,<7`、项目依赖、`pytest` 和 `ruff`；不要修改全局 Python。
4. **只运行 petcore 测试和必要专项门禁**：显式展开 `tests/test_petcore_*.py`，另跑 `tests/test_pr_report_discipline.py` 和 `ruff check petcore tests scripts`；不要运行旧 `pet` 实现整仓 `pytest -q`。
5. 先构建 onedir：

   ```powershell
   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 `
     -Clean -OutputRoot <scratch-output> -PythonPath <venv-python>
   ```

6. 对候选 `dsh-pet-core.exe` 使用隔离 `--root` 执行 `--check`，记录 JSON、返回码、文件清单和 SHA-256。
7. 在隔离目录实机观察启动、设置打开/取消、两只合成宠物（若本机条件具备）、正常退出和进程残留；缺条件必须写 `not available`。
8. 只有 onedir 通过且 `<REPO>/tools/InnoSetup/ISCC.exe` 可用时，才加 `-Installer` 构建安装器；使用全新安装目录和全新数据根目录验证安装、启动、卸载。
9. 任何 Smart App Control/SmartScreen 拦截、依赖安装失败、构建失败、候选 `--check` 非 0 或安装器不可用，都保留原始输出并标记 `blocked`/`partial`，不关闭安全策略、不导入证书、不伪造通过。

## 5. 停止与交付条件

### 必须停止的情况

- 需要修改产品默认行为或架构才能打包；
- 需要真实账号、真实密钥或覆盖已有安装；
- 需要关闭安全软件/Smart App Control、导入证书或提权；
- Git 远端无法 `merge --ff-only`；
- 目标环境缺少 Python 3.11、项目依赖、PyInstaller 或 Inno Setup，且没有安全可追溯的替代方案。

### 回传内容

```text
机器/OS：
仓库根目录：
分支与 HEAD：
Python/PyInstaller/Inno Setup：
屏幕/DPR：
petcore 测试与 Ruff：
源码 --check：
onedir 构建与候选 --check：
启动/设置/退出：
安装器安装/卸载：
SHA-256 与证据目录：
Smart App Control/SmartScreen：
结果：pass / blocked / partial
是否修改代码：
提交 SHA 与推送结果：
剩余缺口：
```

如果确实修改了代码或构建脚本，必须先写失败回归，补 `docs/PETCORE-LOG.md` 的下一个 `LNNN` 和 `docs/PETCORE-LOG-INDEX.md`，并重新跑 petcore-only 门禁。新增报告必须有 `## 修改文件说明`、`## 性能分析`、`## 实机运行记录` 三个章节。
