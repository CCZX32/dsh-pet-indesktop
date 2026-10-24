# P4-c3-D1 / T07：真实候选安装、升级、回滚与资源循环（2026-10-24）

> 分支 `feat/petcore-vpet-architecture`。本批用 T05 的真实 ZIP + `file:` 本地索引，验证
> 「未授权被拒 → 授权安装 → 真实加载 → 合成升级 → 回滚 → 再升级」全链路，并做 30× 装卸与 30× 市场页开关。
> 前序：[T06 根索引与离线链路](PR-REPORT-PETCORE-DISTRIBUTION-T06-2026-10-24.md)、[T04 授权/事务](PR-REPORT-PETCORE-DISTRIBUTION-T04-2026-10-24.md)。

## 一、核心特性

1. **测试内现场构建**：`tests/test_petcore_extension_candidates.py` 用 `build_candidates()` 把四个包真实打成 ZIP，
   再用 `build_index(local=True)` 生成 `file://` 索引。测试不依赖被 gitignore 的 `dist-extensions/`，也不碰网络。
2. **授权门可验证**：同一索引下，不带 `--allow-feature` 安装 feature 包返回 1、消息点名「功能扩展」、
   `mods/` 目录为空；带 flag 才落盘，且四个包都不带 `.trusted`。
3. **真实加载**：每个包装完后用真实 `FeatureManager.load(pack=…, owner=…, entrypoint=…)` 加载，
   diagnostics 为空，再 `stop_owner()` 收尾——不是只检查目录存在。
4. **升级 / 回滚 / 再升级 + 数据保真**：把真实 ZIP 内容改一个版本号合成 `1.1.1`，改写本地索引后 `update` →
   `rollback` → 再 `install`；每步断言 `mods/<id>/mod.json` 版本与
   `feature-data/<id>/todo-slot-0-v2.json` 的 SHA-256 **完全不变**。
5. **资源循环**（scratch 探针，`t07/resource_loop.py`）：30× 卸载/重装 + 30× 市场页「构造→阻塞刷新→dispose」，
   记录 RSS、线程、存活 QWidget、staging/`.part` 残留。

## 二、修改文件说明

| 文件 | 增/删 | 改了什么、为什么 |
|---|---:|---|
| `tests/test_petcore_extension_candidates.py`（新增） | +201 / −0 | 5 条端到端：本地索引可装、未授权被拒且零落盘、四包 ZIP 安装 + 无 `.trusted` + 真实 FeatureManager 加载、升级/回滚/再升级且用户数据 SHA 不变、`doctor` 与 lock 一致。 |
| `.scratch/…/t07/resource_loop.py`（未入库） | — | 60 次循环的资源探针；修正了「不刷新 DeferredDelete 就误判 widget 泄漏」的自身缺陷。 |

产品代码零改动——本批是验收批次，没有发现需要修的产品缺陷。

## 三、性能分析

**端到端测试**：5 条用例合计 **3.20 s**（含一次四包构建，构建本身约 1 s；本地 `file:` 索引读取 <10 ms）。

**资源循环（本机，`resource_loop.json`）**：

| 阶段 | RSS | Python 线程 | 存活 QWidget | staging / `.part` |
|---|---:|---:|---:|---|
| start（四包已装） | 70,651,904 | 4 | 0 | 0 / 0 |
| install 循环 0→25 | 71,905,280 → 72,286,208 | 4 | 0 | 0 / 0 |
| page 循环 0 | 76,726,272 | 4 | 0 | 0 / 0 |
| page 循环 25 | 81,399,808 | 4 | 0 | 0 / 0 |
| end（60 循环后） | 81,752,064 | 4 | 0 | 0 / 0 |

- 30 次装卸 RSS 只涨 **+1.63 MB** 且逐段收敛（72.23 → 72.29 MB），线程恒定 4（无新增 worker）。
- 30 次市场页开关 RSS 涨 **+9.68 MB**，但每 5 轮增量从 14.5 MB 递减到 1.2 MB；同时**存活 QWidget 恒 0**、
  staging/`.part` 恒 0。这是 Qt/分配器缓存型的非单调增长，不是逐轮线性泄漏；有限样本不承诺长期零增长。
- 60 次循环总耗时 **2.54 s**（含一次构建），单次安装约 30–40 ms、单次页面构造+阻塞刷新约 15 ms。

## 四、实机运行记录

| 命令 | 实际结果 |
|---|---|
| `pytest -q tests/test_petcore_extension_candidates.py` | **5 passed in 3.20 s** |
| `.venv/Scripts/python.exe .scratch/petcore-p4c3-distribution/t07/resource_loop.py` | **2.54 s**；`rss_delta=11,100,160`、`threads_delta=0`、`staging=0`、`partials=0`；逐轮数字见上表 |
| 未授权安装（用例内） | exit 1、消息含「功能扩展」、`mods/` 不存在或为空 |
| 四包安装（用例内） | 四个 `mods/<id>/mod.json` + 无 `.trusted`；`FeatureManager.load` 返回 `[]` |
| 升级/回滚（用例内） | `1.1.0 → 1.1.1 → rollback → 1.1.0 → 1.1.1`，`todo-slot-0-v2.json` SHA 三次一致 |
| `doctor`（用例内，带 `--index-url`） | exit 0，输出含已安装包，`market-lock.json` 有对应记录 |

**探针自身修正留痕**：第一版 `resource_loop.py` 只用 `processEvents()` 就统计 QWidget，得到「每页泄漏 69 个」
的假阳性；补 `QCoreApplication.sendPostedEvents(None, DeferredDelete)` 后归零。这条也解释了为什么第一版
市场页 probe 的 RSS 曲线偏陡——不是产品问题。

未覆盖：Windows 原生设置窗手工点击、真实 GitHub Release 下载（资产未上传）、真实 TTS/通知物理点击、
双屏/混合 DPI、非 Windows。

## 五、限制与下一步

1. **公开链路仍未验**：本轮全程 `file:`；HTTPS 逐跳、CDN 跳转、断流续传的真实网络证据要等资产上传后的
   D2（T09 会要求真实逐跳验收）。
2. **升级是合成的**：用同一份源码改版本号，验证的是事务与数据保真，不是「旧版本→新版本」的兼容性矩阵；
   真正的旧版本升级要拿已发布产物，属 D2。
3. **`doctor` 不带 `--index-url` 时会回落默认源**：这是既有语义（CLI 显式源才覆盖），在离线环境下会等超时并报 stale；
   本批没有改它，只在用例里显式传参。是否要把「doctor 只在显式源下检查」写进 CLI 说明，留待 T09 决定。
4. **D1 收口**：T00–T07 全部完成；下一步 D2 = T08（Windows 冻结包 + 签名/SAC 决策）与 T09（性能对照、整仓门禁、发布准备）。
