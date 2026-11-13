# SSQ＋DLT｜统一预测母体 V1

**工程状态：Draft / SHADOW / formal_A=0 / NO_EDGE。**
新的单一预测入口负责完整模型注册、统一预测输出与审计，而不是自动将算法视为有预测优势。

## 第一性原理

每期开奖目标必须包含同一完整模型注册表，不因异常或物理数据不足漏掉结果行。只有开奖前可获得的数据才能影响该期号码；未来球组、开奖后出球顺序、来源不明的原文字节不能被假装成已知特征。

母体每彩种注册 16 条模型位置：

- 6 条冻结 V4.7 研究模型：`hot60`、`ewma`、`shrinkmix`、`pairwise_d2`、`challenger`、`random_null`。
- 5 条 V4.7 探索性模型：`hot30`、`hot120`、`pair_margin`、`pair_residual`、`recency_pair_h45_120`。
- 3 条旧超算独立实现：`supercompute_hot60`、`supercompute_ewma30`、`supercompute_random_null`。
- 2 条物理研究模型：`physical_exit_order`、`physical_ball_group`。

固定的 V4.7 `random_null` 是唯一保留的原统计对照；旧超算的独立随机实现不能替换它。

## 核心重点

### 唯一命令入口

Windows PowerShell（仓库根目录）：

~~~powershell
python -m research.mother_v1.cli --input .\two_games.json --out .\forecasts\new_issue --print-summary
~~~

物理证据账本已保存在本地并可以独立复核时：

~~~powershell
python -m research.mother_v1.cli --input .\two_games.json --out .\forecasts\new_issue_physical --physical-ledger .\research\physical_evidence_v1 --print-summary
~~~

输出为三个不可覆盖的文件：

- `predictions.json`：每彩种 16 个模型的完整输出、状态、模型源码哈希、参数哈希、历史哈希。
- `audit_receipt.json`：本次输入与输出的 SHA-256、不可信本地时间、固定模型数量。
- `full_model_report.md`：完整中文号码表；物理拒绝预测时明确列出 ABSTAIN。

任何一种彩种输入不合法则整批拒绝，不做缺项的“部分预测”。历史数据最少 120 期，严格限制为目标之前、用户标注 as-of 当日或更早的连续期号；尚无外部可信的来源真实性或公布时间验证。

### 物理模型

- `physical_exit_order`：至少 60 期合格的、原文 SHA256 校验通过、匹配开奖前历史的真实出球顺序，才允许输出探索性研究号码。其算法并无已证实优势。
- `physical_ball_group`：必须有未来一期球组在销售截止前已被独立验证的公开证据；当前未实现此证据验证，因此恒为 ABSTAIN。
- 当前 SSQ 官方历史表只有排序结果，不能代表红球的真实出球顺序。当前 DLT 实际物理样本不足，均不能声称做出物理预测。
- 为保持模型列表完整，物理 ABSTAIN 行中另附固定 Random NULL 的展示占位号码，且标注 `fallback_is_physical_forecast=false`；它不是物理预测。

### 独立测试与示例

使用编造的离线数据验证结构、代码哈希、前瞻数据边界：

~~~powershell
python -m unittest research.mother_v1.test_mother -v
python -m research.mother_v1.fixture --out .\fixture.json
python -m research.mother_v1.cli --input .\fixture.json --out .\fixture_run --print-summary
~~~

重放 2026-11-13 对应的两种彩票预测研究：

~~~powershell
python -m research.mother_v1.historical_example --out .\archive_input_20261113.json
python -m research.mother_v1.cli --input .\archive_input_20261113.json --out .\archive_run_20261113 --print-summary
~~~

历史样例中最新 9 期/彩种为原研究当时人工转录的发行机构结果，**没有在此脚本中保存完整官方原文字节与第三方可信开奖前时间戳**。即便脚本以后成功重跑也只能称历史研究回放，不能冒充提前封存的真实预测。

### 老代码审计与清理

| 旧代码 | 身份 | 当前处理 |
|---|---|---|
| `harness_v46/core.py` | 冻结 V4.7 参数、固定 Random NULL | 只读，保留用于精确复现 |
| `harness_v46/model_versions/` | 历史原始源码身份 | 绝对保留，不重写封存 |
| `harness_v46/d2_challenger_lab.py` | 5 条探索算法 | 保留为隔离模型提供者 |
| `supercompute/engine.py` | 3 条原独立算法 | 保留为隔离研究提供者 |
| `supercompute/automation/*physical*` | 官方历史原文字节、球组和出球顺序、失败记录 | 保留为物理证据提供者 |
| 旧 Windows P0 调度与官方来源门禁 | 独立外部调用关系 | 未核验前不删 |
| 废弃的 `desktop._bytes`、`statistics._pmf`、`dlt_physical_source.fetch_http` | 已证明没有内部使用 | 在 PR #489、#490 中清理，母体基于清理后的代码 |
| 旧历史预测与失败样本、源码 SHA、时间收据 | 审计必须的旧记录 | 保留不可变 |

母体取代的是未来统一批次的**调度与输出入口**，不是抹除旧模型的可追溯实现。删除仍被调用的旧文件会破坏复现与审计；不得因用户要求精简而绕过此门禁。

### 未通过的生产门禁

- 当前新母体是研究 PR，未在默认分支部署/排程。
- DLT 官方物理源网络可用性与有效出球历史尚未通过；SSQ 物理出球数据仍未知。
- 缺少独立官方来源签名和第三方可信开奖前封存。
- 没有成功通过独立随机基线和固定 NULL 的正式前瞻显著性检验。

最终研究结论：**NO_EDGE。**

## 权威资料

- 仓库 PR #467：V4.7 冻结核心模型及历史回放。
- 仓库 PR #488：SSQ/DLT 物理开奖采集与不可覆盖审计。
- 仓库 PR #489、#490：两个模型辅助函数和一个物理旧函数的已核实清理。
- 官方历史开奖源：上海市福利彩票发行中心、广东省体育彩票中心；独立来源与公布时点应逐次核实。
