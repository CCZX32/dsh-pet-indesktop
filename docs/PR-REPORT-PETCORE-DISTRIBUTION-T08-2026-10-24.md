# P4-c3-D2 / T08：Windows 冻结候选包与开发证书签名（2026-10-24）

> 分支 `feat/petcore-vpet-architecture`。本批只做「候选包能构建、能签名、能自检、能装扩展」，
> **不安装到系统、不发布、不改安全策略**。安装包未在本机走完安装向导（见第五节）。
> 关联：[D1 验收说明](PETCORE-D1-ACCEPTANCE-2026-10-24.md)、[打包文档](ONEDIR_PACKAGING.md)、[T07 报告](PR-REPORT-PETCORE-DISTRIBUTION-T07-2026-10-24.md)。

## 一、核心特性

1. **构建入口可隔离**：`scripts/build_petcore.ps1` 新增 `-OutputRoot` 与 `-PythonPath`。
   `--distpath/--workpath/--specpath`、`--check` 结果、Inno 的源与输出全部收束到该目录；
   拒绝仓库根、拒绝已含 `dsh-pet-core-setup.exe` 的目录。`-Clean` 仍只传 PyInstaller 的 `--clean`，不删目录。
2. **安装包源目录也可覆盖**：`packaging/petcore.iss` 用 `MySourceDist` / `MyOutputDir` 两个可覆盖变量
   （`#ifndef` 默认值保持旧行为）。**这是本轮抓到的真缺陷**：只重定向 `OutputDir` 时，Inno 会从根 `dist/`
   打包——本机那里躺着一份 832 MB 的旧构建，第一次构建产出的安装包会装进旧代码。
3. **开发证书签名**：exe 与 setup 均由 `CN=DSH Pet Core Dev` 签名，`Get-AuthenticodeSignature` 两者都返回 **Valid**；
   SAC 强制模式下本次**没有**被拦截（此前 3077 针对的是未签名/更早构建）。
4. **冻结包自检与市场闭环**：`--check` 715 ms / exit 0 / `diagnostics: []` / `menu_template: json`；
   冻结包自己的 `market` CLI 用 `file:` 索引把四个候选包全部装上（exit 0），`mods/` 四个目录齐全。
5. **GUI 可启动**：隔离 root 下启动 exe，进程存活（约 96 MB 常驻），随后按验收流程终止——只证明「冻结包能起窗口」，
   不冒充人工视觉验收。

## 二、修改文件说明

| 文件 | 增/删 | 改了什么、为什么 |
|---|---:|---|
| `scripts/build_petcore.ps1` | +29 / −8 | `-OutputRoot`/`-PythonPath`；dist/work/spec 路径解析与两处目录守卫；`--check` 输出、exe 路径、Inno 传参改用 `$distRoot`（含 `MySourceDist`/`MyOutputDir`）。 |
| `packaging/petcore.iss` | +10 / −2 | `MySourceDist`/`MyOutputDir` 预处理器变量；`OutputDir={#MyOutputDir}`；`Source: "{#MySourceDist}\*"`。默认值不变，旧命令照旧可用。 |
| `tests/test_petcore_candidate_packaging.py`（新增） | +63 / −0 | 6 条文本契约：两个新参数、三条 pyi 路径、installer 源/输出、`.iss` 覆盖变量、本批新增的目录守卫、`-Clean` 不含删除语句。 |
| `docs/ONEDIR_PACKAGING.md` | +19 / −0 | 「候选包隔离输出」小节：参数表、守卫语义、本机签名示例命令。 |
| `petcore/AGENTS.md` | +3 / −0 | 打包红线补「候选包必须传 `-OutputRoot`」「`-Clean` 不删目录」。 |
| `docs/PETCORE-D1-ACCEPTANCE-2026-10-24.md`（新增） | +149 / −0 | D1（T00–T07）对外验收说明：能力边界、15 项矩阵、复跑命令、四个设计决定、7 条缺口、给审查者的 4 个问题。 |
| `docs/INDEX.md` | +1 / −0 | 登记验收说明。 |

## 三、性能分析

| 项 | 实测 |
|---|---|
| 构建总时长 | 约 7 分钟（PyInstaller 阶段 + Inno） |
| Inno 编译 | **96.296 s**（ISCC 自报） |
| onedir 体积 | **582 MB**（含 PySide6 / onnxruntime / rapidocr / cv2） |
| 安装包体积 | **261,718,360 B ≈ 261.7 MB**（lzma2 压缩） |
| 冻结包 `--check` | **715 ms**（含 Qt 初始化与配置读取） |
| 冻结包 GUI 启动 | 6 s 内进程存活，RSS ≈ 96 MB（仅采样一次，不是稳态） |

- 运行时开销无变化：本批只改构建入口与安装包装配；`-OutputRoot` 只在构建期生效。
- 构建期新增成本：一次路径解析 + 两次 `Test-Path` 守卫；`--clean` 与原先一致。
- 产物不进仓库：`.scratch/` 与 `dist-extensions/` 均已 gitignore；本报告只记录路径、字节数与 sha256 前缀。

## 四、实机运行记录

命令（本机 Windows / Python 3.12.10）：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 `
  -Clean -Installer -SignThumbprint 217337C099EC8624AC481BFC9F3E1664D0A442E1 `
  -OutputRoot .scratch/petcore-p4c3-distribution/t08/dist
```

| 检查 | 实际结果 |
|---|---|
| 构建退出码 | **0**；日志 4827 行，`signed:` 出现两次（exe、setup） |
| exe 签名 | `Valid`，`CN=DSH Pet Core Dev, O=DSH Pet, C=CN`；15,079,368 B，sha256 `dc40aa268ceb3f4c…` |
| setup 签名 | `Valid`，同一证书；261,718,360 B，sha256 `bc26e800044a2f14…` |
| 安装包源目录 | 日志中 3,816 行引用 `.scratch\…\t08\dist\dsh-pet-core`，确认打的是隔离构建而不是根 `dist/` 旧包 |
| 冻结 `--check` | exit 0 / 715 ms / `diagnostics: []` / `menu_template: json` / `version 0.2.0` |
| 冻结 `market list` | exit 0（不带索引时为 0 包 + stale，符合预期） |
| 冻结 `market install` ×4 | `reminder.todo` / `fun.festival` / `fun.divination` / `voice.chime` 全部 exit 0；四个 `mods/<id>` 存在 |
| GUI 启动 | 进程 `dsh-pet-core.exe` 存活（PID 13308，96 MB），验收后 `taskkill` 终止 |

原始日志与 JSON：`.scratch/petcore-p4c3-distribution/t08/{build.log,verify-frozen.json,dist/check.json}`（gitignored）。

**未做**：安装向导的实际点击流程（`Setup.exe /SILENT` 会写入真实系统目录，本轮不做）；安装后的自启/卸载验证；
Windows 通知中心与真实 TTS；双屏/混合 DPI；非 Windows。

## 五、限制与下一步

1. **安装包只「构建+签名」，没有装到系统**：装机会写 `%LOCALAPPDATA%`、注册表与自启项，属 T09 的隔离安装验收范畴。
2. **SAC 结论只对本次构建有效**：签名 + 时间戳下本次可运行；换构建/换证书要重新验，不能把「这次能跑」外推成策略已解除。
3. **根 `dist/` 有 832 MB 旧构建**：本机历史产物，未被删（不属本批授权），新构建已完全绕开它。
4. **setup 里仍打包 `examples/petcore-mods` 的 10 个扩展**：安装向导按任务勾选写盘，`.trusted` 只在向导路径写；
   与市场安装的授信口径一致，但本轮没有实测勾选/不勾选的落盘差异（T09 补）。
5. **D2 剩余**：T09（before/after 性能对照、整仓全量、发布步骤、`RELEASE_REPO/TAG` 确认、公开索引）。
