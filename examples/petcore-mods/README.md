# 可导入 petcore mod 样板

这 5 个目录是**可安装的 feature mod 包**，不是 core 内置：

- `fun.divination`：抽签
- `fun.festival`：公历节日提醒
- `reminder.todo`：待办清单
- `voice.chime`：系统 TTS 报时
- `media.music`：Windows 系统媒体键

## 安装

```bash
.venv/Scripts/python -m petcore mods install examples/petcore-mods/fun.divination
.venv/Scripts/python -m petcore mods install examples/petcore-mods/fun.festival
.venv/Scripts/python -m petcore mods install examples/petcore-mods/reminder.todo
.venv/Scripts/python -m petcore mods install examples/petcore-mods/voice.chime
.venv/Scripts/python -m petcore mods install examples/petcore-mods/media.music
```

或一键：

```bash
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/install_example_mods.ps1
```

安装后还必须在设置 →「扩展管理」勾选「允许功能扩展」，然后点「重新加载扩展」；也可以重新启动 petcore。
feature 包只从用户数据目录 `%APPDATA%/dsh-pet-core/mods/` 加载，仓库里的 `examples/` 不会被直接执行。

### Windows 安装包

正式安装包（`dist/dsh-pet-core-setup.exe`）默认勾选并安装这 5 个包，用户仍可在安装向导里取消，
装到 `%APPDATA%\dsh-pet-core\mods\<id>`，并附一个 `.trusted` 标记文件——那是
「安装器逐包授权」的证据，带着它就不需要再勾「允许功能扩展」。不勾选就完全不会
写盘；卸载时随目录一起删除。

## 包格式

```text
<id>/
  mod.json            schema=1 / kind=feature / execution=host-only / entrypoint
  host/factory.py     create_host(context) -> FeatureDefinition
```

规范见 [`../../docs/PETCORE-MOD-FORMAT.md`](../../docs/PETCORE-MOD-FORMAT.md)。

## 可用的宿主端口

`context.ports` 提供：

- `presentation`：`say` / `play_animation` / `notify`
- `scheduler`：`call_later` / `call_every` / `cancel`
- `storage`：`data_dir(owner)` / `config_dir(owner)`
- `interaction`：`on_click` / `on_drop` / `on_tick`
- `pets`：只读宠物句柄
- `quiet`：进程级免打扰

`context.host` 提供共享 `config` 与只读宿主信息；跨域能力仍应走端口/事件，不直接 import `pet.*`。

## 约定

- 有 `Contribution(kind="menu")` 的 mod 必须同时提供 `Contribution(kind="settings_page")`。
- 菜单项 id 在 Core 内统一为 `<owner>:<contribution>`。
- 安装后菜单贡献默认进入「扩展」子菜单；可在设置 →「菜单」拖到根或「工具与帮助」。
- 卸载只删除用户数据目录下的包；`examples/` 源目录不会被修改。
