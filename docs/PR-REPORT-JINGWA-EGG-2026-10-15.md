# PR 报告：品牌图标对——DS 鲸鱼与鲸蛙互相出场（截图问答标题 / 加载动画 / 菜单）

> **基线**：`99bdc7f`（main，含 #277）
> **分支**：`feat/jingwa-easter-egg`　**日期**：2026-10-15
> **范围**：8 个文件（实现 4、测试 3、素材 1、文档 1）
> **关联**：用户点单的品牌图标需求（鲸蛙素材由用户提供，豆包 AI 生成图处理）

## 一、核心特性

DeepSeek 鲸鱼（`ds_whale.png`，既有吉祥物）与鲸蛙（`jingwa.png`，新素材）组成
**一对互相出场的品牌图标**：

| # | 位置 | 形态 |
|---|---|---|
| 1 | 截图问答浮窗标题栏 | 每次开新会话随机抽一只摆在标题前（各 50%）；标题文字恒为「截图问答」不变 |
| 2 | 结果面板加载动画（提取文字/翻译过程态） | 两只轮流当浮动主角（约 1.2s 互换 + 轻微缩放脉冲），泡泡动画不变 |
| 3 | 右键菜单「截图」入口 | 鲸蛙图标（品牌对里鲸蛙的固定岗位） |

素材缺席纪律：两个图标各自独立回退——截图问答标题不显示图标、加载动画只剩
一只就单独浮动、全缺席回退三点跳动、菜单回退矢量图标。绝不让图标成为故障点。

**红线 / 不变量**：截图问答的会话/发送/隐私链路零触碰；加载动画的既有行为
（停表时机、防抢焦、泡泡 accent 色）不变；菜单入口的回调与可用性判定不变；
素材加载全部走「`_MEIPASS` → 源码树」双候选 + 进程内缓存。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/screen_capture/brand_icons.py` | +55（新增） | 品牌图标对的唯一加载点：`load_ds_whale`/`load_jingwa`（双候选 + 进程内缓存 + 空图回退）、`pick_brand_icon`（二选一 50/50；只剩一只时它就是答案，不掷骰） |
| `pet/screen_capture/ask_dialog.py` | +52 / −5 | 标题栏固定图标位：`_pick_title_icon`（每次开新会话抽一只）+ `_refresh_egg_icon`（按屏 DPR 出图；`showEvent` 与 `screenChanged` 只重出图不重抽）；`_egg_scaled` 留档供测试核对（`QLabel.pixmap()` 在 offscreen 下归一化 DPR，读它验不了 HiDPI） |
| `pet/screen_capture/result_panel.py` | +31 / −24 | `_LoadingFish` 主角从单只鲸鱼改为图标对轮换（`_current_icon` 相位取模 + 换场缩放脉冲）；素材加载收编进 `brand_icons`（删自带的 `_load_whale`）；泡泡与三点回退逐位不变 |
| `pet/context_menus/shared.py` | +20 / −2 | `add_action` 加 `icon=` 预建图标覆盖（缺省走原矢量查找，其它调用点零影响）；`_jingwa_menu_icon`（鲸蛙素材 → 缺席回退矢量 'size'）；「截图」入口换用鲸蛙图标 |

### 素材

| 文件 | 说明 |
|---|---|
| `assets/chat/jingwa.png` | 鲸蛙图标：用户提供图裁掉右下角「豆包AI生成」水印、边界洪水填充去白底（保住白肚皮）、边缘 0.6px 羽化；847×682 RGBA ≈ 250KB。`assets/chat/` 本就在三端 add-data 清单（build_onedir.ps1:348 / build_macos.sh:139 / build_linux.sh:134），**零构建改动** |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_screen_capture_ask_dialog.py` | +72 / −0 | 五条：图标出场且标题不变、素材缺席隐藏不炸窗、每次开重抽 + 换屏只重出图不重抽、DPR 跟随（注入缝 48px@dpr2）、`pick_brand_icon` 单在场/全缺席语义 |
| `tests/test_screen_capture_result_panel.py` | +30 / −0 | 两条：图标对随相位轮换（相位过换场点换主角）、单素材不轮换 + 全缺席回退三点 |
| `tests/test_menu_layout.py` | +15 / −0 | 一条：「截图」菜单项图标非空（鲸蛙在岗） |

红→绿取证：首版彩蛋测试在实现前全红（`_egg_icon` 属性不存在，
`AttributeError`）；返修轮每轮的红点关键行记录在各自提交信息里。

### 未改动（有意）

- 截图问答标题文字：恒为「截图问答」（第一版草案的 10% 变「鲸蛙问答」被产品
  方向否决——用图标代替文字变化）。
- 动作条（框选后那一排）不加图标：它已经是纯文字五键的紧凑形态，加图标
  会挤坏既有行高；品牌对的出场面按用户点单收在标题栏/加载动画/菜单三处。

## 三、实现要点

**为什么抽 `brand_icons.py` 独立模块**：两个加载点（ask_dialog、result_panel）
加一个菜单点（shared.py）共用同一对素材与同一套双候选路径；各自写一遍就是
三份漂移的候选清单。模块内进程内缓存（首次后零 IO），菜单高频打开零成本。

**加载动画轮换**：不换控件不重建，只在 `paintEvent` 里按相位取模选主角
（`_phase` 步进 0.13/50ms，3.1 相位 ≈ 1.2s 换场），互换瞬间 1/8 周期内
10% 缩放脉冲回弹；单素材时永不换场。泡泡相位与 accent 色断言
（`test_a_loading_result_actually_paints_something`）保持绿。

**HiDPI**：标题图标按 `devicePixelRatioF` 出物理像素 + `setDevicePixelRatio`；
掷骰在 show 之前而选区定位在 showEvent，换屏后 `screenChanged` 重出图
（不重新抽）。加载动画走 `drawPixmap` 逻辑尺寸（Qt 自处理 DPR），无需特判。

## 四、性能分析

实测（本机 Windows 11，Python 3.13，offscreen QApplication）：

| 路径 | 实测 | 触发频率 |
|---|---|---|
| 品牌图标加载（首次，含 PNG 解码） | 0.65 ms/次（n=100，`_jingwa_pixmap` 同口径探针） | 进程内一次（缓存后零 IO） |
| `pick_brand_icon`（缓存命中后） | ≈0.1 µs/次（一次 `random.random()` + 缓存读） | 每次开截图问答一次 |
| 加载动画换场 | 一次 `drawPixmap` 选择，无新对象 | 每 50ms tick 的既有绘制里 |

无新增线程/定时器/网络/进程；加载动画的 QTimer 是既有件（停表时机不变）。

## 五、实机运行记录

- 素材处理人工目检：水印无残留、白底透明、鲸鱼白肚皮完好、边缘无白边（见图
  `assets/chat/jingwa.png`）。
- offscreen 渲染核对：截图问答命中形态（图标在标题左、布局无挤压）；加载动画
  渲染测试断言动画区非空白且 accent 泡泡在（既有用例绿）。
- 说明：offscreen 无 CJK 字体，渲染图文字为方框属环境限制；真机观感（图标
  清晰度、轮换节奏）待发布后的用户反馈确认。

## 六、验证

- 识屏 + 菜单 11 个测试文件：**299 passed, 0 failed**
  （`QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:randomly` 对
  test_screen_capture_* / test_menu_* / test_context_menu_* 等族）。
- `ruff check pet/ tests/` 干净。
- 全量套件与双盲审结论见 PR 描述。
