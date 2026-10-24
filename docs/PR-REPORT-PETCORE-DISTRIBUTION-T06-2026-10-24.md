# P4-c3-D1 / T06：根候选索引、file: 链路与市场页销毁（2026-10-24）

> 分支 `feat/petcore-vpet-architecture`。前序：T01 契约、T02 传输、T03 解包、T04 授权/事务、T05 构建器。
> 本批交付**待发布的根索引**、离线 `file:` 索引与 artifact 链路、以及设置页销毁时不再销毁运行中的线程。

## 一、核心特性

1. **根候选索引** `extensions-index.json`（仓库根，137 行）：由 T05 的 `build_index(local=False)` 从真实候选清单生成，
   schema 1，四个包全部 `blocked=true`、`blocked_reason="待发布：候选产物尚未公开"`；
   每个版本带真实 `size` 与 64 位 `sha256`，URL 指向计划中的 Release 资产。
   **它现在不可安装**——这是刻意的：公开资产尚未上传，索引只用来固定版本/摘要与验收格式。
2. **离线 `file:` 索引**：`--index-url file:///…/extensions-index.json` 现在可用。读取走
   `net/market.py::fetch_index_file`（`urllib.request.url2pathname` 在 `net/` 内，守住架构红线）。
   显式给 `file:` 时**不回落**到公网源——本地索引就是离线选择，失败应报错而不是偷偷联网。
3. **`file:` artifact**：`fetch_artifact` 遇到 `file:` 直接拷贝（预算按文件大小校验），
   不经过 HTTP 栈；这是 T07 用本地索引验收四个候选包的基础。
4. **市场页销毁**：`MarketPage.dispose()` 不再 disconnect 后就丢引用。运行中的 `QThread` 由模块级
   `_ORPHAN_JOBS` 持有到 `finished`，页面已销毁时迟到结果被 `_disposed` 丢弃；`refresh()` 在销毁后不再启动新线程。
   （此前设置页在索引读取中被关闭，存在「QThread 仍在运行而对象被销毁」的崩溃路径。）

## 二、修改文件说明

| 文件 | 增/删 | 改了什么、为什么 |
|---|---:|---|
| `extensions-index.json`（新增） | +137 / −0 | 待发布根索引：四包 size/sha256、全部 blocked、Release URL；提交它是为了固定摘要与让离线验收有输入。 |
| `petcore/market/model.py` | +1 / −1 | `normalize_index_url` 接受 `file://`（此前只认 http(s)，`--index-url file:` 会被静默丢弃）。 |
| `petcore/market/source.py` | +3 / −0 | `file:` 自定义源不回落公网源；http(s) 自定义源保持「先自定义后默认」。 |
| `petcore/net/market.py` | +22 / −0 | `fetch_index_file()` + `HttpFetcher.fetch_index` 分支；体积上限沿用 8 MiB。 |
| `petcore/net/market_transport.py` | +29 / −1 | `file:` artifact 直接拷贝 + 压缩预算；`TransferReport` 同样返回落盘路径。 |
| `petcore/ui/settings/page_market.py` | +8 / −1 | `_ORPHAN_JOBS` 持有运行中线程；`_finished` 清理；`refresh()` 销毁后短路。 |
| `tests/test_petcore_extension_index.py`（新增） | +123 / −0 | 6 条：索引结构与 blocked、可移植 URL、与四个 `mod.json` 一致、file: 可离线加载、CLI list/拒绝安装、file: 不回落。 |
| `tests/test_petcore_market_ui.py` | +41 / −0 | 1 条：索引读取中被 dispose，线程仍能自行结束、迟到结果不写回页面、孤儿集合清空。 |

## 三、性能分析

- **索引读取**：`file:` 路径是本地读 + 解析，实测 6 条索引测试合计 **0.67 s**（此前误走公网回落的版本要 42 s，
  因为要等两个默认源各 8 s 超时）。这是本次最明显的用户可感知改善：离线/本地索引不再「卡 16 秒」。
- **artifact**：`file:` 走 `shutil.copyfile`（一次顺序读 + 一次写），无 socket、无 TLS；没有新增线程。
- **销毁路径**：多一个模块级 `set` 的加/删，O(jobs)（通常 0–1）。代价是线程对象晚几十到几百毫秒释放，
  换来的是不再销毁运行中的 QThread。
- **稳态**：无新增定时器/轮询；`refresh()` 多一次 `_disposed` 布尔判断。
- 不重测 T00 的 before 基线：本批新增的是 `file:` 与本机路径，无旧同工作量可对照；after 对照仍在 T09。

## 四、实机运行记录

本机 Windows / Python 3.12.10 / pytest 9.1.1，`QT_QPA_PLATFORM=offscreen`：

| 命令 | 实际结果 |
|---|---|
| `pytest -q tests/test_petcore_extension_index.py` | **5 → 6 passed**（加入不回落用例后 6 passed in 0.67 s） |
| `pytest -q tests/test_petcore_extension_index.py tests/test_petcore_market_source.py tests/test_petcore_market_ui.py` | **22 passed in 1.15 s** |
| `pytest -q tests/test_petcore_market_ui.py`（含 dispose 回归） | **7 passed in 0.94 s** |
| `ruff check .` | All checks passed |
| CLI 实测（测试内） | `petcore market --index-url file:///…/extensions-index.json list --json` → 4 包、state=blocked、exit 0；`install reminder.todo --allow-feature` → exit 1，消息含「待发布」，磁盘无 `mods/reminder.todo` |
| 索引解析 | `model.parse_index` 返回 4 包、0 problems；`MarketSource.load(file:)` 非 stale |

未覆盖：真实 GitHub Release 的 `github.com → objects.githubusercontent.com` 跳转（资产未上传）；
Windows 原生设置窗交互（dispose 用例为 offscreen 真实 Qt 线程）。

## 五、限制与下一步

1. **索引不可安装**：四包 `blocked=true`，T07 需要用 T05 的 `local=True` 变体（`file://` artifact）验收装卸回滚；
   公开可用的索引要等 Release 上传后由 D2 生成。
2. **Release 仓库/标签仍是常量**：`RELEASE_REPO` / `RELEASE_TAG`（`MerZlin/dsh-pet-indesktop` / `petcore-extensions-v0.2.0-rc1`）
   来自计划，发布前需 T09 确认；本轮没有创建 tag 或上传资产。
3. **UI 的「大小/摘要」展示**沿用既有实现（详情行已显示 size 与 SHA-256 前 16 位），本批未改版式。
4. **dispose 只解决「不要销毁运行中线程」**：阻塞式索引读取本身仍不可取消（8 s 超时上限），彻底取消要改传输层，未做。
5. 下一步 T07：真 ZIP + `file:` 索引的安装/升级/回滚、数据 SHA 保真、30 轮资源与市场页开关。
