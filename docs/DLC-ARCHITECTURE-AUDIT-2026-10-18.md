# Core / DLC 架构审计（Phase 5C，2026-10-18）

> 基线：`dlc/mod-center-port`，Phase 5B 收尾后。
> 本文回答两个问题：**哪些领域已经变成可独立安装的官方包**、**哪些领域为什么
> 继续留在 Core**。结论必须能用文件、测试或探针复核；「建议」不算交付。

## 1. 已交付的官方功能包（7 个）

| 领域 | owner / factory | 形态 | 入口 | 证据 |
|---|---|---|---|---|
| AI 对话 | `official.ai-chat` / `ai-chat/v1` | host-only | 扩展 → AI 对话（包） | `features/ai-chat/`、`tests/test_ai_package_e2e.py` |
| 文件理解 | 随 AI 包 | host-only | 包窗开着时拖文件 | `pet/file_interpret_router.py`、`tests/test_file_interpret_router.py` |
| 屏幕理解 | `official.screen-understanding` / `screen-understanding/v1` | host-worker | 扩展 → 识屏 | `features/screen-understanding/`、`tests/test_screen_package_e2e.py` |
| 账户用量 | `official.account-usage` / `account-usage/v1` | host-only | 扩展 → 账户用量（包） | `features/account-usage/`、`tests/test_account_usage_package_e2e.py` |
| 音乐启动器 | `official.music` / `music/v1` | host-only | 扩展 → 四个播放器（包） | `features/music/`、`tests/test_music_package.py` |
| 语音报时 | `official.voice-chime` / `voice-chime/v1` | host-only | 扩展 → 立即报时（包） | `features/voice-chime/`、`tests/test_voice_chime_package.py` |
| 日常台词 | `official.persona-phrases` / `persona-phrases/v1` | host-only | 扩展 → 今日台词（包） | `features/persona-phrases/`、`tests/test_persona_package.py` |
| 快捷启动 | `official.quick-launch` / `quick-launch/v1` | host-only | 扩展 → 快捷启动 1..5（包） | `features/quick-launch/`、`tests/test_quick_launch_package.py` |

每个包的闭环口径一致：安装 / 启用 / 停用 / 卸载 / 重装都有测试；卸载保留
`feature-data/<owner>/`；包代码不得 import Core 业务模块；Setup 选装、首启回执、
冻结 probe 名单都已接线。

### 1.1 本阶段新增的公共能力端口

`pet/feature_ports.py` 的 `FeatureHostContext` 新增四个端口，由 Core 按 owner
注入，包拿不到窗口/全局配置对象：

| 端口 | 能力 | 生产实现 |
|---|---|---|
| `presentation` | 气泡、通知 | `AppShell` 注册的可见桌宠代理（`MultiWindowProxy` 语义面） |
| `scheduler` | owner 作用域 `QTimer`，`close()` 取消全部 | `pet/feature_host_bindings._BoundScheduler` |
| `audio` | 向 Core 唯一音频通道提交文本 | `AppShell.ensure_audio_channel()` |
| `credentials` | 显式操作集的 owner 作用域凭据 | `CredentialVaultPort(..., operations=...)` |

另新增声明式能力 `process.spawn`（音乐启动器、快捷启动），只表达「会启动用户
自己选择的程序」，仍是兼容性声明，不是沙箱权限。

## 2. 继续留在 Core 的领域与证据

| 领域 | 结论 | 证据 / 原因 |
|---|---|---|
| **Agent / 外部工具** | 保持 Core | 桥接目录 `%APPDATA%/dsh-pet-bridge` 是外部契约，监控线程与钩子安装在 `pet/agent_link.py`；v1 能力模型没有 `os.hooks` / 进程枚举端口，拆包会让外部契约出现第二份真相 |
| **生活提醒** | 保持 Phase-2 进程内插件 | 已有 `pet/plugins/builtin/festival_reminder/`（`PET_FESTIVAL_PLUGIN=1` 启用），行为与内置等价；节日数据约 2.95 MB、11 个 legacy 配置键，改成 DLC 会复制一份数据与配置真相。**决定**：继续 opt-in，默认切换属产品决策，本轮不改 |
| **灵动岛** | 保持 Core | `DynamicIsland` 与每屏 `ScreenHost`、窗口拓扑、`info_mode` 主槽强绑定；v1 没有「主信息槽贡献」端口，第三方 island 协议只增加 `island_metrics` 段（`pet/island_extension_host.py`） |
| **趣味互动** | 保持 Core（暂不拆） | `pet/fun_image_popup.py` 依赖窗口生命周期与本地素材授权；v1 没有图片/弹窗端口。只做气泡文案的「包」会伪装成该领域，不作为交付 |
| **Harness 启动** | 保持 Core | `pet/harness_launcher.py` 与托盘/自启/进程清理同一生命周期；用户的「快捷启动」已由 `official.quick-launch` 覆盖，Harness 本身不拆 |

## 3. 后续若要继续拆分，先补哪些能力

1. **`island.contribute`**：允许包提供一个只读主槽摘要或一个 metrics 段；需要先
   定义多屏时「谁的槽」与停用后的回退，不能直接暴露 `DynamicIsland`。
2. **`window.popup` / 素材端口**：趣味互动要显示图片，需要窗口生命周期与素材
   授权面，而不是把 `PetWindow` 交给包。
3. **`os.hooks` / `process.enumerate`**：Agent 联动要在不持有 Core 管理器对象
   的前提下观察进程/窗口；这比 `process.spawn` 的爆炸半径大，需单独评审。
4. **配置迁移面**：生活提醒要成为 DLC，先决定 11 个 legacy 键与 2.95 MB 数据
   的归属（迁移还是继续由 Core 提供读取端口）。

## 4. 新包检查清单（已固化到测试）

- `mod.json` + `host/factory.py::create_host`，host-only 清单 `worker: null`；
- 只 import `pet.mod_api.v1` 与自己的 host 模块，不 import Core 业务模块；
- 数据结构全部落 `feature-data/<owner>/`，密钥走 owner 作用域凭据库；
- 菜单/设置贡献的命令由包 Runtime 提供，停用后不再执行；
- 构建器产出目录 + ZIP 并用官方验签策略自检；
- Setup 选装、首启回执、`verify_frozen_mod_api` 名单同步更新；
- 卸载只删版本目录，保留个人数据；重装恢复；
- 结构 / 构建 / 绑定 / 生命周期测试齐全，最后过全量分片门。

## 5. 本阶段不改变的口径

- 内置域与官方包**并存**，不为「纯包」删掉内置实现；
- 不做签名，产物仍是 `local_user` 信任口径；
- Setup 反选不卸载，卸载走应用内 MOD 中心；
- 包 UI 仍落在「扩展」子菜单与 MOD 中心设置面板，不注入内置菜单的主位置。
