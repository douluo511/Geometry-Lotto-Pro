# Stock AI Pro — 可交付软件唯一总规范（Delivery Spec）

> **用途**：这是 Stock AI Pro 后续开发唯一基准。  
> **目标**：让 Codex 基于现有工程，做出一个普通 Windows 用户可以“下载 ZIP → 解压 → 双击 → 自动更新 → 自动训练 → 自动预测 → 自动查看结果”的可交付软件。  
> **原则**：不再扩散新功能；没有验证通过的模块不进入生产评分；先把主链做实，再做增强。

---

# 1. 我们到底要做什么

Stock AI Pro 是一套 **A 股选股研究与决策支持软件**。

它不是：
- 保证赚钱的软件；
- 自动下单软件；
- “AI 必涨股”软件；
- 靠故事解释股票的软件。

它要做的是：

> 用严格时间安全的数据和样本外验证，对当前 A 股候选进行相对排序；把估值、风险和交易成本纳入决策；每天冻结预测；随后用真实未来行情验证；如果模型没有持续超过基准，就降低权重、停用路径或进入 NO_TRADE。

最终用户看到：
- 今日 Top20；
- 进攻 / 平衡 / 防守三套组合；
- 每只股票评分拆解；
- 预计交易成本；
- 实时估值；
- 市场状态；
- 模型可信度；
- 最近回测；
- 最近审计；
- 系统健康状态。

---

# 2. 交付成功的唯一标准

真正“可交付”必须满足：

```text
下载 ZIP
→ 解压
→ 双击 ONE_CLICK_START.bat
→ 自动检查/修复环境
→ 自动创建运行目录
→ 自动更新数据
→ 自动训练
→ 自动预测
→ 自动冻结结果
→ 自动打开 Web UI
→ 第二次以后无需重新安装
```

同时：

```text
数据失败 → 不生成伪预测
模型失败 → 不生成伪预测
依赖损坏 → 自动修复或明确报错
网络失败 → 保留上一期有效预测
```

**ZIP 能打开不算交付；普通用户能从空目录跑起来才算交付。**

---

# 3. 当前项目真实状态

## 3.1 已经完成的底座

当前已有 v3.0.0 工程底座，包含：

- Python 项目结构；
- Windows BAT / PowerShell 启动链；
- `.venv` 自动建立逻辑；
- AkShare 数据接入；
- 实时股票池；
- 历史行情增量缓存；
- 当前上市 + 可取得的退市研究池；
- 主/备用行情思路；
- 18 个价格/成交额时间安全特征；
- Ridge；
- HistGradientBoosting；
- 时间切分；
- horizon embargo；
- 市场状态；
- Top20；
- 进攻 / 平衡 / 防守组合；
- 预测冻结；
- SHA-256；
- Walk-forward 基础回测；
- Random 基准；
- Momentum 基准；
- 5 Why；
- 标签打乱；
- 时间错位；
- 特征漂移；
- MODEL TRUST 基础；
- Streamlit UI；
- 日志；
- 自动计划任务；
- 基础自检。

## 3.2 v4.0 最终实现状态

### 成本
已完成并进入生产闭环：
- 佣金与最低佣金；
- 卖出印花税；
- 双边过户费；
- 基础滑点；
- 基于成交额参与度与区间波动的动态冲击；
- 预计往返成本；
- `score_cost`；
- `expected_net_alpha = expected_alpha - estimated_roundtrip_cost`；
- 三套组合与动态成本 Walk-forward；
- Capacity Test。

### 估值
已完成并进入生产闭环：
- 实时 PE/PB；
- 动态 PE 与 PE(TTM) 来源显式区分；
- 行业相对估值；
- 亏损公司与极端估值惩罚；
- 历史估值缓存；
- as-of PIT 合并，禁止用当前估值回填历史；
- 历史覆盖门禁；
- Value Baseline；
- 覆盖不足时明确标记 NOT_VALIDATED。

### 软件自身更新
已完成发行基础设施：
- 稳定 Launcher / 独立 Updater；
- Ed25519 清单签名；
- 包 SHA-256；
- staging；
- 安全解压与路径穿越/符号链接拒绝；
- `versions/<version>` 独立版本目录；
- 原子 `current.json` 切换；
- Health Check；
- 启动失败 Rollback；
- 用户数据隔离到 `%APPDATA%\StockAIPro`。

远程自动更新只有在维护者提供真实 HTTPS 签名 Manifest 地址后才启用；ZIP 不虚构服务器端点。

## 3.3 当前最重要结论

**现在最缺的不是新功能，而是最后的工程闭环和真机交付。**

所以后续禁止再增加：
- 新闻 NLP；
- Transformer；
- 大模型解释；
- 情绪指标；
- 自动交易；
- 更多技术指标。

先把当前主链做成可交付软件。

---

# 4. 最终要达到什么效果

第一次打开，用户只需要：

```text
ONE_CLICK_START.bat
```

系统自动：

1. 检查 Windows；
2. 检查 Python 3.11+；
3. 创建 `.venv`；
4. 安装依赖；
5. 运行 doctor；
6. 创建目录；
7. 更新行情；
8. 校验最新交易日；
9. 更新研究池；
10. 构建训练数据；
11. 时间验证；
12. 训练模型；
13. 今日打分；
14. 计算实时估值；
15. 计算预计成本；
16. 生成 Top20；
17. 生成三套组合；
18. 冻结结果；
19. 打开 Web UI。

失败必须显示：
- 错误原因；
- 日志路径；
- 上次有效预测；
- 修复建议。

---

# 5. 产品核心闭环

```text
数据源
↓
统一数据契约
↓
最新交易日门禁
↓
Live Universe + Research Universe
↓
时间安全特征
↓
市场状态
↓
严格时间验证
↓
Ridge + HGB
↓
模型融合
↓
实时估值
↓
交易成本
↓
统一评分
↓
风险 / 可交易性过滤
↓
Top20
↓
三套组合
↓
NO_TRADE Gate
↓
预测冻结
↓
未来真实结果
↓
Walk-forward
↓
Random / Market / Momentum / Value
↓
5 Why
↓
Reverse Validation
↓
MODEL TRUST
↓
下一交易日
```

---

# 6. 第一优先级：P0 主链

必须完成：

## P0-01 环境自助
- Python 检查；
- `.venv`；
- requirements；
- doctor；
- 自动修复；
- 中文路径；
- 空格路径；
- 双击不闪退。

## P0-02 数据更新
- 当前证券主表；
- 实时行情；
- 历史行情增量；
- 研究池；
- 数据缓存；
- 最新交易日检查。

## P0-03 时间安全
- t 日只用 t 日之前可知数据；
- t 日收盘后生成信号；
- t+1 开盘模拟成交；
- horizon embargo；
- 禁止 random split。

## P0-04 模型
只保留：
- Ridge；
- HistGradientBoosting。

## P0-05 预测
必须输出：
- Top20；
- Final Score；
- Confidence；
- ML；
- Momentum；
- Liquidity；
- Risk；
- Robustness；
- Cost；
- Valuation。

## P0-06 冻结
每天独立目录，禁止静默覆盖。

## P0-07 回测
必须：
- Walk-forward；
- 次日开盘；
- 交易成本；
- Random；
- Market；
- Momentum；
- Value。

## P0-08 审计
必须：
- Label Shuffle；
- Time Shift；
- Feature Ablation；
- Drift；
- Data Coverage；
- Freeze Integrity。

## P0-09 Web UI
必须稳定显示：
- Top20；
- 三套组合；
- 回测；
- 审计；
- 系统健康。

## P0-10 真机发行
必须从全新解压目录通过。

---

# 7. 第二优先级：成本

\[
Cost_i =
Commission_i +
Stamp_i +
Transfer_i +
Slippage_i +
Impact_i
\]

每只股票输出：

```text
estimated_roundtrip_cost_rate
estimated_roundtrip_cost_bps
estimated_roundtrip_cost_cny
score_cost
```

成本进入：
- 统一评分；
- Net Alpha；
- 组合；
- 回测；
- 容量测试。

净收益：

\[
NetReturn =
GrossReturn -
Cost
\]

容量测试固定：

```text
10万
50万
100万
500万
1000万
```

输出：

```text
Capacity Limit
```

---

# 8. 第三优先级：估值

实时：

```text
PE_TTM
PB
```

行业相对：

\[
RelativePE_i=
\frac{PE_i}{Median(PE_{Industry})}
\]

\[
RelativePB_i=
\frac{PB_i}{Median(PB_{Industry})}
\]

规则：
- 负 PE 不算便宜；
- 极端高 PE/PB 加惩罚；
- 缺失值中性处理并降低置信度。

历史估值必须：

```text
ValuationDate <= SignalDate
```

使用 as-of merge。

覆盖不足时：
- 实时估值仍可用于今日；
- 历史回测必须显示 `Valuation OOS = NOT VALIDATED`。

---

# 9. 统一评分

初始权重：

| 模块 | 权重 |
|---|---:|
| ML | 32% |
| Momentum | 15% |
| Liquidity | 7% |
| Risk | 8% |
| Robustness | 8% |
| Cost | 12% |
| Valuation | 18% |

合计 100%。

\[
FinalScore =
0.32ML +
0.15Momentum +
0.07Liquidity +
0.08Risk +
0.08Robustness +
0.12Cost +
0.18Valuation -
Penalty
\]

这是初始权重，不是永久真理。

若严格 OOS 证明某模块没有增益，必须降权或停用。

---

# 10. Net Alpha

\[
NetAlpha =
ExpectedAlpha -
EstimatedCost
\]

若：

\[
NetAlpha \le 0
\]

则：

```text
LOW_PRIORITY
```

若整个候选池的 TopK 平均 Net Alpha 低于阈值：

```text
NO_TRADE
```

---

# 11. 模型验证标准

禁止 random split。

四大基准：

```text
Random
Market
Momentum
Value
```

至少输出：

```text
Rank IC
Mean Excess Return
Positive Excess Rate
Net Return
Max Drawdown
Turnover
Cost Drag
Top20 Excess
```

没有真实 OOS 支持时，禁止声称：
- 模型有效；
- AI 提升胜率；
- 估值增强有效。

---

# 12. Reverse Validation

固定执行：

1. Label Shuffle；
2. Time Shift；
3. Remove ML；
4. Remove Valuation；
5. Value Only；
6. Zero Cost；
7. Capacity；
8. Feature Ablation；
9. Drift；
10. Freeze Integrity。

---

# 13. 5 Why

任何 FAIL / WARN 输出：

```text
Why 1
Why 2
Why 3
Why 4
Why 5
Root Cause
Action
```

禁止为了结果好看直接调阈值。

---

# 14. MODEL TRUST

只有：

```text
HIGH
MEDIUM
LOW
```

由：
- 数据新鲜度；
- 数据质量；
- 研究池覆盖；
- 退市覆盖；
- 估值 PIT 覆盖；
- OOS；
- 四基准；
- Label Shuffle；
- Time Shift；
- Drift；
- Freeze Integrity；
- Cost 后 Alpha；

共同决定。

关键项 FAIL：

```text
MODEL TRUST = LOW
```

---

# 15. NO_TRADE

以下任一情况允许不出手：

- 数据过期；
- 数据质量失败；
- 模型训练失败；
- MODEL TRUST LOW；
- Drift FAIL；
- Net Alpha 不足；
- Risk-Off 且净优势不足。

系统不能每天强行推荐。

---

# 16. 三套组合

## Offense
偏：
- ML；
- Momentum；
- Net Alpha。

## Balanced
偏：
- Net Alpha；
- Valuation；
- Cost；
- Risk；
- Diversification。

## Defense
偏：
- Risk；
- Robustness；
- Valuation；
- Low Cost。

---

# 17. UI 最终只保留 7 个核心页面

1. 今日 Top20
2. 股票诊断
3. 三套组合
4. 回测
5. 估值与成本
6. 模型审计
7. 系统健康

不再无限扩页面。

---

# 18. 文件结构

```text
Stock_AI_Pro/
├── stock_ai/
│   ├── config.py
│   ├── data_source.py
│   ├── data_quality.py
│   ├── features.py
│   ├── valuation.py
│   ├── cost.py
│   ├── regime.py
│   ├── model.py
│   ├── scoring.py
│   ├── portfolio.py
│   ├── backtest.py
│   ├── audit.py
│   ├── drift.py
│   ├── storage.py
│   ├── maintenance.py
│   ├── backup.py
│   └── pipeline.py
├── data/
├── cache/
├── models/
├── predictions/
├── reports/
├── logs/
├── state/
├── backups/
├── tests/
├── app.py
├── doctor.py
├── config.json
├── config.default.json
├── requirements.txt
├── ONE_CLICK_START.bat
├── ENSURE_ENV.bat
├── REPAIR_ENV.bat
├── SETUP_AUTO_UPDATE.bat
├── REMOVE_AUTO_UPDATE.bat
├── RUN_DAILY.bat
├── RUN_BACKTEST.bat
├── RUN_AUDIT.bat
└── RUN_FULL_CHECK.bat
```

---

# 19. 最终交付验收门

只保留 16 个真正影响交付的 Gate。

| Gate | 标准 |
|---|---|
| G01 | Fresh unzip 能启动 |
| G02 | 环境可自动建立/修复 |
| G03 | 数据主链可更新 |
| G04 | 最新交易日门禁有效 |
| G05 | Live / Research Universe 分离 |
| G06 | 时间安全 + embargo |
| G07 | 两模型训练/预测 |
| G08 | 成本正式接入 |
| G09 | 估值正式接入 |
| G10 | Net Alpha + NO_TRADE |
| G11 | Top20 + 三套组合 |
| G12 | Walk-forward + 四基准 |
| G13 | 5 Why + Reverse Validation |
| G14 | Prediction Freeze + SHA256 |
| G15 | Web UI 可正常启动 |
| G16 | Windows 发行 ZIP 真机链路通过 |

只有 16/16 才允许：

```text
DELIVERABLE COMPLETE
```

---

# 20. 真机测试标准

必须在一个全新解压目录执行。

```text
Fresh unzip                 PASS/FAIL
ONE_CLICK_START             PASS/FAIL
Python bootstrap            PASS/FAIL
Dependency install          PASS/FAIL
Doctor                      PASS/FAIL
Directory creation          PASS/FAIL
Live data update            PASS/FAIL
History update              PASS/FAIL
Trade-date freshness        PASS/FAIL
Model training              PASS/FAIL
Prediction                  PASS/FAIL
Cost                        PASS/FAIL
Valuation                   PASS/FAIL
Freeze                      PASS/FAIL
Streamlit startup           PASS/FAIL
Browser UI                  PASS/FAIL
Restart                     PASS/FAIL
Scheduled task              PASS/FAIL
Backtest                    PASS/FAIL
Audit                       PASS/FAIL
ZIP integrity               PASS/FAIL
```

关键项 FAIL：
**不允许叫 COMPLETE。**

---

# 21. Codex 开发顺序

## Phase 1
审计现有工程，对照 16 Gate。

## Phase 2
修 P0 主链：

```text
环境
→ 数据
→ 时间安全
→ 模型
→ 预测
→ 冻结
→ UI
```

## Phase 3
接成本：
- score_cost；
- Net Alpha；
- 动态成本回测；
- Capacity。

## Phase 4
接估值：
- live valuation；
- historical PIT；
- score_valuation；
- industry-relative；
- Value Baseline；
- 覆盖门禁。

## Phase 5
完成：
- 四基准；
- Reverse；
- Drift；
- MODEL TRUST；
- NO_TRADE。

## Phase 6
Fresh unzip 真机发行测试。

---

# 22. 禁止 Codex 做的事情

禁止：
- 新建另一套项目；
- 重写整体架构；
- 增加 Transformer；
- 自动下单；
- 假造收益；
- 假造覆盖率；
- 假造 PASS；
- 用今天估值回填历史；
- 把评分当概率；
- 为了 COMPLETE 隐藏 WARN。

---

# 23. 最终交付文件

最后只交：

```text
Stock_AI_Pro_DELIVERABLE_FINAL.zip
```

必须含：

```text
完整源码
config.json
config.default.json
README_CN.md
requirements.txt
tests/
BUILD_AUDIT.json
PACKAGE_MANIFEST.json
ACCEPTANCE_REPORT.md
ONE_CLICK_START.bat
REPAIR_ENV.bat
SETUP_AUTO_UPDATE.bat
RUN_FULL_CHECK.bat
```

---

# 24. 最终验收报告格式

```text
Version:
Engineering completion:
16 Gates:
Fresh unzip:
One-click start:
Data update:
Prediction:
Cost:
Valuation:
Backtest:
Reverse validation:
UI:
Scheduled task:
ZIP integrity:

Known limitations:
1.
2.
3.
```

---

# 25. 最终目标效果

用户侧：

每天不需要写代码。

系统侧：

```text
更新
→ 验证
→ 训练
→ 排序
→ 成本
→ 估值
→ 组合
→ 冻结
→ 后验验证
→ 回测
→ 审计
```

研究侧持续回答：

> 模型到底有没有真实样本外净 Alpha？

没有：
- 降权；
- 停用；
- NO_TRADE。

---

# 26. 最终项目原则

以后任何新功能必须先回答：

1. 它解决什么真实问题？
2. 没有它，主链能不能交付？
3. 它有没有 PIT 数据？
4. 有没有 OOS 增益？
5. 扣成本后还有没有价值？
6. 如何证明它是假的？

答不出来：
**不进入当前版本。**

---

# 27. 给 Codex 的最终执行命令

```text
你现在只开发一个项目：现有 Stock AI Pro。

不要新建项目，不要继续扩展功能，不要重新设计架构。

以本文件《Stock_AI_Pro_可交付软件唯一总规范.md》作为唯一 Source of Truth。

第一步：
审计现有工程，逐项对照 16 个 Gate，输出 PASS / PARTIAL / FAIL。

第二步：
优先修复 P0 主链：
环境 → 数据 → 时间安全 → 模型 → 预测 → 冻结 → UI。
没有跑通以前，不允许继续加功能。

第三步：
完成成本：
- commission
- minimum commission
- stamp duty
- transfer fee
- slippage
- impact
- score_cost
- Net Alpha
- historical cost backtest
- capacity test

第四步：
完成估值：
- live PE/PB
- industry-relative valuation
- extreme valuation penalty
- historical PIT valuation
- coverage gate
- score_valuation
- Value Baseline
- valuation ablation
- valuation time-shift test

第五步：
完成统一评分、三套组合和 NO_TRADE。

第六步：
完成严格 Walk-forward：
- t close signal
- t+1 open entry
- horizon exit
- embargo
- Random
- Market
- Momentum
- Value
- dynamic trading cost

第七步：
完成：
- 5 Why
- Label Shuffle
- Time Shift
- Feature Ablation
- Drift
- MODEL TRUST
- Freeze Integrity

第八步：
从一个完全新的解压目录做 Windows 发行测试。

用户唯一入口：
ONE_CLICK_START.bat

必须验证：
Fresh unzip
Python bootstrap
Dependency install
Doctor
Data update
Prediction
Cost
Valuation
Freeze
Streamlit
Browser
Restart
Scheduled task
Backtest
Audit
ZIP integrity

任何关键项 FAIL，都不允许标记 COMPLETE。

最后只输出一个发行包：

Stock_AI_Pro_DELIVERABLE_FINAL.zip

并附：
README_CN.md
ACCEPTANCE_REPORT.md
BUILD_AUDIT.json
PACKAGE_MANIFEST.json

最终报告必须写：
Engineering completion
16 Gates
Tests PASS/FAIL
Known limitations

不要停在方案阶段。
持续修复现有工程，直到 16/16 Gate 全部通过，或明确说明当前环境无法验证的真实原因。
```

---

# 28. 最终结论

现在我们不需要“功能最多”的 Stock AI Pro。

我们需要：

> **一个普通用户能下载、解压、双击、真正运行，并每天自己更新、预测、冻结、回测和审计的软件。**

接下来所有工作只围绕：

```text
能运行
能验证
能交付
```

在这三个目标完成前：

**不再增加新功能。**


## 4.1 自研发闭环升级

- 每日预测同时冻结 Champion 与 Ridge/HGB/等权/动量价值 Challenger，结果出现前写入同一冻结 Manifest。
- 真实未来结果可用后，系统自动做配对样本、交易成本后净收益、胜率、Bootstrap 区间、最大回撤非劣与 Audit Trust Gate。
- 候选只有全部通过才标记 `PROMOTABLE_REVIEW`；默认 `auto_promote=false`，绝不静默修改生产模型。
- `RUN_RND.bat` 可手动执行研发闭环；正常每日流程默认自动运行，失败不阻断已冻结的生产预测。
- UI 新增“研发闭环”页，显示退化诊断、5 Why、逆转验证、Challenger Gate 与冻结样本。
- 交付标准保持不降级：唯一 ZIP，源码/安全/失败路径测试，封包后全新解压二次验收通过后才提供下载。

---

## 4.2 可靠性与证据链升级（当前实现）

### A. 配置 Schema 事务迁移
- schema_version = 6。
- 用户配置迁移前必须备份；损坏 JSON 先备份再恢复；未来 Schema 必须拒绝由旧程序读取。
- 程序更新不得覆盖 `%APPDATA%\StockAIPro` 用户数据。

### B. 跨期预测证据链
- 每一期冻结 `manifest.json` 必须记录 `chain_sequence` 和 `previous_manifest_sha256`。
- Audit 必须校验全部历史预测目录的文件哈希和前向链关系。
- 任一期历史冻结结果被修改/替换，整链验收 FAIL。

### C. R&D 证据与候选注册表
- `rnd_evidence.json` 固化软件版本、配置指纹、冻结样本 Manifest 指纹、审计指纹和 Promotion Gates。
- `rnd_candidate_registry.json` 记录候选 ID、evidence_id、建议配置补丁。
- `auto_promote=false` 不得改变；通过 Gate 仅进入 `PROMOTABLE_REVIEW`。

### D. Updater 1.1
- 更新必须有状态日志：DOWNLOADING → STAGED → ACTIVATING → COMMITTED / ROLLED_BACK / REJECTED。
- 坏 release_id 回滚后不得自动无限重试。
- 远程更新只允许 HTTPS；Ed25519 + SHA-256 双校验。
- Manifest version 与包内 VERSION 必须一致。
- ZIP 路径穿越、符号链接、ZIP Bomb 必须在写入正式版本目录前拒绝。
- 中断后活动版本目录缺失时自动回滚上一版本。

### E. 4.2 新增验收 Gate
- CONFIG_SCHEMA_MIGRATION
- CONFIG_FUTURE_SCHEMA_REJECT
- PREDICTION_CROSS_PERIOD_HASH_CHAIN
- RND_REPRODUCIBLE_EVIDENCE
- UPDATER_TRANSACTION_JOURNAL
- UPDATER_FAILED_RELEASE_REPLAY_BLOCK
- UPDATER_VERSION_MATCH
- UPDATER_ZIP_BOMB_GUARD
- INTERRUPTED_UPDATE_RECOVERY

以上 Gate 必须与原有全部工程/回测/安全 Gate 同时 PASS，且最终 ZIP 必须全新解压后二次验收通过，才允许提供下载。

## 4.3 模型同构与发行硬化（当前实现）

- 模型：Ridge + HGB + ExtraTrees 三模型异构集成；验证 Rank IC 权重向等权收缩。
- 回测：与生产共用同一训练/验证/集成函数；外层与内层均保持 horizon 时间隔离。
- R&D：新增 extra_trees_only challenger，继续禁止自动晋级。
- Config Schema 保持 6：本次新增参数向后兼容，不做不必要迁移；未来 Schema 仍 fail-closed。
- Updater 1.2：反降级/重复安装、磁盘空间预检、下载上限、HTTPS 最终跳转检查、Schema 2 内部 Manifest 逐文件校验。
- Release：确定性 ZIP 构建；最终交付必须对最终 ZIP 本体 fresh-unzip 后重跑所有根安全测试、活动版本测试、Manifest 与 Health Check。
