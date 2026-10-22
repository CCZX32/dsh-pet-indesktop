# PR 报告：P4-a 通用取数端口 + 天气 + 文件解读

- 分支：`feat/petcore-vpet-architecture`
- 基线：`b3329d6`
- 日期：2026-10-22
- 范围：`PETCORE-HANDOFF-PLAN-2026-10-22.md` §P4 的第一段（P4-a）

## 1. 修改文件说明

| 文件 | 改动 | 为什么 |
|---|---|---|
| `petcore/contracts/http.py`（新，110 行） | `HttpRequest/HttpResponse/HttpError`、`HttpPort` 协议 | 天气/歌词需要普通 GET；mod 不许 import 网络库，必须有端口 |
| `petcore/net/http.py`（+135） | `build_request`、`fetch_url`：单请求显式路由、共享 deadline、`max_bytes`、只在传输失败/500/502/504 换路由 | 主分支天气是「国内直连 + 海外代理」，进程级固定直连会让另一条路不可用 |
| `petcore/net/__init__.py`（+3/-1） | 导出 `build_request` / `fetch_url` | 与既有 `urlopen` 同层出口 |
| `petcore/contracts/host.py`（+2） | `HostPorts.http` | 端口装配位置 |
| `petcore/ui/ports.py`（+70） | `CoreHttpPort.request/get_json`；`build_ports` 装配 | mod 只拿端口，路由与分类留在 core |
| `petcore/ui/app.py`（+2） | `CoreHost.ports` 保存装配结果 | 受信设置页要能用同一个端口做「立即查看」 |
| `petcore/contracts/capabilities.py`（+1） | 新增 `files.read` | 文件解读读的是用户拖入的任意文本文件，原清单没有对应项 |
| `petcore/config.py`（+40） | 7 个全局键（天气 4 + 文件解读 3）与归一化 | 设置项必须有类型/范围约束；都是全局作用域（所有宠共享一份城市列表） |
| `petcore/ui/icons.py`（+3） | `weather` 图标 | 新菜单项不应退化成圆点占位 |
| `examples/petcore-mods/tool.weather/`（新，6 文件 971 行） | `logic.py` / `client.py` / `runtime.py` / `settings_page.py` / `host/__init__.py` / `mod.json` | 天气以 mod 形态落地；算法从主分支 `pet/weather.py` 搬运，删掉自带传输 |
| `examples/petcore-mods/tool.file-reader/`（新，5 文件 502 行） | `reader.py` / `runtime.py` / `settings_page.py` / `host/__init__.py` / `mod.json` | 拖文件解读；复用 Core 的投喂与 `on_drop`，自身只读 |
| `tests/test_petcore_http_port.py`（新，312 行 / 17 条） | 路由顺序、换路由条件、deadline、体积上限、错误映射 | 端口是新的公共契约，必须钉住 |
| `tests/test_petcore_weather_mod.py`（新，338 行 / 18 条） | 城市名幂等、候选匹配、两源解析、预算、运行时气泡、设置页往返 | 天气的全部纯逻辑与失败路径 |
| `tests/test_petcore_file_reader_mod.py`（新，314 行 / 15 条） | 扫描预算、有界读取、只读、drop 运行时、设置页 | 拖文件链路的完整性 |
| `tests/test_petcore_example_mods.py`（+2） | 新包进可加载/可安装清单 | 防止「目录存在但加载即报错」 |
| `tests/test_petcore_installer.py`（+5/-1） | 新任务与 `{app}\mods` 断言 | 安装器口径不能靠人工记忆 |
| `packaging/petcore.iss`（+6） | `mod_weather` / `mod_filereader`（unchecked，`{app}\mods\<id>` + `.trusted`） | 不勾选不写盘 |
| 文档 | SPEC §23、ROADMAP §23、MOD-FORMAT §11、ARCHITECTURE §14/§16/§17、parity backlog §2/§3.2/§11、examples README、`petcore/AGENTS.md` 四条红线、LOG `L045` + 索引 | 行为变化必须有唯一归属 |

## 2. 性能分析

测量环境：Windows 本机，`QT_QPA_PLATFORM=offscreen`，单次采样（psutil RSS +
`perf_counter`）。命令见 §3。**单次采样不是中位数**，只用于量级判断。

| 路径 | 结果 | 触发频率 |
|---|---|---|
| `import petcore.net.http` | +6.1 MB / 37.5 ms | 首次取数（惰性 import，启动不加载） |
| `import petcore.contracts.http` | +2.2 MB / 22.1 ms | 启动装配端口时 |
| `import petcore.ui.ports`（含 `CoreHttpPort` 定义） | +9.2 MB / 77.2 ms | 启动既有路径，P4-a 只加类定义，没有新模块依赖 |
| 构造 `CoreHttpPort` × 100 | +0.1 MB / 0.5 ms | 每进程一次 |
| 加载 `tool.weather` 包 | +6.9 MB / 27.4 ms | 仅安装并启用该 mod 时（未安装 = 0） |
| 加载 `tool.file-reader` 包 | +0.1 MB / 2.0 ms | 同上（Qt 已由 core 加载，本包无新增依赖） |

- **稳态开销**：两个 mod 都没有定时器/轮询/后台线程常驻；`tool.weather` 只在右键
  「天气」或设置「立即查看」时发请求，`tool.file-reader` 只在 drop 事件后启动一次
  线程，完成后退出。零请求 = 零网络。
- **新增路径成本**：单次天气请求 2 跳（CN 检索 + 实况），实测 0.24–0.26 s；
  open-meteo 兜底 2 跳 4.51 s。失败路径上限是 15 s 总预算（预算耗尽不再发请求）。
- **磁盘**：不写缓存、不写临时文件；文件解读只读被拖入的文件，读取量上限
  200000 字符/次，扫描上限 20000 文件 / 2 s。
- **线程**：每次天气查询 1 个 daemon 线程；每次文件解读 1 个 daemon 线程
  （+ 可选心跳定时器，完成/失败都会 `cancel`）。
- **GUI 线程上的有界工作**：drop 事件里的 `path.is_file()` 扫描与文本读取在主线程执行，
  但有两道硬闸（20000 文件 / 2 秒、200000 字符）；这与 Core 既有投喂测量
  （`engine/feeding.py`）同一口径，不是新增的无界阻塞。想再省可以把扫描移进线程，
  但会改变「拖进来立刻有反应」的手感，本段不做。

## 3. 实机运行记录

### 3.1 真实取数（`CoreHttpPort`，本机网络）

```text
鹿城 -> 鹿城 多云 20.3℃，西风 1级，湿度 58%（中国天气网） | 0.26s
北京 -> 北京 多云 11.3℃，南风 2级，湿度 52%（中国天气网） | 0.24s
open-meteo -> 上海 局部多云 17.7℃，东北风 2级，湿度 71%（open-meteo） | 4.51s
不存在的城市名 FAIL | 天气获取失败（不存在的城市名）：中国天气网：没有找到这个城市；open-meteo：没有找到这个城市 | 1.86s
```

命令：`QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 .venv/Scripts/python` 直接调用
`WeatherClient(CoreHttpPort())`（脚本见 `L045` 记录的口径）。失败用例证明两源原因都
会出现，不会静默。

### 3.2 门禁

```text
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py -q
→ 881 passed in 68.19s

.venv/Scripts/ruff check petcore/... examples/petcore-mods/tool.* tests/test_petcore_*
→ All checks passed
```

新增 50 条测试（http 17 / weather 18 / file-reader 15），覆盖：路由顺序与换路由条件、
共享 deadline、体积上限、错误映射、城市名幂等与候选匹配、两源解析、预算耗尽、
运行时气泡与失败可见、drop 只读与扫描预算、设置页保存/回滚。

### 3.3 安装包

`--root` 临时数据根（`petcore mods install` + `.trusted`）：

```text
installed tool.weather 1.0.0 -> .scratch\p4a-root\mods\tool.weather
installed tool.file-reader 1.0.0 -> .scratch\p4a-root\mods\tool.file-reader
--check: diagnostics=[]；tool.weather enabled=True；tool.file-reader enabled=True
```

冻结包：用 `scripts/build_petcore.ps1 -Clean -Installer
-SignThumbprint 217337C099EC8624AC481BFC9F3E1664D0A442E1` 重建（Successful compile
157 s，`dist/dsh-pet-core-setup.exe` 257,488,664 字节，签名 `CN=DSH Pet Core Dev`），
静默安装到 `E:\dsh-pet-core`（`/TASKS` 含 `mod_weather,mod_filereader`）：

```text
E:\dsh-pet-core\mods\tool.weather\{mod.json,host\,.trusted}
E:\dsh-pet-core\mods\tool.file-reader\{mod.json,host\,.trusted}
--check（安装版 exe + 临时 --root）：diagnostics=[]；
tool.weather 1.0.0 enabled=True（E:\dsh-pet-core\mods\tool.weather），
tool.file-reader 1.0.0 enabled=True（E:\dsh-pet-core\mods\tool.file-reader）
```

安装后启动 `E:\dsh-pet-core\dsh-pet-core.exe`，8 秒后进程存活（PID 23652，RSS 98.9 MB）。

## 4. 未验证 / 限制

- 天气「明天」与逐城市子菜单未做（主分支右键也没有逐城市子菜单；动态子菜单需要
  新的 mod 菜单 populate 端口，留 P4-c 与菜单模板批次一起评估）。
- 文件解读依赖 `file_feeding_enabled`：关闭投喂时 Core 不会派发 drop 事件（已在
  MOD-FORMAT §8 写明）。
- 两个 mod 的设置页只做了离屏测试，未在真实 125% DPI / 900×620 下逐项对照。
- `files.read` 是声明性能力，不是沙箱：拿到 drop 事件后 mod 可以读任意文本文件。
- 天气解析依赖中国天气网的 `var dataSK=` 私有格式，站点改版会退到 open-meteo。
