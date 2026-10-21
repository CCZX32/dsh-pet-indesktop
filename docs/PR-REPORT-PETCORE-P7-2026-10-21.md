# petcore P7：探头/击飞、安装器、扩展管理与彩蛋音效（2026-10-21）

> **基线**：`feat/petcore-vpet-architecture`（P6 收口）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-21
> **范围**：探头/击飞状态机、安装器图标与扩展安装位置、扩展管理导航、彩蛋图片、点击音效

## 一、核心特性

| # | 能力 | 说明 |
|---|---|---|
| 1 | 击飞旋转 | 探头宠物被另一只撞飞时先 `arm_throw_egg()` 再退出探头；飞行中整帧角度跟随速度，落地回正 |
| 2 | 飞行接管态 | `motion.thrown` 期间不掷骰、左键点击不换素材；落地后才回行为链（修「稳定前切动画」「两个位置闪」） |
| 3 | 探头素材闸门 | 探头/彩蛋激活时只允许 idle/转向，探头不翻朝向 |
| 4 | 安装器图标 | setup 与主 exe 都带 `assets/icon.ico`（鲸鱼娘）；卸载列表同图标 |
| 5 | 随附扩展位置 | 5 个选装扩展从 `%APPDATA%` 改到 `{app}\mods\<id>`，`.trusted` 逐包授权，随安装目录卸载 |
| 6 | 扩展管理 | 左侧竖向滚动导航 + 「基础扩展 / 加装扩展」分组；ModsPage 同口径过滤 |
| 7 | 中文名 | `mod.json` 新增 `name_zh`，13 个内置/示例包已补 |
| 8 | 彩蛋图片 | 菜单「工具与帮助 → 彩蛋图片」随机弹内置鲸鱼娘图片，可换目录/标题/开关 |
| 9 | 点击音效 | 默认 / 小黄鸭 / 自定义文件 / 文件夹；duck 补齐 wav；碰撞/碰边复用 |

**红线 / 不变量**

- 探头/飞行的位移语义不变（探头位置归 `EdgeProbeController`，飞行归 `MotionController`）。
- 安装器仍只在用户勾选时写盘；`.trusted` 与 `allow_feature_mods` 并行。
- 用户导入的扩展仍落数据目录，可在设置里卸载。

## 二、修改文件说明

### 实现

| 文件 | 改动意图 |
|---|---|
| `petcore/ui/pet_manager.py` | 碰撞确认重叠后先 `arm_throw_egg()` 再 cancel；低速碰撞立刻回正；碰撞音效走点击音源 |
| `petcore/ui/motion.py` | 删 `_throw_egg_armed`；tick 按 `effects.throw_egg_active` 更新角度；`stop()` 无条件回正；进入 thrown 回调 `_on_thrown()` |
| `petcore/ui/pet_window.py` | `_play_spec` 探头/彩蛋闸门；thrown 不掷骰；飞行点击忽略；`_on_thrown()`；彩蛋控制器；点击音效包接线 |
| `petcore/paths.py` | `is_frozen/install_root/install_mods_dir/user_mods_dirs`；`mods_dirs` 纳入安装目录 |
| `petcore/mods/loader.py` | feature 用户根=数据目录+安装目录；路径 resolve 后判定 |
| `petcore/ui/app.py` | feature 加载 allowed roots 同步 |
| `packaging/petcore.iss` | `SetupIconFile`/`UninstallDisplayIcon`；模组 `DestDir={app}\mods` |
| `scripts/build_petcore.ps1` | PyInstaller `--icon assets/icon.ico` |
| `petcore/mods/manifest.py` | `name_zh` 字段与校验/回退 |
| `petcore/contracts/contributions.py` | `SettingsPageSpec.owner/label/group` |
| `petcore/mods/feature.py` | 设置页带 owner/中文 label/分组 |
| 13 × `mod.json` | 补 `name_zh` |
| `petcore/ui/settings/page_extensions.py` | 左侧竖向导航 + 分组 + `tabs` 门面 |
| `petcore/ui/settings/page_mods.py` | 基础/加装过滤、中文名、随包禁用卸载 |
| `petcore/ui/easter_egg.py` | 彩蛋弹窗控制器 |
| `petcore/media/click_sound.py` | 音效包解析与随机选择 |
| `petcore/media/sound.py` | 非 wav 走 QMediaPlayer 缓存 |
| `petcore/config.py` | `click_sound_pack`、`easter_egg_*` 键 |
| `petcore/ui/settings/page_interaction.py` | 音效音源、彩蛋卡片 |
| `petcore/ui/menu_actions.py` / template / `coverage.py` | 彩蛋菜单入口 |
| `assets/sounds/duck/Ya1.wav`、`Ya2.wav` | mp3 转 wav（保留 mp3） |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_petcore_playback.py` | 新增 5 条探头/击飞/点击/碰撞用例 |
| `tests/test_petcore_installer.py`（新） | setup 图标、`{app}\mods`、frozen 路径、`.trusted` 加载 |
| `tests/test_petcore_extensions_nav.py`（新） | 分组/中文名/过滤/兼容门面/卸载禁用 |
| `tests/test_petcore_click_sound.py`（新） | 音效包解析、duck、随机、非 wav 分支 |
| `tests/test_petcore_easter_egg.py`（新） | 弹窗、空目录、禁用、配置 |
| `tests/test_petcore_p4_fixes.py` | motion 对无 effects 的测试替身保持容忍 |

### 未改动（故意）

- `pet/` 产品代码一行未改。
- 主分支的 `_effects_filter_switch` 只移植语义，不搬 legacy 窗口实现。

## 三、实现要点

- **授权顺序**：`arm_throw_egg()` 必须在 `edge_probe.cancel()` 之前（cancel 会复位姿态）；
  低速碰撞没有 `set_velocity` 切到 thrown，因此分离后检查 `motion.thrown` 并回正。
- **飞行接管**：`MotionController` 进入 thrown 时回调 `window._on_thrown()`，由窗口停 gap、
  停移动计划并绑定 RAISED_DYNAMIC → RAISED_STATIC → idle；`_on_finished` 在 thrown 期间
  只 re-arm，不进入掷骰链。
- **素材闸门**：所有播放都经 `_play_spec()`，因此探头/彩蛋闸门只有一处；turn 的
  `_pending_flip` 在锁定期强制 False。
- **安装路径**：`install_mods_dir()` 仅 frozen 生效，避免源码树把 `repo/mods` 误判成
  安装器授信目录；loader 与窗口加载共用 `paths.user_mods_dirs()`。
- **扩展导航**：`tabs` 门面保留旧 API，内部换竖向列表；分组由 `SettingsPageSpec.group`
  （builtin 或 `.trusted` → base）决定，列表与设置页只认这一处口径。
- **点击音效**：只解析候选，播放仍由 `SoundPlayer` 统一缓存；wav 走 QSoundEffect，
  其它后缀走 QMediaPlayer 池。

## 四、性能分析

- 探头/飞行闸门只在 `_play_spec()` 与 `_on_finished()` 增加常数级判断（每圈一次），
  不引入定时器或线程。
- 碰撞路径新增一次 `arm_throw_egg()` 与 `motion.thrown` 判断，代价在微秒级。
- 音效候选解析在热路径（每次点击）会 stat 目录：默认 builtin 只查 1 个文件；duck 查
  2 个；自定义文件夹上限 128。`_warm_interaction_assets()` 已预热播放器，但未缓存
  候选列表；如实机点击有目录 IO 感，可再加按配置版本缓存。
- 彩蛋图片只在用户点击菜单时读目录并解码一张，不占常驻内存。

## 五、实机运行记录

- 环境：Windows 11，Python 3.13.7，PySide6，`QT_QPA_PLATFORM=offscreen`。
- 门禁：`775 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 全绿；
  `petcore --check` 退出码 0。
- 探头/击飞探针（测试内）：探头宠物被 420px/s 的撞飞后 `motion.thrown=True`、
  `throw_egg_active=True`，速度 (600,0) 时角度 90°，`stop()` 后归零。
- 彩蛋探针（真实资产）：`assets/big_blue_fat_fish` 24 张可读图，`show()` 打开 1 个弹窗，
  `close_all()` 后为 0。
- 音效探针：default → `click.wav`；duck → `Ya1.wav/Ya2.wav`；文件夹按名排序；
  `SoundPlayer.prepare/play` 对两个 wav 均返回 True。
- 打包：`dist/dsh-pet-core-setup.exe` 185,740,254 字节；`ExtractAssociatedIcon` 取 setup 与
  主 exe 图标均为鲸鱼娘（32×32 PNG 目视确认）；主 exe `Subsystem=2`、`--check` 退出码 0；
  冻结包 `mod_dirs` 含 `<安装目录>/mods`，`_internal/assets/sounds/duck` 内含两个 wav。
- **未验证**：真实声卡试听、真实安装到自定义目录/Program Files 的权限与卸载清理、
  多屏彩蛋弹窗层级、真实桌面上的旋转手感。
