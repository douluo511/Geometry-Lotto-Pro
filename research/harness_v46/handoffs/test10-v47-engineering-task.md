# SSQ＋DLT V4.7｜test10 / 09 工程下一轮执行令

**只在现有 #432 convergence 分支继续；不新建互相竞争的规范 PR，不合并 main。**

PR：https://github.com/douluo511/Geometry-Lotto-Pro/pull/432
Issue：https://github.com/douluo511/Geometry-Lotto-Pro/issues/428
深度评审：../V47_DEEP_REVIEW.md

## 已完成且不得重复实现
- 120期最小历史门槛：manifest、CLI forecast、freeze；Pairwise-D2要求120期。
- V4.7 model/source/parameter identity；SHA256_SORT_V1 Random NULL。
- V47 RUN_ID绑定游戏快照上下文、模型/参数/源码身份、工具白名单与编排源码身份。
- Ubuntu与Windows Server 2022最新合成 CI 每个平台36项通过。
- 历史 V4.5/V4.6证据不迁移、不覆写；正式 A=0 / NO_EDGE。

## 继续完成的阻塞项
1. **官方来源解析**：只允许官方来源白名单；保存原始字节、发布时间、抓取时间和SHA；实现两个官方来源的逐期语义比对与缺期/冲突拒绝。不能把本地文件SHA等同官方真实性。
2. **真实快照契约**：把原始文件字节SHA、规范化快照SHA、目标期/停售/开奖时间、as-of和来源证据分别登记；缺任何必需字段即 BLOCKED。
3. **真实外部TSA**：实现一个有响应签名验证的外部RFC3161或等价可信时间提供者接口；只生成请求哈希仍然是 NOT_VERIFIED。
4. **冻结与统计**：持久化模型注册表和预注册协议；追加式提交清单；独立只读评分需验证官方结果证据、目标期、全部六流完整性、唯一主D2、同期开奖Random NULL配对与固定停止规则。
5. **阶段护栏**：逐阶段要求对应证据字段；不能仅靠写入通用 `SHADOW` 状态就将所有关卡标记为通过。未授权/未验证阶段必须明确 BLOCKED/NOT_RUN。
6. **九项 P0 故障注入**：时间穿越、留出集篡改、伪造授权、TSA/SHA失败、官方冲突、缺期/重复写入、槽位替换、指标/择优偏差、断网/断电恢复。区分合成故障与真实主机验收。
7. **Windows真实运行**：在用户主机记录 Task Scheduler 实际触发、冷启动、断网、30分钟补偿和禁止补造预测的日志；GitHub CI不能代替此证据。
8. **版本与迁移**：PR #427 的 V4.5公式包装与 V4.7核心不得直接视为同算法。任何移植都需要明确映射、参数SHA、源码SHA、等价测试和新版本身份。

## 交付格式
实际改动文件、commit SHA、最新CI run及逐平台测试数、P0矩阵、真实/合成证据分类、未完成项、正式A样本数、统计裁决。不要自动购买彩票，不得宣称预测优势。
