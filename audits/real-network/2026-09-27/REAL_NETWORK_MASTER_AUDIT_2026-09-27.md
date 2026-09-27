# Windows EXE 项目真实网络总监察

生成时间：2026-09-27（America/New_York）  
执行口径：用户冻结的 Master System Architecture。任何 `PENDING / WARNING / UNAVAILABLE / SKIPPED / UNKNOWN / NOT_EVALUATED` 均不算 PASS；能启动 EXE 不等于通过。

## 1. 总结论

- 纳入总监察：18 个独立 Windows EXE 项目。
- 真实网络总门明确 PASS：**0 / 18**。
- 本机可定位并实际复验的 Windows 程序：**3 个**（SSQ v6.1.0、DLT v1.0.0、Stock AI Pro）。
- SSQ 与 DLT 的旧版可用程序在本次公网运行中成功取得真实数据并完成多源一致性核对；但它们缺少统一有限重试、指数退避+jitter、Content-Type 验证、逐响应原文留存和完整网络故障注入，因此网络总门仍为 FAIL。
- SSQ 的目标版本 v8.4、DLT 的目标版本 v2.1.2 RC5 均未出现在当前工作区；旧版本网络结果不得继承给目标版本。
- Stock AI Pro 本次 exact binary 的网络访问失败，系统转入明确标记的演示数据，`production_final_pass=FAIL`。它没有把演示数据冒充生产 PASS，但其 exact-binary 验收仍输出 `software_verdict=PASS`，且验收结果没有覆盖真实网络子项，不能作为网络 PASS。
- 其余 15 个项目在当前 Windows 工作区没有可定位的源码 + Exact EXE + 新协议证据链，统一按 `UNAVAILABLE -> FAIL`，不沿用聊天记录中的口头进度或沙盒下载声明。

## 2. 统一验收矩阵

符号：`P`=有本次可复验证据的通过子项；`F`=失败；`U→F`=不可用，按冻结规则计失败。总状态只允许 PASS/FAIL。

| 项目 | 本次对象 | 源可达/真实数据 | 超时 | 有限重试 + 指数退避+jitter | 多源回退/交叉核对 | 解析/语义校验 | Fail-Closed | Contract Test | Fault Injection | 原文+时间+hash+来源 | 网络总状态 | 是否需重构 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 双色球 SSQ | v6.1.0（非目标 v8.4） | P | P | F | 交叉核对 P；回退 F | P | 断网注入 P | F | F（仅验证断网/代理拒绝） | 时间/hash/来源 P；原文留存 F | **FAIL** | 是，重构 NetClient/证据/测试；目标版须重跑 |
| 大乐透 DLT | v1.0.0（非目标 v2.1.2 RC5） | P | P | F | 交叉核对 P；回退 F | P | 断网注入 P | F | F（仅验证断网/代理拒绝） | 时间/hash/来源 P；原文留存 F | **FAIL** | 是，重构 NetClient/证据/测试；目标版须重跑 |
| 心理系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，建立独立可复验网络链 |
| 人性系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，原型不可继承最终门 |
| 投资金融系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，需独立 Source/NetClient/Evidence |
| 英语词根系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，候选版须重新验收 |
| 国学智策/国学经典 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，补权威源与完整失败链 |
| 头部信息系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，信息源与回退链需重建 |
| TalkCraft / 表达训练 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，仍需完整 NetClient 层 |
| Stock AI Pro / 选股软件 | StockAIPro.exe | F（四个端点均失败） | P | F | F | 本次不可验证→F | 最终门 P；网络验收覆盖 F | F | F | F | **FAIL** | 是，网络层与 exact-binary 验收必须重构 |
| 真实资金金融系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，授权/真实资金源为硬前置 |
| Passive Income Pipeline OS / 收益管道 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，需真实外部服务与证据链 |
| 地球Online / 人生底层系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，按独立系统从源层建立 |
| AI 音乐制作系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，API/模型服务失败链需建立 |
| 法哲学原理研习系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，候选 EXE 不得继承旧门 |
| 不赚辛苦钱操作系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，建立真实网络与更新证据 |
| 做自己主人系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，建立独立 Updater/NetClient 证据 |
| 快乐8预测系统 | 未定位当前 Exact EXE/源码 | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | U→F | **FAIL** | 是，规划状态不能进入验收 |

## 3. 已实际执行的证据

### SSQ v6.1.0（非目标 v8.4）

- Exact binary SHA-256：`9ed8ba6f781da0fafd2640e1508d2245814f9c5381828fb3153810ae6c383d0b`
- 本次真实网络时间：`2026-09-27T20:21:24Z` 至 `2026-09-27T20:21:26Z`。
- 中国福彩网 L0：HTTP 200，21 页，2,070 期；最新 `2026112 / 2026-09-27 / 01 04 11 12 17 29 + 11`。
- 上海福彩 L1 与河北福彩 L2：均 HTTP 200，最新期号和号码与 L0 一致；验证标识 `L0_L1_L2_CONSENSUS`。
- Canonical SHA-256：`838c59b4c10c1ead087070dfbf4d51d75300a9483df34ae8fe24e4b4a3b28dae`。
- 断网注入：强制不可达代理后返回 `status=FAIL / error_type=ProxyError`；未生成 `source_evidence.json` 或 `official_history.json`，证明该场景没有错误 PASS。
- 失败项：请求代码只有 `(connect=10s, read=35s)` 超时；没有统一 retry/backoff/jitter；没有 Content-Type 检查；省级源和主源均为必需链，不是回退链；只保存 hash/bytes/URL 清单，没有保存每个原始响应正文；没有 403/404/429/5xx/坏 Content-Type/坏 schema/空数据/多源冲突的完整 fault suite 与 contract suite。

### DLT v1.0.0（非目标 v2.1.2 RC5）

- Exact binary SHA-256：`9023c913fc041e173bc7b879549740e4254b1bb4ab3c42e0733f1be653233427`。
- 本次真实网络时间：`2026-09-27T20:21:26Z` 至 `2026-09-27T20:21:27Z`。
- 国家体彩主源：HTTP 200，30 页，2,928 期；最新 `26110 / 2026-09-26 / 03 24 25 26 35 + 07 09`。
- 江苏体彩交叉源：HTTP 200，100 条重叠记录全部一致。
- Canonical SHA-256：`6b7bd70107c22cca2fd6f3444e5ccd1dba958104c81355fdbd46d1b9f4ee5b5b`。
- 断网注入：强制不可达代理后返回 `status=FAIL / error_type=ProxyError`；未生成新历史或证据文件。
- 失败项：与 SSQ 相同；另外 DLT 的分页 raw manifest 没有记录每页 URL，证据可追溯性更弱。

### Stock AI Pro

- Exact binary SHA-256：`f489194033f546dd25f3f64d234cc6e2381fde971625ee3126cecc94c26559b1`。
- 本次真实网络运行：四个东方财富候选端点均连接失败；`Network check=UNAVAILABLE`，随后使用 `DEMO_SYNTHETIC_OFFLINE`，152 行。
- Fail-Closed：`DataGate=UNAVAILABLE`、`ValidationGate=PENDING`、`FinalPass=FAIL`，没有把演示数据提升为生产 PASS。
- 关键缺陷：exact binary 的 acceptance 仍报告 `software_verdict=PASS`，且输出中没有真实网络、全市场覆盖、历史覆盖和 wire evidence 子项；这与冻结的 Final Gate 口径不兼容。
- 源码审计发现：只有固定的单次页面重试（250ms/750ms），没有统一有限重试、指数退避+jitter；不验证 Content-Type；允许降级到明文 HTTP；只保留合并 wire hash，不保存逐响应原文/URL/时间戳；`real_network` 判断逻辑只排除 `UNAVAILABLE`，因此 `WARNING` 存在被算通过的风险。

## 4. 必须重构的共同项

所有项目在申请网络 PASS 前必须具备并由 Exact EXE 重新跑完：

1. 单一 NetClient：独立 connect/read timeout、幂等请求有限重试、指数退避+jitter、429 `Retry-After`、5xx 重试白名单、总时限与响应大小上限。
2. 响应验证：HTTP、TLS、Content-Type、schema、语义、新鲜度、时间单调性、空数据、重复、跨源冲突。
3. 多源策略：Primary 与 Secondary 必须是独立来源；明确 failover 条件；备用源成功必须标明 `FALLBACK`，不能悄悄当 Primary PASS；跨源不一致必须 HARD FAIL。
4. 证据：逐请求保存 URL、来源级别、UTC 请求/响应时间、HTTP 状态、Content-Type、headers 摘要、原始响应文件、raw SHA-256、parser/schema 版本、canonical SHA-256、父子 lineage。
5. 故障注入：DNS、connect/read timeout、403/404/429/500/502/503、错误 Content-Type、HTML 代 JSON、坏/缺字段、空/截断/超大 payload、hash 不符、多源冲突、缓存损坏、数据库锁/只读/磁盘不足。
6. Fail-Closed：失败可以保留旧缓存供“查看”，但更新结果必须 FAIL；UI 不得显示“更新成功”；Final Gate 必须枚举并拒绝所有非 PASS 状态。
7. Exact EXE 绑定：网络证据、fault/contract 结果、EXE SHA-256、最终交付 hash 必须为同一个版本；行为代码变化后旧证据自动失效。

## 5. 并入总监察表

| 项目范围 | 真实网络门 | 可进入 Exact EXE 最终验收 | 说明 |
|---|---:|---:|---|
| SSQ 目标 v8.4 | FAIL | 否 | 目标 binary 缺失；旧版仅有部分网络证据 |
| DLT 目标 v2.1.2 RC5 | FAIL | 否 | 目标 binary 缺失；旧版仅有部分网络证据 |
| Stock AI Pro | FAIL | 否 | 本次源不可达；网络层与验收逻辑需重构 |
| 其余 15 项 | FAIL | 否 | 当前工作区无可复验源码/Exact EXE/新协议证据 |
| **总计** | **0 / 18 PASS** | **0 / 18** | 无项目可凭本次结果宣布完整版 |

## 6. 证据位置

详细运行文件保存在本任务工作目录的 `work/real-network/` 与 `work/fault-injection/` 下；可交付副本已汇集到 `outputs/evidence/`。机器可读总矩阵为 `outputs/real_network_validation_matrix.json`。

