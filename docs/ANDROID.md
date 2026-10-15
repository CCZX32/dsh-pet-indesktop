# Android 悬浮桌宠

基线：2026-10-15，Android 0.1.0 本地测试版。实现位于 `android/`，最低
Android 8.0（API 26），编译和目标 SDK 为 36。它是原生 Kotlin 客户端，
共用桌面项目的角色素材、定位框、移动曲线和默认台词。
实际验证范围与性能数字见 [本次交付报告](PR-REPORT-ANDROID-PET-2026-10-15.md)。
桌面安装包仍使用 [onedir 流程](ONEDIR_PACKAGING.md)。

## 安装和使用

测试包：`dist-android/dsh-pet-android-0.1.0-debug.apk`。

1. 将 APK 安装到 Android 手机，打开「深深桌宠」。
2. 点击「允许悬浮显示」，在系统页面授予「显示在其他应用上层」权限。
3. 返回应用，点击「启动」。Android 13 及以上会请求通知权限；拒绝通知
   不会冒充悬浮授权失败，仍可从应用内停止桌宠。
4. 点击宠物触发动作和台词，拖动改变位置，快速甩动并松手触发抛掷。
   长按打开设置、暂停/继续、停止菜单；点击菜单外或按返回键关闭菜单。
5. 通知栏与应用内都可以暂停、继续、停止。锁屏会移除悬浮窗并停止帧预取，
   解锁后恢复。系统强制停止后需重新打开应用手动启动。

首版单宠，内置 11 段待机/转向/移动/点击/拖拽动画。抛掷使用悬空动画。
没有登录、网络请求或后台云端服务。AI 聊天、识屏、电脑 Agent 联动、多宠、
商店上架和开机自启动不在这个测试版内。

系统设置、权限页面等可以主动隐藏第三方悬浮窗；这不代表授权被撤销。
系统键盘和状态栏也有更高的窗口层级。实现遵守这些系统边界，参见
[Android 悬浮窗](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_APPLICATION_OVERLAY)
与 [前台服务启动限制](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)。

## Windows 构建

在仓库根目录执行：

```powershell
./scripts/setup_android.ps1
./scripts/build_android.ps1
```

需要本项目 Python 依赖已可用；构建脚本优先使用 `.venv/Scripts/python.exe`，
也可通过 `-Python <解释器路径>` 指定。首次准备 Python 环境沿用仓库
`requirements.txt`。素材导出在构建机调用既有转换器，APK 不包含 Python、Qt
或 ffmpeg 可执行文件。

工具默认安装在 `%LOCALAPPDATA%/dsh-pet-android`：JDK 17、Android SDK、
platform-tools/adb、Build Tools 35.0.0。`-WithEmulator` 额外安装 API 35
Google APIs x86_64 模拟器。脚本校验 JDK、SDK 命令行工具及 Gradle 分发包
摘要；Gradle 官方分发不可达时允许使用校验相同 SHA-256 的镜像。
Java 仅在这些脚本进程中使用 Windows 信任的根证书，不关闭 TLS 校验。

Gradle Wrapper 固定为 8.11.1（含分发包 SHA-256），AGP 8.10.1、Kotlin
2.1.21，Compose BOM 2025.05.01。构建使用一个有界 Java 编译进程，结束后
退出，避免编译守护进程与模拟器长期竞争内存。

默认依次运行 Kotlin 单元测试、Android lint、APK 构建，成功后复制测试包到
`dist-android/` 并输出 SHA-256。设备测试可执行：

```powershell
./scripts/build_android.ps1 -Tasks connectedDebugAndroidTest
```

测试签名固定为当前用户的 `%USERPROFILE%/.android/debug.keystore`；同一密钥
可覆盖升级并保留偏好。该文件不入库，换机器需要自行保管并恢复同一测试密钥。
本测试签名不作为商店发布签名。安装可使用：

```powershell
& "$env:LOCALAPPDATA/dsh-pet-android/sdk/platform-tools/adb.exe" install -r dist-android/dsh-pet-android-0.1.0-debug.apk
```

## 资源与运行契约

- `export_android_assets.py` 使用现有帧序列供给代码准备素材，保留源视频的
  相对路径与大小写；只选 `idle/move/turn/click/drag`。缺动作、缺帧、非法
  定位框或透明通道都会使构建失败。生成物在 `android/app/build/`，不入库。
- `pet/manifest.json` 的 `schema_version=1`；包含画布、身体定位框、台词和
  动画列表。每段声明稳定 ID、源路径、帧率、帧数、帧目录、对称裁剪范围、
  步幅和位移曲线。原始 `body_box` 是位置/贴边锚点；裁剪只缩小悬浮窗。
- `PetEngine` 的坐标和物理计算使用源像素；服务把它映射到手机像素。
  触摸速度先按屏幕坐标求值，再转换为源单位。旋转和大小变更保留归一化位置。
- 解码器只有一个工作线程，合并旧请求，最多缓存三帧；显示帧和正在解码的帧
  另计。移除窗口时清理预取线程和缓存。绘制、窗口和状态变更归 Android 主线程。
- `PetOverlayService` 是进程内唯一悬浮宿主，重复启动幂等。
  Android 14+ 声明 `specialUse` 前台服务类型；仅由用户动作启动，使用
  `START_NOT_STICKY`。没有保活锁、重启广播或后台自动拉起。
- 手机偏好属于独立应用私有存储，不读写桌面版 `config.json` 或 slot 配置。
  生成素材与台词保持桌面数据单源，手机不维护另一份手工动画目录。

### 设置准入记录

参照 [设置变更门禁](SETTINGS-CHANGE-GATES.md)，手机使用独立原生界面，
Qt 窗口截图、桌面多 slot 和桌面菜单编辑器条目不适用。

| 设置 | 归属 | 默认/范围 | 保存与恢复 |
|---|---|---|---|
| `size` | 外观/大小 | 100%，60%–160% | 滑动结束保存并更新运行中的宠物；恢复默认回到 100% |
| `wander` | 互动/移动 | 开 | 即时保存，关闭后结束自主走动，手动拖拽可用 |
| `speech` | 互动/台词 | 开 | 即时保存，关闭时同时清理已显示气泡 |
| `x/y` | 运行状态 | 0.7/1.0，归一化到 0–1 | 拖拽结束、旋转、停止保存；恢复默认回到屏幕下方 |

启停、暂停和授权是命令或系统状态，不写成启动偏好。首版没有旧手机配置迁移；
缺键使用默认值，非有限大小/坐标回退默认并限制范围。恢复默认影响上述手机
偏好和位置；运行状态由当前服务管理。

## 设备验收与性能采样

在专用测试设备执行，脚本会切换本应用的悬浮权限、启动/停止应用和锁屏：

```powershell
$adb = "$env:LOCALAPPDATA/dsh-pet-android/sdk/platform-tools/adb.exe"
.venv/Scripts/python.exe scripts/android_acceptance.py --adb $adb --serial emulator-5554 --output .scratch/android-pet/acceptance
.venv/Scripts/python.exe scripts/android_acceptance.py --adb $adb --serial emulator-5554 --output .scratch/android-pet/soak --measure-only --minutes 30
```

第一条记录安装后授权失败/恢复、三次冷启动、跨应用、真实甩动、长按菜单、
暂停、锁屏和权限撤销；第二条对正在运行的桌宠采样 30 分钟，保存原始 CPU、
内存、绘制/解码计数和电池字段。真机应替换为 `adb devices -l` 中的手机序列号。
模拟器的电池、温度和 CPU 数据不能作为手机耗电或性能承诺。

素材署名与许可见 [第三方声明](../THIRD_PARTY_NOTICES.md) 第 2、9 节。
APK 内包含 `NOTICE.txt` 和 Apache-2.0 全文；角色素材继续限个人非商业用途。
