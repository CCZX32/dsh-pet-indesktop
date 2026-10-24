# P4-c3-D1 / T01：冻结分发跨模块契约（2026-10-24）

> 分支 `feat/petcore-vpet-architecture`，基线 `a4515ad2`（T00 两个文档 commit 已推送）。
> 本批只做 T01：新增预算/传输/来源三个契约、接通 `fetch_artifact` 与 `install_package(origin=)`，
> 不改默认市场源、不改版本号、不改任何业务行为。T02/T03/T05 由 worker 并行实施，T04/T06/T07 随后。
> 关联：[分发计划](superpowers/plans/2026-10-24-petcore-p4c3-distribution.md)、[MOD-FORMAT §18](PETCORE-MOD-FORMAT.md)、[日志 L065](PETCORE-LOG.md)。

## 一、核心特性

1. **预算契约**（`petcore/contracts/archive.py`）：`ArchiveLimits(compressed, expanded, entries)` 不可变，
   三字段必须正整数（`bool` 拒绝），`allows()` 等于上限算通过；默认 `MARKET_ARCHIVE_LIMITS` = 64 MiB / 256 MiB / 10000。
   越界抛 `BudgetExceeded(kind, limit, actual)`，消息带实测值与上限。
2. **传输契约**（`petcore/contracts/http.py`）：`TransferSpec`（默认只允许 https、最多 3 跳、`RESUME_IF_MATCH`）、
   `TransferReport`、`ResumePolicy`。字段校验在构造期完成；`expected_sha256` 只作描述，最终校验仍归 `market/verify.py`。
3. **来源契约**（`petcore/contracts/market.py`）：`PackageOrigin` 四值 + `writes_trusted_marker()`——只有安装向导
   投放的 `bundled` 包可带 `.trusted`。
4. **下载入口**（`petcore/net/market_transport.py`）：`fetch_artifact(spec, dest_dir, *, limits, progress, cancel) -> TransferReport`。
   当前实现委托既有 `download_to`，并在**下载完成后**复核压缩体积（越界删 `.part` 抛 `BudgetExceeded`）；读流计数留给 T02。
5. **安装入口**（`petcore/market/install.py`）：`install_package(..., origin=PackageOrigin.MARKET, ...)`；来源无授信资格时
   剔除包内自带的 `.trusted` 并在成功消息里点名（防标记走私）。这不是 T04 的事务工作，只钉住「谁能带标记」。

## 二、修改文件说明

| 文件 | 增/删 | 改了什么、为什么 |
|---|---:|---|
| `petcore/contracts/archive.py`（新增） | +54 / −0 | 预算数值、不可变类型与越界异常；三 worker 共用的唯一数值来源。 |
| `petcore/contracts/market.py`（新增） | +28 / −0 | 来源枚举与「谁能写 `.trusted`」的判定；把 AGENTS 的授信红线变成可测函数。 |
| `petcore/contracts/http.py` | +52 / −0 | 传输描述/结果/续传策略；默认 https 与跳数上限写成契约，避免各层各写一套。 |
| `petcore/net/market_transport.py`（新增） | +66 / −0 | 冻结下载签名并接通既有实现；下载后体积复核可用，读流加固由 T02 替换内部。 |
| `petcore/market/install.py` | +18 / −0 | `origin` 参数与 `.trusted` 剔除；市场/本地包不能靠包内标记自我授信。 |
| `tests/test_petcore_distribution_contracts.py`（新增） | +211 / −0 | 11 条：预算边界/异常字段、Spec 校验、HTTPS 默认、loopback 下载、压缩预算、三种来源的标记行为。 |
| `docs/PETCORE-MOD-FORMAT.md` | +47 / −0 | §18 固化契约表与冻结签名，供 worker 只依赖签名。 |
| `docs/PETCORE-MARKET.md` | +14 / −0 | 标明「契约已冻结、行为未加固」，防止把 T01 读成分发可用。 |
| `docs/PETCORE-SPEC.md` | +13 / −0 | 边界表：预算只作用于市场 feature、默认源与发布未变。 |
| `docs/PETCORE-LOG.md` / `docs/PETCORE-LOG-INDEX.md` | 见 L065 | 批次记录与索引。 |
| `docs/PR-REPORT-PETCORE-DISTRIBUTION-T01-2026-10-24.md`（新增） | 本报告 | 三章证据与后续边界。 |

本报告自身不计入上表；文档 `docs/INDEX.md` 与 `PETCORE-ROADMAP.md` 同批追加。

## 三、性能分析

本批**不改变任何稳态运行路径**：预算对象只在市场调用时构造；`fetch_artifact` 是新增入口（现只有测试调用）；
`install_package` 的 `origin` 分支只在解包目录上做一次 `Path.exists()`（无标记时立即返回）。

- 新增调用点：`install_package` 每次安装一次 `exists()`；`fetch_artifact` 下载完成后一次 `stat` 级体积复核。
- 无新增线程、定时器、网络请求或常驻内存；无新增磁盘写入（越界时才删除 `.part`）。
- 基线不重测：T00 已在同机采到 `before-perf.json`（download 32.739 ms / resume 33.141 ms / extract 12.993 ms /
  install_local_dir 38.512 ms / idle_market_page 13.369 ms，3 轮 15 s 预热 + 60 s 采样）。T01 没有可与之对照的旧路径，
  按纪律标「新增路径无旧对应」，after 对照在 T09 用同一探针重跑。
- 已知缺口：`fetch_artifact` 的体积复核发生在下载完成之后，**不能**阻止大文件先落盘——这是显式中间状态，T02 必须把计数移进读流。

## 四、实机运行记录

命令均在本机（Windows / Python 3.12.10 / PySide6 6.12.0 / pytest 9.1.1）执行：

| 命令 | 实际结果 |
|---|---|
| `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest -q tests/test_petcore_distribution_contracts.py` | **11 passed in 1.73s** |
| `... -m pytest -q tests/test_petcore_market_install.py tests/test_petcore_market_cli.py tests/test_petcore_market_net.py tests/test_petcore_market_source.py tests/test_petcore_market_ui.py tests/test_petcore_install.py tests/test_petcore_architecture.py` | **63 passed in 11.09s** |
| `.venv/Scripts/python -m ruff check petcore tests` | **All checks passed** |
| loopback 下载（`test_fetch_artifact_writes_file_and_reports_bytes`） | 4096 字节落盘、`.part` 已清理；`TransferReport.path` 指向最终文件 |
| 压缩预算（`test_fetch_artifact_enforces_compressed_budget…`） | 2048 字节对 1024 上限 → `BudgetExceeded(kind=compressed)`，`.part` 与成品都不存在 |
| 来源标记（参数化 3 例） | `market` / `local-zip` 装完无 `.trusted` 且消息含「已移除」；`bundled` 保留 `.trusted` |

未做：GUI 实机（本批不碰界面）、远端 HTTPS 下载（无发布源）、解包预算（T03）、逐跳与 Range（T02）。
整仓与高负载不在本批范围，按计划在 T07 后统一跑。

## 五、限制与下一步

- `fetch_artifact` 的续传与跳转仍是旧实现语义，T02 必须替换内部并通过 `Content-Range`/416/预算/跳转四组回归。
- `open_pack` / `install` 的 `limits` 参数尚未落地（T03），因此**解包预算此刻不生效**；不得对外声称已有展开上限。
- `origin` 目前只负责标记剔除；`allow_feature` 授权、事务恢复与 manifest 交叉校验仍归 T04。
- 默认索引源未改（仍指 `MerZlin/dsh-pet-extensions`），切换与 Release 属 D2，需用户确认。
