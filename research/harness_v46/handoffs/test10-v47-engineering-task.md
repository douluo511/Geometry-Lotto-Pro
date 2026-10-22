# SSQ＋DLT V4.7｜test10 / 09 工程下一轮执行令

**只在现有 #432 convergence 分支继续；不新建互相竞争的规范 PR，不合并 main。**

PR：https://github.com/douluo511/Geometry-Lotto-Pro/pull/432  
Issue：https://github.com/douluo511/Geometry-Lotto-Pro/issues/428  
深度评审：../V47_DEEP_REVIEW.md

## 当前已提交的实现
- V4.7 六研究流、固定 SHA256_SORT_V1 Random NULL、120期历史门槛和参数/模型源码SHA。
- 双彩种 manifest-derived RUN_ID；manifest、完整规范化 snapshot preimage 均追加式保存。
- 冻结时绑定 manifest 与 snapshot；08 独立只读批次检查重新加载快照并确定性重放六模型，拒绝合法号码的事后替换。
- `source_fetch.py` 已加入受限HTTPS原始字节抓取、每彩种域名白名单、重定向校验、25MB上限；本地抓取时间不可信，HTTP Last-Modified不冒充发布时间。原始字节可通过SQLite BLOB保全，但来源真实性仍为 NOT_VERIFIED。
- 双来源 120+ 已解析记录比较器；校验期号/开奖时间顺序、号码范围、as-of、来源之间一致性及与锁定快照一致性。它不抓取或解析真实网页，故 G00/G01 仍 BLOCKED。
- 精确 D2 基线二项检验、同期开奖 Random NULL 配对精确检验、交集并集 p 值、明确家族 Holm、模型率精确置信区间和保守配对差区间。输入结果/12项家族均未认证，始终 SHADOW / NO_EDGE。
- Windows Task Scheduler 代码仅通过静态检查和CI；未在用户主机安装、未做冷启动/断网实测。
- 最近已观测代码提交 `51de08dc90da6599772a5a86366ef2f358070baf` 的 CI Run #39749449435：Ubuntu/Windows各70项测试成功；Ubuntu跳过一项Windows专用PowerShell解析测试。随后仅有文档更新；每次执行前仍必须核对PR #432当前HEAD及其CI。

## 下一轮最高优先级
1. 用 `source_fetch.py` 对两个不同官方根域执行受控live fetch；实现并验证具体官方页面/API解析器。保存真实原始字节、URL、HTTP头、抓取时刻、可证实的发布时间、raw SHA和parser版本SHA。现在只有fetch原语和mock测试，没有live请求或source parser。
2. 将两个来源的解析输出与原始字节、120+逐期快照严格绑定；不能仅接受调用者提供的“已解析数组”。逐期核对缺期、重复期、号码、日期和冲突。若来源格式或发布时间不能核实，G01=BLOCKED。
3. 核验两个彩种的官方最新期、下一合法目标期、停售/开奖时间与休市安排；不得凭开奖星期推定实际停售时间。
4. 实现外部RFC3161或等价第三方可信时间证明，验证返回令牌/签名和时间；仅生成请求SHA仍为 NOT_VERIFIED。
5. 将正式12项假说映射到既有注册身份；未确认映射之前，新统计模块只是算术工具，不能冒充有效预注册。新 Challenger 另行预注册。
6. 继续执行九类P0，严格区分合成注入与真实主机验收；保留DLT 69/2880负控异常，直到根因证据闭环。

## 每轮交付格式
实际改动文件、Commit SHA、最新CI Run与逐平台测试数、P0矩阵、原始数据/快照/参数/源码SHA、外部封存状态、正式A样本数、NO_EDGE裁决、未解决问题与下一项可证伪假说。禁止自动购买彩票；禁止宣称其他ChatGPT聊天框已自动互通。
