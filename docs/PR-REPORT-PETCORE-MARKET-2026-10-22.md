# petcore 插件市场 v1（索引 + 安装/更新/回滚）

> **基线**：`5451b67`（`feat/petcore-vpet-architecture`）
> **分支**：当前工作树（本地改动，未提交）　**日期**：2026-10-22
> **范围**：31 个文件（新增 19、修改 12）
> **关联**：[`PETCORE-MARKET.md`](PETCORE-MARKET.md)、[`plugin-phase-04-updates/PLUGIN-UPDATE-PROTOCOL.md`](plugin-phase-04-updates/PLUGIN-UPDATE-PROTOCOL.md)

## 一、核心特性

用户可以在设置 →「扩展管理 → 插件市场」浏览静态索引、搜索/分类、查看版本与更新说明，
并完成下载、SHA-256 校验、安装、更新和回滚。市场是 Core 的一部分，不是可被停用的
mod；索引只存元数据，artifact 走 GitHub Release（第一版），下载源在索引里是有序
多 URL 列表。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 静态索引 | `index.json` schema 1；id/kind/version/core/api/平台/能力/认证/阻止/替代/截图 |
| 2 | 多源与缓存 | 官方 raw → GitHub Contents API → 自定义镜像；ETag/304 + 5 分钟内存 TTL + 磁盘缓存 |
| 3 | 下载 | 多 URL 顺序回退、`.part` Range 续传、可取消、大小 + SHA-256 校验 |
| 4 | 安装 | staging → manifest 交叉校验（id/kind/version）→ 备份 → 原子替换 → `market-lock.json` |
| 5 | 更新/回滚 | 版本比较、最近 2 份备份、回滚后把被替换版本反向备份 |
| 6 | 生效语义 | content 与 host-only feature 立即 `reload_mods()`；worker/未知包提示重启 |
| 7 | UI | 扩展管理左导航「插件市场」；搜索、分类、状态标签、离线过期提示、索引源设置 |
| 8 | CLI | `petcore market list/show/install/update/rollback/doctor` |
| 9 | npm 决策 | 只保留 artifact URL 层接口，不引入 Node/npm；理由见 `PETCORE-MARKET.md` §1 |

**红线 / 不变量**：

- feature 包仍受 `allow_feature_mods` 约束，市场安装不自动授信。
- 校验失败、版本不符、被阻止的包绝不替换已安装版本。
- 索引/下载只走 `petcore/net/`；`market/` 不 import 联网库（架构守卫）。
- `market-lock.json` 不是「安装了什么」的真值，真值仍是 `mods/<id>/mod.json`。

## 二、修改文件说明

### 实现（新增）

| 文件 | 行数 | 改动意图 |
|---|---|---|
| `petcore/market/__init__.py` | 3 | 包声明 |
| `petcore/market/model.py` | 513 | 索引数据类、per-package 容错解析、版本排序、平台别名、`package_state()` 七态判定 |
| `petcore/market/source.py` | 237 | 有序索引源、内存 TTL、磁盘缓存与原子写、ETag/304、stale 降级 |
| `petcore/market/errors.py` | 23 | `MarketError` / `IntegrityError` / `ManifestMismatch` / `DownloadError` / `TransferCancelled` |
| `petcore/market/verify.py` | 60 | 文件 SHA-256、大小校验、包内 manifest 与索引交叉校验 |
| `petcore/market/download.py` | 114 | 多 URL 回退、缓存命中、`.part` 保留/删除、完整性失败换源 |
| `petcore/market/install.py` | 445 | 安装编排、硬链接优先备份、原子替换、lock、回滚、重启判定 |
| `petcore/market/cli.py` | 335 | `petcore market` 六个子命令与 `--offline/--index-url/--json` |
| `petcore/net/market.py` | 178 | 唯一 HTTP 实现：索引 GET（含 GitHub Contents API base64）、Range 下载、进度/取消 |
| `petcore/ui/settings/page_market.py` | 536 | 市场页：加载线程、安装/回滚线程、状态标签、索引源保存/丢弃 |

### 实现（修改）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `petcore/mods/install.py` | +7 / −0 | 暴露 `open_pack()`，让市场复用既有解包与 zip-slip 防护，不复制安全逻辑 |
| `petcore/cli.py` | +18 / −0 | 把 `market` 子命令接到 `petcore.market.cli`，转发 `--root/--index-url/--offline` |
| `petcore/config.py` | +2 / −0 | 新增全局键 `market_index_url`（默认空 = 官方源） |
| `petcore/ui/settings/page_extensions.py` | +5 / −0 | 在 `ModsPage` 之后注册 `MarketPage`（同一左导航） |

### 测试（新增）

| 文件 | 行数 | 覆盖 |
|---|---|---|
| `tests/test_petcore_market_model.py` | 241 | 解析/字段容错/latest/yanked/保留 id/未知字段/平台别名/Core 与 API 兼容/七态优先级 |
| `tests/test_petcore_market_source.py` | 187 | 源顺序、自定义源优先、ETag/304、内存 TTL、磁盘缓存、损坏缓存、离线降级 |
| `tests/test_petcore_market_net.py` | 168 | 真实 `http.server`：索引 GET、304、Contents API 解码、404、Range 续传、服务器忽略 Range、取消 |
| `tests/test_petcore_market_install.py` | 291 | 安装、更新、回滚、SHA 失败保留旧版、manifest 版本不符、阻止、feature 闸门、worker 重启、镜像回退 |
| `tests/test_petcore_market_cli.py` | 169 | 真实 localhost HTTP 端到端：list → install → update → rollback、离线缓存、未知包退出码 |
| `tests/test_petcore_market_ui.py` | 210 | 列表/安装/更新/回滚、离线 banner、索引源保存与丢弃、feature 置灰、左导航顺序 |

### 测试（修改）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `tests/test_petcore_extensions_nav.py` | +26 / −16 | 导航契约新增「插件市场」，同步行号、标签门面与折叠/深链索引 |

### 文档

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `docs/PETCORE-MARKET.md` | 新增 207 | 索引契约、npm 结论、来源/缓存、安装流水线、生效语义、CLI、信任边界 |
| `docs/market-index.schema.json` | 新增 76 | 索引 JSON Schema（可复制到独立索引仓库） |
| `docs/INDEX.md` | +2 | 登记市场文档与 PR 报告 |
| `docs/PETCORE-MOD-FORMAT.md` | +8 / −1 | 新增 §6.2 市场安装；§7 在线更新指向市场文档 |
| `docs/PETCORE-ROADMAP.md` | +16 | 新增 §21 市场 v1 状态表 |
| `docs/plugin-phase-04-updates/PLUGIN-UPDATE-PROTOCOL.md` | +2 | 标明 petcore 实现以 `PETCORE-MARKET.md` 为准，本文保留设计历史 |
| `petcore/AGENTS.md` | +3 / −1 | 扩展导航顺序加入「插件市场」；新增市场边界条目 |
| `docs/PETCORE-LOG.md` / `PETCORE-LOG-INDEX.md` | 新增 L033 + 索引行 | 变更记录 |

### 未改动

- `petcore/mods/manifest.py`、`loader.py`：市场复用现有校验与发现，不新增第二套格式。
- `petcore/net/http.py`：继续作为唯一代理/直连兜底，市场只调用它。
- `pet/` 旧壳：本批不改动。

## 三、实现要点

1. **两层容错**：索引级错误（schema 不对、packages 不是列表）整体失败；包级错误只丢
   该包并记诊断。`latest` 指向不存在的版本 → 丢包；版本条目字段不合法 → 保留包但
   不可安装，UI 能解释原因。
2. **下载与校验分离**：`net/market.py` 只负责把字节写到 `.part`；`download.py` 负责
   逐个 URL 重试、校验、缓存命中与删除坏 `.part`；`verify.py` 负责大小/SHA-256 与
   manifest 交叉校验。
3. **备份在安装前**：`mods.install.install()` 成功后会删除自己的 `.trash-*`，所以
   回滚备份必须由市场先做，且用硬链接优先（大角色包避免二次复制）。
4. **回滚不删恢复源**：回滚时先把当前版本放到 staging，装完再放进备份树，避免
   「备份保留 2 份」的清理把正在恢复的源删掉。
5. **UI 不阻塞**：索引与安装各用 `QThread` + 信号；`refresh(blocking=True)` 只给测试
   用。页面在 `showEvent` 首次显示时才发网络请求，构造本身无 IO。
6. **已安装扫描**：每次刷新只扫一遍 `mods/` 的 `mod.json` 取版本，列表重建不再逐包
   读盘（实测 19.9 ms → 0.49 ms / 50 包）。

## 四、性能分析

**方法**：`QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/Scripts/python .scratch/market-bench.py`
（脚本在 `.scratch/`，不进版本库）　环境：Windows 11、Python 3.12.10、PySide6 6.11、本机 SSD。

| 指标 | 实测 | 归属 |
|---|---|---|
| 500 包 × 3 版本索引解析 | 中位 **12.4 ms**，峰值内存 **1.9 MB** | 新增，打开页面/每次刷新一次 |
| 索引冷读（含磁盘缓存写） | 中位 **18.8 ms** | 新增，5 分钟一次或手动刷新 |
| 索引内存命中 | **< 0.1 ms** | 新增，列表/筛选不触发网络 |
| 1 MB artifact 本机下载 | 中位 **31.8 ms**（≈33 MB/s） | 新增，仅安装时 |
| 1 MB SHA-256 | 中位 **1.15 ms** | 新增，仅校验时 |
| 1 MB 安装全流程（解包+复制+摘要+原子替换） | 中位 **31.2 ms** | 新增，仅安装时 |
| 50 包市场页首次刷新 | **8.6 ms** | 新增，打开页面一次 |
| 50 包列表重建 | 中位 **0.49 ms** | 新增，每次筛选/安装后 |

**结论**：

1. **稳态开销**：市场页关闭后没有轮询、没有常驻线程；只有打开页面且首次显示时发
   一次索引请求。下载线程只在安装期间存在。
2. **新增路径成本与触发频率**：索引解析/冷读各最多 5 分钟一次；下载与安装是用户
   动作级；列表重建 0.49 ms/次。
3. **系统调用/网络/磁盘/线程**：新增 1 类网络请求（索引）与按需下载；新增
   `market/` 目录下的缓存/下载/备份写盘；无新增常驻线程；无注册表/服务改动。
4. **内存与缓存**：500 包索引峰值 1.9 MB，磁盘缓存 471 KB（500 包 × 3 版本）；下载
   缓存按包版本保留一个 zip，备份最多 2 份；均位于用户数据目录，可手动清理。

## 五、实机运行记录

**环境**：本机 Windows 11，`.venv` Python 3.13.7；真实 `windows` Qt 平台用于截图，
offscreen 用于测试。

### 1. 真实 localhost 网络端到端（CLI）

```text
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_market_cli.py -q
...                                                                      [100%]
3 passed in 18.48s
```

用例启动真实 `ThreadingHTTPServer` 与真实 `urllib`，完成：`list` 读到 available →
`install` 落盘 → 切换索引到 v2 → `update` → `rollback` 回到 v1；另测 `--offline`
使用磁盘缓存与未知包退出码。

### 2. 真实 Qt 渲染（截图）

```text
env -u QT_QPA_PLATFORM PYTHONPATH=. .venv/Scripts/python .scratch/market-shot.py
E:\Work\dsh-pet-0\.scratch\market-page-real.png
```

真实 `windows` 平台、1000×760（截图为 1500×1140，1.5 倍 DPI）下确认：

- 左导航/页面标题、索引状态行（源地址 + 更新时间）正常；
- 列表能同时显示「未安装」「可更新（已安装 v0.9.0）」「已被阻止」；
- 详情显示 feature、Core 要求、大小、SHA-256 前缀与更新说明；
- feature 在 `allow_feature_mods=True` 时按钮可用；`tests/test_petcore_market_ui.py`
  另有 `False` 时置灰且安装被拒绝的断言；
- 索引源输入框与「恢复官方索引」按钮在页面底部。

截图在 `.scratch/market-page-real.png`（未入库，供人工复核）。

### 3. 门禁与自检

```text
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_market*.py -q
53 passed in 24.90s

QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py tests/test_architecture.py -q
689 passed in 56.23s

.venv/Scripts/ruff check pet/ tests/ petcore/
All checks passed!

.venv/Scripts/python -m petcore --check
（JSON 尾部）"diagnostics": [], "menu_template": "json"
```

### 4. 未验证 / 如实登记

- **全量 pytest**：`9092 passed / 18 skipped / 2 failed`（21m32s）。两条失败均与市场无关：
  `test_chat_subsystem.py::test_append_message_atomic_across_store_instances`（跨实例
  并发，负载相关）与 `test_petcore_p5.py::test_checked_menu_row_paints_a_mark`
  （`test_chat_subsystem` 修改应用 palette 未恢复）。已给后者加 autouse 恢复夹具，
  两文件合跑 `178 passed / 1 skipped`；前者合跑通过，按负载 flake 记录。
- **未对真实 GitHub raw 索引做端到端**：`MerZlin/dsh-pet-extensions` 仓库尚未创建，
  本批只冻结契约与 schema；创建仓库、上传首个 `index.json` 后需要再跑一次真实网络。
  可直接复制的骨架在 `.scratch/dsh-pet-extensions/`（`index.json`、schema、
  `scripts/validate.py`、`validate.yml`、`README.md`）；推送到 GitHub 需要账号授权，
  本批未执行。
- **未走代理/未测国内速度**：本机 localhost 与常规网络；GitHub 直连慢的问题按计划
  留给后续 CDN/镜像，客户端已有多源与自定义索引入口。
- **未做数字签名**：当前信任边界是索引里的 SHA-256 + HTTPS + 仓库控制权；文档与 UI
  均未写成「已签名」。
- **未构建安装包**：本批只改 Python 与文档；`petcore` onedir 未重出，冻结包里的市场
  行为未验证。
- macOS/Linux 未跑；`worker` 类 feature 只验证了「提示重启、不调用 reload」，没有真实
  worker 插件可装。
