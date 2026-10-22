# SSQ＋DLT V4.7｜REA＋Harness 深度评审与首轮代码改进

**状态：DRAFT / SHADOW。** 本文件记录代码级评审与已提交的 V4.7 研究分支改动，不代表官方数据已通过核验、外部 TSA 已完成、正式 A 已获授权或 D2 优势已证实。V4.5 正式八槽与历史证据未修改。

## 1. 本轮实际执行的选择

统一候选实现仍以 PR #432 的 `research/harness_v46/` 为整合入口：保留 #426 的不可变 per-RUN_ID/per-lottery context 设计，采用 #425 当前版本的确定性重放校验，并在该整合分支上推进 V4.7 的明确契约。#427 保留为独立历史研究分支；不把其预测或账本行直接迁入新版本。

### PR 代码定位与兼容性

| PR | 代码定位 | 可复用内容 | 不可直接合并/未证明 |
|---|---|---|---|
| #425 | `research/harness_v46/` 六流研究核心；规范单彩种 snapshot、candidates、primary D2、ticket | 规范数据结构、固定模型名、重放验证、追加式本地账本 | HEAD 本身不含 #426 的 run_context 身份门；原始来源真伪、外部 TSA、正式授权仍缺 |
| #426 | 基于较早 #425 提交的 run_context 增强 | RUN_ID＋彩种＋目标期＋快照哈希＋as-of＋cutoff 不可混用 | 其 base 不是 #425 当前 HEAD；需将当前 #425 的重放强化显式移植，不可假设自动包含 |
| #427 | `research/ssq_dlt_v46_harness/`，包装 V4.5 模型 | 十角色映射、历史模型研究实现、独立 smoke 测试 | 使用 `game/history/asof`，而 #425/#426 使用 `lottery/draws/as_of/sales_cutoff`；不同模型公式、参数、输出 schema 与 ledger，不能直接迁移预测 |
| #429 | 双彩种原子账本与 staged publication | 同一 SQLite transaction 内双彩种批次提交、冲突回滚 | DB commit 与文件发布不是同一个 ACID 事务；发布失败仍需恢复，不能声称已产生外部可信封存 |
| #430 | D2 配对精确检验与 Holm-12 探索性模块 | 作为独立评估组件候选 | 输入结果仍由调用者提供；不能证明开奖来源、预测冻结或预注册真实性 |
| #431 | 独立只读 12/12 完整性审计 | 完整批次、SHA 与结构检查 | 本地 DB 一致性不等于官方来源真实性、外部 TSA 或正式 A 资格 |
| #432 | test10 convergence、状态机、manifest、调度原型 | 唯一整合 PR；运行身份、角色/工具声明、合成测试 | 角色工具白名单目前是代码契约，不是进程/OS 沙箱；TSA 只是 NOT_VERIFIED 请求记录；真实 Windows 冷启动与30分钟恢复未验收 |

### 算法差异：禁止把同名模型当成同一模型

**#425/#426 原型算法定义：**

- Hot60：最近60期前区/红球出现频率，分数降序、号码升序打破平局。
- EWMA：最多最近120期；每期先将全部号码权重乘0.92，再对当期号码加0.08。
- ShrinkMix：近期60期频率与完整可用历史频率融合，近期权重为 60/(60+200)，`tau=200`。
- Pairwise-D2：最近120期；期望共现计数为 `count(a)*count(b)*(k-1)/(n*k)`，残差为 `(observed-expected)/(n+200)`；组合分数再加单号边际项 `(count(a)+count(b))/n`。因此它并非纯粹的“只按配对残差排序”，必须用边际分数消融实验验证增量。
- Challenger：对固定30/60/120窗口的配对分数取最小值，选择最大最小分数的组合；当前仍是未注册探索候选。
- V4.6 Random NULL 原来使用 Python `random.shuffle`；V4.7 已登记新的 SHA256 排序排列规则，属于新的对照算法版本，不得与旧 seed/version 的结果混算。

**#427 包装的 V4.5 算法定义：**

- Hot60：最近60期频率。
- EWMA：所有输入历史，半衰期20期。
- ShrinkMix：Hot60 与 EWMA 各占一半，并各自使用20个均匀伪观测收缩。
- Pairwise-D2：最近60期配对出现次数优先、单号边际和次之；D2 直接选对，不等于 #425 的120期残差模型。
- Random NULL：SHA256 派生种子后调用 Python MT19937 抽样。
- #427 的 wrapper 又把 `ordered_dan`、`D1-D5` 规范成有序前缀；这与 V4.5 原模块中独立生成的 Dk 集合并不完全相同，必须保留为新版本契约，不能宣称算法等价。

因此：V4.5 模型、#427 wrapper、#425/#426 模型各自保留原版本与历史。任何迁移必须重新登记模型版本、参数合同与源码 SHA256；不可把历史预测重算后覆盖旧记录。

## 2. 本轮已提交到整合分支的代码改进

1. **120期硬门槛**：新增 `validate_study_snapshot`。双彩种 manifest、CLI 预测入口与 freeze 写入均拒绝少于120期的历史快照；Pairwise-D2 也要求完整120期，而不再接受60–119期却使用标注为120期的参数。
2. **固定随机对照的跨平台排列**：V4.7 使用 `SHA256_SORT_V1`，按 `SHA256(prefix|ball)` 排序生成排列，避免把 Python 版本的 shuffle 实现当作随机算法定义。新 seed ID：`SSQ-DLT-V47-NULL-SHA256-SORT-v1-20261022`。旧 V4.6 随机结果保留，不能混算。
3. **参数 SHA256 完整化**：参数合同覆盖模型参数、模型版本、号码规则摘要、平局规则、ticket 后区生成算法和 seed ID。
4. **源码身份**：每个候选包含模型核心源码文件字节 SHA256；RUN manifest 包含模型源码 SHA、参数 SHA、工具白名单与编排源码 SHA。
5. **RUN_ID 身份强化**：新 schema 使用 `V47-` 前缀；RUN_ID 派生输入包括两个彩种各自的目标期/as-of/cutoff/快照摘要、六个模型注册身份、参数 SHA、源码 SHA 和工具白名单。旧 V4.6 RUN_ID 不迁移、不覆盖。
6. **回归测试**：新增少于120期的 manifest/CLI/freeze 阻断测试、Pairwise 120期窗口测试、参数合同完整性测试及 SHA256 排列输入顺序不变测试。

这些改动是工程防护增强，不是命中率提升证据。合并前必须以本分支最新 CI 原始日志确认测试结果。

## 3. SHA 身份的精确定义

- `raw_evidence[].sha256`：实际官方原始文件的字节 SHA256。
- `snapshot_sha256`：规范化 JSON 对象的语义摘要。
- `parameters_sha256`：完整 V4.7 参数合同摘要。
- `model_source_sha256`：模型核心源码文件的字节 SHA256。
- `harness_source_sha256`：编排模块源码文件的字节 SHA256。
- `prediction_sha256`：规范化冻结预测 payload 的 SHA256。

以上哈希保护不同对象，不能互相替代。哈希只证明给定字节/对象的身份，不证明来源官方、生成时间早于停售、操作者有授权或文件无法被有权限者替换。

## 4. 统计功效复核

假设单个固定模型、每期开奖独立、基线已知，备择概率为基线绝对增加1个百分点，单侧精确二项检验，目标功效至少80%，且不做中途窥视。复算结果：

| 彩种 | 基线 (p_0) | 假设 (p_1) | 单项 α=0.05 最小期数 | α=0.05/12 保守最小期数 |
|---|---:|---:|---:|---:|
| SSQ | 15/528 = 2.8409% | 3.8409% | 1,972 | 3,816 |
| DLT | 10/595 = 1.6807% | 2.6807% | 1,284 | 2,474 |

复算临界值与功效：

- SSQ，n=1,972，拒绝临界值 X≥69；基线尾概率约0.048869，备择功效约0.800614。
- SSQ，n=3,816，X≥137；基线尾概率约0.004049，备择功效约0.800838。
- DLT，n=1,284，X≥30；基线尾概率约0.048206，备择功效约0.800366。
- DLT，n=2,474，X≥60；基线尾概率约0.003937，备择功效约0.800565。

最后一列使用 Bonferroni 的 α=0.05/12 作为保守设计阈值；这不是声称精确计算了完整 Holm step-down 的功效。同期配对 Random NULL 的 McNemar/符号检验功效还依赖两组结果的 discordant-pair 比例，不能由独立二项样本量直接推断。

**保持原12项家族的建议（尚未注册）**：每个“模型×彩种”只有一个主要声明：同时超过理论基线与同期 Random NULL。可先对两项单侧检验分别计算 p 值，取 `p_joint = max(p_baseline, p_paired_null)` 作为交集-并集检验的候选级 p 值，再对原12个候选级 p 值执行 Holm。这个规则必须在新前瞻输出之前由审计角色书面注册；在注册之前不得当作已生效规则。

## 5. 仍然 BLOCKED / NOT_RUN

- 没有通过 G00/G01 的真实官方双来源、至少120期原始文件、逐期语义交叉核对与可信目标期/停售时间验收。
- 尚无已验证的外部 RFC 3161 TSA token / 第三方见证签名；当前 `tsa_request` 只是本地不可变请求身份，状态仍是 `NOT_VERIFIED`。
- 聊天框之间没有自动消息通道；十角色图和 handoff JSON 不会自行发送到另一个 ChatGPT 对话，也不提供 OS 级隔离。
- 没有真实 Windows 冷启动、计划任务触发、断网/断电恢复日志；CI 不能替代用户主机实测。
- DLT 69/2880 负对照异常仍为 UNRESOLVED。
- 研究正式 A=0、NO_EDGE；不自动购买彩票。

## 6. 接受标准

- `ENGINEERING_PASS`：最新提交在 Ubuntu/Windows CI 通过，并完成真实 P0 故障注入；合成测试通过只是其中一部分。
- `RESEARCH_VALID`：真实官方 as-of 数据、事前唯一主D2、不可覆写提交、外部可信事前时间证明、官方结果独立核验与只读复盘齐全。
- `D2_EDGE_CONFIRMED`：冻结模型在未来未见开奖中，同时满足预注册的基线与同期 Random NULL 优势、置信区间/校正/停止规则与独立复验。


## 7. Follow-up integrity hardening — 2026-10-22

At reviewed HEAD `0b4ba1c195df365d3ef5bb2fefcc795655e7ed42`, the convergence branch adds two narrowly scoped fixes:

- Ledger and workflow initialization enable `PRAGMA recursive_triggers=ON` on application write connections. Regression tests now attempt `INSERT OR REPLACE` against frozen prediction, run-context and TSA rows; these paths must fail on initialized application connections.
- The V4.7 manifest's orchestration-source identity is now a canonical digest over `convergence.py`, `schedule.py`, `cli.py`, `windows_shadow_tasks.ps1` and `invoke_v46_shadow.ps1`, so changes to the scheduler/CLI entrypoints change the manifest identity. `core.py` remains separately bound by each model-source SHA.

Observed exact-head CI run: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39732792617 — Ubuntu and Windows Server 2022 both succeeded with 36 tests each; Ubuntu skips the Windows-only PowerShell parser test, while Windows runs it.

**Security boundary:** SQLite `recursive_triggers` is connection-specific. This improves the application's initialized write paths; it does not stop a separate client using different PRAGMA settings, a privileged user changing the database file, or replacement of the entire file. These triggers are defense-in-depth, not WORM storage. External trusted pre-cutoff evidence remains BLOCKED / NOT_RUN.
