# PR 报告：P4-b 语音端口 + 报时 + 音乐歌词 + 动画循环

- 分支：`feat/petcore-vpet-architecture`
- 基线：`d869d942`（P4-a）
- 日期：2026-10-22
- 范围：`PETCORE-HANDOFF-PLAN-2026-10-22.md` §P4 的第二段（P4-b）

## 1. 修改文件说明

| 文件 | 改动 | 为什么 |
|---|---|---|
| `petcore/contracts/speech.py`（新，111） | `SpeechRequest/SpeechResult/SpeechProviderInfo/SpeechError/SpeechPort` | mod 需要「说话」，但不该自己合成、更不该碰网络 |
| `petcore/net/tts.py`（新，603） | edge-tts(WSS)、豆包 SSE、MiMo(OpenAI 兼容)、provider 规格与默认音色 | 第三方 TTS 网络栈只允许出现在 `net/` |
| `petcore/speech/cache.py`（112） | `cache/tts` 下 sha1 命名、非空才命中、失败即删、按 mtime 裁剪 | 0 字节缓存是边缘 TTS 的经典静音源 |
| `petcore/speech/service.py`（341） | 后端链、无网预检换默认音色、2 次重试 + 默认兜底、密钥读写 | 把「失效音色/瞬时 429」变成可恢复 |
| `petcore/platform/sapi.py`（212） | Windows SAPI5（ctypes COM + 线程 CoInitialize） | 断网也能出声，且不依赖 Qt |
| `petcore/contracts/host.py`（+4/-1） | `play_animation(loop=)` / `release_loop()`、`HostPorts.speech` | 唱跳/报时需要持续动作；合成需要端口 |
| `petcore/ui/ports.py`（+132/-2） | `CoreSpeechPort`：后台合成、共享音频通道、stop/playing、GUI 线程回调 | 播放与线程归 core，mod 只发请求 |
| `petcore/ui/pet_window.py`（+19/-1） | `_loop_active` + `_play_spec()` 唯一清除点 + `_on_finished()` 接管解除 | 循环不能绕过探头/击飞的素材闸门 |
| `petcore/ui/app.py`（+11/-2） | 适配器转发 loop/release；`CoreHost.speech` | 装配点 |
| `petcore/config.py`（+176） | `speech_*` 8 + `voice_chime_*` 11 + `music_*` 10，全局作用域与归一化 | 设置页保存后重启不丢；运行时时区/范围受控 |
| `examples/petcore-mods/voice.chime/**`（1.1.0） | 删旧 `factory.py`（-134）；`schedule/quotes/runtime/settings_page/host/__init__` | 日程与台词留在 mod，合成改走端口；运行时无 Qt |
| `examples/petcore-mods/media.music/**`（1.1.0） | `now_playing/lyrics/players/runtime/settings_page`；`factory.py` 变包入口 shim（+38/-140） | 从「媒体键样板」升级为真正的 Now Playing + 歌词 + 唱跳 |
| `tests/test_petcore_speech.py`（464 / 16） | 缓存、重试、预检、密钥、provider 可用性、CoreSpeechPort 回调、配置归一化 | 合成链路的失败模式必须钉住 |
| `tests/test_petcore_chime_mod.py`（478 / 25） | 日程数学、台词轮换、免打扰、错误气泡、预缓存单线程、设置页 | 报时的「到点/只响一次/静默」全是易错点 |
| `tests/test_petcore_music_mod.py`（683 / 29） | LRC/偏移、两源回退、缓存、唱跳状态机、歌词节流、设置页 | 音乐链路最长，回归成本最高 |
| `tests/test_petcore_interaction.py`（+54 / 3） | 循环重播、接管解除、`_play_spec` 清除 | 循环接缝是新的公共行为 |
| `petcore/cli.py`（+34） | `--check` 新增 `speech` 字段：后端、缓存目录、每家 provider 可用性 | 冻结包是否真的带 edge-tts/winrt/pycaw，必须有一条可复核的证据 |
| `scripts/build_petcore.ps1`（+8/-1） | 收集 `edge_tts`、`winrt.windows.media.*`、`pycaw` | 惰性 import 在冻结包里不会自动被收集 |
| 文档 | SPEC §24、ROADMAP §24、MOD-FORMAT §12、ARCHITECTURE §14、ANIMATION-BACKLOG、parity backlog、examples README、`petcore/AGENTS.md`、LOG `L046` + 索引 | 行为变化必须有唯一归属 |

## 2. 性能分析

环境：Windows 本机、`QT_QPA_PLATFORM=offscreen`、单次采样（psutil RSS + `perf_counter`）。
单次采样不是中位数，只用于量级判断。

| 路径 | 结果 | 触发频率 |
|---|---|---|
| `import petcore.contracts.speech` | +3.5 MB / 31.5 ms | 启动装配端口时一次 |
| `import petcore.speech.service` | +1.9 MB / 9.1 ms | 同上（惰性） |
| `import petcore.net.tts` | +5.3 MB / 46.6 ms | **首次真正合成**才加载；启动不加载 |
| `import petcore.platform.sapi` | +0.0 MB / 0.9 ms | 首次 SAPI 合成（惰性） |
| `SpeechService()` | +0.0 MB / 0.0 ms | 每进程一次 |
| 加载 `voice.chime` 包 | +14.5 MB / 86.3 ms | 仅安装并启用时（含设置页 Qt 控件） |
| 加载 `media.music` 包 | +1.5 MB / 13.6 ms | 同上 |

- **稳态开销**：`voice.chime` 一个 25s 定时器（没到点直接 return）；`media.music` 一个
  1s 轮询，`poll()` 实测 **1.0 µs**（GUI 线程只做比较），SMTC 读取在常驻 worker 线程
  （1.3–37.4 ms，median 1.6 ms，冷启动），同一时刻只允许一个读取。
- **新增路径成本**：edge 首次合成 3.39s（26,208 B），缓存命中 0.0s；SAPI 97,234 B；
  `speech_backend="sapi"` 命中 0.25s；歌词一次抓取 33 行 0.66s（酷狗源）。
- **网络**：只在用户点「立即报时/试听」、到点报时、检测到播放时抓歌词；无播放器 /
  免打扰 / 关闭功能 = 零请求。歌词与 TTS 都不落盘音频以外的内容。
- **线程**：chime 每次合成 1 个 daemon 线程（预缓存最多 1 个）；music 1 个常驻 SMTC
  worker + 每首歌 1 个歌词线程（in-flight 去重）。没有新增进程。
- **磁盘**：TTS 缓存在 `<data_root>/cache/tts`（默认上限 200 个文件）；歌词缓存
  在 `data_dir/media.music/lyrics`（默认 80 条）；都按 mtime 裁剪。

## 3. 实机运行记录

```text
# 真实合成（本机）
edge_synthesize -> .scratch/tts-probe/edge.mp3  26,208 B  3.39 s
SpeechService(edge) -> miss 15,552 B 2.92 s / hit 0.0 s
speech_backend=sapi -> 118,834 B .wav, cache hit 0.25 s
SAPI voices: Huihui (zh-CN), Zira (en-US)

# 真实合成（走新配置 + SpeechService，本机复测）
providers: edge=True/sapi=True/doubao=False/mimo=False（无 Key）
first:  edge zh-CN-XiaoxiaoNeural 20,304 B cached=False 2.99 s
second: cached=True 0.000 s

# 真实歌词（CoreHttpPort）
fetch_lyrics("...") -> 33 lines, source=酷狗 0.66 s
（网易云搜索只返回翻唱且歌手不匹配 → 按设计回退）

# SMTC（本机没有正在播放的会话）
get_now_playing() -> None, reason=系统里没有正在播放的媒体会话。, 47 ms
transport("pause") -> 当前没有可控制的播放器…
open_netease -> 还没有配置网易云音乐的路径…

# 真实 Qt 循环（QtScheduler + offscreen）
2 polls in 2.6 s, worker joined on stop

# 配置落盘往返（Config.save → Config.load）
voice_chime_times ["9:05","25:00","07:30"] -> ["07:30","09:05"]（非法项丢弃并排序）
voice_chime_rate 9.0 -> 2.0；music_lyric_cache_limit 9999 -> 2000
music_player_paths {"netease":"C:/x.exe","bad":3} -> {"netease":"C:/x.exe"}
speech_backend/fallback -> edge / sapi
```

门禁：

```text
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
  tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
→ 1282 passed in 68.18s

.venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods → All checks passed
python -m petcore --check → exit 0
```

新增 74 条测试（speech 17 / chime 25 / music 29 / 循环 3），既有测试零删除。

### 3.3 冻结包与安装

```text
build: Successful compile 110.9 s
dist/dsh-pet-core-setup.exe  258,499,016 B  签名 CN=DSH Pet Core Dev, O=DSH Pet, C=CN
install: /SILENT /TASKS="mod_aichat,mod_ocr,mod_divination,mod_festival,mod_todo,
         mod_chime,mod_music,mod_weather,mod_filereader" -> E:\dsh-pet-core  exit 0

installed exe --check（临时 --root）:
  diagnostics: []
  voice.chime 1.1.0 enabled=True
  media.music 1.1.0 enabled=True
  speech.backend=edge  fallback=sapi
  speech.providers: edge available=True / sapi available=True /
                    doubao available=False(reason=auth) / mimo available=False(reason=auth)

启动 E:\dsh-pet-core\dsh-pet-core.exe，8 秒后进程存活（PID 20528，RSS 108.6 MB）
```

`edge` 在冻结包里 `available=True` 证明 `edge_tts` 真的进了 PYZ（PYZ-00.toc 里 28 条
`edge_tts*`，另含 `pycaw` 与 `winrt.windows.media.*`）。**冻结包内的真实发声**仍需在
安装版里点一次「立即报时/试听」；本报告只验证到模块存在与源树真实合成。

## 4. 未验证 / 限制

- **真实播放器下的唱跳与逐行歌词**未验证：本机没有正在播放的媒体会话，动画与歌词
  只覆盖到「检测/状态机/节流」层。
- 豆包与 MiMo 真实合成无 Key（两者报 `auth`）；字段与错误分类已测。豆包的 `pitch`
  未移植 ffmpeg `asetrate`，该字段对豆包无效。
- 口型（lip-sync）主分支也未实现，不在本轮。
- `release_loop()` 不硬切：当前这圈播完才回行为链（最长一个 clip）。
- `voice.chime` 的预缓存线程是 daemon、`stop()` 不 join；阻塞的网络合成不会拖住退出，
  但也可能在退出瞬间被丢弃（下一次到点会重新合成）。
- 冻结包已重建并安装，`--check` 证明 `edge_tts`/`winrt`/`pycaw` 进了 PYZ；**但没有在
  安装版界面里点过「试听/立即报时」**，冻结包内的真实发声仍属未验证项。
