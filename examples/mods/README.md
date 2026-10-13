# 可运行 MOD 样例

> **移植基线（2026-10-13，本仓库分支 `dlc/mod-center-port`）**：这三个样例移植自 DLC 分支
> `codex/phase3-worker`，保持**作者侧源码形态**（`mod.json` + `host/` + `worker-src/`）。
> 打包入口已落地（D2/D3/D4）：`scripts/build_mod_example.py` 一条命令把它打成**可导入的
> 目录 + ZIP**，`--check` 或 `scripts/verify_feature_package.py` 做发布前自检
> （清单 + 验签 + 装前子进程预检）；`build_character_mod_example.py`（官方包构件）不在本仓库。
> 逐项对照见 [MOD 教程 · 移植基线与现状](../../docs/modding/README.md#移植基线与现状2026-10-13)。

- `hello-local`：非官方 host-only，菜单 + 配置 + 设置草稿。
- `echo-worker`：非官方 host-worker，真实握手、请求、取消与退出。
- `persona-phrases.json`：现有台词导入格式，不是安装包。

**`persona-phrases.json` 直接可用**（台词模板，见
[台词模板教程](../../docs/modding/PERSONA-TEMPLATES.md)）。`hello-local` / `echo-worker`
是**功能扩展**样例，先打包再导入：

```bash
python scripts/build_mod_example.py examples/mods/hello-local .scratch/my-mods/hello-local-1
python scripts/build_mod_example.py .scratch/my-mods/hello-local-1 --check
```

**源码目录不是包**：`examples/mods/hello-local` 里没有 `manifest.json`，直接拿它去导入会被
如实拒（`route_rejected`）——先过打包入口。`echo-worker` 那条 host-worker 路径需要冻结的
worker 可执行（`--worker-bundle`），本机不可验证。

详细步骤与接口见 [MOD 教程](../../docs/modding/README.md)。输出到新的 `.scratch/` 目录，
原素材和已安装包都不修改。
