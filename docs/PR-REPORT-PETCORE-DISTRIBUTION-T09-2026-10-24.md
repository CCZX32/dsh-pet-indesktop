# P4-c3-D2 / T09：性能对照、整仓门禁、安装器验收与发布准备（2026-10-24）

> 分支 `feat/petcore-vpet-architecture`。本批是 D2 的收口：把「能不能发」变成可核对的数字与流程，
> **不执行任何发布动作**（不建 tag、不传资产、不切默认源）。
> 关联：[发布手册](PETCORE-EXTENSIONS-RELEASE.md)、[T08 签名包](PR-REPORT-PETCORE-DISTRIBUTION-T08-2026-10-24.md)、[D1 验收说明](PETCORE-D1-ACCEPTANCE-2026-10-24.md)。

## 一、核心特性

1. **before/after 性能对照**（同一探针、同机、3 轮 15 s 预热 + 60 s 采样）：新增的逐跳校验、读流预算、
   解包计数与交叉校验**没有把路径拖慢**，中位差在噪声内，下载/解包的 p95 反而下降。
2. **整仓全量**：`pytest -q` 未过滤、正常退出，**9941 passed / 18 skipped / 20 warnings / 1220.48 s / exit 0**。
3. **安装器隔离验收**：静默装到 `.scratch`，四种任务组合逐一验证「不勾选完全不落盘、勾选才写 `mods/<id>` + `.trusted`」，
   每次卸载后目录与 HKCU 卸载项都清理干净。
4. **发布手册**：`docs/PETCORE-EXTENSIONS-RELEASE.md` 固化五步流程与每步回滚，明确 agent 不自动发布。

## 二、修改文件说明

| 文件 | 增/删 | 改了什么、为什么 |
|---|---:|---|
| `docs/PETCORE-EXTENSIONS-RELEASE.md`（新增） | +96 / −0 | 发布手册：产物摘要、三个先决确认、五步流程（重建/上传/索引/HTTPS 验收/可选切源）、逐步回滚、明确不做。 |
| `docs/PR-REPORT-PETCORE-DISTRIBUTION-T09-2026-10-24.md`（本报告） | 新增 | 性能对照、整仓与压力证据、安装器矩阵、发布准备边界。 |
| `docs/PETCORE-LOG.md` / `PETCORE-LOG-INDEX.md` | 见 L071 | 批次记录与索引。 |
| `docs/INDEX.md` / `docs/PETCORE-ROADMAP.md` / `docs/PETCORE-D1-ACCEPTANCE-2026-10-24.md` | 小幅 | 登记发布手册与 T09 状态；验收矩阵补「真实 HTTPS 未验」的最终口径。 |

产品代码零改动——T09 只做验收与发布文档；探针脚本全部在 `.scratch/petcore-p4c3-distribution/t09/`（gitignored）。

## 三、性能分析

### 3.1 before / after（同一探针 `before_perf.py` / `after_perf.py`）

环境：本机 Windows / Python 3.12.10 / PySide6 6.12.0；loopback HTTP + 合成包（下载 4 MiB、解包 8 MiB）；
每项 5 次预热 + 30 次测量；随后 3 轮「15 s 预热 + 60 s 采样」，每轮循环约 170–180 次。

| 操作 | before 中位 | after 中位 | 差值 | before p95 | after p95 |
|---|---:|---:|---:|---:|---:|
| 下载（新建） | 32.739 ms | 32.485 ms | −0.254 | 38.774 | 34.230 |
| 下载（续传） | 33.141 ms | 33.214 ms | +0.073 | 34.889 | 34.994 |
| 解包（8 MiB 展开） | 12.993 ms | 12.689 ms | −0.304 | 15.060 | 13.630 |
| 本地目录安装 | 38.512 ms | 37.328 ms | −1.184 | 40.433 | 42.493 |
| 市场页构造 | 13.369 ms | 13.865 ms | +0.496 | 17.270 | 14.777 |

- 中位差全部小于 1.2 ms；p95 上「下载 −4.5 ms、解包 −1.4 ms」是真实改善（读流预算提前截停 + 计数循环
  取代 `copyfileobj` 的整块写入）。
- CPU 中位：R1/R2 33.3% 对 33.3%，R3 40.95% → 33.3%；每轮计数 170–180 对 178–180，吞吐未退化。
- RSS：三轮 before 274/443/597 MB，after 273/440/607 MB（探针每轮构造约 180 个市场页且不 dispose，
  属探针自身累积；同口径下可比）。
- 结论：**没有新增稳态成本**；新增开销只在调用路径（每 206 一次头解析、每 64 KiB 一次计数、每次解包一次 `infolist()`）。

### 3.2 冻结包（T08 产物）

`--check` 715 ms；onedir 582 MB；setup 261,718,360 B；Inno 编译 96.296 s。GUI 启动 RSS ≈ 96 MB（单次采样）。

### 3.3 高负载复跑（受影响族 ×3）

7 个受影响测试文件（market net / transport security / archive limits / extension build / candidates /
market install / market ui）在 **20 个本次脚本自有的 CPU 负载进程**下连跑三遍；每轮开始前 1 秒采样均为 **100.0%**，
结束时负载进程全部回收（`stress.json`）：

| 轮次 | 负载前 CPU | 结果 | 用时 | 退出码 |
|---|---:|---|---:|---:|
| 1 | 100.0% | **92 passed** | 105.10 s | 0 |
| 2 | 100.0% | **92 passed** | 146.78 s | 0 |
| 3 | 100.0% | **92 passed** | 110.94 s | 0 |

三遍全绿，没有新增 skip/xfail；耗时波动来自负载进程与候选包构建的竞争，不改变结论。

## 四、实机运行记录

### 4.1 整仓全量（最终代码树）

```bash
PYTHONUTF8=1 QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q --tb=short --junitxml=.scratch/petcore-p4c3-distribution/t09/full-t09.xml
```

实际输出：**9941 passed / 18 skipped / 20 warnings in 1220.48 s，exit 0**；JUnit 9959 例，failure/error 均 0。
18 条 skip 与 L064 记录的同源（符号链接权限 3、缺 ffmpeg 3、素材/GIF 2、真实前台窗口 2、POSIX 2、macOS 2、
`tzset` 1、Cocoa 1、headless 截图 1、opt-in 声卡 1），petcore 域无 skip。

### 4.2 安装器隔离矩阵（`.scratch/petcore-p4c3-distribution/t09/installer-acceptance.json`）

| 用例 | 安装 exit | `mods/` 内容 | `.trusted` | 卸载 exit | 目录已删 |
|---|---:|---|---|---:|---|
| `/TASKS=`（显式空） | 0 | 空 | 无 | 0 | 是 |
| `/TASKS=mod_todo` | 0 | `reminder.todo` | 有 | 0 | 是 |
| `/TASKS=mod_todo,mod_festival` | 0 | `fun.festival` + `reminder.todo` | 各自有 | 0 | 是 |
| 不传 `/TASKS`（两次） | 0 | 空 | 无 | 0 | 是 |

装完 `dsh-pet-core.exe` 存在；卸载后 HKCU 无本次安装的残留卸载项（扫描到的 `dsh-pet-standalone`
是机器上原有的另一套安装，未触碰）。

**一处必须说清的反常**：最早有一次手工调用装出了 9 个带 `.trusted` 的包。用 `.ps1` 文件固定参数后连跑 5 次都是上表结果；
根因是 Git Bash/MSYS 会把 `/TASKS=...` 改写成 `C:/Program Files/Git/TASKS=...`（探针输出里能看到），
导致参数根本没传给 Inno。**这是调用方式问题，不是安装器行为**；正式验收一律用 `.ps1` 文件传参。

### 4.3 发布准备

- 默认索引源未改（仍 `MerZlin/dsh-pet-extensions`）；根 `extensions-index.json` 四包仍 `blocked=true`。
- `RELEASE_REPO` / `RELEASE_TAG` 仍是拟定常量，手册第 2 节要求发布前由用户确认。
- 未执行：`gh release`、`git tag`、上传资产、切默认源。

## 五、限制与后续

1. **真实 HTTPS 下载仍未验**：D1/T07 全程 `file:`，T09 也没有改变这一点；手册 §3.4 把它列为发布后的必做验收。
2. **安装器只验静默模式**：向导界面的人工点击、安装后自启、覆盖升级（同 AppId 的旧版 → 新版）未验。
3. **性能探针是合成负载**：loopback + 固定大小包，不代表 CDN 延迟或真实磁盘；进程级 CPU 不含 GPU/Qt 绘制。
4. **高负载只覆盖受影响族**：整仓未在 20 个负载进程下重跑（成本约 20 分钟 ×3，收益有限）。
5. **开发证书不可用于公开分发**：正式发布要换 CA 证书并重新签名，SAC/SmartScreen 结论也要重测。
