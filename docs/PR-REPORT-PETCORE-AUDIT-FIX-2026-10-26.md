# petcore 审计缺陷修复（2026-10-26）

> 基线：`feat/petcore-vpet-architecture`，起点 `1c1507f1` + 工作区既有的 P5/P6 改动。
> 输入清单：`docs/PETCORE-CODE-AUDIT-2026-10-26.md`（28 条 + 1 条补记）。
> 记录：`docs/PETCORE-LOG.md` 的 `L088`~`L094`。

## 一、改了什么（按批次）

| 批次 | 主题 | 关键变化 |
|---|---|---|
| L088 | 安全与授权 | 授信 = 位置 + 标记（导入剥 `.trusted`、只在安装目录生效）；更新安装回查清单条目；`fetch_url` 协议白名单与内网拦截（模型驱动路径）；安全重定向（限跳、禁降级、跨源剥凭据头）；ZIP 拒绝 ADS/保留名/大小写重名 |
| L089 | 配置与迁移 | `config.json` 增受管 `extra` 区块（第三方扩展偏好可存、密钥样式值拒绝）；补 41 条同名旧键并记 `dropped:`；`--check` 只读；坏配置改名留档；回滚留 `.pre-rollback`、多记录同目标只按最早恢复、失败保标记；`completed` 判据收紧；待办历史改 `list[str]` |
| L090 | 网络与对话 | `urlopen` 每轮重建请求（代理兜底真正生效）；`Retry-After` 不换路；新增 `tls` 分类与 `HTTPException` 归类；`Body.truncated` 让 TTS 拒绝半截音频；SSE `incomplete`/`end_reason` + 错误帧 + 多行 `data:`；检索 45s 预算；取消打断阻塞读并返回 `cancelled`；余额单飞；兜底音色按实际音色缓存 |
| L091 | 运行时卫生 | 重载前 `detach_all()` + 清 mod 子模块（真的读新代码）；`SystemExit` 转诊断；`cancel_owner` 真实现；`on_tick` 返回注销函数 |
| L092 | UI 可达性 | 灵动岛卡片态不再因折行停采、卡片宽改用胶囊自然宽；设置页横向滚动；互动页差异写入；菜单编排不再自行落盘且 `is_dirty` 正确；搜索覆盖按钮/下拉/列表；覆盖表修正；探针每拍调和重试 |
| L093 | 结构守卫与构建 | 守卫解析相对 import 并新增三组红线；枚举下沉 `contracts`；`-OutputRoot` 收束 + `-DryRun`；`--check --strict` 成为构建门；presentmon 前置校验 |
| L094 | 画质与动画 | 命中测试与绘制互逆；冷 meta 墙钟推进 + 帧断流看门狗；聊天壁纸按 DPR；`load_pixmap` 按需解码；portable 根、`--root ""`、缩略图缓存按实例隔离 |

另修一条审计未编号缺陷（AUD-43）：`network_info_enabled` / `memory_trim_enabled` /
`quiet_minutes_default` 由共享 feature 运行时读取却按宠写入 → 已并入 `GLOBAL_CONFIG_KEYS`，
`ScopedConfig` 把未登记键路由到全局。

## 二、修改文件说明

- 产品代码：`petcore/{config,cli,paths,performance}.py`、`net/{http,errors,tts,websearch}.py`、
  `api/chat.py`、`account/presenter.py`、`speech/service.py`、`update/service.py`、
  `mods/{install,trust,manifest,feature}.py`、`market/install.py`、
  `migration/{__init__,config_data,todos}.py`、`contracts/{enums,content}.py`、`engine/enums.py`、
  `ui/{app,ports,pet_window,island,probes,pet_manager}.py`、
  `ui/chat/{window,themes}.py`、`ui/settings/{base,dialog,page_interaction,menu_editor,coverage}.py`、
  `media/{images,thumbnails}.py`、`scripts/build_petcore.ps1`。
- 测试：新增 `test_petcore_{mods_trust,http_safety,update_anchor,config_extra,migration_safety,api_chat_stream,mods_reload,pages_smoke}.py`；
  更新 `test_petcore_{architecture,update,migration_todos,example_mods,extensions_nav,candidate_packaging,installer,move_sync,settings,settings_coverage,speech,balance,island_window,probe_hub}.py`
  （其中 4 处原先把缺陷当成期望，按新语义改写并在 LOG 里注明）。
- 文档：`petcore/AGENTS.md`（新增 9 条红线 + 改写「看不清就不采」）、
  `docs/PETCORE-MOD-FORMAT.md` §14.3.1/§14.3.2、`docs/PETCORE-SPEC.md` §26.9、
  `docs/PETCORE-CODE-AUDIT-2026-10-26.md` §十一 修复状态、
  `docs/PETCORE-LOG.md` + `docs/PETCORE-LOG-INDEX.md`（L088~L094）。

## 三、性能分析

| 场景 | 修前 | 修后 | 说明 |
|---|---|---|---|
| 灵动岛展开卡片（GPU/FPS） | 5s 内 GPU start 7 次 / FPS start 12 次 | 0 次启停（复用同一采样器） | 去掉 1Hz 自激闭环 |
| 12MP 图片解码（彩蛋/配图） | 92.4ms（整图解码再缩） | ~9ms（`setScaledSize` 按目标解码） | 峰值内存同步下降 |
| 聊天壁纸（150% 屏） | 1.5 倍上采样（发虚） | 物理像素 1:1 | 缓存键含 DPR |
| `--check` | 会写 `config.json` + `migration-backup` + 日志 | 只写日志 | 诊断不再改数据 |
| 迁移回滚 | 覆盖用户改动且无法追溯 | 留 `.pre-rollback` 副本 | 多域同目标只按最早恢复 |
| 全量 petcore 套件 | 1613 passed / 190–205s | **1708 passed / 210.12s** | 新增 95 个用例 |

## 四、实机运行记录

- `./.venv/Scripts/ruff check petcore tests examples scripts` → `All checks passed!`
- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest -q $(ls tests/test_petcore*.py)`
  → **1708 passed in 210.12s，exit 0**（`.scratch/full-run.log`）
- `pytest tests/test_petcore_docs.py tests/test_pr_report_discipline.py` → **297 passed**
- `python -m petcore --check --root .scratch/check-strict` → exit 0；
  `--check --strict` 同根 → exit 0、`strict.problems = []`、`characters=1`、`builtin_readable=24`
- `pwsh -File scripts/build_petcore.ps1 -DryRun -OutputRoot rel-candidate`
  → `dist: E:\Work\dsh-pet-0\rel-candidate`（相对路径不再落到进程 CWD）；
  `-OutputRoot 'E:\Work\dsh-pet-0\'` → 抛 `must not be the repository root`
- `git diff --check` → 无空白错误

**未验证**（沿用审计报告 §七 的限制）：真实 PresentMon 读数、真实安装器全流程（未重建 setup）、
真实钥匙串、多屏混合 DPI、真实外网 SSE 形状、真实声卡。`--check` 的 `performance` 段仍是
进程内计数器（跨进程恒 0），本轮只补了 `capabilities` 读出口，没有引入 IPC 采样。

## 五、仍未做完（下一轮）

1. **AUD-35 余项**：缩略图的 PNG 编码/落盘仍在 GUI 线程（约 2ms/张）。
2. **AUD-39 余项**：安装器仍未真跑 `ISCC`（SAC 拦截新构建），只有 dry-run 与文本级断言。
3. **AUD-41 余项**：仍有一批模块零测试（`media/clip.py`、`ui/feeding.py`、`content/modcontent.py` 等）。
4. **AUD-42 余项**：缩略图磁盘缓存没有 LRU 上限（只做了实例隔离）。
5. 迁移的 `unsupported` 仍计入失败清单（未装待办扩展时 `petcore migrate` 退出 1）。
