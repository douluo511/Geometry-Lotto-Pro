# SSQ＋DLT V4.7｜test2 官方数据核验任务

**状态：待人工复制到 test2 聊天框。该文件不会自动发送到另一个 ChatGPT 对话。**

## 唯一职责
只做官方数据、目标期和历史快照核验；不选号、不看任何模型当期候选、不批准正式 A。

## G00：逐彩种确认目标
对双色球 SSQ 和大乐透 DLT 分别从发行机构官方页面确认：
- 最新已开奖期、官方开奖日期和完整号码；
- 下一合法未开奖目标期及其官方期历依据；
- 当期实际销售截止时间、开奖时间和时区；
- 休市、节假日、特殊开奖安排及公告；
- 官方发布时刻与本次抓取时刻。

此前的暂定期号只作为待查线索，不能直接锁定。任何字段缺少权威证据，G00=BLOCKED。

## G01：每彩种至少120期快照
每个彩种分别交付：
1. 至少120期、全部早于目标期的历史记录；不能用目标开奖结果或任何未来发布的数据。
2. 两个不同的官方来源及原始文件字节。保存URL、抓取时间、发布时间、文件大小、原始文件SHA256。
3. 机器可读JSON/CSV；逐期检查期号唯一、期序和开奖时间严格递增、号码范围与数量正确、缺期/重复期、跨来源号码一致性。
4. 精确区分三种摘要：原始来源文件字节SHA256、规范化快照JSON SHA256、数据内容/字段校验结果。不能把一种哈希冒充另一种。
5. 为每个彩种保存单独的 as-of、目标期、停售时间、开奖时间、来源清单、历史记录数、冲突报告和哈希复算方法。
6. 在独立复算后返回实际文件/提交链接和SHA256，不得人工编造哈希或用示例数据冒充官方历史。

## 输出格式
- SSQ：G00 PASS/BLOCKED；G01 PASS/BLOCKED；目标期；停售/开奖时间；历史记录数；两个原始文件SHA256；规范快照SHA256；来源差异与缺期。
- DLT：同上。
- 若任何一项不合格，说明具体缺失证据和可继续的非阻塞事项；不得为了出号而降级要求。
- 本任务完成前，test3–test8不得生成有效前瞻候选。只有两个彩种各自G00/G01通过，才可向六个模型分发各自同一份锁定快照。

正式状态继续 SHADOW；没有外部可信事前时间证明、授权和独立审计时，不得声称正式 A 或 D2_EDGE_CONFIRMED。


## 2026-10-22 live-review notes — source leads, not admission

- Shanghai Welfare Lottery Center homepage currently displays SSQ issue 2026120, dated 2026-10-20: red 13 14 16 18 20 31, blue 03 — https://www.swlc.net.cn/index.html
- Gansu Sports Lottery Center history page currently displays DLT issue 26120, dated 2026-10-21: front 01 06 10 15 32, back 03 04 — https://www.gstc.org.cn/wanfa/dlt_history
- These pages establish only the latest visible page facts. They do not satisfy the two-source 120+ history requirement, nor prove the next target's actual sales cutoff or absence of special scheduling.
- Candidate official roots for controlled verification: SSQ `swlc.net.cn` + `cwl.gov.cn`; DLT `gstc.org.cn` + `fjtc.com.cn` or `sporttery.cn`. The current code can preserve supplied raw bytes and compare supplied parsed rows, but no live official fetch/parser has yet bound raw bytes to parser output. Treat all G00/G01 states as BLOCKED until that gap is closed.
