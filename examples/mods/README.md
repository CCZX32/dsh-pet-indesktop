# 可运行 MOD 样例

> **移植基线（2026-10-13，本仓库分支 `dlc/mod-center-port`）**：这三个样例移植自 DLC 分支
> `codex/phase3-worker`，保持**作者侧源码形态**（`mod.json` + `host/` + `worker-src/`）。
> DLC 的打包脚本（`scripts/build_mod_example.py` / `build_character_mod_example.py`）
> **未移植**，所以本仓库没有"一条命令把它打成可导入 ZIP"的入口；MOD 中心按成品包的
> `manifest.json` 接入。逐项对照见 [MOD 教程 · 移植基线与现状](../../docs/modding/README.md#移植基线与现状2026-10-13)。

- `hello-local`：非官方 host-only，菜单 + 配置 + 设置草稿。
- `echo-worker`：非官方 host-worker，真实握手、请求、取消与退出。
- `persona-phrases.json`：现有台词导入格式，不是安装包。

**在本仓库直接可用的是 `persona-phrases.json`**（台词模板，见
[台词模板教程](../../docs/modding/PERSONA-TEMPLATES.md)）。`hello-local` / `echo-worker`
是**功能扩展**样例：本仓库尚未接入功能扩展宿主运行时，导入会被如实拒绝并说明原因
（见 [MOD 教程 · ZIP 导入探针缺陷](../../docs/modding/README.md#四zip-导入探针缺陷2026-10-10--2026-10-13-收口口径)）。

详细步骤与接口见 [MOD 教程](../../docs/modding/README.md)。输出到新的 `.scratch/` 目录，
原素材和已安装包都不修改。
