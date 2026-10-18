# Phase 5B：Setup 回执消费 + AI/文件理解交付闭环（2026-10-18）

> 基线：`dlc/mod-center-port`，5A Setup + 便携切片完成后（`4941cac`）。
> 本轮按 5B 计划推进前四片：5B-1 启动回执消费、5B-2 AI 包生命周期、5B-3 文件理解
> 包侧闭环、5B-4 其余官方领域交付矩阵。签名仍按 2026-10-18 决定不做。

## 0. 结论

- Setup 勾选官方包后**首次启动自动安装并启用**：`pet/startup_receipt.py` 读 `{app}\startup-receipt.json`，
  按盘上 `features/<pkg>/manifest.json` 核对，对没有 active 版本的 owner 调一次
  `LocalFeatureRuntime.install_official(enabled=True)`，然后删除回执；单包失败不阻塞启动。
- 冻结实测发现并修掉一个真实交付阻塞：PyInstaller 漏收 `pet.mod_api`，导致
  `--feature-package-probe` 对所有官方包统一 `import_failed`，Setup 回执/MOD 中心
  安装全被拒。已加 hidden-import，并在构建脚本里加了**用构建产物 exe 跑真实 probe** 的门。
- AI 包生命周期补了「无包无入口」与「卸载后重装保留偏好」两条验收；
  文件理解补了「卸载时当场摘掉包路由」「停用后不创建解读器」两条验收。
- 5B-4 交付矩阵已落 `docs/PLUGIN-DOMAIN-DELIVERY-MATRIX-2026-10-18.md`。

## 1. 修改文件说明

新增：

| 文件 | 行数 | 改了什么 + 为什么 |
|---|---|---|
| `pet/startup_receipt.py` | 215 | 回执读取/校验/一次性消费：schema 严格、只认布尔字段、按盘上 manifest 核对、逐 owner 安装与失败隔离、始终删除回执、`QTimer` 延后执行。 |
| `tests/test_startup_receipt.py` | 204 | 缺回执/坏回执/false/true/缺包/已 active/单包失败/未知键/显式 features 目录/`QTimer` 接线/AppShell 接线判据。 |
| `scripts/verify_frozen_mod_api.py` | 112 | 构建门：用源码验签策略生成真实 probe 作业，交给**构建产物 exe** 逐包跑，要求 `ok=true`；失败退出 1。 |
| `tests/test_bundle_official_probe.py` | 42 | 锁 hidden-import 与构建期 frozen probe 接线、验证器退出码契约。 |
| `docs/PLUGIN-DOMAIN-DELIVERY-MATRIX-2026-10-18.md` | 48 | 12 行领域矩阵：现状证据、可拆性、能力/数据边界、建议批次；明确 5B 本轮范围。 |

修改：

| 文件 | +/− | 改了什么 + 为什么 |
|---|---|---|
| `pet/app.py` | +10 | AppShell 构造出功能宿主后 `schedule_consume` 一次（延后 1.5 s）；失败只记日志，不阻塞启动。 |
| `pet/feature_management.py` | +7/−2 | `install_official(enabled=False)`：默认保持 MOD 中心「装成停用」；Setup 回执传 `enabled=True`，用 `install` 事务一次完成安装+启用（勾选即启用意图）。 |
| `pet/feature_package_preflight.py` | +4/−1 | `DSH_PET_PROBE_DEBUG=1` 时把导入失败原因写 stderr（不进回执/上游），用于定位冻结包导入问题。 |
| `tests/test_ai_package_e2e.py` | +56 | 无包状态（无 entry/无菜单/无挂载）与卸载后重装保留 `preferences.json`。 |
| `tests/test_ai_package_host.py` | +43 | 卸载时当场清掉包路由并回落内置；停用后 `file_interpret_offer` 不创建解读器。 |
| `scripts/build_onedir.ps1` | +13/−1 | hidden-import `pet.mod_api` / `pet.mod_api.v1`；复制 features 后用构建产物跑 `verify_frozen_mod_api.py`。 |
| `docs/INDEX.md` | +2 | 登记 5B-4 矩阵文档与本文。 |
| `docs/DLC-HANDOFF-2026-10-15.md` | +1 | §6.2 增加 5B 交付条目与冻结 probe 阻塞的修复记录。 |
| `docs/modding/PORT-STATUS.md` | +2/−2 | Phase 5B 行补 5B-1..5B-4 状态、证据落点与新测试。 |

## 2. 性能分析

环境：Windows，Python 3.12（`.venv`），同机 `timeit`。

| 场景 | 实测 | 说明 |
|---|---|---|
| 无回执时 `consume()` | **13.4 µs/call**（5000 次） | 只做一次 `is_file()`；每进程一次 |
| 回执消费 | 一次 `QTimer.singleShot(1500ms)` + 2 次包安装提交 | 首次启动一次；之后没有回执文件即早退 |
| 冻结 probe 门（两个官方包） | **约 1.1 s** | 构建期一次，不是运行期成本 |

- 稳态开销：启动后没有回执就是 13.4 µs 的一次检查，相对配置读写可忽略。
- 新增系统调用/磁盘/线程/网络：只在有回执时读一个 JSON、删一个文件；安装走既有
  事务链（原本就会起后台线程）。**没有新线程、没有网络**。
- 内存：新模块只 import 标准库与 `official_features`；无第三方依赖、无模块级大对象。
- 包体：hidden-import `pet.mod_api`（两个小模块）对产物体积无可见影响；
  `verify_frozen_mod_api.py` 只在构建机跑。

## 3. 实机运行记录

### 3.1 冻结 probe 失败 → 修复

安装包（5B 代码）安装两个官方包后启动，回执被消费但安装被拒。probe 作业实测：

```text
== official.ai-chat exit 78
stderr: feature package probe import failed: PackageVerificationError:
        official host import failed: No module named 'pet.mod_api'
== official.screen-understanding exit 78
stderr: ... No module named 'pet.mod_api'
```

根因：`pet.mod_api` 只被包 host 导入，Core 没有静态引用，PyInstaller 未收。
修复：`build_onedir.ps1` 增加 `--hidden-import pet.mod_api` / `pet.mod_api.v1`；
构建期新增 `verify_frozen_mod_api.py` 门（用构建产物 exe 逐包 probe）。修复后
构建日志：

```text
[features] probing bundled packages through the frozen exe...
[frozen-probe] ai-chat (official.ai-chat): ok — ok
[frozen-probe] screen-understanding (official.screen-understanding): ok — ok
[frozen-probe] 2 package(s) passed
```

修复后，最终 Setup + 冻结 onedir 实测（`/TASKS=official_ai_chat,official_screen`，
隔离 APPDATA，offscreen 启动）：

```text
receipt before launch: True
process exited early: False
receipt after launch: False
ai versions dir: True     ai version: 1.0.0
screen versions dir: True screen version: 1.0.0
state official.ai-chat: {"active":"1.0.0","enabled":true,...,"pending_transaction":null,...}
state official.screen-understanding: {"active":"1.0.0","enabled":true,...,"pending_transaction":null,...}
uninstall exit=0 dir_exists=False
```

即：勾选安装 → 首启自动安装并**启用**两个官方包 → 回执删除 → 卸载清空目录。
日志（`.scratch/receipt-gate-5.log`）与 AppData 里的 `state.json` 一致。

### 3.2 自动化门

```text
ruff check pet tests scripts → All checks passed
pytest tests/test_startup_receipt.py tests/test_ai_package_host.py \
       tests/test_ai_package_e2e.py tests/test_file_interpret_router.py \
       tests/test_bundle_official_probe.py
→ 65 passed
```

全量分片门：`python scripts/ci_shards.py --include-isolated --jobs 4` →
**4 个主分片 + 15 个隔离分片全部通过，墙钟 1153.8 s**（主套件 435 文件 /
8991 用例；日志 `.scratch/final-full-shards-5b3.log`）。

6 路并发的一轮曾出现 `tests/test_decode_fanout_integration.py::test_two_clips_share_single_decode`
的 `feed 超时`（1900 ms 预算）以及一个"所有用例都通过但分片被判失败"的 runner 异常；
降到 4 路后全绿。这两条按已知负载敏感族记录，不计为本次产品缺陷。

## 4. 边界与未验证

- **回执语义**：只处理 `ai_chat` / `screen` 两个已知键；未知键忽略（前向兼容）。
  回执始终删除，安装失败不会在下次启动自动重试（MOD 中心仍有「安装」行）。
- **UI**：没有新增弹窗；用户可见结果是 MOD 中心/菜单里包变为可用。
- **冻结 GUI 人工观感**：仍用 offscreen 启动验证状态落盘，没有人工点击菜单。
- **签名**：本轮仍不做；没有 Authenticode/Ed25519 产物。
- **Setup 反选卸载**：沿用 5A 结论，升级保留上一版装下的包；卸载走应用内。
