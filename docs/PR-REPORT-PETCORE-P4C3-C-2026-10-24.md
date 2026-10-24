# P4-c3 C：完整待办提醒（2026-10-24）

> 初版状态（保留当时记录；后续联合验证见文末）：实现及关联自动化通过；本批性能、Windows综合和累计全仓验收待C–E冻结后补充，不以B全仓替代。
> 关联：[B报告](PR-REPORT-PETCORE-P4C3-B-2026-10-24.md)、[规格](PETCORE-SPEC.md)、[路线图](PETCORE-ROADMAP.md)、[日志](PETCORE-LOG.md)。

## 一、核心特性

按slot保存版本化清单/触发标记；非模态面板新增、编辑、删除（两步确认）、启停、一次性/每日/无时间和下一条预览。默认提前5分钟/语音关闭，10分钟宽限内补发、超时跳过；同tick同条目的到期覆盖提前，多个条目合并一次文字交付。一次性超过宽限归档。DND走B统一摘要，无积压语音。

## 二、修改文件说明

<!-- FILE_TABLE -->
统计切片：baseline-c→baseline-d；20个文件。命令为`git diff --no-index --numstat --ignore-cr-at-eol`，新文件与空基线比较。C/D冻结切片之后的联合文档回填和边界修复归E；不是把此前48文件全算成本批。

| 文件 | 增/删 | 性质 | 改了什么及原因 |
|---|---:|---|---|
| `docs/INDEX.md` | +2 / −0 | 修改 | 登记C/D/E报告并移入PR存档，提供唯一文档入口。 |
| `docs/PETCORE-LOG-INDEX.md` | +2 / −0 | 修改 | 登记本批LNNN范围和证据入口，避免只改日志不改索引。 |
| `docs/PETCORE-LOG.md` | +8 / −0 | 修改 | 追加逐批实现、失败到通过记录与准确后续边界。 |
| `docs/PETCORE-ROADMAP.md` | +5 / −0 | 修改 | 分开实现/自动化/源码实机/待分发状态，旧批次保留为历史。 |
| `docs/PETCORE-SPEC.md` | +5 / −0 | 修改 | 补充提醒域默认值、版本化数据及当前验收层次。 |
| `docs/PR-REPORT-PETCORE-P4C3-C-2026-10-24.md` | +41 / −0 | 新增 | 记录本批逐文件/TDD/性能/Windows实机与限制；追加当前证据而不抹去历史失败。 |
| `examples/petcore-mods/reminder.todo/host/__init__.py` | +3 / −0 | 新增 | 声明包入口以支持相对导入，宿主不承担待办业务规则。 |
| `examples/petcore-mods/reminder.todo/host/factory.py` | +10 / −112 | 修改 | 精简为菜单/设置/runtime接线，替代旧纯文本清单入口。 |
| `examples/petcore-mods/reminder.todo/host/model.py` | +90 / −0 | 新增 | 实现版本化条目、occurrence高水位、10分钟宽限/提前/到期和下一条预览。 |
| `examples/petcore-mods/reminder.todo/host/panel.py` | +170 / −0 | 新增 | 新增非模态CRUD编辑器、启停、删除确认、下一条预览和可见保存失败。 |
| `examples/petcore-mods/reminder.todo/host/runtime.py` | +188 / −0 | 新增 | 每15秒协调slot调度与交付；生命周期取消和先建job避免同步回调未绑定token。 |
| `examples/petcore-mods/reminder.todo/host/settings_page.py` | +65 / −0 | 新增 | 保留每宠偏好与取消恢复，窄页纵向行避免控件裁切。 |
| `examples/petcore-mods/reminder.todo/host/store.py` | +33 / −0 | 新增 | 旧清单/备份保留，按slot原子保存v2，磁盘成功才提交内存。 |
| `examples/petcore-mods/reminder.todo/mod.json` | +11 / −4 | 修改 | 更新候选版本、Core>=0.2.0,<1.0.0与实际能力声明；不改变feature授权默认。 |
| `petcore/__init__.py` | +1 / −1 | 修改 | Core候选提升0.2.0，API版本不变，为新增通用接口声明兼容边界。 |
| `petcore/config.py` | +7 / −0 | 修改 | 加入各宠物提醒偏好及安全默认，不把业务状态或宠物设置变为全局。 |
| `petcore/mods/json_store.py` | +33 / −0 | 新增 | 共用原子JSON读写：同目录临时文件、fsync、replace，失败不损坏原文件。 |
| `tests/petcore_reminder_support.py` | +70 / −0 | 新增 | 复用真实Qt调度/免打扰，合成宠物与OS/TTS边界，不mock业务调度。 |
| `tests/test_petcore_todo.py` | +125 / −0 | 新增 | 覆盖无损迁移、跨午夜/宽限/回拨/重启、去重、归档、原子失败。 |
| `tests/test_petcore_todo_runtime.py` | +120 / −0 | 新增 | 覆盖slot交付、CRUD设置取消、隐藏/DND、关宠与同步语音拒绝。 |

没有删除产品文件；原始JSON表保存在`.scratch/petcore-p4c3/c-file-stats.json`。
<!-- /FILE_TABLE -->

## 三、实现要点

- `todo-slot-N-v2.json`与legacy-v1备份均在mod数据目录；旧配置不删除、不推断日期。atomic临时文件、flush/fsync、replace后才更新内存，失败不声称成功。
- 每条lead/due保存occurrence高水位，跨午夜/重启/回拨不重放。偏好仍是宠物配置；设置取消不恢复运行数据文件。
- 一个15秒调度器，无变化tick不写盘。停用/关宠关闭面板、撤销语音与迟到交付代次。
- Core候选0.2.0/API1；todo1.1.0要求Core>=0.2.0。代码回滚保留v2，旧代码只能看到旧兼容文本清单。

## 四、性能分析

待C–E冻结后同环境15秒预热、60秒采样、前后各三遍实测，不能用测试耗时充当性能结论。

## 五、实机运行记录

当前为真实Qt offscreen自动化（面板30循环），尚不等同Windows源码综合实机。后者与D/E统一执行；无真实账号/外部TTS。

## 六、测试与验证

- `c-model-red`：1failed/10errors（新数据入口缺失）；`c-model-green`：11passed/1.15s。
- `c-runtime-red`：4errors（runtime尚不存在）；`c-runtime-green`：18passed/2.25s。
- 首次关联命令包含不存在的test_petcore_config.py，exit4/no tests；已纠正文件名，未排除失败用例。
- `c-related-2`：95passed/13.05s、exit0（待办、配置归属、安装、扩展导航、架构、B端口、设置）。Ruff通过。
- 原始TXT/JSON和完整命令在`.scratch/petcore-p4c3`；累计全仓/高负载待最终冻结后执行。

## 七、限制与后续

D/E及分发未实施；本报告不宣称可发布。其他Python/平台/双屏/真实TTS/安装包仍无本批证据；不会操作真实安装。


## 八、2026-10-24 C–E联合验证补充

联合同环境15秒预热+60秒采样，before1–3/最终after4–6各三遍：CPU均值0.588%→0.553%，RSS采样末均值45.409→48.250MiB；Core timer1→3（新增todo/festival15秒），停用后0，六轮无变化采样write_count/bytes与网络/TTS均0。完整逐轮数字、命令、成本与限制见[E报告性能节](PR-REPORT-PETCORE-P4C3-E-2026-10-24.md#四性能分析)。不是把测试耗时当性能。

Windows最终源码`cde-native-5`21.7433603秒/exit0，独立配置和四mod本地安装、双宠、隐藏通知、合成02-29生日、DND两条摘要、设置保存取消、30面板/30装卸和退出通过；真实PCM结束后2.8138102秒揭签。此前120次资源排查已保留，完整路径/截图/物理通知点击缺口见[E报告实机节](PR-REPORT-PETCORE-P4C3-E-2026-10-24.md#五实机运行记录)。无真实生日或账号。

高负载20worker/CPU99.8–99.9%三遍86passed，覆盖C/D/E及B端口与Qt退出；最终累计整仓9837passed / 20skipped / 15warnings / 1565.27s / exit0，petcore/公共门1662passed，Ruff通过；原文与skip归因见E报告。D/E目前均已实现，初版“尚未实施”是当时快照；分发仍未开始，没有可发布结论。
