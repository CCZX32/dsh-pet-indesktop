# 显式便携模式（portable.json）2026-10-18

> 基线：分支 `dlc/mod-center-port`，提交范围 = 便携切片（`pet/runtime_layout.py` +
> `scripts/write_portable_marker.py` + `build_onedir.ps1` 的 zip 标记）。本文是**合同**：
> 标记格式、解析规则、哪些路径跟随便携根、哪些 OS 级契约不跟，以及当前验证边界。

## 1. 两种数据布局

| 模式 | 触发条件 | app 数据根 |
|---|---|---|
| 安装态 / 普通绿色包 | exe 旁没有 `portable.json` | Windows：`%APPDATA%\dsh-pet-standalone-<variant>` |
| 显式便携 | exe 旁有合法 `portable.json` | 标记里 `data` 指向的目录（相对 exe 目录） |

便携是**显式**的：没有标记就绝不猜。反过来，标记存在但不可用时**直接报错**，
不静默回退 `%APPDATA%`——否则用户以为数据在便携目录，实际写回了系统目录。

## 2. 标记格式

`portable.json` 与 exe 同级，内容（canonical）：

```json
{"schema":"dsh-pet-portable/v1","data":"data"}
```

- `schema` 必须逐字等于 `dsh-pet-portable/v1`；
- `data` 是**相对** exe 目录的路径，允许嵌套（如 `"user data/dsh-pet"`），
  不许绝对路径、盘符、UNC、`.`/`..` 段；
- 解析后必须仍在 exe 目录内（`resolve()` 之后仍是前缀）；
- 目标目录首次启动自动创建；已存在则原样复用，不动内容。

内容唯一来源：`pet/runtime_layout.py::canonical_marker_text()`。构建脚本调用
`scripts/write_portable_marker.py --zip <zip>` 把标记追加到 zip 根目录，写入端与
读取端不会各抄一份 schema。

## 3. 校验规则（失败即报错）

按顺序：

1. 标记必须是普通文件（symlink / junction / reparse point 拒绝；目录拒绝）；
2. UTF-8（允许 BOM）JSON 对象，schema 与 `data` 合法；
3. exe 目录到数据目录之间任何**已存在**的段都不能是 reparse point（防 junction 逃逸）；
4. Windows 卷必须是 **NTFS**（v1 不支持 exFAT/FAT）；
5. 数据目录可创建、是目录、不是 reparse point；
6. 可写探针（创建并删除一个临时文件）。

错误以 `pet.runtime_layout.PortableLayoutError` 抛出：主进程在 `main()` 里捕获后弹
启动错误框并退出；`--settings` 进程同样弹框退出；其它入口（worker/预检/卸载清理）
按各自退出码失败。Windows 上目录的"只读"属性不可靠，因此**以可写探针为准**。

## 4. 跟随便携根的路径

统一入口是 `runtime_layout.app_data_dir()`，以下都由它派生：

| 路径 | 位置 |
|---|---|
| `Config.dir`（`config.json` / `config-slot-N.json` / 会话 / 日志 / 锁） | `<portable>/…` |
| 插件与官方功能包安装状态（`plugins.json`、`plugins/<id>`、`official-packages/`） | `<portable>/…` |
| 外部角色目录（`characters/`） | `<portable>/characters` |
| 歌词缓存、音效缓存、harness 探测缓存 | `<portable>/…` |
| 灵动岛用户扩展根 | `<portable>/island-extensions`（`ROOT_DIR_NAME`） |
| 单实例门、设置锁、IPC 锁 | `<portable>/…` |

安装态这些路径与改动前逐字一致（`tests/test_config_*`、`test_overlay_settings_command`、
`test_click_sound`、`test_music_lyric` 等既有用例锁定）。

## 5. 不跟随便携根的 OS 级契约

- **开机自启**：注册表 `Run` 值 / Linux autostart 文件仍按 OS 规则登记，指向 exe；
- **DSH 桥接目录**：`%APPDATA%\dsh-pet-bridge` 是外部 DSH 插件的读取契约，
  搬走会让集成失效，因此不随 app 数据根迁移；
- **Qt `QStandardPaths` 文档位置**：本产品没有用户文档依赖它。

## 6. 打包与发布

- `scripts/build_onedir.ps1` 默认在 `<name>-portable.zip` 根目录写 `portable.json`；
  `-NoPortableMarker` 产出不带标记的绿色包（安装态布局）。
- Inno Setup 安装包的 `[Files]` 基础复制**排除** `portable.json`：安装态绝不继承
  便携标记（构建树里残留标记也不会把安装版变成便携版）。
- 便携包与安装包共用同一份 exe 与 `features/`，区别只在数据根。

## 7. 边界与未验证项

- **同机同用户、NTFS**：跨机器/换用户需要重新授权（凭据不随包）；
- **Unicode 路径 / 空格路径**：可工作（`data` 支持空格段），但本轮未做专门的
  跨盘/只读介质人工验收；
- **卸载**：便携包没有卸载器；删除目录即卸载，`data\` 随目录一起删除。安装版
  卸载器只删安装器记录的文件，便携标记本身被排除在复制之外；
- **数据迁移**：便携模式**不**自动从 `%APPDATA%` 导入旧数据（显式模式不偷偷读写
  系统目录）。需要在便携包里继续用旧数据时，手动把旧数据目录内容放进
  `data\`（同用户、同版本目录布局）。
- 本机验证证据见 [`PR-REPORT-PORTABLE-SETUP-2026-10-18.md`](PR-REPORT-PORTABLE-SETUP-2026-10-18.md)；
  Inno Setup 编译/安装/卸载证据见同一报告。
