# P4-c3-D1 / T02+T03+T05：传输加固、解包预算与可复现候选包（2026-10-24）

> 分支 `feat/petcore-vpet-architecture`。三个 worker 按不重叠写集并行，主模型复核 diff、补齐契约口径并集成。
> 提交：`94d80650`（T02）、`359446b5`（T03）、`34a247cb`（T05）。
> 前序：[T01 契约冻结](PR-REPORT-PETCORE-DISTRIBUTION-T01-2026-10-24.md)；计划：[分发 T00–T09](superpowers/plans/2026-10-24-petcore-p4c3-distribution.md)。

## 一、核心特性

| 批次 | 交付 |
|---|---|
| T02 传输 | 206 只在 `Content-Range` 起点等于 `.part` 长度时追加；416 只在本地长度与 `expected_size`/`bytes */N` 一致时算完成；压缩预算移进读流；跳转受 `max_redirects` + 协议白名单 + 主机约束；所有路径 `finally` 关闭响应；取消保留 `.part` |
| T03 解包 | `open_pack/install` 接受 `limits`；解包前按中央目录预检条目数与展开字节；写入阶段按实际读到的字节计数（防声明造假）；失败清理 staging；`limits=None` 行为不变 |
| T05 构建 | 白名单可复现 ZIP 构建器 + 独立校验器；固定 `date_time`/属性/排序/压缩级别；候选清单只含 size/sha256/files 等可移植字段 |
| 契约修正（主模型） | `TransferSpec.allowed_hosts`：跨主机跳转必须显式列出（GitHub Release 必需）；`resumed_from` 文档口径收窄为「仅服务端区间对齐时非零」 |

**为什么改契约**：T02 按「同主机」实现后发现 GitHub Release 的
`github.com → objects.githubusercontent.com` 会被拒绝。与其在生产接线时才发现，不如现在把
「显式允许列表」写进契约：默认仍只允许同主机，调用方要对某个 CDN 放行必须自己列出来。

## 二、修改文件说明

| 文件 | 增/删 | 改了什么、为什么 |
|---|---:|---|
| `petcore/net/market.py` | +378 / −48 | 新增 `TransportPolicy`（含 `allowed_hosts`）、`DownloadOutcome`、`Content-Range` 解析、`validate_redirect`、禁止自动跟随的 redirect handler；重写下载循环。 |
| `petcore/net/market_transport.py` | +25 / −14 | `fetch_artifact` 走 `download_with_outcome`，预算在读流生效，`ResumePolicy.RESTART` 先删 `.part`，报告真实跳数。 |
| `petcore/contracts/http.py` | +7 / −2 | `allowed_hosts` 字段与空值校验；`resumed_from`/`allowed_hosts` 文档口径。 |
| `tests/test_petcore_market_transport_security.py`（新增） | +670 / −0 | 25 条：206 错位/缺头、416 两义、读流越界、跨主机/降级/超跳数、同主机跟随、读失败关闭、取消状态、GitHub Release 允许列表。 |
| `petcore/mods/install.py` | +55 / −10 | `limits` 逐层下传；`_check_declared_budget`；`copyfileobj` → 计数循环；失败清理。 |
| `tests/test_petcore_remote_archive_limits.py`（新增） | +245 / −0 | 9 条：条目/展开预检、声明造假、限额内通过、`limits=None` 不变、失败无残留、逃逸与符号链接仍拒。 |
| `scripts/build_petcore_extensions.py`（新增） | +549 / −0 | 白名单收集、确定性 ZIP、原子落盘（`.part` → 自检 → `os.replace`）、候选清单与待发布索引生成。 |
| `scripts/verify_petcore_extensions.py`（新增） | +373 / −0 | 独立校验：解包重算 size/sha、字段与 `mod.json` 一致、拒绝 `.trusted` 与不可移植路径。 |
| `tests/test_petcore_extension_build.py`（新增） | +398 / −0 | 16 条：两次构建同 sha、白名单、清单一致、篡改/`.trusted` 被拒、只读源码树可构建。 |
| `.gitignore` | +2 / −0 | 忽略 `dist-extensions/`（候选产物不入库）。 |
| `docs/PETCORE-MOD-FORMAT.md` | +5 / −3 | §18.2 补 `allowed_hosts`、416 语义、读流预算与 `resumed_from` 口径。 |

## 三、性能分析

三个批次都没有新增常驻线程、定时器或后台轮询；新增成本集中在**市场调用路径**：

| 路径 | 触发频率 | 实测/口径 |
|---|---|---|
| `Content-Range` 解析 | 每次 206 响应一次 | 纯字符串解析，微秒级；无新增 IO |
| 读流计数 | 每个 64 KiB 块一次整数加法 | 与 `write()` 同量级，可忽略但未单独基准 |
| 跳转校验 | 每次 3xx 一次 | 纯比较，无 DNS/网络 |
| 解包预检 | 每次 zip 解包一次 `infolist()` | 一次中央目录遍历；40 个条目的包远小于 1ms |
| 写入计数 | 每块一次比较 | 与既有 `copyfileobj` 相比多一次整数累加 |
| 构建器 | 仅开发时手动运行 | 4 包约 1 秒级；产物 9.6–41.5 KB |

- T00 的 `before-perf.json`（download 32.739 ms / extract 12.993 ms）是旧实现基线；T02/T03 引入计数与校验后**尚未重测**，
  after 对照按计划在 T09 用同一探针重跑。本报告不声称「更快」，也不把新增校验说成免费。
- 无新增磁盘写入（预算越界时才删除 `.part`/staging）；无新增网络请求；无遥测。
- 一个可观察的行为变化：`fetch_artifact` 越界时会**提前**失败，因此不再产生完整大文件，磁盘占用只会更低。

## 四、实机运行记录

本机 Windows / Python 3.12.10 / pytest 9.1.1，全部 `QT_QPA_PLATFORM=offscreen`：

| 命令 | 实际结果 |
|---|---|
| `pytest -q tests/test_petcore_market_transport_security.py tests/test_petcore_market_net.py tests/test_petcore_distribution_contracts.py` | **46 passed in 18.04s**（含主模型新增的 2 条 `allowed_hosts`） |
| `pytest -q tests/test_petcore_remote_archive_limits.py tests/test_petcore_install.py tests/test_petcore_installer.py tests/test_petcore_extension_build.py tests/test_petcore_market_install.py tests/test_petcore_market_cli.py` | **62 passed in 8.91s** |
| `ruff check petcore tests scripts` | **All checks passed** |
| `python scripts/build_petcore_extensions.py`（真实构建） | 4 包：`fun.divination` 19169 B、`fun.festival` 41454 B、`reminder.todo` 9655 B、`voice.chime` 17522 B；`excluded unknown=0` |
| `python scripts/verify_petcore_extensions.py --candidate-manifest dist-extensions/candidate-manifest.json` | **verified 4/4，exit 0**（主模型独立复跑，未采信 worker 自述） |
| worker 红证据 | T02：旧实现 18 failed/5 passed；T03：`TypeError: unexpected keyword argument 'limits'` 8 failed/1 passed；T05：`ModuleNotFoundError: scripts.build_petcore_extensions` exit 2 |

**实机未覆盖**：真实 HTTPS / 系统代理 / CDN / GitHub Release 下载（本机无发布源）；解包预算的**市场路径**尚未接线
（`install_package` 仍调 `open_pack` 不带 limits，属 T04）；Windows 原生 GUI 无关（本批不碰 UI）。

## 五、限制与下一步

1. **生产路径尚未切换**：`petcore/market/download.py` 仍走 `HttpFetcher.download → download_to(policy=None)`，
   由 urllib 自动跟随跳转；T02 的逐跳防护只在 `fetch_artifact` 生效。T04 必须把市场安装改为使用 `fetch_artifact`
   并传 `MARKET_ARCHIVE_LIMITS`，否则本次加固等于摆设。
2. **解包预算未接线**：`install_package` 的 `open_pack(...)` 还没传 limits（T03 worker 已在禁止写集内标注）。T04 处理。
3. **多 URL 回退未实现**：`fetch_artifact` 仍只用 `spec.urls[0]`；T04/T06 决定回退顺序与失败聚合。
4. **`install()` 不抛 `BudgetExceeded`**：沿用返回 `(False, msg)` 的旧契约；需要按异常分类时在 `open_pack` 层拦截（T04）。
5. **目录来源不套预算**：`open_pack(dir, limits=...)` 原样返回目录；市场只走 zip，暂不处理，已写入 T04 备注。
6. **构建器边界**：白名单比计划更窄（不收 LICENSE/README）；`build_index` 的仓库/tag 是拟定常量，发布前由 T06 确认。
