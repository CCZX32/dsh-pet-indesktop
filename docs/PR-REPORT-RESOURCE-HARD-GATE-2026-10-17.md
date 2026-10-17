# 资源包内容硬门（逻辑摘要 / 严格清单 / 事务恢复 / 自检 / 任意版本激活）

> 分支：`dlc/mod-center-port`；基线：`8c8dd7b`（阶段 0 收口提交）。
> 范围：`pet/mod_management.py` 及其新增纯逻辑模块；不引入上游
> `pet/content/` 的 `versions/<v>` / `active.json` / `previous.json` 指针树。
> 上游参照：上游 DLC 实现分支（只读、不合并；分支名与基线 SHA 属仓库内工作档案）。

## 一、修改文件说明

### 新增文件（行数为 `wc -l`）

| 文件 | 行数 | 改了什么 / 为什么 |
|---|---:|---|
| `pet/mod_hashing.py` | 130 | 逻辑 SHA-256：目录与 ZIP 同 digest、跳过 `manifest.json`、拒绝符号链接/越界/重复 ZIP 条目。零 Qt，供导入、更新、自检共用。 |
| `pet/mod_manifest.py` | 354 | 资源包严格清单契约：`kind` / `api_version` / `core_requires` / `platforms` / 禁 `entrypoint` / 禁可执行文件 / 派生 cache 必须在包根外 / 角色目录与视频素材 / `integrity.sha256` 对账；结构化 `ManifestIssue(code, message)`。 |
| `pet/mod_transactions.py` | 202 | 目录搬移事务日志：`install` / `activate` / `remove` × 四阶段（`prepared` → `version_removed` → `swapped` → `committed`，删除为 `prepared` → `deleted` → `committed`），原子写与形状校验。 |
| `tests/mod_package_fakes.py` | 63 | 测试夹具：完整资源包清单（避免各测试文件各写一份最小清单）。 |
| `tests/test_mod_hashing.py` | 112 | 目录/ZIP 同 digest、清单跳过、内容变更、符号链接、ZIP 越界/重复、路径安全。 |
| `tests/test_mod_manifest.py` | 228 | 严格契约逐条（id/version/kind/api/core/platform/entrypoint/executable/derived cache/characters/videos/integrity）与宽松手动目录。 |
| `tests/test_mod_transactions.py` | 244 | 日志读写 + 三阶段恢复矩阵（`version_removed` 恢复、`swapped` 补提交/回退、删除重试、歧义态、越界路径）。 |
| `tests/test_mod_management_hard_gates.py` | 185 | 严格导入、同版本同/异 digest、更新保留旧版、自检失败回滚、任意版本激活、保留版本列表。 |

### 修改文件（`git diff --numstat`）

| 文件 | +/− | 改了什么 / 为什么 |
|---|---:|---|
| `pet/mod_management.py` | +322/−37 | `_read_package` 增加 `strict` 与 `digest`；`install` 先严格校验再落盘、同版本摘要幂等/拒绝；`_publish` / `_swap_in` / `remove` 接入事务日志；激活后自检并可回滚；新增 `activate(package_id, version)` 与 `retained_versions`；恢复入口与 staging 清理。 |
| `pet/mod_center_controller.py` | +27/−4 | 增加 `activate` 动作与 `activate_version` / `retained_versions`；更新冲突判据优先读 `content.characters[0]`；**修掉既有缺陷**：`kind=content` 的完整资源清单此前会被误判成异物而拒绝导入。 |
| `pet/mod_center_ui.py` | +13/−0 | 「更多」菜单增加「切换版本」子菜单（列出保留版本）；对没有该能力的测试后端安全降级。 |
| `scripts/ci_shards.py` | +16/−2 | `--include-isolated` 下把两个 CPU 负载敏感的灵动岛像素文件单独成片；CI 串行主套件仍照常包含它们。 |
| `tests/test_architecture.py` | +5/−0 | 三个新纯逻辑模块加入零 Qt 名单。 |
| `tests/test_mod_management.py` | +31/−14 | 夹具改用完整清单；长文本截断测试改为「手动素材宽松 / 导入严格拒绝」两条。 |
| `tests/test_mod_center_controller.py` | +24/−10 | 夹具改用完整清单；新增 `kind=content` 不被路由拒绝的回归。 |
| `tests/test_settings_mod_domain.py` | +2/−8 | 夹具改用共享的完整清单。 |

## 二、性能分析

环境：Windows 11，Python 3.12.10，16 核，`QT_QPA_PLATFORM=offscreen`。
样本与命令（实测输出）：

```text
hash 10MiB: 11.2 ms            # content_sha256(10 MiB 单文件包)
validate 10MiB: 11.8 ms        # validate_resource_package 同上
shallow read shenshen: 9.7 ms  # _read_package(deep=False)，423 MB / 25,530 帧
strict reject shenshen: 0.1 ms # 无 manifest 的 423 MB 树，短路后不再遍历
ResourceMods(no journals): 0.83 ms avg  # 20 次构造取平均
```

- **稳态开销**：MOD 中心每次构造多一次 `mod-staging/transactions` 空目录扫描，实测 0.83 ms（20 次平均）；无日志时只做一次 `glob`，不读文件。
- **新增路径成本与频率**：严格导入/更新对包做两次逻辑摘要（staging 源一次、落位后自检一次），10 MiB 样本每次 11.2 ms；摘要按 1 MiB 分块流式读取，内存不随包大小增长。只发生在用户显式导入/更新/切换版本时，不在列表/启动热路径。
- **列表路径**：`_managed_rows` 仍是浅扫；`_retained_versions` 从深扫改为浅扫（只读顶层与 `videos/`），避免为「切换版本」子菜单重新递归 `frameseq/`。423 MB / 25,530 帧样本浅读 9.7 ms。
- **新的系统调用 / 网络 / 磁盘 / 线程**：新增的是导入时的顺序文件读取（摘要）和事务日志的原子写（每次操作 3–4 个小 JSON）；无新增网络、线程或常驻定时器。
- **内存**：摘要与扫描均为流式/迭代，不缓存整包；新增的 `ManifestIssue` 列表按 code 去重，不会因 25,530 个文件膨胀。

## 三、实机运行记录

```text
$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -p no:randomly \
    tests/test_mod_hashing.py tests/test_mod_manifest.py tests/test_mod_transactions.py \
    tests/test_mod_management_hard_gates.py tests/test_mod_management.py \
    tests/test_mod_center_controller.py tests/test_mod_center_contracts.py \
    tests/test_mod_center_ui.py tests/test_mod_catalog.py tests/test_settings_mod_domain.py \
    tests/test_mod_center_end_to_end.py
223 passed, 2 skipped in 28.07s

$ .venv/Scripts/python.exe -m ruff check pet tests scripts
All checks passed!
```

- **真目录、真事务链**：上述用例在 `tmp_path` 上真实创建/搬移/删除目录，恢复矩阵直接构造四个阶段的落盘状态；不是 mock 存储层。
- **MOD 中心 UI**：`test_mod_center_ui.py` / `test_settings_mod_domain.py` 用真实 `ModernSettingsDialog` 与真实控件树（offscreen）验证，包括「更多 → 切换版本」子菜单的启用条件与动作派发。
- **未做人工桌面验收**：本会话没有可交互桌面，未做「真鼠标点开设置页 → 更多 → 切换版本」的人工记录；机器判据覆盖到真实 Qt 控件与真实 `ResourceMods`，但最终观感仍列为本片未验证项。
- **全量分片门（最终）**：`python scripts/ci_shards.py --include-isolated --jobs 6` → **21/21 分片通过**（6 主分片 + 15 个隔离文件串行；9175 条用例，墙钟 554.0s；本机 16 核 / offscreen）。日志 `.scratch/final-full-shards-5.log`。此前并行满载下的 worker/媒体/像素族假红已按 `LOCAL_LOAD_SENSITIVE` 隔离复跑。

## 四、边界与未做

- 不引入 `active.json` / `previous.json` / `versions/<v>` 版本指针树；启用态仍由目录位置表达。
- 不引入 Starter / bundled 资源包概念；`assets/characters/` 是内置素材，不是可安装包。
- 不引入 `python -m pet.content` CLI；本仓库没有 `pet/content/` 树。
- 冻结态 / Setup 投递 / 官方包装卸 UI 属于阶段 3–4。
- **迁移边界**：严格契约只作用于新导入/更新；已安装的旧包仍可列表、停用、删除。用旧的最小清单保留版本做回滚/切换会被严格校验拒绝——这是有意的 fail-closed，报告在此登记。

## 五、顺带修掉的既有缺陷

`ModCenterController.unsupported_package_message` 在 `declared_kind()` 返回空串（正确资源包）之后，仍把所有非空 `kind` 当成异物拒绝。此前测试夹具省略 `kind`，所以没暴露；文档里的完整资源清单（`kind=content`）会被 MOD 中心拒收。已改为只拒绝 `kind != content`，并加回归用例。
