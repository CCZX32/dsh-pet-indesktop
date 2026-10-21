# petcore 主分支功能矩阵（2026-10-22）

> 基线：主分支 `147170f` 与重写分支 `0922b13`。本表是 P0 审查快照，
> 不是运行时契约；实现状态以后续 `PETCORE-MAIN-PARITY-BACKLOG.md` 为准。

| 功能域 | 主分支能力 | petcore 状态 | 目标阶段 | 证据/限制 |
|---|---|---|---|---|
| 桌宠窗口与输入 | 透明窗口、穿透、拖拽、置顶、托盘、锁定、Shift 拖动 | 已对齐 | 保持 | petcore geometry/interaction tests；非 Windows 未实机 |
| 动画与物理 | 待机节拍、行为权重、拖拽、弹弓、回旋、碰撞、投喂 | 基础已对齐 | P2 | 仍缺完整 Graph 类别入口 |
| 边缘探头 | 贴边探头、点击拉直、自动回探头 | 已对齐 | 保持 | Windows 单屏已验，多屏/跨平台未验 |
| 多宠 | 单进程多宠、独立位置和每宠配置、碰撞、逐宠退出 | 窗口/碰撞已实现，配置作用域有缺陷 | P1 | SettingsDialog 和 feature 当前读 host.config |
| 角色与素材 | 角色发现、热加载、角色包、WebM/GIF/帧序列 | CLI 和旧素材适配已实现 | P2 | GUI 导入缺失，媒体仍适配旧 `pet` |
| 菜单与设置 | 现代菜单、编排器、搜索、非模态设置 | Core 已实现 | 保持 | 业务域设置页尚未齐全 |
| 自言自语/点击台词 | 台词、配图、角色档案、朗读 | Core feature 已实现 | P1/P4 | 当前配置读取主宠 |
| AI 对话 | 会话、流式输出、Markdown、历史、模型路由 | 未实现 | P3 | Worker 只有协议 |
| 识屏/截图提问 | 截图、OCR、翻译、视觉模型、主动识屏 | 未实现 | P3 | 需要 worker 和隐私门 |
| Agent 联动 | DSH、Claude、Cursor、自定义 Agent、富事件状态 | 未实现 | P4 | 需要 worker/事件聚合 |
| API/账户/余额 | 服务规格、钥匙串、余额、缓存、自动刷新 | API 基础已实现，账户未实现 | P3 | `petcore/account/` 不存在 |
| 音乐 | 播放器入口、SMTC、歌名、歌词、唱歌动画 | 只有系统媒体键样板 | P4 | example 不应视作默认交付 |
| 语音 | TTS provider、音色、语速、口型、报时 | 只有简单报时样板 | P4 | provider 和缓存未迁移 |
| 待办/节日/抽签 | 面板、提醒、节日、每日一签、语音 | 仅 example mod | P2/P4 | 计划默认随安装包安装 |
| 天气/文件识别 | 城市天气、拖文件解读 | 未实现 | P4 | 网络和 worker 域 |
| 灵动岛 | 胶囊、段化、聊天、指标、碰撞 | 未实现 | P5 | 独立 UI 宿主 |
| 性能治理 | 隐藏态低功耗、共享解码、预热、FPS/GPU/网络 | 大部分未实现 | P5 | 需要稳定性能预算 |
| 更新与发布 | 在线更新、回滚、三端构建、安装卸载 | 有基础构建，缺切换/E2E | P5/P6 | 真实安装升级尚未跑通 |
| VPet 素材 | LPS/PNG 角色包 | 有架构参考，无运行时支持 | 非目标 | 只借鉴 Graph/寻址思想 |

## 有意差异

- 播放速率保持 petcore 当前 `0.5–2.0x`，不按主分支的高倍率范围扩张。
- VPet LPS/PNG 不进入本轮交付。
- petcore 首轮保持最多 16 只桌宠，身份容量扩展不作为本轮隐含承诺。

## 当前门禁快照

```text
petcore tests: 603 passed
petcore + architecture/report/CI guards: 900 passed, 5 skipped
ruff check pet/ tests/ petcore/: All checks passed
python -m petcore --check: exit 0
```

## 关键缺口

1. 每宠设置路径实际绑定主配置，必须在业务迁移前修复。
2. v4 配置、slot 配置、会话、待办、API 凭据和旧缓存没有迁移/回滚协议。
3. Worker 没有进程宿主，账户目录也没有实现。
4. 5 个 example mod 尚未成为默认安装能力。
5. 多屏、安装器端到端、非 Windows 窗口行为和完整媒体导入缺真实证据。
