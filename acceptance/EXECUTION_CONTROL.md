# 18 个 Windows EXE：执行控制表

基线：用户冻结的完整工程链、业务完整度与禁止空壳标准。整理日期：2026-09-30。

这份表是工作目录与下一件可验收产物，不是 18 个项目已完成的声明。Issue 的 open/closed、历史 CI 绿色或 EXE 文件名均不能作最终验收。工程／业务分母及当前候选证据未完整核证时，两条线和综合完成度都填“未核证”。

## 先解决真正限制交付的事情

1. 每个项目先有完整需求基线和实际入口清单；缺源码就明确恢复来源，不先造界面。
2. 把“禁止空壳”变成逐入口的输入→调用→后端效果→失败传播→证据对账；测试数量、截图与关键字存在不能替代。
3. 先在已有 SSQ 实现中修可复现的验收漏洞，同时建立可复用报告预检。其他项目逐个接入，不能宣称共用工具完成就等于 18 项通过。
4. 开发轮次优先最多两条正在推进的交付链，减少并行半成品；其余保持在目录，缺口不删、不重命名成完成。
5. 每次修复以“一个问题＋反例＋回归＋证据”收口。候选变更后仍完整重走 Real Network→Windows Build→Exact EXE→实体点击及成品联网→Same Hash→Final Gate。

## 固定目录

以下“下一件产物”是待核证／待执行事项，不是已达成结论。源码、分支和现有证据应先恢复检查，不能直接重写已有项目。

| 项目 | 任务入口 | 下一件可验收产物 |
|---|---|---|
| 双色球 SSQ | [#6](https://github.com/douluo511/Geometry-Lotto-Pro/issues/6) | 修复验收器假 PASS 路径；同一 GUI 更新操作的原文独立重解析与哈希绑定；完整入口基线 |
| 大乐透 DLT | [#7](https://github.com/douluo511/Geometry-Lotto-Pro/issues/7) | 当前分支来源／NetClient／GUI 调用证据与完整业务基线对账 |
| 心理系统 | [#9](https://github.com/douluo511/Geometry-Lotto-Pro/issues/9) | 实际用户任务、知识／案例范围与安全边界逐项验收 |
| 人性系统 | [#12](https://github.com/douluo511/Geometry-Lotto-Pro/issues/12) | 恢复分支真实功能与来源证据，补完整入口清单 |
| 投资金融系统 | [#13](https://github.com/douluo511/Geometry-Lotto-Pro/issues/13) | 当前真实数据、风险／成本／泄漏验证和成品入口证据 |
| 英语词根系统 | [#8](https://github.com/douluo511/Geometry-Lotto-Pro/issues/8) | 内容覆盖、学习任务结果与更新／Same Hash 逐项复核 |
| 国学智策／国学经典 | [#10](https://github.com/douluo511/Geometry-Lotto-Pro/issues/10) | 资料来源、规则／案例范围及实际检索／推理入口证据 |
| 头部信息系统 | [#14](https://github.com/douluo511/Geometry-Lotto-Pro/issues/14) | 当前真实来源、时效／冲突与用户信息任务验收 |
| TalkCraft／表达训练 | [#15](https://github.com/douluo511/Geometry-Lotto-Pro/issues/15) | 训练任务→Engine→评估→真实反馈的完整执行证据 |
| Stock AI Pro／选股软件 | [#16](https://github.com/douluo511/Geometry-Lotto-Pro/issues/16) | 精确源码恢复、演示回退隔离、独立验证与成本基线 |
| 真实资金金融系统 | [#17](https://github.com/douluo511/Geometry-Lotto-Pro/issues/17) | 源码／目的恢复，真实数据与泄漏／成本／风险契约 |
| Passive Income Pipeline OS | [#18](https://github.com/douluo511/Geometry-Lotto-Pro/issues/18) | 精确 v0.2 源码与真实用户流程恢复，核实更新／联网 |
| 地球 Online／人生底层系统 | [#19](https://github.com/douluo511/Geometry-Lotto-Pro/issues/19) | 原始需求、业务规则和源码恢复，冻结可实测任务 |
| AI 音乐制作系统 | [#20](https://github.com/douluo511/Geometry-Lotto-Pro/issues/20) | 原始目的、素材授权、实际创作／导出链及源码恢复 |
| 法哲学原理研习系统 | [#21](https://github.com/douluo511/Geometry-Lotto-Pro/issues/21) | 候选源码、原始资料及研习案例／反例基线恢复 |
| 不赚辛苦钱操作系统 | [#22](https://github.com/douluo511/Geometry-Lotto-Pro/issues/22) | x64 候选源码恢复，真实业务任务与数据／规则证据 |
| 做自己主人系统 | [#23](https://github.com/douluo511/Geometry-Lotto-Pro/issues/23) | 候选源码、完整任务清单及更新／失败路径恢复 |
| 快乐 8 预测系统 | [#24](https://github.com/douluo511/Geometry-Lotto-Pro/issues/24) | 完整官方历史数据可复盘证明；不可用则阻断模型及最终发布 |

总控：[Issue #11](https://github.com/douluo511/Geometry-Lotto-Pro/issues/11)。保留 18 条记录，不能以缺源码为由移出范围。

## 每个工作项的最小执行卡

```text
项目／issue：
原始需求／业务目标：
当前候选 commit／EXE hash：
本次唯一缺口及可复现反例：
修复范围／不改变的合同：
成功与失败退出条件：
实际执行／UTC／环境／测试日志 URI＋SHA-256：
仍然未核证的项：
下一件可验收产物：
```

输出卡必须根据执行结果填写，不预填 PASS。测试夹具只用于可控测试，不作为真实生产数据或 Real Network 证明。

## 四层证据，不能混为一谈

| 层次 | 能证明什么 | 不能代替什么 |
|---|---|---|
| 结构校验 | 字段、类型和格式满足 schema | 证据真实性、完整范围、正确百分比 |
| 报告语义／文件预检 | 独立基线清单、引用、版本、时间、文件哈希与重算覆盖率一致 | 真实执行来源、业务价值、人工签核 |
| 项目专用动态验收 | 当前源码与 Exact EXE 实际执行、物理点击、真实联网／后端效果及失败路径 | 完整业务范围和长期维护能力 |
| 全项目最终放行 | 工程 100%＋业务 100%＋完整证据＋Final Gate PASS | 当前外部服务永久可用的承诺 |

## 不绕过现有阻断，也不虚构授权

当前仓库治理另要求独立仓库与独立更新器进程。可见聊天中的“独立 EXE”不能自行推导这两项已经获批。本轮保留现有阻断；把来源／批准依据作为独立治理项补齐。搬仓库本身不算功能进展，仓库结构通过也不替代禁止空壳。

## 长期使用必须有验收产物

备份恢复实测、坏盘／损坏数据恢复、更新中断与回滚、依赖和数据源维护责任、证据保留及访问控制、普通权限与中文路径、版本迁移和退出／导出能力，都须映射回冻结需求与具体测试。若原完整范围尚未定义这些阈值，提出明确补充基线，不能填写“已支持”。

每小时监督继续唯读；只有实质变化通知。开发推进必须单独形成修复与测试，不把“监控正在运行”描述成“代码正在完成”。
