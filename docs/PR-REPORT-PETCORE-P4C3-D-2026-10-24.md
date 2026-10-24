# P4-c3 D：节日、节气与生日提醒（2026-10-24）

> 初版状态（保留当时记录；后续联合验证见文末）：已实现、关联自动化126passed；性能/Windows综合/累计全仓待C–E冻结后验收，未发布。
> 关联：[C报告](PR-REPORT-PETCORE-P4C3-C-2026-10-24.md)、[规格](PETCORE-SPEC.md)、[路线图](PETCORE-ROADMAP.md)、[日志](PETCORE-LOG.md)。

## 一、核心特性

移植仓库当前tracked `pet/festival*.py`纯规则与文案（不是import旧pet业务、不是合并主分支）；覆盖46个节日/节气规则、农历闰月排除、大小月除夕、浮动节日与同日多节日。保留手动查询，新增自动默认关闭/语音默认关闭、分类、1–6次或自定义时点和文案。

生日仅本地MM-DD，默认空、分类全关仍有效、02-29只闰年；自动总开关关闭时不提醒生日。按slot持久化日高水位与已触发点；启动过首点补一次，已提醒当天重启不重复。一个15秒timer、64项日历缓存、DND共用B摘要。让位规则依据当前配置/日期/分钟，不依赖tick先后，停用撤销。

## 二、修改文件说明

<!-- FILE_TABLE -->
统计切片：baseline-d→baseline-e；25个文件。命令为`git diff --no-index --numstat --ignore-cr-at-eol`，新文件与空基线比较。C/D冻结切片之后的联合文档回填和边界修复归E；不是把此前48文件全算成本批。

| 文件 | 增/删 | 性质 | 改了什么及原因 |
|---|---:|---|---|
| `docs/INDEX.md` | +2 / −0 | 修改 | 登记C/D/E报告并移入PR存档，提供唯一文档入口。 |
| `docs/PETCORE-LOG-INDEX.md` | +2 / −0 | 修改 | 登记本批LNNN范围和证据入口，避免只改日志不改索引。 |
| `docs/PETCORE-LOG.md` | +7 / −0 | 修改 | 追加逐批实现、失败到通过记录与准确后续边界。 |
| `docs/PETCORE-ROADMAP.md` | +5 / −0 | 修改 | 分开实现/自动化/源码实机/待分发状态，旧批次保留为历史。 |
| `docs/PETCORE-SPEC.md` | +5 / −0 | 修改 | 补充提醒域默认值、版本化数据及当前验收层次。 |
| `docs/PR-REPORT-PETCORE-P4C3-D-2026-10-24.md` | +43 / −0 | 新增 | 记录本批逐文件/TDD/性能/Windows实机与限制；追加当前证据而不抹去历史失败。 |
| `examples/petcore-mods/fun.festival/host/__init__.py` | +3 / −0 | 新增 | 使用包入口，纯规则留在mod内而非import旧pet业务。 |
| `examples/petcore-mods/fun.festival/host/cleaning.py` | +53 / −0 | 新增 | 抽取文案/时点清洗纯函数，去掉旧语音模块业务依赖。 |
| `examples/petcore-mods/fun.festival/host/domain.py` | +49 / −0 | 新增 | 纯生日MM-DD校验/分类合并、每日有限缓存及显示文案选择。 |
| `examples/petcore-mods/fun.festival/host/factory.py` | +10 / −100 | 修改 | 连接完整runtime/设置/手动查询，不授权自动提醒。 |
| `examples/petcore-mods/fun.festival/host/festival.py` | +318 / −0 | 新增 | 移植现有提醒配置、分类、时点与文案纯逻辑，保留主线规则。 |
| `examples/petcore-mods/fun.festival/host/festival_calendar.py` | +145 / −0 | 新增 | 移植lunar-python农历/节气转换与浮动节日/除夕算法。 |
| `examples/petcore-mods/fun.festival/host/festival_data.py` | +160 / −0 | 新增 | 移植稳定节日/节气规则表，保持农历闰月与同日多节日语义。 |
| `examples/petcore-mods/fun.festival/host/festival_quotes_cn.py` | +327 / −0 | 新增 | 保留中华节日文案与来源分组，避免运行时依赖旧pet目录。 |
| `examples/petcore-mods/fun.festival/host/festival_quotes_west.py` | +176 / −0 | 新增 | 移植西方文案入口与基础引用，保持原有文案选择。 |
| `examples/petcore-mods/fun.festival/host/festival_quotes_west_game.py` | +80 / −0 | 新增 | 移植游戏类西方节日文案及原始出处。 |
| `examples/petcore-mods/fun.festival/host/festival_quotes_west_movie.py` | +98 / −0 | 新增 | 移植影视类文案及原始出处。 |
| `examples/petcore-mods/fun.festival/host/festival_quotes_west_song.py` | +52 / −0 | 新增 | 移植歌曲类文案及原始出处，分发授权仍需后续复核。 |
| `examples/petcore-mods/fun.festival/host/runtime.py` | +166 / −0 | 新增 | slot日高水位/去重、默认关闭、生日与DND共用交付、独立分钟让位规则。 |
| `examples/petcore-mods/fun.festival/host/settings_page.py` | +113 / −0 | 新增 | 分类/自动/生日/次数或自定义时点/文案/语音；依赖项禁用及窄页纵向布局。 |
| `examples/petcore-mods/fun.festival/host/store.py` | +33 / −0 | 新增 | 版本化日与触发时点，原子保存、无变化不落盘、异常状态不覆盖。 |
| `examples/petcore-mods/fun.festival/mod.json` | +11 / −4 | 修改 | 更新候选版本、Core>=0.2.0,<1.0.0与实际能力声明；不改变feature授权默认。 |
| `petcore/config.py` | +27 / −0 | 修改 | 加入各宠物提醒偏好及安全默认，不把业务状态或宠物设置变为全局。 |
| `tests/test_petcore_festival.py` | +139 / −0 | 新增 | 覆盖默认关闭、生日类别独立、日状态、重启/回拨、设置取消与让位规则。 |
| `tests/test_petcore_festival_calendar.py` | +422 / −0 | 新增 | 移植已知日期期望，覆盖闰月/除夕/24节气/浮动节日与生日边界。 |

没有删除产品文件；原始JSON表保存在`.scratch/petcore-p4c3/d-file-stats.json`。
<!-- /FILE_TABLE -->

## 三、实现要点

- 原始规则来源为本地tracked实现（festival来源commit04269ac57ea3f9ce0c1676f6c9ed0fe7c0eea558）；本地origin/main旧引用不含这些文件，不声称已核对远端最新主分支。
- `festival-slot-N-v2.json`与设置快照分离、原子提交后交付；损坏或不可写不覆盖。普通tick不补一整天错过时点，重启只补一次。
- 清洗函数移为mod内纯模块；lunar-python仍为现有依赖。没有节日动画开关、外部生日请求或新服务器。
- fun.festival1.1.0要求Core>=0.2.0/API1。代码回滚不删除v2，旧版本只保留其手动查询能力。

## 四、性能分析

待最终冻结后15+60秒、前后各三遍实测。默认自动关闭不换算、不起工作线程、不写运行状态；这项需与数字共同验收，不仅凭代码断言。

## 五、实机运行记录

目前完成真实Qt offscreen设置回归；Windows原生、明暗窄宽截图与生日（合成日期）在C–E联合场景执行，尚不宣称完成。没有真实生日/账号/外部TTS。

## 六、测试与验证

- `d-red`：新包入口不存在，收集1error/exit2；保留原始输出。
- `d-green`：60passed/3.63s/exit0；历法纯用例由原本的已知日期断言移植，未以实现输出反填期望。
- `d-related`：126passed/14.54s/exit0；覆盖C、配置、安装、架构、B端口、设置。Ruff通过。
- runtime新增生日/02-29、默认、跨日/回拨/重启、无变化不写盘、DND、取消、写失败和独立让位规则；正式chime发声接入在E做最小适配。
- 原始记录`.scratch/petcore-p4c3/d-*.txt/json`；完整全仓和CPU高负载待最终代码冻结执行。

## 七、限制与后续

E48签/chime适配尚未实现。文案保留旧版权分文件结构与出处，不代表新增公开分发授权结论；候选分发阶段仍需携带NOTICE并审核。其他Python/平台/双屏/真实TTS/安装包未验证；没有发布。


## 八、2026-10-24 C–E联合验证补充

联合同环境15秒预热+60秒采样，before1–3/最终after4–6各三遍：CPU均值0.588%→0.553%，RSS采样末均值45.409→48.250MiB；Core timer1→3（新增todo/festival15秒），停用后0，六轮无变化采样write_count/bytes与网络/TTS均0。完整逐轮数字、命令、成本与限制见[E报告性能节](PR-REPORT-PETCORE-P4C3-E-2026-10-24.md#四性能分析)。不是把测试耗时当性能。

Windows最终源码`cde-native-5`21.7433603秒/exit0，独立配置和四mod本地安装、双宠、隐藏通知、合成02-29生日、DND两条摘要、设置保存取消、30面板/30装卸和退出通过；真实PCM结束后2.8138102秒揭签。此前120次资源排查已保留，完整路径/截图/物理通知点击缺口见[E报告实机节](PR-REPORT-PETCORE-P4C3-E-2026-10-24.md#五实机运行记录)。无真实生日或账号。

高负载20worker/CPU99.8–99.9%三遍86passed，覆盖C/D/E及B端口与Qt退出；最终累计整仓9837passed / 20skipped / 15warnings / 1565.27s / exit0，petcore/公共门1662passed，Ruff通过；原文与skip归因见E报告。D/E目前均已实现，初版“尚未实施”是当时快照；分发仍未开始，没有可发布结论。
