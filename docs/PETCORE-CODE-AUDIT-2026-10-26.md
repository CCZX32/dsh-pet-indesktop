# petcore 代码审计报告（2026-10-26）

> **基线**：分支 `feat/petcore-vpet-architecture`，代码提交 `1c1507f1` + 工作区未提交的 P5 修复 / P6 迁移与探针改动（27 改 + 14 新增）。
> **性质**：只读审计。本报告**不包含任何代码改动**，目的是把问题定位到行、给出复现方式与验收标准。
> **门禁基线（审计开始时实测）**：`ruff check petcore tests scripts` → `All checks passed!`；`pytest tests/test_petcore_*.py` → **1613 passed in 204.70s**。
> 也就是说：下面所有缺陷**都在全绿的套件下存活**。

---

## 一、审计方法与验收标准

按「写码前先看先查、写完必须审查、产物要有验收标准」执行，分五步：

| 步骤 | 做法 | 产出 |
|---|---|---|
| 1. 读规矩 | 通读 `petcore/AGENTS.md`（429 行红线）、`docs/PETCORE-MOD-FORMAT.md`、`docs/PETCORE-MARKET.md`、`docs/PETCORE-ARCHITECTURE.md` §19 | 每条发现必须能对应到「哪条红线被违反」或「哪条文档承诺没兑现」 |
| 2. 分域深读 | 9 个方向并行读码：分层/主窗口线程/岛与探针/设置与菜单/mod 与市场/网络与 API 与账户/更新与迁移/配置路径 CLI/测试与打包/素材媒体语音 | 各域原始发现 |
| 3. 独立复现 | 对每条 P0/P1 写最小实验（临时目录、`QT_QPA_PLATFORM=offscreen`、localhost 服务端），**不接受「看代码觉得会」** | 真实命令输出 |
| 4. 红队证伪 | 另开两个独立 agent 专挑假阳性，要求逐条给 `CONFIRMED / 降级 / FALSE POSITIVE / UNVERIFIABLE`，且必须有自己的实验输出 | 纠掉 1 条误判、降级 6 条、修正 4 处数字/机制描述 |
| 5. 交叉校验 | 把红队结论与我的复现对齐，冲突处以实验为准 | 本报告的最终分级 |

**每条发现的验收标准统一为三问**：
1. 位置能不能精确到 `path:line`（不能只写文件名）；
2. 触发路径是不是真实用户操作（不是「理论上可以」）；
3. 修复后用什么命令、什么现象证明它真的好了（写在条目末尾的「验收」）。

**严重度定义**：

| 级别 | 含义 |
|---|---|
| **P0** | 安全/授权绕过，或不可逆的用户数据破坏 |
| **P1** | 真实功能错误（用户会稳定遇到，或导致数据不可用/静默丢失） |
| **P2** | 特定条件才触发，或破坏契约但不丢数据 |
| **P3** | 画质/性能/可维护性问题 |

---

## 二、发现总表

共 **28 条**（P0 ×1、P1 ×9、P2 ×12、P3 ×6）。「证据」列标注证据强度：`实测`＝我或红队跑出真实输出；`结构`＝只做了代码行级确认，触发条件需要特定环境。

### A. 安全与授权

| 编号 | 严重度 | 问题 | 位置 | 证据 |
|---|---|---|---|---|
| AUD-01 | **P0** | 本地导入的 ZIP 自带空文件 `.trusted` 即被授信，绕过 `allow_feature_mods` 执行任意 Python | `petcore/mods/install.py:73-109`、`petcore/mods/loader.py:150-160`、`petcore/mods/trust.py:22-26` | 实测 |
| AUD-02 | P1 | 更新 `install()` 的信任锚是自证侧车（同目录可写），从不回查 manifest 的 sha256 | `petcore/update/service.py:369-393`、`:412-437` | 实测（红队） |
| AUD-03 | P2 | `fetch_url`/`HttpPort` 无 scheme 与内网地址校验，`file://` 可读本地文件；模型可被诱导读 loopback | `petcore/net/websearch.py:375-396`、`petcore/ui/ports.py:579-596` | 实测（域审计） |
| AUD-04 | P2 | 跨源 302 会把 `Authorization`/`X-Api-Key` 原样转给新主机（TTS/对话都受影响） | `petcore/net/http.py:120-139` | 实测（域审计） |
| AUD-05 | P2 | ZIP 解包未处理 NTFS 备用数据流（`a.py:evil`）、大小写冲突、Windows 保留名 | `petcore/mods/install.py:135-171`、`petcore/mods/manifest.py:61` | 实测（域审计） |

### B. 数据完整性（迁移 / 配置）

| 编号 | 严重度 | 问题 | 位置 | 证据 |
|---|---|---|---|---|
| AUD-06 | **P1** | `rollback()` 无条件覆盖目标、失败也删标记；多域共享一个 `config.json` 时留下**半迁移态**；`not_found` 不计失败 → 退出码 0 | `petcore/migration/__init__.py:323-345`、`:362-365` | 实测（红队，三场景） |
| AUD-07 | **P1** | `Config` 从 `DEFAULTS` 重建，**丢弃所有未登记键**：第三方 mod 的 `host.config.set("my.key")` 当场消失、不落盘；手写进 `config.json` 的未知键重启即丢 | `petcore/config.py:840-843`、`:1282-1287`、`:1349-1350` | 实测（我 + 红队） |
| AUD-08 | **P1** | 旧配置 159 个出厂键里 **41 个同名可无损搬却没搬**（`weather_city`、`todo_reminder_lead_minutes`、`voice_chime_voice`、`hotkey_open_chat`、`music_*`、`festival_*`、`island_metrics` 等），config 域还**不记 `dropped`**（sessions/api 域都记） | `petcore/config.py:359-427`、`migration/config_data.py:49-101` | 实测（红队） |
| AUD-09 | P2 | 域级 `completed` 只要有一条 `migrated` 就封存整域，同批的 `failed_write` 不再重试，第二轮报 `already_migrated` | `petcore/migration/__init__.py:297-299` | 实测（红队，`--force` 可救） |
| AUD-10 | P2 | 迁移写给待办的 `todo-slot-0-legacy-v1.json` 是 dict 文档，扩展期望 `list[str]` → v2 缺失时待办功能不可用 | `petcore/migration/todos.py:321` vs `examples/petcore-mods/reminder.todo/host/store.py:32-48` | 实测（红队） |
| AUD-11 | P2 | `--check` 不是只读：有旧壳数据时写 `config.json` + `migration-backup/` + 日志，且这次写入**绕过 `migration.json` 标记**（判据是「目标文件不存在」，正是 AGENTS 禁止的写法） | `petcore/cli.py:443-459`、`petcore/config.py:661-710` | 实测（我 + 红队） |
| AUD-12 | P2 | `config.json` 损坏（截断）时只记一条无人读取的 `skipped_invalid`，随后启动路径把整份 `DEFAULTS` 写回同一路径，**无备份** | `petcore/config.py:661-673`、`petcore/ui/pet_window.py:684`、`petcore/ui/pet_manager.py:219` | 结构 + 实测（域审计） |

### C. 运行时正确性（网络 / 语音 / 会话）

| 编号 | 严重度 | 问题 | 位置 | 证据 |
|---|---|---|---|---|
| AUD-13 | **P1** | `urlopen` 的「代理失败→直连」兜底是**空转**：第二次尝试复用已被 `ProxyHandler` 改写的同一个 `Request`（`host` 已变成代理地址），于是「直连」再拨一次代理 | `petcore/net/http.py:99-117`（对照 `:174` 的 `fetch_url` 每轮重建） | 实测（我） |
| AUD-14 | **P1** | 「重新加载扩展」/市场覆盖安装后仍执行**旧代码**：`reload_mods()` 不清 `sys.modules` 里的 mod 子模块（`host/runtime.py`），界面却提示「已重新加载」 | `petcore/ui/app.py:968-981`、`petcore/mods/feature.py:104-126`（`_drop_modules_under` 只在卸载路径用） | 实测（我） |
| AUD-15 | P1 | SSE 断流/半截响应被当成「回答完成」：没有 `[DONE]` 也返回 `ChatResult`，半条回答落进会话；`data: {"error":…}` 被静默吞成空回答 | `petcore/api/chat.py:516-537`、`:595-600`、`petcore/ui/chat/controller.py:412-436` | 实测（域审计，裸 socket 服务端） |
| AUD-16 | P2 | 响应体截断无任何信号（`Content-Length` 不符、`max_bytes` 截断都不报），TTS 会把半截 mp3 原子写进缓存 | `petcore/net/http.py:207-226`、`petcore/net/tts.py:284-291` | 实测（域审计） |
| AUD-17 | P2 | 错误分类缺口：TLS 证书错误归为「网络不可达」，`IncompleteRead`/`BadStatusLine` 返回 `None`（裸异常外溢） | `petcore/net/errors.py:108-120`、`petcore/api/chat.py:552-556` | 实测（域审计） |
| AUD-18 | P2 | 换路由**不看 `Retry-After`**：`500 + Retry-After` 仍然切代理，与 AGENTS 明文相反（主分支参考实现是显式禁止） | `petcore/net/http.py:180-186` | 实测（域审计，localhost 假代理） |
| AUD-19 | P2 | `BalancePresenter` 单飞失效：`cancel()` 已把 future 摘出 `_inflight`，`_done()` 又无条件 `pop`，同一 slot 实测并发 2 次 | `petcore/account/presenter.py:78-111` | 实测（域审计） |
| AUD-20 | P2 | TTS 兜底音色的产物写进**请求音色**的缓存键：第二次命中会拿默认音色的音频、谎报用户选的音色 | `petcore/speech/service.py:158-161` | 实测（域审计） |
| AUD-21 | P2 | `FeatureManager.load()` 只 `except Exception`，mod 里 `sys.exit()` 会让整个 core 以退出码 3 死掉、无任何诊断 | `petcore/mods/feature.py:152-168`、`petcore/ui/app.py:447-474` | 实测（红队，端到端） |
| AUD-22 | P2 | 卸载/重载不撤 `interaction` 订阅：`stop_owner()` 只撤 speech/reminders，旧的点击/投喂包装器仍挂在窗口上，一次点击触发两个 runtime | `petcore/mods/feature.py:299-311`、`petcore/ui/ports.py:459-465`（`cancel_owner` 全仓无调用者） | 实测（红队） |
| AUD-23 | P2 | 联网检索没有整次预算：最坏 3×timeout + 12×20s ≈ 7 分钟；取消只在轮/调用之间生效 | `petcore/api/chat.py:26-28`、`:363-427` | 结构 + 实测（域审计） |
| AUD-24 | P2 | 取消不打断阻塞读：服务端静默时线程卡在 `readline()` 直到 socket 超时，用户拿到「连接超时」而不是「已停止」 | `petcore/api/chat.py:516-556` | 实测（域审计，5.05s） |

### D. UI / 设置 / 灵动岛

| 编号 | 严重度 | 问题 | 位置 | 证据 |
|---|---|---|---|---|
| AUD-25 | **P1** | 灵动岛展开卡片 → GPU/FPS 每秒一次「停采→清快照→再起」振荡，且卡片把这两段报成「当前环境未接入可用 GPU/FPS 探针」+ crit | `petcore/ui/island.py:777-790`、`:370-404`、`:815-836`、`petcore/ui/probes.py:118-155` | 实测（红队：5s 内 start 7–12 次） |
| AUD-26 | **P1** | 设置里最小窗口 720×500 下，API 页右半列整段被裁、横向滚动条被强制关闭 → 「保存服务」鼠标够不到，Tab 聚焦也不滚进来 | `petcore/ui/settings/base.py:152`、`petcore/ui/settings/page_api.py:126-228` | 实测（红队几何） |
| AUD-27 | P2 | 设置页「整组回写」：互动页一次写 35 个键、用打开时定格的控件值，覆盖菜单里刚改的键并落盘（实测 `golden_spin_on_click` 被翻回 False） | `petcore/ui/settings/page_interaction.py:862-887`（`_current()` 只读控件，无 `showEvent` 重同步） | 实测（红队） |
| AUD-28 | P2 | 菜单编排提前落盘：`MenuEditor.confirm_save()` 自己 `config.save()`，排在 API 页之前，所以「API 校验失败 → 点取消」之后磁盘仍是新菜单；且 `is_dirty()` **恒为 True**，不碰菜单也会写盘 + `reload_menu()` | `petcore/ui/settings/menu_editor.py:127-144`、`petcore/ui/settings/dialog.py:368-436` | 实测（红队，disk before/after） |
| AUD-29 | P2 | 设置搜索只覆盖「标题 + label 文案」快照：按钮文字（「生成子宠」「保存服务」）、下拉选项、列表项搜不到；动态改写的文案不重新入索引 | `petcore/ui/settings/dialog.py:236`、`:265-275`、`petcore/ui/settings/base.py:349` | 实测（我 + 域审计） |
| AUD-30 | P2 | 覆盖表 4 条落点写错页/不存在，而守卫测试只断言「字符串非空」，抓不到漂移 | `petcore/ui/settings/coverage.py:16/30`、`tests/test_petcore_settings_coverage.py:58` | 实测（域审计） |
| AUD-31 | P2 | 探针启停是「边沿触发」：`FpsProbe.start()` 被拒后不重试（返回值被丢弃），在下一次 wanted 变化前保持死亡 | `petcore/ui/probes.py:135-150`、`petcore/platform/fps.py:1514-1550` | 实测（红队，6s 内 0 次重试） |
| AUD-32 | P3 | 聊天壁纸不按 DPR 缩放（150% 屏上 1029×686 铺到 1544×1029 设备像素，**发虚**但几何不变） | `petcore/ui/chat/window.py:347-383`、`petcore/ui/chat/themes.py:175-190` | 实测（红队，1.0 vs 1.5 对照） |
| AUD-33 | P3 | 冷 meta 的 webm clip 让 `frames_per_loop=1`：未声明 `move_curves` 的角色首帧即到终点（看起来像瞬移）；位移只由帧回调推进、无看门狗 | `petcore/ui/pet_window.py:569-607`、`petcore/media/clip.py:55` | 实测（域审计） |
| AUD-34 | P3 | Q弹 + 旋转同时激活时 `is_transparent_at` 与 `paintEvent` 不互逆（实测 12.8–19.9px 偏差、45/231 采样点判为透明） | `petcore/ui/pet_window.py:903-934` | 实测（域审计） |
| AUD-35 | P3 | `media/images.load_pixmap` 先整图解码再缩小：12MP 图 92.4ms（`setScaledSize` 只要 9.3ms）；缩略图 PNG 编码/落盘在 GUI 线程 | `petcore/media/images.py:91`、`petcore/media/thumbnails.py:253/312` | 实测（域审计） |

### E. 工程守卫 / 构建 / 测试

| 编号 | 严重度 | 问题 | 位置 | 证据 |
|---|---|---|---|---|
| AUD-36 | P2 | 架构守卫 `_imports()` **丢弃全部相对 import**（446 条），`test_engine_never_imports_ui` 的输入集恒为空，永远绿 | `tests/test_petcore_architecture.py:20` | 实测（我 + 红队） |
| AUD-37 | P1 | 打包 `-OutputRoot` 用**进程 CWD** 解析相对路径（`Set-Location` 不改它），且尾部反斜杠可绕过「拒绝仓库根」守卫 | `scripts/build_petcore.ps1:23/30/32` | 实测（红队 pwsh） |
| AUD-38 | P1 | 构建冒烟只验退出码：`--check` 恒返回 0，`check.json` 写出来**没人读**，所以「菜单模板没进包 / 配图缺失 / 角色未打包」都能构建成功 | `petcore/cli.py:225`、`scripts/build_petcore.ps1:158-163` | 结构 + 实测 |
| AUD-39 | P2 | 安装器/打包测试全部是「.iss/.ps1 字符串存在性」，12 个用例零执行；漏写一个 `Tasks:` 就是「不勾选也写盘」而测试不会红 | `tests/test_petcore_installer.py:16-73`、`tests/test_petcore_candidate_packaging.py:18-67` | 实测（红队） |
| AUD-40 | P2 | `verify_presentmon` 放在 PyInstaller **之后**，与它自己 docstring 的「必须在起跑之前挡住」相反，缺件要白跑一次完整打包 | `scripts/build_petcore.ps1:129-147`、`scripts/verify_presentmon.py:9-10` | 结构 |
| AUD-41 | P3 | 19 个模块零测试触达，其中 `ui/settings/pages_core.py`（1054 行）与 `contracts/capabilities.py` 最刺眼（AGENTS 明文要求新能力必须登记该文件，却无人读它） | 见 §七 | 实测（静态引用分析） |
| AUD-42 | P3 | `paths`：portable 根落在 `_internal`（升级即丢）、`--root ""` 变当前目录、缩略图磁盘缓存写 `%TEMP%` 共享目录且只写不删（不受 `--instance` 约束） | `petcore/paths.py:72-76`、`petcore/media/thumbnails.py:33/171-179` | 结构 + 实测（域审计） |

---

## 三、P0 与 P1 详述

### AUD-01（P0）本地 ZIP 自带的 `.trusted` 就是授权凭证

**位置**：`petcore/mods/install.py:73-109`（`_copy_pack` 原样复制）、`petcore/mods/loader.py:150-160`、`petcore/mods/trust.py:22-26`（`is_file()` 即授信）、`petcore/ui/app.py:468`（`features.load`）。

**现象**：`install()` 不剔除包内 `.trusted`；loader 的授权判断是 `if not ((allow_feature_mods or trusted) and in_user_mods)`。于是「导入 ZIP」这个普通操作就可以让一段 Python 在用户进程里执行，而 `allow_feature_mods` 默认是 `False`。

**我本人的复现**：

```text
A) kind=feature + entrypoint + 包内 .trusted
    install=True  load_mods(allow_feature_mods=False) -> [('evil.feature', True)]   diagnostics=()
B) 同上但不带 .trusted（对照组）
    install=True  load_mods(allow_feature_mods=False) -> [('evil.feature', False)]  diagnostics=('feature mods disabled',)
```

红队补充的三点让这条更严重：

1. **代码在 `install()` 的同一个会话里就执行了**：`page_mods._install` → `host.reload_mods()` → `features.load()` → `exec_module`。用户唯一的动作是在文件对话框里选了一个 zip，**没有任何确认框**。
2. **市场通道是干净的**（`market/install.py:185` 会剥标记，且全仓没有调用方传 `BUNDLED`），所以这是「本地导入路径独有的缺口」——不是设计上的两套语义。
3. **列表还会把它标成「随安装包」**（`page_mods.py:198-211`），正好把手工导入的包伪装成安装器投放的官方包。

**为什么是 P0**：这是唯一一条「用户以为在装素材、实际在跑代码」的路径，且绕过了项目自己设定的授权闸门。

**修法（两条选一，代价都很小）**：
- `mods/install.py` 落盘前剥掉 `<pack>/.trusted`（与 market 对齐，约 2 行 + 1 个用例）；
- 更彻底：`trust.is_trusted()` 只认 `paths.install_mods_dir()` 下的标记，即「只有安装器投放的位置才算授信」，`root/mods/` 里任何自我声明的标记都不算。这同时把 AUD-02 的利用面砍掉一半。

**验收**：
```bash
# 造带 .trusted 的 feature 包 → install → load_mods(allow_feature_mods=False)
# 期望：[('evil.feature', False)] 且 diagnostics 非空；不带标记的对照组行为不变
QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/test_petcore_mods_import.py -q
```

---

### AUD-06（P1）`rollback()` 不是回滚：覆盖用户改动、留半迁移态、失败也删标记

**位置**：`petcore/migration/__init__.py:323-345`（`backup==""` → `unlink`；否则 `shutil.copy2` 无条件覆盖）、`:362-365`（无条件删标记）。

**红队实测的三个场景**：

```text
(i) 迁移 → 用户改 scale=2.5、加自定义键 → rollback
    rollback 后 scale: 1.0 | 用户自定义键还在: False
    config.json 最终内容 == 迁移前原文件? False     ← 比原描述更糟：是半迁移态
    仍含迁移进来的键: ['always_on_top','self_talk_enabled','todo_items','screen_name']

(ii) 目标原本不存在的域（会话/待办）→ 用户又写了新数据 → rollback
    rollback 后会话目录: ['new1.json','new2.json']   ← 用户新写的文件没被删
    迁移写入的 s1.json 被删且无副本                        ← 这部分符合预期

(iii) 删掉一个备份文件 → 部分失败 → 看标记
    active_pets  not_found
    rollback 后标记仍存在: False | 失败条目数: 0 | CLI exit code: 0
```

**比我最初判断更糟的两点**（原报告没有，红队发现）：
- `config.json` 有三条 restore 记录（config → slots → active_pets），按序覆盖同一个文件，最终落盘的是**第三条备份**，即「迁了 config+slots、还没迁 active_pets」的中间态。也就是说 rollback 之后用户既不在迁移前、也不在迁移后。
- `not_found` 不在 `FAILURE_STATUSES` 里 → 部分失败的 rollback 打印全绿、退出码 0；`shutil.copy2(backup, target)` 在 target 恰好是同名目录时会把文件拷进目录，报告照样写 `rolled_back / restored`。

**为什么是 P1 而不是 P0**：`migration.run/rollback` 只挂在 `petcore migrate` CLI，桌宠启动路径不跑它，所以只有用户**主动**执行才会触发。但文档把它当作恢复手段正面宣传（`docs/PETCORE-ARCHITECTURE.md:307`、`docs/PETCORE-ROADMAP.md:574`），按文档操作会被反噬，因此不能降到 P2。

**注意**：现有测试把这个语义**当成期望**写进了断言（`tests/test_petcore_migration.py:135/160` 的 `test_rollback_removes_files_that_did_not_exist_before`），修行为必须同时改测试。

**修法方向**：restore 条目里记录「迁移时目标的摘要」；回滚前先给当前文件留一份 `.pre-rollback`；`not_found`/`failed_write` 计入失败；只有全部成功才删标记；同一 target 的多条 restore 合并成一次写入（取最早的那份备份）。

**验收**：跑上面三个场景，期望 (i) 用户改动有 `.pre-rollback` 副本且报告点明「已覆盖」；(ii) 迁移产物与用户新文件都不丢；(iii) 标记保留、退出码 1。

---

### AUD-07（P1）`Config` 丢弃所有未登记键 → 第三方 mod 的设置永远存不住

**位置**：`petcore/config.py:840-843`（`_normalize` 从 `dict(DEFAULTS)` 重建，只拷同名键）、`:1282-1287`（`set()` 后立刻归一化）、`:1349-1350`（`ScopedConfig.set` 同一路径）。

**我的复现**：

```text
g.set("mymod.enabled", True)  →  同进程 get: None
                                 落盘里有该键: False
ScopedConfig.set("mymod.alpha", 1) → get: None
DEFAULTS 键数: 194
```

**红队补充的影响面**：
- `docs/PETCORE-MOD-FORMAT.md` §14.3/§15.2 **明确让 mod 设置页写 `host.config`**，却从没写「你的键必须先在 core `DEFAULTS` 三处登记」——而那是 core 文件，第三方 mod 改不到。
- 现存 10 个官方 mod 的 **71 次 `.config.set()` 全部只写 `DEFAULTS` 已有键**（0 例越界），所以现网没有破坏，定 P1 而不是 P0。
- 第三条通道（`StoragePort.data_root()` + 自建 JSON）只覆盖「运行状态」，不覆盖「用户在设置页勾的偏好」，不能当免责理由。
- 附带更广的后果：手写进 `config.json` 的未知键**重启即消失**（`load()` 也走 `_normalize`）。

**修法方向**（两种，选边由 owner 定）：
1. `_normalize` 保留未登记键（白名单只用于钳制已知键的取值），风险是「任意 mod 都能往全局配置塞键」，需要配套命名空间（`mods.<id>.*`）；
2. 给 `ScopedConfig.set` 一个显式的 mod 命名空间落点（例如 `mods.<owner>.<key>`，作为 `DEFAULTS` 之外的第二个受管区块），并在文档里写清。

**验收**：`Config.set("mymod.enabled", True)` 后同进程 `get` 返回 `True`、`save()` 后磁盘有该键、`load()` 后仍在；同时 194 个已知键的钳制行为不变（现有 `test_petcore_config*.py` 全绿）。

---

### AUD-08（P1）升级静默重置老用户的扩展设置

**位置**：`petcore/config.py:359-427`（`_LEGACY_KEY_ALIASES` 57 条 + 白名单式 `_map_legacy_data`）、`petcore/migration/config_data.py:49-101`（detail 只记 `keys:<added>`，从不记丢掉的）。

**红队实测的数字（更正了我最初的估计）**：

```text
旧壳出厂键 159 个
别名表覆盖 39 个
与 petcore DEFAULTS 同名却没进别名表：41 个
  ['chat_always_on_top','chat_background','chat_follow_pet','click_show_balance',
   'divination_hint','divination_speak','festival_*'(13),'hotkey_look_screen',
   'hotkey_open_chat','hotkey_screen_capture','island_metrics','music_*'(7),
   'todo_reminder_enabled','todo_reminder_lead_minutes','todo_reminder_speak',
   'voice_chime_*'(5),'weather_city','weather_city_codes','weather_city_list','weather_enabled']
未覆盖任何别名的旧键：120 个
```

抽样 13 个键 → 12 个静默消失，`detail` 只有 `keys:character,festival_enabled,scale`。

**后果**：在旧壳里配过「待办提前 15 分钟 / 城市北京 / 报时音色 / 聊天快捷键 / 占卜语音」的用户，升级后这些值回到 `DEFAULTS` 默认值，且报告全绿。这不是丢文件，是用户可见的功能回归。

**修法**：补齐 41 条同名别名（纯数据，成本极低）；config 域与 sessions/api 域对齐，把没搬的键写进 `detail="dropped:…"`。

**验收**：造一份含上述键的旧壳配置 → `petcore migrate` → 新 `config.json` 里 41 个键的值与旧壳一致；再补一条断言「config 域 detail 含 `dropped:` 当且仅当有键被丢」。

---

### AUD-13（P1）「代理失败→直连」的兜底是空转

**位置**：`petcore/net/http.py:99-117`。同文件 `:174` 的 `fetch_url` 每轮都 `build_request(...)`，注释还专门写了「避免复用被 OpenDirector 改过的对象」——`urlopen` 这条路径没有。

**我的复现**（urllib 语义确认）：

```text
before: 127.0.0.1:54600 | /a
open raised: URLError
after : 127.0.0.1:1 | http://127.0.0.1:54600/a
=> 直连 opener 再开同一个 req，会拨到: 127.0.0.1:1     ← 还是代理
```

域审计端的端到端：把系统代理指向死端口后，`AccountService.fetch_balance` 返回 `FAIL reason=network`，`_force_direct` 仍为 `False`；同一个 URL 走 `fetch_url` 得到 `200`。

**为什么是 P1**：这个模块存在的唯一理由就是「加速器/VPN 退出后系统代理还残留」这个场景；现在它在这一场景下完全失效，`chat`/`balance`/`probe`/`websearch` 四条链路一起报「网络不可达」。

**修法**：与 `fetch_url` 对齐——每次尝试重新 `build_request`（或在 `except` 分支里重建 `Request`）。

**验收**：`http_proxy=http://127.0.0.1:1` 指向死端口、origin 存活时，`urlopen` 一次成功、`_force_direct` 置位；把系统代理改回可用后（新进程）仍走代理。补一条在真 `ProxyHandler` 下跑的用例（现有测试用假 opener，正因如此才没抓到）。

---

### AUD-14（P1）「已重新加载」实际跑旧代码

**位置**：`petcore/ui/app.py:968-981`（`reload_mods` 只 `stop()` + 重扫）、`:951-966`（`_drop_modules_under` 只在 `uninstall_mod` 里调）、`petcore/mods/feature.py:104-126`。

**我的复现**：

```text
first load  -> v1
second load (after editing runtime.py) -> v1        expected v2
stale modules still in sys.modules: ['petcore_feature_demo_owner', 'petcore_feature_demo_owner.runtime']
```

**后果**：用户手动更新 `mods/<id>/` 后点「重新加载扩展」，或从插件市场覆盖安装（`page_market` 会追加「（已重新加载）」文案），界面说成功、实际还是旧实现，只有重启进程才生效；旧模块的全局状态（锁、缓存、daemon 线程）也继续存活。10 个可分发扩展里 9 个用 `host/__init__.py:create_host`，全部受影响。

**修法**：`reload_mods()` 前对每个 `mod.path` 调 `_drop_modules_under(path)`（复用已有实现）。

**验收**：把某个 mod 的 `host/runtime.py` 改成打印不同字符串 → 点「重新加载扩展」→ 点桌宠 → 看到新字符串。补一条用例：`import_entrypoint` 两次，第二次前改写子模块文件，断言读到新值。

---

### AUD-15（P1）SSE 断流被当成「回答完成」

**位置**：`petcore/api/chat.py:516-537`（逐行 `json.loads`、只认 `choices`）、`:595-600`（`ChatResult` 没有「不完整」字段）、`petcore/ui/chat/controller.py:412-436`（`_apply_done` 直接落盘）。

**域审计实测**（裸 socket 服务端）：

```text
B drop before [DONE]      0.03s text='半条' chunks=1 finish='' cancelled=False   ← 无异常
6 empty body 200          0.05s text='' chunks=0 finish=''                       ← 静默
7 SSE error frame         0.06s text='' chunks=0 finish=''                       ← 401 被吞成空回答
A multi-line data field   0.06s RAISE NetworkError: 服务端返回了无法识别的响应    ← 合法 SSE 被拒
5 truncated chunk         RAISE IncompleteRead(0 bytes read)                     ← 未分类
```

**后果**：半条回答被当作完整一问一答写进会话，用户下次打开看不出任何截断；配置错的 Key（HTTP 200 + 错误帧）表现成「模型没说话」。

**修法**：`ChatResult` 增 `incomplete`/`end_reason`；`raise ChatTruncated` 的条件从「reasoning 且空正文」扩展到「没有收到 `[DONE]` 或 `finish_reason` 为空但正文非空」；识别 `data: {"error":…}` 并转成 `AuthError`/`ProtocolError`；支持多行 `data:` 拼接。

**验收**：上面 5 个 case 各一条 pytest（现有 `test_petcore_api_chat.py` 已有裸 socket 夹具，扩它即可）。

---

### AUD-25（P1）展开灵动岛卡片 = 把要看的探针关掉

**位置**：`petcore/ui/island.py:777-790`（卡片行预算 290–370px）、`:370-404`（wanted 计算与边沿触发）、`:611/624/845`（展开态一律按 card budget 重排）、`:815-836`（`_probe_unavailable_reason` 报 crit）、`petcore/ui/probes.py:118-155`。

**红队实测**：

```text
capsule plan.width=636 folded=[]
  card width=340 budget=290 -> plan.width=286 folded=['mem']
transitions in 5s: 16                       ← 每秒 3 次 wanted 翻转
probe start/stop in 5s: gpu=7/11 fps=12/6
card rows claiming 'probe not wired': [('GPU', '该指标不可用：当前环境未接入可用 GPU/FPS 探针'),
                                       ('帧率', '该指标不可用：当前环境未接入可用 GPU/FPS 探针')]
```

闭环的每一环都实测到了：推快照 → 段回 `_row` → 展开态按 card budget 重排把 gpu/fps 折进 `+N` → wanted 空 → 停采 + `clear_probe_snapshot()` → 行变短 → wanted 复原 → 再 start。

**后果**：`island_metrics` 里只要带 `gpu`/`fps`，点一下胶囊（唯一的正常查看动作）就进入 1Hz 的 PDH 基线重建 + PresentMon 子进程启停；卡片同时把「我自己把采样停了」呈成「这台机器没有这个能力」。

**修法方向**：wanted 的计算不应该用「展开态折行结果」，而应该用「用户启用的段集合」；折行只影响**显示**，不影响**采样**（与 AGENTS「看不清就不采」不冲突——看不清指的是岛隐藏/段未启用，不是卡片放不下）。或者卡片态改用独立的分页/滚动，而不是折进 `+N`。

**验收**：`DynamicIsland(metrics=['cpu','gpu'])` + 真 hub，`expand_card()` 后 5 秒内 `gpu` 的 start 次数应为 **1**（不是 5–7），卡片不再出现「未接入探针」文案。

---

### AUD-26（P1）最小窗口下 API 页主按钮不可达

**位置**：`petcore/ui/settings/base.py:152`（`ScrollBarAlwaysOff`，只有 `prepare_embedded` 才 `AsNeeded`）、`petcore/ui/settings/page_api.py:126-228`（`QHBoxLayout` 平铺左右两列，右列 `setMinimumWidth(300)`）、`dialog.py:123`（`setMinimumSize(720,500)`）。

**红队实测**：

```text
window 720x500 | viewport 506 | content 731 | hbar AlwaysOff max=225 | 保存服务 x 608..685 inside=False
window 900x620 | viewport 686 | content 731 | max=45                 | 保存服务 inside=True   ← 只差 1px
after setFocus: h value 0 | after ensureWidgetVisible: h value 225   ← Tab 聚焦也不滚进来
```

**为什么是 P1**：产品自己声明 720×500 是最小可用尺寸，在那里「保存服务」鼠标完全够不到、键盘也不行，用户填完表单找不到保存。只在宽度 ≤720 触发（默认 900 宽余量 1px），所以如果你认为「720 不算受支持配置」，可以降到 P2。

**修法**：`base.py` 的横向策略在窗口宽度不足时改 `AsNeeded`（或对 API 页用 `add_row(expand=True)` 竖向排布）；顺带给右列一个 `setMinimumWidth(0)` + 允许换行。

**验收**：720×500 下 API 页 `content.width() <= viewport.width()`，或横向滚动条可见且能滚到「保存服务」；Tab 遍历时视口跟随。

---

### AUD-37 / AUD-38（P1）打包链路的两处「看着成功其实没收束」

**AUD-37**（`scripts/build_petcore.ps1:23/30/32`）：`Set-Location $root` 只改 PowerShell 位置，`[IO.Path]::GetFullPath($OutputRoot)` 用的是**进程 CWD**。红队 pwsh 实测：

```text
Process CWD = C:\Users\26102 ; PS location = E:\Work\dsh-pet-0
GetFullPath('rel')  = C:\Users\26102\rel        ← 相对路径落到调用者目录
GetFullPath('E:\Work\dsh-pet-0\') -eq GetFullPath('E:\Work\dsh-pet-0') = False   ← 尾部反斜杠绕过守卫
```

**AUD-38**（`petcore/cli.py:225` + `scripts/build_petcore.ps1:158-163`）：`_check` 无条件 `return 0`，脚本只看 `$LASTEXITCODE`，`check.json` 写出来没有任何代码读。于是「`menu_templates` 没进包 → `menu_template="builtin"`」「`assets/big_blue_fat_fish` 缺失 → `builtin_readable=0`」「角色素材没打包 → `characters=[]`」这三种「只有装机后才炸」的缺口都能构建成功。AGENTS 明文写着 `--check` 的 `self_talk_images` 是「安装包素材/Qt 插件是否正常的第一证据」，但没有任何消费者。

**修法**：`-OutputRoot` 相对路径按 `$root` 解析（`Join-Path $root $OutputRoot` 再 `GetFullPath`），守卫比较前 `TrimEnd('\','/')`；构建脚本 `ConvertFrom-Json` 读 `check.json` 并对 `menu_template`/`builtin_readable`/`characters`/`diagnostics` 逐项断言。

**验收**：`-OutputRoot rel` 的输出落在 `<repo>/rel`；`-OutputRoot "E:\Work\dsh-pet-0\"` 被拒；故意不打 `menu_templates` 时构建**失败**。

---

## 四、被证伪与被降级的条目（审查纪律的产物）

这一节是本次审计最重要的部分之一：**独立红队推翻了我最初 2 条判断、降级了 6 条、修正了 4 处数字或机制描述**。把它写出来，是为了让后来者知道「哪些看起来像 bug 的东西其实不是」。

| 原判断 | 裁定 | 依据 |
|---|---|---|
| 灵动岛隐藏/关闭后 GPU/FPS 探针**一直跑到进程退出** | **FALSE POSITIVE** | `stop()` 确实不 sync，但 hub 的 1Hz `_poll` 每拍都把快照推回岛 → `set_probe_snapshot` → `_update_size` → `_sync_sampling`；此时 `_clock` 已停 → wanted 变空 → 1.0s 内收口。不变式是「探针在跑 ⇒ hub timer 活着 ⇒ 至多一拍被叫停」 |
| `FpsProbe.start()` 被拒后**永久失效**，隐藏→显示也救不回 | 降级 P1→**P2** | 「不重试」属实（6s 内 0 次），但隐藏会把 wanted 变空、显示后就是一次新边沿，实测重试成功。正确描述是「在下一次 wanted 变化前保持死亡」 |
| 设置页整组回写会覆盖**滚轮缩放** | 部分误判，P1→**P2** | 该页 `_on_changed` 的 35 个键里**没有 `scale`**；滚轮那条真实路径是 `reject()` 的快照 restore。真实被覆盖的是 `golden_spin_on_click`/`no_move`/`drag_physics_enabled`/`playback_speed`（已实测翻回） |
| 菜单提前落盘导致「取消无法回滚」，P1 | 降级 P1→**P2**，但**更糟** | 现象成立；额外发现 `MenuEditor.is_dirty()` 恒 True（`value()` 是 dict、`_initial_value` 是 list），所以**不碰菜单也会写盘 + `reload_menu()`** |
| 聊天壁纸在 150% 屏上被**放大 1.5 倍** | 降级 P1→**P3** | DPR 不写回属实（1029×686 铺到 1544×1029 设备像素），但逻辑几何与 100% 完全一致 → 症状是**发虚**，不是放大/裁切 |
| `SystemExit` 逃出 `load()`，P1 | 降级 P1→**P2** | 端到端实测 `python -m petcore` 以 3 退出、无诊断，但需要用户显式开 `allow_feature_mods` 或装 `.trusted` 包 |
| 卸载不撤 `interaction`，P1 | 降级 P1→**P2** | 实测重载后 1 条 listener 触发 2 个 runtime；但仓库内 3 个点击消费者都在自己的 `stop()` 里退订，只有第三方不自退订才中招 |
| 架构守卫盲区是 P1 | 降级 P1→**P2** | 用能解析相对 import 的 AST 重建依赖图：`engine→ui` **0 条**、`engine→net/api/account` **0 条**。唯一跨界反向依赖是 `contracts/content.py:7 → ..engine.enums`（该模块只 import `enum`）。是「守卫失效但目前干净」 |
| 迁移未映射键「138 里 29 个」 | 数字更正，建议 P2→**P1** | 实际是 **159 个出厂键里 41 个同名可无损搬却没搬**，抽样 13 键 12 个静默消失 |
| 迁移 rollback「删掉用户新数据」 | 描述更正 | 实测用户后写的会话文件**没被删**（restore 只登记迁移产物）；被无声覆盖的是「同一文件上的用户修改」 |
| 待办备份格式冲突 → 扩展**永久加载失败** | 描述更正 | 异常原文是 `ValueError: invalid migration backup; preserved`，但 `tick()` 吞掉它、面板显示「待办文件无法读取」，扩展本体正常；再跑一次 `migrate` 会自愈 |
| `_imports` 盲区是被 `continue` 分支放行的 | 机制更正 | 不是：跨包相对 import（`level=2`）在 `_imports` 第一层就被丢了，`continue` 只对绝对 `petcore.*` 生效 |

**另外，红队顺带发现 5 条原清单没有的问题**：`MenuEditor.is_dirty()` 恒 True；`IslandProbeHub._poll` 与 `sync()` 重入导致隐藏态多推一帧；卡片宽度因折叠而缩水（420→340，budget 370→290，越折越窄的棘轮）；部分折叠时「停采但不清快照」留下过期段；聊天壁纸缓存键不含 DPR，跨屏不重算。

---

## 五、不作为缺陷、但值得记录的观察

这些是审计中确认「行为正确」的关键点，避免后来者重复怀疑：

- **动画/物理/碰撞红线守住了**：帧驱动位移（`move_position_at_frame`）、待机 re-arm（`_on_finished` 不先 `advance()`）、探头/击飞只播 idle/转向、碰撞不瞬移（`set_velocity` 前重锚 `_x/_y`）、`body_box` 钳制、内切三圆链 + 主分支分离规则、气泡按 `head_box→body_box→整窗` 锚定并同帧合并。
- **密钥纪律**：`api.json`/`config.json` 无 Key，`ApiRequest.repr` 不含密钥，日志只记异常类型名/状态码，`migrate_credentials` 只做钥匙串→钥匙串；`BalancePresenter.cancel()` 确实在锁外取消（AGENTS 那条死锁红线的修法是对的）。
- **探测器的「不伪造读数」在探针层成立**：`GpuSample.__post_init__` 钉死「只有 ok 带读数」，跨线程 `read`/`close` 被拒，owner 线程退出后的接管与基线重建有效；FPS 无权限时如实报 `access denied` 而不是 0。
- **迁移的幂等标记、dry-run 零写盘、备份优先**这三条硬规则落实了（dry-run 三次快照比对「差异：无写入」）。
- **截图物理/逻辑像素口径正确**：GDI 直抓物理矩形（1280×800 逻辑屏抓到 1920×1200），150% 下不会裁半屏；`grab_screen_image` 的 QImage + DPR=1.0 复位到位。
- **mod 卸载顺序、未登记文件保留、`.trusted` 包可卸载、市场下载的 sha256 双份校验、重定向策略（逐跳、https 不降级、跨主机白名单）**都实现得比文档要求的更细。
- **本轮新代码的测试是真行为测试**：`platform/fps.py`/`gpu.py` 用假 PDH 与假 Popen 测真行为，`migration/*` 覆盖标记幂等/dry-run/回滚，`ui/probes.py` 测真启停闸。这是全套件里质量最好的部分。

---

## 六、修复批次建议

按「用户会真遇到 × 后果严重度 × 修复成本」排序。同一批可以合成一次提交（同文件、同测试族）。

| 批次 | 内容 | 涉及文件 | 预估改动量 | 为什么这个顺序 |
|---|---|---|---|---|
| **S0（安全）** | AUD-01 | `mods/install.py` 或 `mods/trust.py` + 1 用例 | ~5 行 | 唯一真实绕过授权闸门的代码执行路径；顺带砍掉 AUD-02 的利用面 |
| **S1（数据）** | AUD-07 + AUD-08（同一文件） | `config.py`（归一化策略 + 41 条别名 + `dropped:` 记账）、`migration/config_data.py` | 中等 | 升级即静默重置扩展设置 + 第三方 mod 设置存不住，两者都是「设置不生效」类投诉，且同源 |
| **S2（迁移安全）** | AUD-06 + AUD-09 + AUD-10 | `migration/__init__.py`（completed 判据 + rollback 语义）、`migration/todos.py`；同时改 `tests/test_petcore_migration.py:135/160` | 中等 | 唯一不可逆的数据破坏；三条共用 `MigrationContext` 与同一批夹具 |
| **S3（网络）** | AUD-13 + AUD-15 + AUD-17 + AUD-18 + AUD-16 | `net/http.py`、`net/errors.py`、`api/chat.py` | 中等 | 「代理失效即全站不可用」+「半条回答当完整」，用户可感知最强 |
| **S4（UI 可达性）** | AUD-25 + AUD-26 + AUD-27 + AUD-28 + AUD-29 | `ui/island.py`、`ui/probes.py`、`ui/settings/{base,page_api,page_interaction,menu_editor,dialog}.py` | 较大 | 探针振荡与保存按钮不可达都是「唯一正常操作就踩到」 |
| **S5（运行时卫生）** | AUD-14 + AUD-21 + AUD-22 + AUD-19 + AUD-20 | `ui/app.py`、`mods/feature.py`、`ports.py`、`account/presenter.py`、`speech/service.py` | 中等 | 「已重新加载」说谎 + 启动能被一个 mod 打死 |
| **S6（构建守卫）** | AUD-37 + AUD-38 + AUD-39 + AUD-40 + AUD-36 | `scripts/build_petcore.ps1`、`tests/test_petcore_{architecture,installer,candidate_packaging}.py` | 中等 | 让「只有装机后才炸」的缺口在构建期就红 |
| **S7（画质与体验）** | AUD-32 + AUD-35 + AUD-33 + AUD-34 | `ui/chat/*`、`media/images.py`、`media/thumbnails.py`、`ui/pet_window.py` | 中等 | 发虚与卡顿，不影响正确性 |
| **S8（其余）** | AUD-02/03/04/05/11/12/23/24/30/31/41/42 | 分散 | 较大 | 纵深防御与诊断一致性 |

**关于 AUD-36 的一个前置条件**：修好 `_imports()` 之后守卫会立刻抓到 `contracts/content.py:7 → ..engine.enums`，所以这两处必须一起改（把 `AnimatType/GraphType/ModeType` 下沉到 contracts 内，或允许 contracts 依赖 `engine.enums` 这个零依赖叶子并在测试里显式白名单）。

---

## 七、未覆盖与限制

**没做的验证**：

- 真实 PresentMon/ETW 会话与有权限时的真实帧率（本机无 Performance Log Users，且审计期间刻意不在 1Hz 环路里反复 spawn/kill ETW 会话）。
- 真实安装器全流程（未跑 `build_petcore.ps1 -Installer`，未编译 `petcore.iss`；本机 SAC 会拦新构建）。
- 真实钥匙串读写（所有迁移/凭据实验都注入内存假后端，避免写用户 Credential Manager）。
- 真实多屏/混合 DPI 下的岛与聊天窗（只有 1.5 倍单屏 + `QT_SCALE_FACTOR` 对照）。
- 真实音频设备（无声卡环境、`QMediaPlayer` 卡在 Loading 的分支）。
- 真实外网 API（DeepSeek/博查/Tavily/豆包/MiMo 的 SSE 与错误形状）；所有网络实验都是 localhost。
- 覆盖空洞统计是「静态引用分析」而非行覆盖率（本机未装 `coverage`），可能低估真实覆盖：69 个模块在 `tests/` 里零路径引用，其中真空白 19 个（`ui/settings/pages_core.py` 1054 行、`ui/settings/page_pets.py` 189 行、`media/clip.py` 166 行、`platform/sampling.py` 135 行、`contracts/capabilities.py` 39 行等）。

**审计本身的局限**：

- 每个域由不同 agent 深读，跨域交互（例如「设置页 → 探针 → 岛 → 配置落盘」的完整链路）只在发现指向它时才追；不排除仍有跨域竞态没被发现。
- 红队只复核了 P0/P1 与少数 P2，P3 条目大多只有单一证据来源。
- 严重度里的「用户会不会真遇到」依赖我对使用习惯的判断；AUD-26 就明确标注了「若 720 不算受支持配置可降 P2」。

---

## 八、修改文件说明

**本报告不包含任何代码改动。** 审计期间对仓库的唯一写操作是：

| 文件 | 动作 |
|---|---|
| `docs/PETCORE-CODE-AUDIT-2026-10-26.md` | 新增（本报告） |
| `docs/PETCORE-LOG.md` | 追加 `L087`（审计记录） |
| `docs/PETCORE-LOG-INDEX.md` | 追加 `L087` 索引行 |
| `docs/INDEX.md` | 登记本报告 |

工作区原有的 27 个改动 + 14 个未跟踪文件（P5 修复 / P6 迁移与探针）**未被我触碰**，仍处于未提交状态。所有实验脚本、夹具、临时 mod 包、临时数据根都在系统 temp 与 `.scratch/`（已 gitignore）。

---

## 九、性能分析

审计中实测到的性能数据（供后续优化取基线）：

| 场景 | 实测 | 说明 |
|---|---|---|
| 全量 petcore 套件 | 204.70s / 1613 passed | 最慢 5 条：`test_petcore_cli.py::test_pack_legacy_and_check_mod_character` 15.03s、`monitor_lifecycle[sys]` 6.03s、`reminder_ports` 音频 4.91s、`ocr_mod` 真跑 rapidocr 4.20s、`tray` 3.89s |
| 灵动岛 1Hz tick | mean 0.891ms / max 2.28ms | `set_probe_snapshot` mean 0.875ms |
| 展开态卡片重建 | mean 1.69ms / max 11.06ms | 配合 AUD-25 时每秒触发一次 |
| GUI 线程全屏抓图 + PNG 编码 | 60.6ms + 233.6ms = **~294ms** | 1920×1200；4K 双屏约 3.6 倍面积 ≈ 1s |
| `shrink_png → 1024` | 128.4ms | 后台线程 |
| 12MP JPEG 解码 | 全解 92.4ms vs `setScaledSize` 9.3ms | AUD-35 |
| 缩略图 PNG 编码 / 落盘 / 读盘 | 0.49ms / 1.73ms / 0.46ms 每张 | 106 段动画首开菜单 ≈ 150–230ms GUI 线程 |
| `_package_is_verified()` 整包哈希 | 64MB 92ms / 500MB ~0.72s | 在 GUI 线程同步调（AUD-02 相关） |
| 设置对话框首次构建 | 657ms → 后续 367/338ms | 每次打开都重建 8 页（含所有 mod 设置页） |
| `fps_permission.check()` | 1.8–3.9ms（首次 13.6ms） | GUI 线程同步调用，可接受 |
| `FpsWindow.add_event` | 6.3–7.9µs/帧 | 144fps ≈ 9ms/s CPU（worker 线程） |
| GPU 单拍读取 | 冷启 283.6ms / 稳态 2.14–3.49ms | PDH |
| 探针振荡代价（AUD-25） | 5s 内 GPU start 7 次 / FPS start 12 次 | 每次 FPS start 都要重建 PresentMon 会话 |

**结论**：常规路径没有性能问题；真正的性能风险是「AUD-25 的 1Hz 启停振荡」和「AUD-35 的 GUI 线程解码/编码」，两者都能用一行到十行的改动消除。

---

## 十、实机运行记录

**环境**：Windows，`E:\Work\dsh-pet-0`，`.venv/Scripts/python.exe`（3.12），PySide6 6.12.0，PyInstaller 6.22.3，Inno 6.7.3（`tools/InnoSetup/ISCC.exe`）；屏幕 1280×800 逻辑 @ DPR 1.5（物理 1920×1200）；GPU 三个适配器（AMD Radeon 780M ×2 + Microsoft Basic Render Driver）；当前账户不在 Performance Log Users。

**跑过的实验（全部只读，未安装/未改注册表/未弹 UAC/未写真实钥匙串）**：

| 编号 | 实验 | 关键真实输出 |
|---|---|---|
| E1 | 架构守卫喂相对 import | 守卫只看到 `{'PySide6.QtCore'}`；全部 engine 模块可见名字 `['__future__','collections.abc','dataclasses','enum','math','os','pathlib','random','time','typing']` |
| E2 | 造带/不带 `.trusted` 的 feature zip | 带：`[('evil.feature', True)]`；不带：`[('evil.feature', False)]` + `feature mods disabled` |
| E3 | `import_entrypoint` 加载 → 改子模块 → 再加载 | `v1` → `v1`（期望 v2），`sys.modules` 里残留 `...runtime` |
| E4 | `ProxyHandler` 就地改写 `Request` | `before: 127.0.0.1:54600 \| /a` → `after: 127.0.0.1:1 \| http://127.0.0.1:54600/a` |
| E5 | `Config.set` 未知键 | `get → None`，落盘无该键，`DEFAULTS` 194 键 |
| E6 | `python -m petcore --check --root <temp>` | 新增 `config.json` / `logs/petcore.log` / `migration-backup/dsh-pet-standalone-config.json`；`migration.marker=false` 但 `backups=1` |
| E7 | 红队：岛展开 5s 振荡 | `transitions 16`、`gpu 7/11`、`fps 12/6`、卡片常驻「未接入可用 GPU/FPS 探针」 |
| E8 | 红队：岛隐藏后探针收口 | `hide+0.6s wanted=[] hub_timer=False gpu=1/1/3` → **证明 A1 是假阳性** |
| E9 | 红队：FPS start 被拒后重试 | 0–1.2s 连续 `False`，1.52s `True`；hub 侧 6s 内 0 次重试；hide→show 后恢复 |
| E10 | 红队：设置页整组回写 | `keys written by _on_changed: 35`；菜单把 `golden_spin_on_click` 改 True 后，改一行 `no_move` → 内存与磁盘都变回 False |
| E11 | 红队：菜单提前落盘 | 用户没碰菜单，`disk after refused save has menu_layout: True`；取消后磁盘仍是新菜单，内存已恢复 → 两者不一致 |
| E12 | 红队：API 页裁切 | 720×500：viewport 506 / content 731 / max 225 / 「保存服务」`inside=False` |
| E13 | 红队：聊天壁纸 DPR | 1.0×：`1.00x` 上采样；1.5×：`1544×1029 device px` from `1029×686 source` = `1.50x`，几何尺寸相同 |
| E14 | 红队：mod 里 `sys.exit(3)` | `SystemExit: 3 ESCAPED load()`；`python -m petcore` → `EXIT=3`，日志只有 `starting petcore` |
| E15 | 红队：重载后点击 | `click listeners: 2`，一次点击触发 `[old runtime]` + `[new runtime]` |
| E16 | 红队：迁移 rollback 三场景 | 见 §三 AUD-06 的实测块（含「`config.json` 最终 == 迁移前原文件? False」） |
| E17 | 红队：`completed` 封存写失败 | 第一轮 `completed.sessions=True` + `failures=[('sessions','failed_write',…)]`；第二轮 `already_migrated`；`--force` 救回 |
| E18 | 红队：旧键丢失统计 | 159 出厂键 / 39 别名覆盖 / 41 同名未搬 / 抽样 13 键丢 12 |
| E19 | 红队：待办备份格式 | 迁移写的备份是 dict → `ValueError: invalid migration backup; preserved` |
| E20 | 红队：更新侧车替换 | 换包+改侧车 → `installer_started / ok=True`，launcher 被调用；陈旧侧车 → `invalid_package` |
| E21 | 红队：`-OutputRoot` 路径解析 | `GetFullPath('rel') = C:\Users\26102\rel`；尾部反斜杠 `-eq root` 为 False |
| E22 | 依赖图重建（解析相对 import） | `engine→ui: 0`、`engine→net/api/account: 0`、`contracts→petcore.*: 40`（唯一跨界 `contracts/content.py → engine.enums`）、`platform/* → Qt: 33`（全在文档允许的 core Qt 侧） |
| E23 | 基线门禁 | `ruff` 全绿；`1613 passed in 204.70s` |

**未能实机验证的**（如实登记，未用推断冒充结论）：真实 PresentMon 帧率（无权限）、真实安装器全流程（SAC）、真实钥匙串、真实多屏混合 DPI、真实声卡、真实外网 API、真实 GUI 点击（导入 ZIP 的对话框流程只从源码读到「无确认框」，没有截图证据）。

---

## 附：一句话结论

**架构分层、动画物理、密钥纪律、探针「不伪造读数」这些真正的难点是守住的；出问题的全是「接缝」**——授权标记被当成了内容（AUD-01）、迁移被当成了回滚（AUD-06）、`completed` 被当成了域级（AUD-09）、守卫被当成了覆盖（AUD-36）、`--check` 被当成了只读（AUD-11）、「已重新加载」被当成了已生效（AUD-14）。这些接缝有一个共同点：**每一处都有一份文档说它是对的，而没有任何一条测试在它错的时候会红**。

---

## 十一、修复状态（2026-10-26 本轮）

| 审计项 | 状态 | 落点 |
|---|---|---|
| AUD-01 本地导入 `.trusted` 绕过授权 | 已修 | L088 |
| AUD-02 更新安装信任锚 | 已修（含缓存清单回退） | L088 |
| AUD-03 scheme / 内网地址 | 已修（内网拦截只加在模型驱动的 `fetch_page_text`；`HttpPort` 保留内网以支持本地 LLM） | L088 |
| AUD-04 跨源 302 转密钥 | 已修 | L088 |
| AUD-05 ADS / 保留名 / 大小写冲突 | 已修 | L088 |
| AUD-06 回滚覆盖/半迁移/删标记 | 已修 | L089 |
| AUD-07 未登记键无法持久化 | 已修（`extra` 区块） | L089 |
| AUD-08 旧键 41/159 静默丢失 | 已修（补别名 + `dropped:`） | L089 |
| AUD-09 域级 `completed` 封存失败 | 已修 | L089 |
| AUD-10 待办历史格式冲突 | 已修 | L089 |
| AUD-11 `--check` 不是只读 | 已修（`persist=False`） | L089 |
| AUD-12 坏配置被静默覆盖 | 已修（改名留档 + `--check` 暴露） | L089 |
| AUD-13 代理兜底空转 | 已修 | L090 |
| AUD-14 重载跑旧代码 | 已修 | L091 |
| AUD-15 SSE 断流当成功 | 已修（`incomplete`/`end_reason` + 错误帧 + 多行 data） | L090 |
| AUD-16 截断无信号 | 已修（`Body.truncated` + TTS 拒绝半截音频） | L090 |
| AUD-17 TLS/HTTPException 分类 | 已修 | L090 |
| AUD-18 换路不看 Retry-After | 已修 | L090 |
| AUD-19 余额单飞失效 | 已修 | L090 |
| AUD-20 兜底音色写错缓存键 | 已修 | L090 |
| AUD-21 `SystemExit` 打断启动 | 已修 | L091 |
| AUD-22 interaction 订阅不撤 | 已修 | L091 |
| AUD-23 检索无整次预算 | 已修（45s） | L090 |
| AUD-24 取消不打断阻塞读 | 已修（0.5s 读超时循环 + 返回 cancelled） | L090 |
| AUD-25 岛展开致探针 1Hz 振荡 | 已修（含 AGENTS 红线改写） | L092 |
| AUD-26 720 宽 API 页不可达 | 已修（横向滚动；未改上下排布） | L092 |
| AUD-27 设置页整组回写 | 已修（差异写入） | L092 |
| AUD-28 菜单编排提前落盘 / `is_dirty` 恒真 | 已修 | L092 |
| AUD-29 搜索漏按钮/下拉 | 已修 | L092 |
| AUD-30 覆盖表落点写错 | 已修（测试改成行级可达） | L092 |
| AUD-31 探针被拒后不重试 | 已修（每拍调和） | L092 |
| AUD-32 壁纸不按 DPR | 已修 | L094 |
| AUD-33 冷 meta 瞬移 / 无看门狗 | 已修 | L094 |
| AUD-34 命中与绘制不互逆 | 已修 | L094 |
| AUD-35 整图解码 / 缩略图编码在 GUI 线程 | **部分**：`load_pixmap` 已按需解码；缩略图 PNG 编码/落盘仍在 GUI 线程 | L094 |
| AUD-36 守卫看不见相对 import | 已修（并新增三组红线） | L093 |
| AUD-37 `-OutputRoot` 收束失效 | 已修（+ `-DryRun`） | L093 |
| AUD-38 冒烟只验退出码 | 已修（`--check --strict` + 脚本解析 check.json） | L093 |
| AUD-39 打包/安装器测试只验字符串 | **部分**：新增 pwsh dry-run 与 `Tasks:` 真断言；安装器仍未真跑 | L093 |
| AUD-40 presentmon 校验顺序 | 已修 | L093 |
| AUD-41 零测试模块 | **部分**：`pages_core`/`page_pets`/`SamplingLoop` 与 capabilities 读出口已补；其余零测试模块未全补 | L093 |
| AUD-42 路径与缓存 | **部分**：portable 根、`--root ""`、实例缓存目录已修；缩略图 LRU 上限未做 | L094 |

另修一条审计未编号的缺陷（记作 AUD-43）：`network_info_enabled` / `memory_trim_enabled` /
`quiet_minutes_default` 由共享 feature 运行时读取，却按宠写入 → 子宠设置空转。已并入
`GLOBAL_CONFIG_KEYS`，`ScopedConfig` 也把未登记键路由到全局（L089）。
