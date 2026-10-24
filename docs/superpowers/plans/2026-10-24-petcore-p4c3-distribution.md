# P4-c3 分发准备与候选产物验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:executing-plans`；用户已允许继任模型使用多智能体，也可使用 `superpowers:subagent-driven-development`。严格按本文写集分工，不把公共接口的决定外包给互不知情的 worker。所有步骤用 checkbox 跟踪。

**Goal:** 将已经完成 A–E 的四个功能扩展做成可复现的本地候选 ZIP，补齐市场传输/解包/授权门禁，验证真实隔离安装、更新失败恢复、回滚及 Windows 候选程序；公开发布仍须另行确认。

**Architecture:** 保留 `net → market 编排 → mods 安装器 → UI` 的既有分层，不新建服务端、不另起插件体系。通用预算放 stdlib contracts；只有远程功能包使用新预算，角色包保持原边界。构建器只打包明确允许的源码，读取实际 ZIP 生成大小与摘要；市场索引继续使用 schema_version 1。

**Tech Stack:** Python 3.11、PySide6、stdlib urllib/zipfile/hashlib、pytest、Ruff、现有 PowerShell/PyInstaller 构建入口、GitHub 仓库文件/CDN/Release。

**Spec:** [PETCORE-SPEC](../../PETCORE-SPEC.md#2026-10-24-p4-c3-e与提醒域当前状态)、[市场契约](../../PETCORE-MARKET.md)、[MOD-FORMAT](../../PETCORE-MOD-FORMAT.md)、[A–E 最终报告](../../PR-REPORT-PETCORE-P4C3-E-2026-10-24.md)。本文实现用户批准的“仓库分发与兼容、验证与验收”部分，不重新实施提醒域。

**基线/效力:** 2026-10-24，`feat/petcore-vpet-architecture`，Core 0.2.0/API 1；A–E 已实现，分发尚未开始。本计划是下一阶段的执行契约，checkbox 初始全部未完成，不能把本文中的命令或期望结果当作已经执行的证据。当前交付的提交号通过 [L062](../../PETCORE-LOG.md#l062--2026-10-24--分发阶段详细交接与本批提交交付) 与 [日志索引](../../PETCORE-LOG-INDEX.md) 查询，避免写一个提交自身不可能预知的 SHA。

## Global Constraints

- 工作区 `E:\AI\DSH\dshpet`；PowerShell；Git 为 `D:\DELL\Git\cmd\git.exe`；用项目 `.venv\Scripts\python.exe`，必验 Python 3.11，不改全局 Python。
- 按实际执行日期记报告和 LNNN；新文档登记 `docs/INDEX.md`。本计划的 2026-10-24 是编写日期，不强行当作继任模型的执行日期。
- 已实现版本：Core `0.2.0`，`api_version="1"`；`reminder.todo`、`fun.festival`、`fun.divination` 为 `1.1.0`，`voice.chime` 为 `1.1.1`；四包 `core_requires=">=0.2.0,<1.0.0"`。没有实际已发布同版本证据，不随意加版本；发现远端同版本不同摘要，停止，交用户定新版本，绝不覆盖 Release 内容。
- `allow_feature_mods` 默认关闭；`certified`、源名称、ZIP 内 `.trusted` 都不是授权。保留安装向导由用户明确选择产生的本地授信语义，不能为消除远程风险把合法本地授权全部删掉。
- 远程 feature 包：压缩最多 `64 * 1024 * 1024` 字节，展开最多 `256 * 1024 * 1024` 字节，ZIP 条目最多 `10_000`（文件、目录均计数）。读流中持续计数；不只信 ZIP/HTTP 头。角色/content 包不套这组新增预算。这里“远程功能包”指市场分发通道的feature（显式本地镜像也用于复现同一通道预算）；普通 `mods.install` 本地目录/ZIP仍不默认加这组预算。
- 不覆盖旧数据格式；`todo-slot-N-v2.json`、`festival-slot-N-v2.json`、`daily-v2.json` 及迁移备份在代码回滚后保留。旧代码只能读其兼容的旧数据，禁止为了演示回滚删除 v2 文件。
- 不做角色素材下载/v6 播放适配、Agent 写入、灵动岛第二阶段、Core 自更新、节日专属动画、新提醒功能或大规模重构。
- 不 reset/clean/stash 隐藏既有修改；不改系统安全策略、证书、真实用户配置、真实安装、自启；不用真实账号或生日。不得运行会写默认用户目录的 `scripts/install_example_mods.ps1` 作为隔离验收。
- 当前用户授权提交/推送的是 A–E 与本交接文档。继任阶段可以在隔离分支开发；其提交/推送按届时用户授权办理。**不自动上传 Release、不创建公开包、不合并 main、不强推。**
- 无法完成的验收明确写阻断/缺口；测试通过只证明测试范围，不能声明不存在问题。不能用历史 Windows 源码截图证明本次冻结包、远端链路或其他平台通过。

## 0. 继任模型启动卡（先读这部分，再读任务）

### 0.1 状态与证据，不要从 A 重做

| 域 | 2026-10-24 已有证据 | 下一阶段仍要做什么 |
|---|---|---|
| A 质量阻断 | Python 3.11；全仓原生退出恢复，历史报告保留原失败 | 新网络/安装/构建代码之后重跑全仓并检查退出码 |
| B 通用接口 | slot 交付、DND、单语音通道、真实播放结束、取消代次 | 只防止分发装卸引入回归，不改 API 语义 |
| C/D/E | 完整待办、历法/生日、48签、30轮装卸/面板、真实 PCM 时序 | 用新 ZIP 与冻结程序重复验证，不拿目录安装当 ZIP 验收 |
| A–E 最后全仓 | 9837 passed / 20 skipped / 15 warnings / 1565.27s，exit 0 | 本交接提交前另跑门禁，结果见交付报告；下一阶段自己再跑 |
| 压力/性能 | 20 个 CPU 工作进程三遍 86 passed；15s+60s×3 前后测量 | 本阶段网络/解包/安装新路径重新建基线 |
| Windows | 隔离双宠、设置、合成生日、DND、真实本地 PCM、退出 | 外部 TTS、通知物理点击、其他 Python/平台、双屏、冻结包仍有缺口 |
| 分发 | **没有**本阶段 ZIP、根 `extensions-index.json`、公开 Release 或远端验收 | T00–T09 全部由继任执行 |

本机上一阶段原始记录在 `.scratch/petcore-p4c3/`（gitignored），新阶段记录放 `.scratch/petcore-p4c3-distribution/`。新机器 clone 不会有 scratch；先以已提交报告定位范围，缺原始输出就重新采集，不能伪造目录或声称看过不存在的文件。

当前代码中已读到的缺口（不是未经复现就下的“已修复”结论）：

1. `petcore/net/market.py::download_to` 对 206 未校验 Content-Range；416 可能仅凭本地长度返回；未设流量硬上限，默认 opener 可自动重定向。
2. `petcore/mods/install.py::_extract_zip` 有路径逃逸/符号链接防护，但使用 `copyfileobj` 无展开预算；不能破坏 A 已修复的 Python 3.11 清理与回滚。
3. `petcore/market/verify.py::verify_manifest` 目前只核对 id/kind/version。
4. `petcore/market/source.py::DEFAULT_INDEX_URLS` 仍指向 `MerZlin/dsh-pet-extensions/main/index.json`；本阶段目标仓库实际为 `MerZlin/dsh-pet-indesktop`，不是凭文件名推测的新仓库。
5. `MarketPage.dispose` 仅断开 done/failed；是否有退出时活跃 QThread、迟到 reload，要先复现，不能直接假定安全或全局 patch Qt。
6. `market/install.py` 锁文件写失败与 apply 失败可能已经改变磁盘。要区分“文件已装、激活失败”和“事务未提交”，不能因为函数未抛异常就判验收成功。

### 0.2 必读顺序（不要一次灌入整份日志）

1. 根 `AGENTS.md`、`petcore/AGENTS.md`、`docs/INDEX.md`、`docs/PETCORE-LOG-INDEX.md`。
2. `docs/PR-REPORT-PETCORE-P4C3-E-2026-10-24.md`，需要追根因时才读 A/B/C/D/质量报告。
3. `docs/PETCORE-MARKET.md`、`docs/PETCORE-MOD-FORMAT.md` §6/§17、本计划。
4. 网络任务读 `docs/NETWORK-PROXY-AND-VPN-2026-09-22.md`；构建任务读 `docs/ONEDIR_PACKAGING.md` 与 `docs/STABLE_BUILDS.md`。
5. UI 任务读 `.agents/skills/qt-ui-review/SKILL.md`；新增实质 UI 再读 `desktop-pet-ui-style` 与设置变更门禁。

### 0.3 通用命令与准确记录

以下均在仓库根运行；`$P/$G/$S` 只在本 PowerShell 会话有效：

```powershell
Set-Location -LiteralPath 'E:\AI\DSH\dshpet'
$G = 'D:\DELL\Git\cmd\git.exe'
$P = Join-Path $PWD '.venv\Scripts\python.exe'
$S = Join-Path $PWD '.scratch\petcore-p4c3-distribution'
New-Item -ItemType Directory -Path $S -Force | Out-Null
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
& $G status --short
& $G branch --show-current
& $G rev-parse HEAD
& $P -c "import sys,PySide6,pytest; print(sys.version); print(PySide6.__version__); print(pytest.__version__)"
```

测试命令不要通过管道丢失退出码。每次执行后立刻保存 `$LASTEXITCODE`；不同运行用不同 label，旧失败文件不覆盖：

```powershell
$label = 't00-market-baseline-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$watch = [Diagnostics.Stopwatch]::StartNew()
& $P -m pytest -q --tb=short tests/test_petcore_market_net.py tests/test_petcore_market_install.py tests/test_petcore_market_source.py tests/test_petcore_installer.py *> "$S\$label.txt"
$code = $LASTEXITCODE
@{ exit_code=$code; elapsed_s=$watch.Elapsed.TotalSeconds; label=$label } | ConvertTo-Json | Set-Content -Encoding utf8 "$S\$label.json"
Get-Content -LiteralPath "$S\$label.txt" -Tail 30
if ($code -ne 0) { throw "gate failed: $label (exit=$code)" }
```

## 1. 多智能体规则与依赖图

主模型先做 T00/T01。之后可同时给 A/B/C 三个 worker 明确任务，**最多 3 个 worker**，主模型同时做不重叠的源码审查/证据准备；不要开纯等待的重复审查代理。每次只分配表内写集，子代理不得改其他文件、提交、推送、下载大依赖或操作真实用户目录。

| 执行者 | 可并行任务 | 独占写集 | 禁止写入 |
|---|---|---|---|
| 主模型 | T00、T01、T04、T06–T09 | 公共协议、`market/install.py`、`market/verify.py`、source/CLI/UI 集成、构建 PowerShell、全部正式文档 | 不在 worker 工作时修改其文件 |
| A 网络 | T02 | `petcore/net/market.py`、新增 `petcore/net/market_transport.py`、`tests/test_petcore_market_net.py`、新增 `tests/test_petcore_market_transport_security.py` | `net/http.py`、market 编排/安装、公共协议、文档 |
| B 解包 | T03 | `petcore/mods/install.py`、新增 `tests/test_petcore_remote_archive_limits.py` | `market/install.py`、旧清理回归测试、协议、文档 |
| C 构建器 | T05 | 新增 `scripts/build_petcore_extensions.py`、`scripts/verify_petcore_extensions.py`、`tests/test_petcore_extension_build.py` | 根索引、既有 build_petcore.ps1、正式文档、具体 mod 源码 |

```text
T00 基线 → T01 接口冻结 → [T02 网络 || T03 解包 || T05 构建器]
                         T02 + T03 → T04 安装/身份/授权事务
                         T04 + T05 → T06 源/CLI/UI/根索引集成
                                      → T07 真实候选安装/恢复
                                      → T08 Windows 冻结包
                                      → T09 全部门禁/报告/交付
```

worker 必须在其工作区直接编辑文件，交回：修改路径、测试红/绿原始输出位置、命令及退出码、未决问题、patch/commit 引用。主模型逐文件复核后再整合；不能只信“已完成”。共享工作区时严格写集；fork/worktree 时由主模型一次一个集成，不能混用未提交差异直接 `cherry-pick`。无可用多代理工具时串行做，结果不降级。

**停机规则：**同一族连续两次修补仍失败，停止堆分支，回读失败日志/引入点；身份/权限/摘要不一致、远程分支漂移、未知用户数据、安装事务损坏、进程退出崩溃或真实依赖不可用，停在对应门禁并写 HANDOFF。可独立继续的其他任务继续，不把受阻阶段标完成。

## 2. T00 — 基线、可复现记录与执行账本（主模型）

**文件：**只创建 `.scratch/petcore-p4c3-distribution/{HANDOFF.md,spec.md,issues/,baseline/}`。本交付已经建立初始交接；继任先读再更新，另起带时间戳的 baseline 子目录，不覆盖交付快照。

- [ ] 执行 §0.3；确认所在提交包含 L062/A–E，保存 `status --porcelain=v1`、`diff --binary`、`diff --numstat`、未跟踪清单和文件 SHA256。新的 dirty 不为零时逐项归属，不能清除。
- [ ] 用 `& $P -m pip freeze` 保存依赖；探针 `importlib.util.find_spec('PyInstaller')`、Python3.11、Qt/lunar，记录可执行路径。只给未来独立构建 venv 安装必要依赖，不能先升级当前已验环境。
- [ ] 运行 §0.3 的市场基线，再跑 `tests/test_petcore_architecture.py`、`tests/test_petcore_docs.py`。预期 exit 0；失败归因并先关闭，不宣称是“旧测试随便跳过”。
- [ ] 复制当前受影响源文件到 baseline/source（含 net/market、market、mods/install、构建脚本）；T09 性能对照从这份快照取旧实现，禁止在产品目录反复 reset 版本。
- [ ] 在改产品代码前采集§11.1的三轮before基线。探针放scratch并固定输入：同一4MiB压缩/8MiB展开的合成包、同一loopback服务器、同一源码目录；缓存命中/空闲分别测，下载/解包操作次数固定并记录。未来新增功能没有旧入口就标“新增路径无旧对应”，不能用不同工作量算加速。探针和原始数字归档；没有before不放行T01。
- [ ] 创建 T00–T09 账本：`Status: ready-for-agent` 属于 triage；另用 `Execution: not-started/running/blocked/completed` 记录执行状态，禁止发明新的 triage 值。
- [ ] 更新 HANDOFF：目标、分支/HEAD、基线目录、最后 red/green、确切下一命令、无/有活跃进程、写集所有者。T00 完成才允许派 worker。

**退出门：**基线可读、命令可复现、没有未归属改动；新阶段尚无可发布结论。

## 3. T01 — 冻结跨任务接口（主模型，禁止并发修改）

**文件：**新增 `petcore/contracts/market.py`、`tests/test_petcore_market_policy.py`；修改 `petcore/market/download.py` 的 `ArtifactFetcher`、`petcore/market/source.py` 的 `IndexFetcher/SourceResult`、`petcore/net/market.py::HttpFetcher` 的转发参数。实现策略由后续任务完成，本任务不让不安全旧实现被标成安全。

**约定的新接口（不是说当前已有）：**

```python
# petcore/contracts/market.py — stdlib only
from dataclasses import dataclass

REMOTE_FEATURE_MAX_BYTES = 64 * 1024 * 1024

@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_expanded_bytes: int = 256 * 1024 * 1024
    max_entries: int = 10_000

REMOTE_FEATURE_ARCHIVE_LIMITS = ArchiveLimits()
```

- `download_to` 与 `ArtifactFetcher.download/HttpFetcher.download` 在原参数之后追加 keyword-only `max_bytes: int | None = None, allow_local: bool = False`；旧位置参数不动。
- `fetch_index/IndexFetcher.fetch_index/HttpFetcher.fetch_index` 追加 keyword-only `allow_local: bool = False, cancel: Callable[[], bool] | None = None`；304/ETag/IndexFetch 原语义保留。
- `SourceResult` 追加 `allow_local_artifacts: bool = False`。它只能来自实际使用的、用户显式选择的本地索引；不能读索引 JSON 中的同名字段作为权限。
- `install_package` 和 `download_artifact` 后续追加 keyword-only `allow_local_artifacts: bool = False`。不改变 `allow_feature=False` 默认值。
- `open_pack(source, work_root=None, *, limits: ArchiveLimits | None = None, cancel: Callable[[], bool] | None = None, reject_trust_marker: bool = False)`；未传 limits 的旧调用行为保持。新参数由 T03 实现、T04 传入，不提前让用户路径绕过门禁。
- `TransferCancelled` 仍是取消的专用异常；不转换成普通网络失败再尝试下一镜像。`InstallError` 仍由 mods 层抛出，market 层负责明确捕获 `mod_install.InstallError` 并记录失败/清理，不让 UI 捕获不明裸异常。

**TDD 种子：**

```python
# tests/test_petcore_market_policy.py
from dataclasses import FrozenInstanceError
import pytest
from petcore.contracts.market import (
    ArchiveLimits, REMOTE_FEATURE_MAX_BYTES, REMOTE_FEATURE_ARCHIVE_LIMITS,
)

def test_feature_policy_exact_and_immutable():
    assert REMOTE_FEATURE_MAX_BYTES == 67_108_864
    assert REMOTE_FEATURE_ARCHIVE_LIMITS == ArchiveLimits(268_435_456, 10_000)
    with pytest.raises(FrozenInstanceError):
        REMOTE_FEATURE_ARCHIVE_LIMITS.max_entries = 1
```

- [ ] 先建测试，运行 `& $P -m pytest -q tests/test_petcore_market_policy.py`，记录新模块缺失的 red。
- [ ] 加上述 contracts 与协议声明，更新所有测试 fake 的签名/转发断言。禁止 `except TypeError: retry_without_security_keywords` 兼容法，那会绕过新门禁。
- [ ] 运行 policy、market source/net/install、架构测试；未实现 T02/T03 的行为测试不能提前标绿。
- [ ] 在 HANDOFF 复制精确签名并锁定写集；向 A/B/C 分别发送 T02/T03/T05 与本节。公共接口改动只有主模型接收建议后串行处理。

## 4. T02 — 逐跳 HTTPS、续传正确性、上限与响应释放（worker A）

**文件：**按 §1 A 写集。读取现有 `net/http.py::urlopen`，但不修改它；保留系统代理优先/传输失败直连的既有工厂接缝。不要因为市场限制改坏 TTS、天气或聊天代理。

**算法要求：**

1. 新增 `market_transport.py` 的市场专用 opener：禁自动 redirect；逐次读取 Location，经校验后才打开下一跳，最多 5 跳。每个 3xx/HTTPError/304/416 的 response 都要 close。最终 `geturl()` 也检查，但**不能用最终 URL 检查代替逐跳检查**。
2. 默认只允许 HTTPS，拒绝 userinfo、空主机、`file:/http:/ftp:/data:`。远程路径不能访问 localhost/回环字面地址。用户显式本地源才可 `file://` 本机文件或 HTTP loopback；拒绝 UNC/file远程主机；本地源只能在本地来源域内跳转，禁止本地→远程或远程→本地的跨信任域重定向；远程fallback由MarketSource另起请求，不能继承本地授权。不要自建 DNS/代理栈或声称防住所有 DNS rebinding。
3. `http.urlopen` 的 opener factory 给 `(use_proxy, context)`，每次返回带禁止自动重定向 handler 的 opener；不要 `install_opener()` 污染进程全局。沿用代理路线且不记录代理地址、URL query、userinfo 或裸异常敏感文本。
4. `expected_size`、`max_bytes` 必须是正整数（None 表示该字段未知/不设新增预算）。远程 feature 声明大于 64MiB 在打开连接前拒绝；响应 Content-Length 超限在创建/覆盖 part 前拒绝；无长度时逐块计数，写入前检查 `done + len(block)`。已有 part 超限先报明确失败，不继续追加。
5. 新建无 Range 请求只接受完整 200；206 仅允许自己发过 Range。续传必须解析单段 `bytes start-end/total`，start 等于本地长度，end>=start，total/end/expected_size 一致，拒绝 multipart、负数、缺字段、超界与读流短/长。Range 被忽略返回 200 时从零重写，不能追加。
6. part 的小型 sidecar 保存源 URL 的无敏感标识、expected_size、强 ETag（不接受 `W/`）。已有 part 没有可靠 sidecar 时安全重下；有强 ETag 发 If-Range。跨 URL/校验信息变化时重下；同一不可变包仍由 market 最终 SHA-256 校验，sidecar 不是信任根。sidecar 原子写、最终完成/清除 part 时同步清理，不存凭据。
7. 416：仅 `Content-Range: bytes */N`、本地长度=索引 expected_size=N 且后续会执行 SHA256 时可返回已有长度；其它情况关闭响应后最多一次从零重试。未知 size 不能直接当成功。错误206、资源变化也最多一次重下，不无限镜像/Range重试。
8. 取消检查在请求前、每次 read 前/后、写入前、源切换前；关闭所有 response/stream；只保留同身份、可安全恢复的 part。连接/读取阻塞只能在 timeout/返回后协作取消，不能宣称立即杀线程；GUI 停用不 join 等待。
9. index 的 8MiB 上限在原始响应及 GitHub API base64 解码后均检查，取消不回写缓存；304 HTTPError 同样 close。

**最小红例（接口已有，行为还未实现时必须红）：**

```python
# tests/test_petcore_market_transport_security.py
import pytest
from petcore.net.market import download_to

def test_remote_file_cannot_read_local_payload(tmp_path):
    private = tmp_path / "synthetic.txt"
    private.write_bytes(b"synthetic only")
    part = tmp_path / "remote.zip.part"
    with pytest.raises(Exception):
        download_to(private.as_uri(), part, expected_size=14)
    assert not part.exists()
```

初次定位后把泛化 Exception 收窄为产品定义的具体错误类（如现有 NetworkError 分类）；必须同时证明 opener 未读取文件，而不是读完后才报错。保留原 loopback server fixture，只在显式本地测试传 `allow_local=True`；不要将全部测试默认授权本地。

- [ ] 增加上述红例与 redirect 链观察器：HTTPS→HTTPS 成功；HTTPS→HTTP/file/loopback 拒绝且被拒目标访问次数=0；第6跳拒绝；每个 response.closed=True。
- [ ] 将 `_Handler` 扩展成参数化回归：正确206、start错、total错、缺Content-Range、响应短/长、200忽略Range、正确/错误416、ETag变化、无长度超限、取消、镜像切换。用8/32字节预算做单测，不造256MiB内存垃圾。
- [ ] 分批最小实现每个 red，记录实际错误，不把本来正确的测试当“红证据”。网络边界用 fake opener 与 loopback 服务器；Event/Condition协调断流，不用固定 sleep。
- [ ] `& $P -m pytest -q tests/test_petcore_market_net.py tests/test_petcore_market_transport_security.py tests/test_petcore_net.py tests/test_petcore_http_port.py`；再 Ruff A 写集。若共享 http 回归红，不得扩大写集偷偷改它。
- [ ] 交回文件、red/green、响应释放证明、仍未测试的真实外网/代理路径。不可报告未发布 GitHub 下载通过。

## 5. T03 — 远程功能包解压预算与取消（worker B）

**文件：**`petcore/mods/install.py`、新增 `tests/test_petcore_remote_archive_limits.py`。使用 T01 ArchiveLimits；不引入网络库，不修改 Python 3.11 `_chmod_retry/_remove_path` 根因修复。

**接口：**落实 T01 的 open_pack 参数，传至 `_source_pack/_extract_zip`；`limits=None` 保持非远程/content旧边界。取消可在 mods 层抛 `InstallError("extraction cancelled")`，T04 将其区分为取消失败，不继续镜像安装。

```python
# tests/test_petcore_remote_archive_limits.py
import zipfile
import pytest
from petcore.contracts.market import ArchiveLimits
from petcore.mods.install import InstallError, open_pack

def test_extraction_stops_at_actual_byte_budget(tmp_path):
    archive = tmp_path / "tiny.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("mod.json", b"{}")
        z.writestr("host/data.bin", b"x" * 20)
    stage = tmp_path / "stage"
    with pytest.raises(InstallError):
        with open_pack(archive, stage, limits=ArchiveLimits(10, 10)):
            pytest.fail("oversized archive yielded a usable directory")
    assert not list(stage.glob(".unpack-*"))
```

- [ ] 先跑该用例确认 red，补条目数（目录也算）、边界恰等、分块累计、单文件超限、ZIP头与实际读量不一致模拟、取消和 CRC错误用例。
- [ ] 保留路径防护；补绝对路径、`../`、反斜线逃逸、Windows drive/UNC、ADS `name:stream`、设备名/尾点尾空格碰撞、重复/大小写归一后冲突、symlink、加密条目失败。不要通过“先解压再扫描”修这些问题。
- [ ] `reject_trust_marker=True` 时任何层级 `.trusted` 都拒绝；不能只在构建器排除而信任下载包。`False` 的合法本地目录授权路径保持，交 T04 集成测试证明。
- [ ] 在读取每块前/后检查 cancel；每条目/每块实际累计，超限在 write 前报错。读取大小用固定上限，不能 `read()` 整个成员。预检查仅作早拒，不能替代流量计数。
- [ ] `TemporaryDirectory` 正常与异常都清理；清理本身失败保留可诊断路径/原因，不改为 ignore_errors。禁止覆盖原安装目录来“试着解包”。
- [ ] `& $P -m pytest -q tests/test_petcore_remote_archive_limits.py tests/test_petcore_install.py tests/test_petcore_installer.py tests/test_petcore_character_pack.py`；角色包无新增64/256MiB门槛。Ruff，交回 red/green 与真实未覆盖的 OS 限制。

## 6. T04 — 交叉校验、权限与事务恢复（主模型，T02/T03 合入后）

**文件：**`petcore/market/{download,verify,install}.py`、`tests/test_petcore_market_install.py`、新增 `tests/test_petcore_market_manifest_security.py`；只有明确复现需要才改 `mods/trust.py`，不能改变已有明确授权契约。

**入口与数据流：**`install_package → download_artifact → open_pack → verify_manifest → backup_pack → mod_install.install → save_lock → GUI apply`。根、旧版本、授权、budget均在启动下载前确定；错误不能触发 apply。

**身份红例：**

```python
# tests/test_petcore_market_manifest_security.py
import dataclasses
from pathlib import Path
import pytest
from petcore.market.model import MarketPackage, MarketVersion
from petcore.market.errors import ManifestMismatch
from petcore.market.verify import verify_manifest
from petcore.mods.manifest import load_manifest

def test_index_cannot_hide_package_capability():
    manifest, problems = load_manifest(Path("examples/petcore-mods/reminder.todo"))
    assert manifest is not None, problems
    version = MarketVersion(manifest.version, 1, "0" * 64, ("https://example.invalid/a.zip",))
    package = MarketPackage(
        id=manifest.id, kind=manifest.kind, name=manifest.name,
        version=manifest.version, versions=(version,), api_version=manifest.api_version,
        core_requires=manifest.core_requires, execution=manifest.execution,
        capabilities=manifest.capabilities,
    )
    verify_manifest(manifest, package, version)
    hidden = dataclasses.replace(package, capabilities=())
    with pytest.raises(ManifestMismatch):
        verify_manifest(manifest, hidden, version)
```

- [ ] 先跑该测试 red；参数化 id/kind/version/api_version/core_requires/execution/capabilities 错配。capabilities按去重集合比较，其余按协议规范值比较；不把版本范围“字符串差异不重要”当放行理由，构建器应从manifest同源生成。
- [ ] 下载前根据 `package.kind == "feature"` 传 `max_bytes=REMOTE_FEATURE_MAX_BYTES`；所有 content 维持None。解包前 feature传 limits 与 `reject_trust_marker=True`；cancel一路透传。expected_size大于预算时 fakefetcher调用0次；limits=None的角色回归保持。
- [ ] SHA/size失败、包不兼容/能力不匹配必须发生在备份/替换前。加载前再用当前 Core/API 范围校验，不只信索引的兼容筛选。
- [ ] 任何 certified/source伪造/ZIP标记，都不能使 `allow_feature=False` 安装或加载。被拒绝时 fetcher/apply调用0次；允许安装后用户关授权再重载，远程包不因自带marker继续加载。
- [ ] 为备份创建失败、只读/占用文件、os.replace失败、锁文件写失败、apply失败、回滚备份损坏/错ID/路径逃逸补失败注入。只 mock文件系统失败点/OS/网络边界，不mock整个 install_package得到想要的答案。
- [ ] 锁文件backup路径必须解析在 `root/market/backup/<id>` 内，禁止锁文件指向任意用户目录。更新失败原安装和可回滚备份保持；回滚过程中先保护当前版本，再原子恢复，任何补偿失败报告两个阶段，不吞异常。
- [ ] 决定并测试事务语义：替换前失败=原版本不动；替换后锁写失败=尝试恢复旧目录及旧lock，恢复失败明确“需人工恢复”；初装没有旧版则保留可诊断的未完成状态，不声称可发布。apply失败不能算候选验收通过，清晰区分已落盘/需重启，不强行在worker线程调用Qt。
- [ ] 对比安装前后 synthetic v2运行文件SHA，任何失败/卸载/回滚都不删除数据；只处理所属mods/market目录。备份失败停止，不把 ignore_errors 作为优化。
- [ ] 跑 `tests/test_petcore_market_install.py`、新manifest安全测试、install/installer、market CLI/UI与architecture；Ruff。确认上一阶段原48修改和A–E没有丢失，再放行 T06。

## 7. T05 — 可复现 ZIP 与生成清单（worker C，可与 T02/T03 并行）

**新文件：**`scripts/build_petcore_extensions.py`、`scripts/verify_petcore_extensions.py`、`tests/test_petcore_extension_build.py`。根 `extensions-index.json` 由主模型 T06 放置，不让 worker覆盖。

**构建接口（固定，主模型/测试直接调用）：**

```python
# scripts/build_petcore_extensions.py
# build_candidates(repo_root: Path, output_dir: Path) -> Path
# 返回 output_dir / "candidate-manifest.json"；不联网、不改源码、不自动安装。
# build_index(candidate_manifest: Path, *, local: bool = False) -> dict
# 从四个ZIP的mod.json与实际文件摘要生成schema_version1市场字典。
# local=False: 四包blocked、待发布Release URL；local=True: blocked=False、绝对file URI。
# CLI: python scripts/build_petcore_extensions.py --repo-root . --output <new-dir>
# verify_petcore_extensions.py CLI: --candidate-manifest <path>
```

`candidate-manifest.json` 是构建证据，不是市场schema，结构固定：

```python
import hashlib
from pathlib import Path

def artifact_record(archive: Path, mod_id: str, version: str) -> dict:
    data = archive.read_bytes()  # 构建端已先验证每包不超过64MiB；运行时下载不要整包read。
    return {"id": mod_id, "version": version, "file": archive.name,
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

# build_candidates 收集四个 artifact_record 后写以下根字段：
# schema_version=1, status="pending-publication", core_version="0.2.0",
# api_version="1", artifacts 使用四条实际计算结果组成的列表。禁止使用示意摘要/大小。
```

```python
# tests/test_petcore_extension_build.py
import hashlib
import json
from pathlib import Path
from scripts.build_petcore_extensions import build_candidates

def test_same_source_produces_identical_four_archives(tmp_path):
    root = Path(__file__).resolve().parents[1]
    a = json.loads(build_candidates(root, tmp_path / "a").read_text("utf-8"))
    b = json.loads(build_candidates(root, tmp_path / "b").read_text("utf-8"))
    assert {x["id"] for x in a["artifacts"]} == {
        "reminder.todo", "fun.festival", "fun.divination", "voice.chime",
    }
    assert a["artifacts"] == b["artifacts"]
    for item in a["artifacts"]:
        data = (tmp_path / "a" / item["file"]).read_bytes()
        assert item["size"] == len(data)
        assert item["sha256"] == hashlib.sha256(data).hexdigest()
```

- [ ] 先运行上述新测试red，再实现固定四ID白名单，manifest解析和版本/Core/API校验复用现有实现。
- [ ] 当前四包只有 `mod.json` 与 `host/`：允许manifest、`host/**/*.py`及明确存在的LICENSE/README；固定排除 `.trusted`、install.json、__pycache__、pyc、缓存/凭据/个人配置、隐藏文件。发现未知非生成资源先报错，不能悄悄打进去或悄悄漏掉将来需要的资源。文件/目录symlink一律拒绝，输出目录不能在输入包内部。
- [ ] ZIP按相对POSIX路径排序、固定时间戳1980-01-01、固定权限/压缩方式/等级，不收集绝对路径或本机时间；同环境重复构建摘要相同。不要宣称不同zlib版本一定逐字节相同，记录构建依赖。
- [ ] 写新临时ZIP→校验ZIP/manifest→计算size/SHA→原子换名；目标存在且内容不同则拒绝覆盖，内容相同可复用。中途失败不能留下 `status=verified` 或半个rootindex。
- [ ] 实现build_index：先调用verifier，读取每包manifest映射市场id/kind/name/name_zh/author/latest/api_version/core_requires/execution/capabilities/versions；summary可用manifest名称，certified固定false，不推断支持平台（空列表只表示不限制、不是实机支持声明）。待发布URL统一用拟定tag，released_at省略；local=True只供隔离验收，绝不写到根索引。
- [ ] verifier独立重读每个ZIP，核大小/SHA/id/version/API/Core/capabilities/实际成员白名单；四包齐全；删除/篡改1字节/注入`.trusted`/unknown文件时exit非0。不能只验证生成器自己的JSON字段存在。
- [ ] 用copy到tmp的合成污染源码测试排除/拒绝，不在真实examples植入凭据。检查新产物没有绝对路径、用户数据、ZIP内信任标记。
- [ ] `& $P -m pytest -q tests/test_petcore_extension_build.py tests/test_petcore_manifest.py tests/test_petcore_architecture.py`；Ruff；worker只交源码测试，不把本机ZIP或路径commit。

## 8. T06 — 仓库索引、来源授权、CLI/UI集成（主模型）

**文件：**新增根 `extensions-index.json`；修改 `petcore/market/{source,model,cli}.py`、`petcore/ui/settings/page_market.py`、`tests/test_petcore_market_{source,model,cli,ui}.py`；新增 `tests/test_petcore_extensions_index.py`。不要把 `packs-index.json` 混入这条线。

**索引决定：**根索引使用市场 schema_version1/四包。待发布包写 `blocked: true`、`blocked_reason: "待发布：候选产物尚未公开"`；urls 是说明中约定的GitHub Release预期地址，size/SHA来自T05实际ZIP，`released_at`不填虚假发布日期。另在scratch生成 `local-index.json`，四包 `blocked=false`、urls为候选ZIP的 `Path.as_uri()`；该绝对本机文件**不提交**。

**计划的发布仓库与源：**`MerZlin/dsh-pet-indesktop`，根文件 `extensions-index.json`。CDN、raw、API三个URL从同一repo/ref/path生成并测试，拟定tag `petcore-extensions-v0.2.0-rc1` 只作为待批准发布指针，不创建tag。未发布ref不切换生产默认源，不让当前用户突然只得到404；将已实现新源列表用于显式测试源/本地验收，保留用户自定义源。真正切换 DEFAULT_INDEX_URLS 与取消blocked列为另行确认后的发布步骤，不能假称已经上线。

```python
# tests/test_petcore_extensions_index.py （T05生成后再创建根索引）
import json
from pathlib import Path
from petcore.market.model import parse_index_text

def test_repository_index_is_explicitly_pending_and_schema_one():
    text = Path("extensions-index.json").read_text("utf-8")
    raw = json.loads(text)
    index, problems = parse_index_text(text)
    assert raw["schema_version"] == 1
    assert index is not None, problems
    assert {p.id for p in index.packages} == {
        "reminder.todo", "fun.festival", "fun.divination", "voice.chime",
    }
    assert all(p.blocked and "待发布" in p.blocked_reason for p in index.packages)
    assert all(p.versions and p.versions[0].size > 0 for p in index.packages)
```

- [ ] 先跑根索引缺失red；调用T05真实构建/verifier，再由产物生成两个索引，根索引不得手填sha/size。测试用构建器重新打包与根索引逐字校验，禁止只对格式64hex做断言。
- [ ] 在source新增纯函数 `repository_index_urls(ref: str) -> tuple[str, str, str]`，仅接受正则 `[A-Za-z0-9][A-Za-z0-9._-]*` 的tag/commit（这批不接收带斜杠的branch），避免在纯层引入urllib；返回同仓同ref的CDN/raw/API三URL；用`petcore-extensions-v0.2.0-rc1`固定用例测试顺序与文件名，不请求未发布地址。生产DEFAULT_INDEX_URLS暂不自动切换。
- [ ] 源顺序固定CDN→raw→API，304仅复用该source匹配etag/cache；换source不得发前一源etag。解析API base64与离线过期提示保持；缓存写失败要诊断，不抹掉仍可用旧缓存。
具体URL生成体放source，输入校验使用stdlib `re.fullmatch`，不发请求：

```python
import re

def repository_index_urls(ref: str) -> tuple[str, str, str]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ref) is None:
        raise ValueError("release tag or commit required")
    repo = "MerZlin/dsh-pet-indesktop"
    filename = "extensions-index.json"
    return (
        f"https://cdn.jsdelivr.net/gh/{repo}@{ref}/{filename}",
        f"https://raw.githubusercontent.com/{repo}/{ref}/{filename}",
        f"https://api.github.com/repos/{repo}/contents/{filename}?ref={ref}",
    )
```

- [ ] 本地授权沿真实来源传递：`custom_url=file://...`或显式HTTP-loopback并实际命中，才能 `SourceResult.allow_local_artifacts=True`。custom远程索引、远程 fallback、伪造JSON字段、来自别的源的离线缓存均False；URL输入校验由net任务执行，不能通过文件前缀拼接绕过。
- [ ] CLI将该flag传 install_package；UI取这次SourceResult的flag，不用长期可变“曾经选过本地源”全局开关。`--offline`不会放宽权限；不得自动启用allow_feature_mods。
- [ ] 补缓存/来源变换红例：本地失败→远端fallback返回fileURL必须拒绝；本地cache换远端配置也不能保留本地权限；索引自身重定向到file拒绝。
- [ ] 对MarketPage关闭/重复刷新/安装取消先写真实Qt事件循环和独立进程红例。确认风险后加generation/取消Event，disconnect不是销毁仍活跃QThread；保留强引用到finished，再deleteLater；UI不wait两秒、关页后不reload、不发迟到弹窗。重开页不能启动同一未退出安装的替代任务。
- [ ] 使用受控阻塞网络Event测试：开始→关闭/取消→旧任务仍活→重开→允许旧任务退出→进程exit0；所有线程回收、子菜单/对象生存无Qt全局patch。
- [ ] 跑全部market测试、menu/tray/settings生命周期、architecture、docs；补LNNN与索引，分开“已实现本地路径/未发布远端”。

## 9. T07 — 四个真实候选包隔离安装与失败恢复（主模型）

**文件：**新增 `tests/test_petcore_extension_candidates.py`；证据脚本放scratch，不把一次性故障注入混入产品。使用真正的T05 ZIP，不用手写tinyzip替代候选验收；恶意/失败包另建synthetic副本。

- [ ] 新建唯一目录 `$S\acceptance-<timestamp>`，确认resolved绝对路径在工作区下；实际 `--root` 全部指向它，不使用默认data_root。保存安装前目录/配置/数据SHA。
- [ ] 通过真实CLI读取显式local-index，先不授权安装，预期失败且mods/用户数据未变；再明确传 `--allow-feature`安装四个包。`--allow-feature`只授权本次操作，不给包写 `.trusted`。

```powershell
# $R 是本次新建的隔离root；$I 是 local-index.json 的 file URI。
& $P -m petcore market --root $R --index-url $I list --json
& $P -m petcore market --root $R --index-url $I install reminder.todo --json
# 以上拒绝是预期测试结果；单独记录非0，不当构建失败，也不替后续安装开权限。
& $P -m petcore market --root $R --index-url $I install reminder.todo --allow-feature --json
& $P -m petcore market --root $R --index-url $I install fun.festival --allow-feature --json
& $P -m petcore market --root $R --index-url $I install fun.divination --allow-feature --json
& $P -m petcore market --root $R --index-url $I install voice.chime --allow-feature --json
```

- [ ] 用真实 `FeatureManager` 与隔离配置显式授权，断言四包真实加载且功能可用；普通用户授权关闭后不加载。不要用“安装目录存在”代替执行加载。
- [ ] 旧包取已记录基线提交中的源码（`git show <recorded-sha>:<path>`导出到scratch）或明确synthetic旧版本；前者用于真实升级兼容，后者只用于故障注入。禁止改当前manifest假装发布旧版本。
- [ ] 真实旧包→当前候选→rollback旧包→再次安装候选。覆盖只读文件、下载断流、错误Range、摘要错、预算超限、capabilities错、备份失败、替换失败、lock写失败和apply失败；逐步断言旧版本/lock/备份一致、无半包、恢复结果准确。
- [ ] 每轮前后读取合成的todo/festival/daily-v2状态SHA，不能回滚掉已触发状态或删除新格式数据；旧版无法读取新格式这一限制必须写到用户说明。
- [ ] 执行30轮安装/加载/停用/卸载与30轮市场面板开关；每轮记录RSS、线程、Qt活动timer、旧QThread退出、残留staging/part数量。卸载仅删除包所属文件，保留mod用户数据。
- [ ] 通知点击用Qt信号的自动化证据单列，若无人实际点击系统通知不得写“物理点击通过”。无需真实TTS；本地PCM可证明播放回调但不能证明外部服务联网。

**退出门：**四包实装/加载/回滚通过，所有故障路径不会冒报成功；任何失败都不能签署“候选可验收”。本地file链路不等同远端HTTPS端到端验收。

## 10. T08 — Windows 冻结候选包与资源（主模型）

**文件：**必要时修改 `scripts/build_petcore.ps1`、新增 `tests/test_petcore_candidate_packaging.py`；若只补缺失依赖仍需验证冻结包。当前A–E报告已明确当前venv无PyInstaller，不能把早期历史构建当可用产物。

- [ ] 探针当前Python/PyInstaller/Inno/资源存在性；读 `docs/ONEDIR_PACKAGING.md` 与 `STABLE_BUILDS.md`。对缺项只装到项目新建 `.venv-p4c3-build`，记录版本/安装日志；不得升级全局Python或原已验venv。
- [ ] 先为构建脚本新增隔离输出参数写失败测试：`-PythonPath`、`-OutputRoot`，默认旧入口保持；候选参数把dist/work/spec与--check输出全部收束到 `$S\frozen-<timestamp>`。验证参数不接受稳定exe路径或用户安装目录，绝不使用 `-Clean` 去删除未经确认的目录。
- [ ] 构建包含 `lunar_python`、mod源码/引用资源、Qt插件、声音/菜单资源及第三方许可证。现有构建还包含OCR/语音依赖，不能为变绿删掉依赖或把缺失强行忽略；安装依赖失败保留探针与阻断。
- [ ] 先构建onedir，不要求本阶段自动安装到系统；`--check --root <isolated>`输出与exit码独立保存。`--check`成功还要实际加载四个候选ZIP和两只宠物。
- [ ] 原生运行时移除 `QT_QPA_PLATFORM=offscreen`，使用w32真实桌面；验证两宠、菜单/托盘/设置保存取消、隐藏待办通知、安静期汇总、合成2032-02-29生日、抽签、停用、退出；录真实可见结果、截图和完整进程退出码。
- [ ] 若Smart App Control/SmartScreen拦截：保留程序路径/摘要/退出错误/安全日志探针，标记“冻结包实机验收阻断”。不关安全策略、不导入信任证书、不给程序提权。不要把策略拦截算成已通过，也不要编造系统原因。
- [ ] 其他Python、macOS/Linux、双屏、真实外部TTS若无条件列探针和缺口；Windows冻结包受阻时本阶段只能交未验候选及阻断，不写全面完成。

## 11. T09 — 性能、压力、整仓门禁与交付（主模型）

**文件：**更新 `docs/PETCORE-{SPEC,ROADMAP,MOD-FORMAT,MARKET,LOG,LOG-INDEX}.md`、`petcore/README.md`、`examples/petcore-mods/README.md`、`docs/INDEX.md`；新增执行当日 `docs/PR-REPORT-PETCORE-P4C3-DISTRIBUTION-YYYY-MM-DD.md`（文件名日期必须取实际执行日）、`docs/PETCORE-EXTENSIONS-RELEASE.md`。四大文档只由主模型写。

### 11.1 性能/压力（不要只写“可忽略”）

- [ ] 用T00改动前已采集的数字及源码快照与最终代码同机对照；若before缺失，先在独立隔离源码树恢复已记录基线并重测，不能混用新协议与旧单文件形成伪基线：索引缓存命中/刷新、loopback安全传输、候选下载/解包/安装、空闲市场页、30开关/装卸。分别预热15秒、采集60秒、重复3次，报告样本量和机器/依赖/输入。真正外网未发布则测量标本地网络，不冒充CDN延迟。
- [ ] 每秒采样进程CPU/RSS/线程；统计Qt活动timer、采样次数、磁盘写入调用/bytes、网络请求/bytes、启停耗时。安装耗时独立统计至少30次；报告峰值、末值、趋势而不只均值。新增哈希/解压/ETag sidecar/重试的触发频率逐项说明。
- [ ] 明确无变化tick不写盘、语音关闭TTS请求0、停用活动任务0；网络取消在阻塞read时的最长等待及UI响应单独测。预算失败最迟在越界块写入前，不能在下载完成后才统计。
- [ ] 受影响线程/Qt/取消测试在CPU高负载下跑3遍；worker为本任务所有，Event控制停止、finally回收；记录实际CPU与PID，不按名称kill系统Python。主测试预算宽，不用sleep赌时序。

### 11.2 最终门禁（最后代码冻结后，不能边修边引用前一轮结果）

```powershell
& $P -m ruff check .
& $P -m pytest -q --tb=short tests/test_architecture.py tests/test_petcore_architecture.py tests/test_petcore_docs.py tests/test_pr_report_discipline.py
$petcoreTests = (Get-ChildItem tests -Filter 'test_petcore*.py').FullName
& $P -m pytest -q --tb=short @petcoreTests
& $P -m pytest -q --tb=short "--junitxml=$S\full-final.xml"
& $G diff --check
```

- [ ] 每条按§0.3保存原始输出/退出码，前条失败停止，不用最后命令exit0覆盖前面的失败。整仓必须未过滤、执行完成且进程exit0；记录passed/skipped/warnings及每个skip真实原因。
- [ ] 门禁后再修改任何产品/测试/依赖代码，重跑相关门禁与风险对应全仓。只改文档可跑文档门，但需hash证明产品未漂移，不能把修改前全仓写成修改后的验证。
- [ ] PR报告逐文件原因+增删行、新增/删除列表、性能实测、Windows记录、失败原文与剩余缺口；附件不能只留无法随clone获得的scratch路径，关键命令/摘要必须写入已跟踪报告。
- [ ] 补LNNN与索引、文档互链；各状态明确“实现/自动化/源码实机/冻结包实机/待发布”，不把总测试数当功能验收。

### 11.3 交付包与发布待办（本轮不执行公开动作）

- [ ] 本地交付：四个immutable命名ZIP、candidate-manifest、根待发布索引、独立verifier输出、冻结候选（如可构建）、PR报告、升级/回滚数据说明、更新后的HANDOFF。每个产物列路径/字节/SHA256，ZIP/EXE/个人路径不提交源码Git。
- [ ] 发布说明逐步列出：用户确认目标repo/tag→再次验证摘要→检查同版本不存在或完全一致→人工上传Release资产→真实HTTPS逐跳/Range/断流验收→确定索引ref→切换三源并取消blocked→验证ETag/离线回退。每步写失败回滚方式，不提供默认自动执行整串发布命令。
- [ ] 若公开地址未发布，状态必须“本地候选通过，待发布；远端端到端未验”。未经用户再次确认，不调用gh release/create/upload、git tag/push tag、发布API或覆盖既有资产。
- [ ] 最后给用户“完成项/修改文件/证据/限制/下一步”，不要仅说全部完成；将活跃进程、未完成任务、精确下一命令写HANDOFF。没有活跃任务也明确写0。

## 12. 自审覆盖矩阵与验收签字

| 原批准要求 | 落点 | 通过证据 |
|---|---|---|
| 仓库清单+GitHub Release，不新服务 | T05/T06/T09 | schema1待发布索引、构建实际摘要、发布步骤 |
| CDN/raw/API、ETag/cache/过期提示 | T02/T06 | 来源切换/304/离线测试，未发布远端单列 |
| 逐跳HTTPS/Range/上限/取消/释放 | T02/T04 | 恶意跳转目标访问0、206/416参数矩阵、close断言 |
| 64MiB/256MiB/10000只用于功能包 | T01/T03/T04 | 实际流量计数、content边界未变 |
| ID/version/API/Core/capabilities、授权 | T04/T06 | manifest错配red-green、flag来源、marker攻击拒绝 |
| 真实安装/更新失败/回滚、旧数据保留 | T04/T07 | 四包真实ZIP和数据SHA、故障注入 |
| Core0.2/API1/四包版本固定 | Global/T05 | manifest与ZIP/index逐字一致 |
| Python3.11、完整pytest正常退出 | T00/T09 | 全仓原始输出/XML/exit0，无新增skip掩盖 |
| 负载3遍、15+60×3、30循环 | T07/T09 | CPU/IO/线程/timer/网络/耗时实测 |
| Windows冻结/双宠/日历与语音 | T08 | 实机截图和进程退出；SAC或依赖阻断保留 |
| 不公开发布/不改真实数据/不扩功能 | Global/T09 | pending状态、明确发布再确认 |

**继任模型最终自检：**每个T的checkbox有证据；任何未过门禁不勾完成；没有编造的命令结果、摘要或链接可用性；代理写集无冲突；文档只以执行当日事实为准。遇到本计划与当前代码漂移，先更新问题清单与接口对照，不机械执行过时行号。
