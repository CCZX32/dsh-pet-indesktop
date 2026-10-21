# petcore 分阶段 AI 交接计划（2026-10-22）

本文件把 `PETCORE-ROADMAP.md` 的后续阶段拆成可以交给不同 AI 独立执行的工作包。
每个阶段从上一个阶段的提交开始，不能跳过前置契约。

## P0 审查与契约冻结

- 输入：主分支 `147170f`、petcore `0922b13`。
- 输出：功能矩阵、审查报告、Core/mod/worker 边界、配置作用域和迁移边界。
- 验收：矩阵覆盖主 README 的功能域；每项缺口有唯一阶段、测试命令和用户效果。
- 提交：`docs(petcore): freeze parity audit`。

## P1 Core 基础、配置作用域与迁移

- 负责：当前宠物上下文、每宠/全局配置、设置窗口绑定、feature ports、v4/slot 迁移、备份与回滚。
- 禁止：迁移业务功能；不要在本阶段实现 AI、音乐或 Agent。
- 验收：主宠和子宠改角色、缩放、播放速率、台词、音效互不污染；全局设置明确作用域；迁移失败不覆盖原文件。
- 提交：`feat(petcore): isolate per-pet configuration and migration`。

## P2 WorkerHost、媒体解耦与离线默认能力

- 负责：WorkerHost、JSONL 生命周期、媒体后端接口、完整 Graph 类别、GUI 角色导入、5 个 example mod 默认安装。
- 禁止：让业务 mod 直接 import Core 网络实现；不把 example mod 改成 Core 内置。
- 验收：真实子进程测试；安装包默认有待办/节日/抽签/报时/音乐；目录和 zip 角色都能导入预览。
- 提交：`feat(petcore): add worker host and offline parity mods`。

## P3 API/账户与 AI/识屏

- 负责：`petcore/account/`、余额与缓存、AI 会话、截图/OCR/翻译、三个全局热键。
- 验收：每宠会话隔离；密钥不落日志；截图不写盘；Worker 取消/超时/崩溃有用户反馈。
- 提交：`feat(petcore): add account and worker AI capabilities`。

## P4 业务功能域

- 负责：Agent、TTS、音乐/歌词、待办/节日/抽签/报时、天气、文件识别。
- 验收：每个域有设置页、菜单入口、端口权限、失败/取消/隐藏态行为和 Windows 最小实机探针。
- 提交：`feat(petcore): migrate business feature domains`。

## P5 灵动岛、性能与系统能力

- 负责：灵动岛宿主、FPS/GPU/网络/内存诊断、隐藏态低功耗、共享解码、预热、更新和安装器 E2E。
- 验收：每项性能有环境、命令和样本量；真实冻结包完成安装、升级、卸载和回滚探针。
- 提交：`perf(petcore): add island diagnostics and runtime governance`。

## P6 多屏、跨平台与发布切换

- 负责：Windows 真双屏/混合 DPI、macOS/Linux 冒烟、发布入口切换、旧 `pet/` 兼容层收敛和可回滚发布。
- 验收：完整功能矩阵通过；无法实测的平台能力必须有探针结果和限制说明。
- 提交：`release(petcore): switch entrypoint and complete platform acceptance`。

## 每阶段固定交付

1. 先写红测试，再改实现。
2. 跑受影响测试、ruff、必要的高负载时序测试。
3. 更新 `PETCORE-SPEC.md`、`PETCORE-ROADMAP.md`、`PETCORE-LOG.md`、`PETCORE-LOG-INDEX.md`。
4. 更新差距台账、架构文档和 `docs/INDEX.md`（如事实发生变化）。
5. 报告必须包含修改文件说明、性能分析、实机运行记录、测试、限制和回滚。
6. 阶段完成后创建一个可运行的本地 git commit。
