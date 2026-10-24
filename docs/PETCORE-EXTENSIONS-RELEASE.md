# petcore 功能扩展发布手册（待执行）

> 状态：**未发布**。本地候选产物已验收；公开索引、Release 资产与默认源切换均未发生。
> 依据：[分发计划](superpowers/plans/2026-10-24-petcore-p4c3-distribution.md) T09、[T07 验收](PR-REPORT-PETCORE-DISTRIBUTION-T07-2026-10-24.md)、[T08 签名包](PR-REPORT-PETCORE-DISTRIBUTION-T08-2026-10-24.md)。
> 执行前提：**用户明确批准发布**。本手册里的命令不得由 agent 自动整串执行。

## 1. 当前产物（本地，未上传）

| 包 | 版本 | 字节 | sha256 |
|---|---|---:|---|
| `fun.divination` | 1.1.0 | 19169 | `b6b47112423d5b763d31b8884b8f3ce3f6c4a1cbb21608ef2ba0b4d9b81c6f9c` |
| `fun.festival` | 1.1.0 | 41454 | `e4c5111441fff3545d7f5a6e36bd01ccf7aeb6b78b04e560b681020f15b2e6ac` |
| `reminder.todo` | 1.1.0 | 9655 | `e431ba505cf92037d2cb1fed8ff88cf2b39ea6bfc4ac5d6af92ca47056fee2c0` |
| `voice.chime` | 1.1.1 | 17522 | `dc4094c09625226cb76b2bfaf7d792524553dc47c74a74b8a60451ce84dd5ffb` |

冻结候选（本地）：`dsh-pet-core.exe` 15,079,368 B / `dc40aa268ceb3f4c…`；`dsh-pet-core-setup.exe`
261,718,360 B / `bc26e800044a2f14…`；两者开发证书签名 `Valid`。**开发证书只在本机可信，公开分发必须换 CA 证书。**

## 2. 发布前必须确认的三件事

1. **仓库与标签**：`scripts/build_petcore_extensions.py` 里的 `RELEASE_REPO` / `RELEASE_TAG` 当前是拟定值
   （`MerZlin/dsh-pet-indesktop` / `petcore-extensions-v0.2.0-rc1`）。发布前由用户确认或改写。
2. **同版本是否已存在**：远端同版本摘要必须与本地产物**逐字节一致**；不一致就停，由用户决定新版本号，
   绝不覆盖既有 Release 资产。
3. **默认索引源**：`petcore/market/source.py::DEFAULT_INDEX_URLS` 仍指向 `MerZlin/dsh-pet-extensions`。
   切换到本仓库属于发布动作，需用户明确批准并在切换后做一次真实 HTTPS 验收。

## 3. 步骤（每步失败都要能回滚）

### 3.1 重建并核对候选（任意机器可复现）

```bash
python scripts/build_petcore_extensions.py --output dist-extensions
python scripts/verify_petcore_extensions.py --candidate-manifest dist-extensions/candidate-manifest.json
```
预期：`verified 4/4`；四个 sha256 与 §1 一致。**不一致不要继续。**

### 3.2 上传 Release 资产（人工）

上传四个 ZIP 与 `candidate-manifest.json` 到确认后的仓库/标签；不覆盖同名资产。
上传后用浏览器或 `curl -I` 确认 200 与 `Content-Length` 与清单一致。

回滚：删除本次 Release（或改标签为预发布），保持旧索引仍指向旧资产。

### 3.3 生成公开索引

```bash
python - <<'PY'
import json, sys
sys.path.insert(0, "scripts")
from build_petcore_extensions import build_index
index = build_index("dist-extensions/candidate-manifest.json", local=False)
open("extensions-index.json", "w", encoding="utf-8", newline="\n").write(
    json.dumps(index, ensure_ascii=False, indent=2) + "\n"
)
PY
```
`schema_version` 必须仍是 1；四包 `blocked` 由 `true` 改由发布流程显式改为 `false`（本手册不做）。
提交前跑 `pytest -q tests/test_petcore_extension_index.py`。

回滚：`git checkout -- extensions-index.json`。

### 3.4 真实 HTTPS 验收（发布后必须做）

```bash
python -m petcore market --root .scratch/https-accept --index-url https://raw.githubusercontent.com/<repo>/<tag>/extensions-index.json list --json
python -m petcore market --root .scratch/https-accept --index-url <同上> install reminder.todo --allow-feature --json
```
要观察并记录：逐跳跳转（`github.com → objects.githubusercontent.com` 命中 `allowed_hosts`）、
`Content-Range` 续传、断流重试、`sha256` 校验、`mods/` 落盘与 `market-lock.json`。
**本地 `file:` 验收不能代替这一步。**

回滚：不切默认源就不影响用户；已下载的候选可在隔离 root 内删除。

### 3.5 切换默认源（可选，需单独批准）

改 `DEFAULT_INDEX_URLS` 为新索引地址（保留旧地址作第二源），跑
`pytest -q tests/test_petcore_market_source.py tests/test_petcore_market_cli.py`，再跑真实 HTTPS 验收。
回滚：改回旧地址并 reload。

## 4. 明确不做

- 不由 agent 执行 `gh release create/upload`、`git tag`、`git push --tags`。
- 不覆盖已存在资产、不强推、不合并 `main`。
- 不在未确认的情况下把 `blocked` 改成 `false`。
- 不把开发证书用于公开分发。
