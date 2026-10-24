# P4-c3-D1 / T04：身份、授权与安装事务（2026-10-24）

> 分支 `feat/petcore-vpet-architecture`。前序：T01 契约、T02 传输、T03 解包、T05 构建器。
> 本批把市场安装真正接到加固传输与预算上，并把交叉校验与「锁写失败」做成一致的事务语义。
> 关联：[MOD-FORMAT §18](PETCORE-MOD-FORMAT.md)、[T01 报告](PR-REPORT-PETCORE-DISTRIBUTION-T01-2026-10-24.md)。

## 一、核心特性

1. **市场安装改走 `fetch_artifact`**：`market/download.py` 在 fetcher 提供 `fetch` 时优先使用逐跳加固入口
   （`HttpFetcher.fetch → fetch_artifact`），并按 URL 构造 `TransferSpec`（size、GitHub CDN 允许列表、超时）。
   只实现 `download` 的测试替身仍走旧路径，既有测试不必重写。
2. **预算真正生效**：`download_artifact` 与 `install_package` 默认传 `MARKET_ARCHIVE_LIMITS`；
   压缩预算在读流里截停，展开预算在解包预检/计数写入里截停；`BudgetExceeded` 被转成
   `InstallOutcome(False, …)` 而不是穿透到 UI。
3. **交叉校验扩展**（`verify.verify_manifest`）：除 id/kind/version，还拒绝
   ①包内能力不在已知能力表、②包内能力超出索引为该包声明（防提权）、
   ③`api_version` 与索引不一致、④包内 `core_requires` 不满足当前 Core。
4. **事务一致性**：`market-lock.json` 写失败不再留下「文件是新版、锁是旧版」的半提交状态——
   有备份就换回旧版，没有就删掉新装目录，并如实回报「已回滚」/「回滚失败」。
5. **回环例外**：明文 `http` 只对本机回环（`127.0.0.1` / `::1` / `localhost`）自动放行，
   由 `TransferSpec.allow_loopback_http`（默认真）控制，可在测试或收紧环境时关掉。

**为什么把 loopback 判断移进 `net/`**：架构门禁禁止 `market/` import 网络库，`urllib.parse`
也算网络栈。判断放进 `net/market_transport.py`（允许区）既守住红线，也避免在 market 层手写 URL 解析。

## 二、修改文件说明

| 文件 | 增/删 | 改了什么、为什么 |
|---|---:|---|
| `petcore/market/download.py` | +60 / −3 | `limits` 参数；`_fetch_one` 优先 `fetcher.fetch`（逐跳加固），否则旧 `download`；`GITHUB_ARTIFACT_HOSTS`；失败聚合保留多 URL 回退。 |
| `petcore/net/market.py` | +8 / −0 | `HttpFetcher.fetch()` 转调 `fetch_artifact`（局部 import 避免循环依赖）。 |
| `petcore/net/market_transport.py` | +13 / −1 | `_effective_schemes()`：仅回环自动放行 http；`allow_loopback_http=False` 时回到 https-only。 |
| `petcore/contracts/http.py` | +3 / −0 | `TransferSpec.allow_loopback_http` 字段与文档。 |
| `petcore/market/install.py` | +32 / −8 | `limits` 参数并下传下载/解包；`_stage_manifest(core_version=)`；捕获 `BudgetExceeded`；锁失败 `_rollback_failed_commit()`。 |
| `petcore/market/verify.py` | +35 / −2 | 能力表 / 索引授权 / api_version / core_requires 四类交叉校验，错误点名不一致字段。 |
| `tests/test_petcore_market_install.py` | +180 / −0 | 7 条：加固 fetch 被使用、预算失败不留包、能力越权被拒、索引授权通过、api 漂移（安装与直调两条）、锁失败回滚新装、锁失败恢复旧版。 |
| `tests/test_petcore_market_transport_security.py` | +17 / −1 | 回环默认放行、可关闭两条；原「默认 https 拒绝 http」用例改用非回环主机，保住原意。 |
| `docs/PETCORE-MOD-FORMAT.md` | +4 / −4 | §18.2 loopback 口径；§18.4 三条签名标「已落地」。 |

## 三、性能分析

- **稳态**：无新增线程/定时器/轮询。安装路径新增一次 `getattr(fetcher, "fetch")` 探测与一次
  `TransferSpec` 构造（微秒级）。
- **下载路径变化**：每跳一次 `Content-Range` 解析（T02），每次安装一次临时 staging 目录创建/删除
  （`market/downloads/.fetch-<id>-<ver>`）；相比原先直接写 `.part` 多一次 `os.replace`，属于常数级。
- **校验成本**：`verify_manifest` 新增集合差与一次版本比较，遍历条目数与包内能力（≤6 项）。
- **失败路径更省**：预算越界在下载/解包阶段终止，不再产生完整大文件；锁失败会回滚，避免用户磁盘上留半包。
- 不重测基线：T00 `before-perf.json` 已在册；本批无旧实现可对照的相同工作量（旧路径是「不加固」），
  按纪律标「新增路径无旧对应」，最终 after 对照在 T09 用同一探针。

## 四、实机运行记录

本机 Windows / Python 3.12.10 / pytest 9.1.1，`QT_QPA_PLATFORM=offscreen`：

| 命令 | 实际结果 |
|---|---|
| `pytest -q tests/test_petcore_market_install.py tests/test_petcore_market_transport_security.py tests/test_petcore_market_cli.py tests/test_petcore_architecture.py` | **57 passed in 23.70s** |
| `pytest -q tests/test_petcore_market_*.py tests/test_petcore_distribution_contracts.py`（6 文件） | **58 passed in 13.78s** |
| 全量 petcore + 公共架构/PR 门 | **1738 passed in 123.00s** |
| `ruff check petcore tests` | All checks passed |

关键行为实测（同一轮测试内）：本地 `http://127.0.0.1` 索引 + 真实 `HttpFetcher.fetch` 的 CLI 端到端
`list → install → update → rollback` 通过；把 `allow_loopback_http` 关掉后同一 URL 在连接前被拒
（`NetworkError(PROTOCOL)`，服务端命中数为 0）。

未覆盖：真实 HTTPS/CDN/系统代理下载；Windows 原生 GUI（本批不碰 UI）；真实签名/密钥。

## 五、限制与下一步

1. **T06 待办**：`install_package` 的 `limits` 尚未在设置页/CLI 暴露为可调项（当前固定默认值）；
   根索引、`MarketPage` 的 `dispose` 与迟到 reload、条目的 size/sha 展示仍在 T06。
2. **`install()` 仍不抛 `BudgetExceeded`**：市场路径经 `open_pack` 已能捕获；本地目录/ZIP 安装保持
   返回 `(False, msg)` 的旧契约，未改语义。
3. **目录来源不套预算**：`open_pack(dir, limits=...)` 原样返回目录；市场只走 zip。
4. **多 URL 回退**已存在但在 T04 未加针对性故障注入（T02 已覆盖单 URL 的传输失败）；T07 会用真实旧包补。
5. 本批未验证「锁写失败时 UI 是否会重载」——回滚走文件层，UI 刷新属 T06/T07。
