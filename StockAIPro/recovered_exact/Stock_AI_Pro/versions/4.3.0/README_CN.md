# Stock AI Pro 4.3 Deliverable

## 1. 定位

Stock AI Pro 是本地 A 股研究与决策支持软件。生产链为：

**数据更新 → 新鲜度/PIT检查 → 时间安全训练 → 成本/估值 → Expected Net Alpha → Top20/三套组合 → TRADE/WATCH/NO_TRADE → 冻结预测 → Walk-forward → 5 Why / 逆转验证 → R&D Champion/Challenger。**

评分是横截面相对排序，不是上涨概率；软件不保证盈利，也不自动向券商下单。

## 2. 唯一入口

Windows 解压后双击：

`ONE_CLICK_START.bat`

首次运行会准备本地 Python 环境和版本依赖。以后同一目录长期使用，不需要重新打包。

## 3. 软件与用户数据彻底分离

业务代码位于：

`versions/<version>/`

Windows 用户数据默认位于：

`%APPDATA%\StockAIPro`

其中保存行情、PIT 估值、模型、冻结预测、报告、日志和用户配置。软件版本更新不会覆盖这些数据。

## 4. 4.2 新增：配置 Schema 安全迁移

4.2 将配置 Schema 升级到 6：

- 旧 Schema 自动与新默认配置深度合并，保留用户自定义值。
- 迁移前自动备份到 `backups/config_migrations/`。
- 配置损坏时先备份损坏文件，再恢复可启动默认配置。
- 如果用户配置 Schema 高于当前程序支持版本，旧程序拒绝启动，防止回滚时破坏新配置。

## 5. 4.2 新增：跨期预测哈希证据链

过去只验证“单期冻结目录是否被篡改”。4.2 在每一期 `manifest.json` 中增加：

- `chain_sequence`
- `previous_manifest_sha256`

因此每一期都链接上一期 Manifest 的 SHA-256。审计会验证整条历史链；修改、替换或插入任一期历史冻结结果都会导致链断裂。链头状态保存在：

`state/prediction_chain.json`

## 6. 4.2 新增：R&D 可复核证据

R&D 不再只输出 `PROMOTABLE_REVIEW`。现在同时生成：

- `reports/rnd_evidence.json`：记录软件版本、配置指纹、冻结样本 Manifest 指纹、审计指纹、Promotion Gates。
- `reports/rnd_candidate_registry.json`：记录通过 Gate 的候选、候选 ID 和配置补丁。

候选 ID 由证据与配置补丁确定；`auto_promote=false` 保持不变。研究层可以自动提出候选，但不能静默修改生产模型。

## 7. 4.2 新增：Updater 事务恢复与更新攻击防护

根目录稳定 Launcher/Updater 与业务版本解耦。更新流程：

`Signed Manifest → HTTPS/本地受控源 → staging → SHA-256 → ZIP安全检查 → versions/<new> → 独立venv → Health Check → 原子 current.json 切换 → 新版启动确认 → Commit / Rollback`

4.2 Updater 1.1 新增：

- `update_journal.json` 更新事务日志。
- 失败 `release_id` 本机记录，坏版本不会下次启动无限重装。
- Manifest 版本与包内 `VERSION` 必须一致。
- 远程 Manifest/包禁止明文 HTTP。
- ZIP 路径穿越、符号链接拒绝。
- ZIP 文件数、解压后总体积、压缩比限制，防 ZIP Bomb。
- 更新中断后若活动版本目录不存在，会自动切回上一版本。

发布私钥绝不进入用户 ZIP，客户端只包含 Ed25519 公钥。

**远程软件自动更新需要维护者提供 HTTPS Manifest/发行地址。最终包默认关闭远程软件更新，避免连接不存在的服务器；行情/模型每日自动更新不受影响。**

## 8. 4.3 新增：三模型异构集成与同构回测

- 生产模型由 Ridge + HistGradientBoosting 升级为 Ridge + HistGradientBoosting + ExtraTrees。
- 验证权重使用 Rank IC，并向等权组合收缩，降低单一验证窗口过拟合。
- `model_disagreement` 与模型预测区间同时保留，继续进入稳健性判断。
- Walk-forward 不再只用 Ridge；每个历史评估点都在过去训练区内部用 horizon embargo 验证窗口学习三模型权重，再用相同模型栈预测。
- R&D 增加 `extra_trees_only` Challenger；任何 Challenger 仍只允许进入 `PROMOTABLE_REVIEW`，禁止自动晋级。
- 配置 Schema 保持 6；新增模型参数采用向后兼容默认合并，避免破坏 4.3→4.2 回滚。
- Updater 1.2 增加自动反降级、磁盘空间预检、下载上限、HTTPS 最终跳转校验和 Schema-2 包内逐文件 Manifest 校验。
- 发行工具增加确定性 ZIP 构建测试，同一源码树可生成字节一致的归档。

## 8. 生产模型

当前生产链仍保留 4.1 已验证的工程能力：

- Ridge + HistGradientBoosting + ExtraTrees，三模型时间安全验证/集成。
- Horizon Embargo，t 日收盘信号，t+1 开盘模拟执行。
- 动态交易成本：佣金、最低佣金、卖出印花税、过户费、滑点、流动性冲击。
- PE/PB 估值与行业相对估值；动态 PE 明确标注，不冒充 PE(TTM)。
- 历史估值仅用 `valuation_date <= signal_date` 的 PIT 数据。
- `Expected Net Alpha = Expected Alpha - Estimated Roundtrip Cost`。
- 数据/模型证据不足时允许 `NO_TRADE`。

## 9. 回测、审计与 R&D

Walk-forward 同时比较 Random、Market、Momentum、Value，并做动态成本和 10万/50万/100万/500万/1000万容量压力测试。

审计包含：未来字段隔离、Embargo、Label Shuffle、Time Shift、冻结哈希、**跨期预测哈希链**、Universe/退市覆盖、估值 PIT、动态成本、Capacity、Value/Random Baseline、Feature Drift、Champion/Challenger 事前冻结。

R&D 通过配对样本、Bootstrap 区间、胜率、回撤非劣和 Audit Trust Gate 判断 Challenger 是否只进入 `PROMOTABLE_REVIEW`。

## 10. 常用入口

- `ONE_CLICK_START.bat`：数据更新、预测并打开 UI
- `SETUP_AUTO_UPDATE.bat`：Windows 工作日无人值守每日流程
- `CHECK_SOFTWARE_UPDATE.bat`：检查软件自身更新
- `RUN_DAILY.bat`：仅每日生产链
- `RUN_RND.bat`：仅 R&D 闭环
- `RUN_BACKTEST.bat`：Walk-forward 回测
- `RUN_AUDIT.bat`：模型审计
- `RUN_FULL_CHECK.bat`：工程全验收
- `FIRST_RUN_DIAGNOSE.bat`：环境诊断
- `WINDOWS_FIRST_RUN_ACCEPTANCE.bat`：目标 Windows 真机 + 实时数据验收

## 11. 真实边界

- 构建环境无法替代目标 Windows 真机执行 `.bat / PowerShell / Task Scheduler`。
- 第三方公开行情/估值接口可能变化；系统只能做主备源、超时、重试与失败保护。
- 历史逐日 ST/停牌/涨跌停排队和真实冲击无法用免费公开数据完整复原。
- PIT 估值覆盖不足时 Value Baseline 会明确标记未验证。
- 工程测试证明链路按设计运行，不证明未来存在稳定 Alpha。

## 12. 唯一 ZIP 交付标准

任何后续版本都必须执行：

**源码/功能测试 → 失败路径/安全测试 → Manifest → 封包 → 全新空目录解压 → 二次全量验收 → ZIP CRC/Manifest/Health Check → 只提供一个最终 ZIP。**

构建事实见 `ACCEPTANCE_REPORT.md` 与 `BUILD_AUDIT.json`。
