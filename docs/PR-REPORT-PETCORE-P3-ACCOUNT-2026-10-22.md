# petcore P3：Core 账户与余额基础——修改文件说明、性能分析、实机运行记录

> **基线**：P2 提交 `3e29bee`
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-22
> **范围**：账户服务、余额协议、API port 和稳定错误分类
> **关联**：[P2 报告](PR-REPORT-PETCORE-P2-WORKER-OFFLINE-2026-10-22.md)、[功能矩阵](PETCORE-FUNCTION-MATRIX-2026-10-22.md)

## 一、核心特性

Core 新增 `AccountService`，通过现有 `ApiStore` 和钥匙串读取 DeepSeek 余额协议，提供
30 秒内存缓存、多币种选择、稳定错误分类和 `ApiPort.fetch_balance()`。请求正文和响应体
不会进入日志，密钥仍只从钥匙串读取。另增加按 slot/角色隔离的聊天会话存储，为后续 AI
worker 提供历史边界；AI/识屏/Agent 业务尚未接入。

## 二、修改文件说明

| 文件 | 改动意图 |
|---|---|
| `petcore/account/__init__.py` | 导出账户服务。 |
| `petcore/account/service.py` | 余额请求、缓存、协议解析和错误分类。 |
| `petcore/contracts/api.py` | 为 mod API port 增加余额查询能力。 |
| `petcore/ui/ports.py` | CoreApiPort 转发到账户服务。 |
| `petcore/ui/app.py` | CoreHost 创建并持有进程级 AccountService。 |
| `tests/test_petcore_account.py` | 覆盖缓存、多币种、缺密钥、未知协议和 HTTP 429。 |
| `petcore/chat/session_store.py` | 每宠/每角色会话文件、消息上限、原子写和路径隔离。 |
| `tests/test_petcore_sessions.py` | 覆盖主宠/子宠隔离、消息上限、临时文件收口和路径逃逸。 |

## 三、实现要点

- 余额 endpoint 固定由服务的 `balance_protocol` 决定，未知协议不会猜 URL。
- HTTP 401/403、429、网络、超时和协议错误只向上抛稳定 reason，不回显响应体。
- 缓存按 service id 隔离，默认 30 秒；显式 `force=True` 可绕过缓存。
- 账户服务属于 Core，业务 mod 只能通过 `HostPorts.api` 调用。

## 四、性能分析

本阶段没有运行时常驻线程；每次非缓存查询产生 1 次网络请求和 1 次有界响应读取，缓存命中只做一次字典查找。网络请求由调用方决定是否放入 WorkerHost，当前没有同步接入桌面菜单。

| 指标 | 实测 | 归属 |
|---|---:|---|
| 账户/API/net/架构测试 | 84 passed / 1.89s | 新增 Core 服务 |
| 会话存储测试 | 3 passed / 0.83s | 新增每宠历史路径 |
| 默认缓存 TTL | 30 秒 | 新增内存状态 |
| 新增常驻线程 | 0 | 本阶段 |
| 新增磁盘写入 | 0 | 余额只在内存缓存 |

## 五、实机运行记录

```text
pytest test_petcore_account.py test_petcore_api.py test_petcore_net.py test_petcore_architecture.py -q
84 passed in 1.89s
pytest tests/test_petcore_sessions.py -> 3 passed in 0.83s

ruff check petcore tests/test_petcore_account.py
All checks passed!
```

真实钥匙串和远程 DeepSeek 请求未在夜间执行，测试使用可控 transport 接缝；缺密钥、429、
响应解析和缓存行为均已实测。真实账户请求、菜单气泡和余额自动刷新留给后续 P3 UI/worker 阶段。

## 六、测试与验证

| 门 | 结果 |
|---|---|
| Account/API/net/architecture | 84 passed |
| ruff | 通过 |

## 七、已知限制与后续

- 尚未增加余额菜单/设置按钮和异步 UI 展示。
- 尚未把会话存储接到 AI worker 或聊天窗口。
- 尚未迁移主分支余额档位动画、自动刷新和灵动岛展示。
- API Key 仍以 Core API service id 为钥匙串 key，旧 Chat 配置的 key 不自动复制。

## 八、风险与回滚

本阶段只新增 Core 服务和 port，不改变现有菜单；可直接 `git revert`。缓存为进程内存，回滚不会留下磁盘状态。
