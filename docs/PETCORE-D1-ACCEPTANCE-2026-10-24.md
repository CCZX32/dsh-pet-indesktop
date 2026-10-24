# petcore 分发能力验收说明（D1 / T00–T07，2026-10-24）

> 面向：接手开发者、外部审查者、产品验收人。
> 结论先行：**「四个功能扩展能被安全地下载、校验、安装、升级、回滚」这条链路已经在本地闭环并留证；
> 但公开下载链路（HTTPS/CDN/Release）与安装包候选尚未验收。**
> 分支 `feat/petcore-vpet-architecture`，D1 末提交 `698b2312`。
> 逐批细节见 [T01](PR-REPORT-PETCORE-DISTRIBUTION-T01-2026-10-24.md)、[T02/T03/T05](PR-REPORT-PETCORE-DISTRIBUTION-T020305-2026-10-24.md)、
> [T04](PR-REPORT-PETCORE-DISTRIBUTION-T04-2026-10-24.md)、[T06](PR-REPORT-PETCORE-DISTRIBUTION-T06-2026-10-24.md)、[T07](PR-REPORT-PETCORE-DISTRIBUTION-T07-2026-10-24.md)。

## 1. 这批东西能做什么、不能做什么

| 能做 | 不能做（当前） |
|---|---|
| 用本地 `file:` 索引安装四个官方扩展，装完可被真实 `FeatureManager` 加载 | 从 GitHub Release 真实下载（资产未上传） |
| 未授权的 feature 包一律拒绝，磁盘零变化 | 安装包（EXE）候选的公开分发 |
| 解包与下载都有硬预算（64 MiB / 256 MiB / 10000 条目） | 已发布旧版本 → 新版本的兼容矩阵（本轮升级是合成版本） |
| 索引/包内 manifest 的能力、API、Core 兼容性交叉校验 | 真实 TTS、通知物理点击、双屏混合 DPI、非 Windows |
| 锁写失败自动回滚到旧版本；用户数据（`feature-data/`）SHA 不变 | 公开索引（根索引里四包仍 `blocked=true`） |

## 2. 交付清单

| 批次 | 提交 | 一句话 |
|---|---|---|
| T00 基线 | `a4515ad2` 及之前 | 基线快照、环境探针（含 SAC=1）、before 性能数字 |
| T01 契约 | `81f25f91` | 预算/传输/来源三个契约 + `fetch_artifact`、`install_package(origin=)` 签名 |
| T02 传输 | `94d80650` | 206/416 语义修正、读流预算、跳转三重约束、`allowed_hosts` |
| T03 解包 | `359446b5` | 解包前预检 + 写入计数（防 ZIP 声明造假） |
| T05 构建 | `34a247cb` | 可复现 ZIP 构建器 + 独立校验器 |
| 文档 | `d2a33c88` | T02/T03/T05 报告与 D1 进度 |
| T04 授权/事务 | `b128a8d1` | 生产安装接加固传输与预算、四类交叉校验、锁失败回滚 |
| T06 索引/离线 | `55ee7b51` | 根索引（blocked）、`file:` 索引/artifact、市场页安全销毁 |
| T07 验收 | `698b2312` | 真实 ZIP + `file:` 索引的授权/安装/加载/升级/回滚 + 60 次循环资源 |

**新增公共接缝**（改这些前先读 `docs/PETCORE-MOD-FORMAT.md` §18）：

- `petcore/contracts/archive.py`：`ArchiveLimits`、`BudgetExceeded`、`MARKET_ARCHIVE_LIMITS`
- `petcore/contracts/http.py`：`TransferSpec`（含 `allowed_hosts`、`allow_loopback_http`）、`TransferReport`、`ResumePolicy`
- `petcore/contracts/market.py`：`PackageOrigin`、`writes_trusted_marker()`
- `petcore/net/market_transport.py::fetch_artifact()`、`petcore/mods/install.py::open_pack/install(limits=)`

## 3. 验收矩阵（每条都能复跑）

| # | 要求 | 实现落点 | 证据 | 状态 |
|---|---|---|---|---|
| 1 | 下载能断点续传且不会把错位数据拼在一起 | `net/market.py` 206 分支校验 `Content-Range` 起点 | `tests/test_petcore_market_transport_security.py`（25 条） | 已验证（loopback） |
| 2 | 服务端 416 不能变成「假装下载完成」 | 416 只在长度与 `expected_size`/`bytes */N` 一致时完成 | 同上 | 已验证 |
| 3 | 下载体积有硬上限，不能先落盘再判断 | 读流累计，越界抛 `BudgetExceeded` 并删 `.part` | 同上 + `test_petcore_distribution_contracts.py` | 已验证 |
| 4 | 跳转不能把用户带到任意主机/明文 | 跳数 + 协议白名单 + 主机白名单 | 同上（含 GitHub Release 用例） | 已验证（单元） |
| 5 | 解包有展开上限，且不信 ZIP 声明 | 预检 + 计数写入 | `tests/test_petcore_remote_archive_limits.py`（9 条） | 已验证 |
| 6 | 包内不能靠自带 `.trusted` 自我授信 | `install_package(origin=)` 剔除并提示 | `test_petcore_market_install.py` 参数化 3 例 | 已验证 |
| 7 | 包内能力不能超出索引授权 | `verify.verify_manifest` 四类校验 | 同上（越权/api 漂移/未知能力） | 已验证 |
| 8 | 锁写失败不能留半包 | `_rollback_failed_commit()` | 新装回滚 + 旧版恢复两条用例 | 已验证 |
| 9 | 四个扩展能真装、真加载 | T05 ZIP + CLI + `FeatureManager` | `test_petcore_extension_candidates.py`（5 条） | 已验证（`file:`） |
| 10 | 升级/回滚不丢用户数据 | 三步切换 + SHA 比对 | 同上 | 已验证 |
| 11 | 市场页关闭时不销毁仍在运行的线程 | `_ORPHAN_JOBS` | `test_petcore_market_ui.py` | 已验证（offscreen Qt） |
| 12 | 索引可离线用且不偷偷联网 | `file:` 不回落默认源 | `test_petcore_extension_index.py` | 已验证 |
| 13 | 真实 HTTPS/代理/CDN 下载 | — | — | **未验证** |
| 14 | 已发布旧版升级矩阵 | — | — | **未验证**（本轮用合成版本） |
| 15 | 安装包候选（EXE/Inno） | `scripts/build_petcore.ps1 -OutputRoot -SignThumbprint` | [T08 报告](PR-REPORT-PETCORE-DISTRIBUTION-T08-2026-10-24.md)：exe/setup 均签名 Valid、冻结包 `--check` 715 ms、四包经冻结 CLI 安装成功 | 已完成（未装系统） |

**门禁真实结果**（本机 Windows / Python 3.12.10 / PySide6 6.12.0 / pytest 9.1.1）：

- 全量 petcore + 公共架构/PR 门：**1756 passed**（最后一批 T07 后复跑）
- `ruff check .`：All checks passed
- `python -m petcore --check`：exit 0
- 高负载：T02/T03/T05 的受影响族在 3 个 worker 并行下各自红→绿；未做 CPU 打满三遍（D1 以功能验收为主，D2/T09 补）

## 4. 自己复跑（约 3 分钟，不需要网络）

```bash
cd /e/Work/dsh-pet-0
.venv/Scripts/python scripts/build_petcore_extensions.py          # 产出 4 个 ZIP + candidate-manifest.json
.venv/Scripts/python scripts/verify_petcore_extensions.py \
    --candidate-manifest dist-extensions/candidate-manifest.json  # 期望 verified 4/4

QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest -q \
  tests/test_petcore_distribution_contracts.py \
  tests/test_petcore_market_transport_security.py \
  tests/test_petcore_remote_archive_limits.py \
  tests/test_petcore_market_install.py \
  tests/test_petcore_extension_build.py \
  tests/test_petcore_extension_index.py \
  tests/test_petcore_extension_candidates.py
```

四个候选包（可复现，两次构建 sha 相同）：

| 包 | 版本 | 字节 | sha256（前 12 位） |
|---|---|---:|---|
| `fun.divination` | 1.1.0 | 19169 | `b6b47112423d` |
| `fun.festival` | 1.1.0 | 41454 | `e4c5111441ff` |
| `reminder.todo` | 1.1.0 | 9655 | `e431ba505cf9` |
| `voice.chime` | 1.1.1 | 17522 | `dc4094c09625` |

## 5. 关键设计决定（审查时请重点看这四条）

1. **预算只作用市场 feature 包**。本地目录/ZIP 安装与角色/content 包沿用零预算（`limits=None`）。
   理由：角色包实测 93MB 级且是用户自己的文件，给本地安装加隐藏上限会破坏既有行为。
2. **`.trusted` 只由安装向导写**。市场包内自带的 `.trusted` 会被剔除并在消息里点名。
   理由：标记一旦能被包内文件触发，「安装向导才授信」这条边界就形同虚设。
3. **锁写失败 = 回滚，不是「装好了但没记账」**。有备份换回旧版，没有就删掉新装目录。
   理由：留下「文件新版、锁旧版」的状态，后续 `update` 会做出错误决策。
4. **跨主机跳转必须显式白名单**。默认只同主机；GitHub Release 由调用方列出
   `objects.githubusercontent.com` 等 CDN 主机。`file:` 索引显式给出时不回落到公网源。
   理由：既不让公开源悄悄把请求引到任意主机，也不让正常的 Release 跳转直接失效。

## 6. 已知缺口（不接受「应该没问题」的说法，逐条列）

1. **公开链路零实机**：没有一次真实的 HTTPS 下载、CDN 跳转、断流续传。所有网络证据都是 loopback。
2. **升级是合成的**：把同一份源码的 `mod.json` 改版本号当新版本，验证的是事务与数据保真，不是兼容矩阵。
3. **`doctor` 不带 `--index-url` 会回落默认源**（既有语义），离线环境会等超时并报 stale。
4. **索引四包 blocked**：公开资产不存在，装不到是刻意的；`RELEASE_REPO/TAG` 仍是拟定常量。
5. **资源循环是有限样本**：60 次循环 widget 归零、线程恒 4、无 staging/`.part` 残留；RSS 有非单调增长
   （页面段每 5 轮增量 14.5→1.2 MB），不承诺长期零增长。
6. **平台面**：仅 Windows 单屏；双屏/混合 DPI、macOS/Linux、真实声卡、通知物理点击均未验。
7. **取消能力有限**：索引读取与阻塞式下载不可强杀，只能等超时。

## 7. 请审查者重点确认

- `verify.verify_manifest` 的「能力 ⊆ 索引声明」是否会误伤未来新增能力？（新增能力需同时在索引里声明）
- `_rollback_failed_commit` 在「无备份 + 删除失败」时只报「回滚失败」——这个降级是否够清楚？
- `allowed_hosts` 的白名单是否应该由索引声明而不是代码常量？（当前是 `market/download.py::GITHUB_ARTIFACT_HOSTS`）
- `file:` 不回落默认源，会不会让「用户填错本地路径」表现为长时间无响应？（当前立即报错，符合预期但值得确认）

## 8. D2 收口补充（2026-10-24）

- **整仓**：`pytest -q` 未过滤 **9941 passed / 18 skipped / exit 0**（1220.48 s）；受影响族在 20 个负载进程下三遍全绿。
- **性能**：before/after 同探针，中位差 < 1.2 ms，下载/解包 p95 改善（38.77→34.23、15.06→13.63）。
- **安装器**：静默装到 scratch 的四种任务组合全部符合「不勾选不落盘、勾选写 `mods/<id>` + `.trusted`」，卸载干净。
- **仍未验**：真实 HTTPS/CDN/断流、向导人工点击与覆盖升级、双屏/混合 DPI、非 Windows。
- **发布**：未执行任何公开动作；流程与回滚见 [发布手册](PETCORE-EXTENSIONS-RELEASE.md)，发布前需你确认 `RELEASE_REPO/TAG` 与同版本摘要。
