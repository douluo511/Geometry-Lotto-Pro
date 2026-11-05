独立 agent 代码审查：Issue #468 / Draft PR #467，version-bound frozen replay

审查基线为本地 Git HEAD `861ee53ad172a8ba80bbfb24a2a6597c51c57230`，范围为其上的未提交 tracked diff，以及 frozen_replay.py、model_versions/*.source、test_versioned_frozen_replay.py、.gitattributes 和所给 spec/plan。此次没有修改 production 文件、ledger、历史冻结或远端，也没有创建 PR/合并。所有反例仅修改临时复制的包和虚构 SHADOW 证据。不是人工独立签字，不是 formal A 或正式验收。

审查发现与修复复核：

1. **P1，已修复：原 snapshot_bundle 配置在升级后无法重试旧 dual run。** 初始代码先用当前 core/orchestration 计算新 manifest run_id，再判是否已有；A freeze/score 后仅给 core 加一行注释 B，使用原 bundle 在 draw 后调用 advance_workspace，实际得到 `ASOF_OR_CUTOFF_FAIL_NO_RETROACTIVE_FORECAST`。原 DB/receipts 未改，但正常 Windows 配置会一直进入这个阻塞分支。修复先只读验证已有 run，按完整持久化双游戏快照匹配；唯一匹配复用原 run，多匹配明确 BLOCKED。对应同配置单游戏路径也把新模型生成移到真正新 freeze 的分支。独立探针随后得到 `STUDY_SHADOW_READY`，证据逐字节不变。

2. **依赖隔离问题，已修复并收紧范围：旧 report builder 可借当前 statistics 改写报告。** 初始代码把当前 statistics 别名给归档包。实际在升级副本 statistics.py 追加 `FAIR_D2 = {"SSQ": 0.5, "DLT": 0.5}`，旧双游戏 replay 成功，两个反馈仍显示归档 scorer SHA `970927...07e0`，但 fair_d2_baseline 已为 0.5。修复先把旧 builder 唯一需要的 FAIR_D2 绑定到归档 core 规则；随后进一步对当前 FAIR_D2 与固定 RULES 的已知不一致明确返回 `REPLAY_STATISTICAL_BASELINE_MISMATCH`，阻断累计研究漂移。这个 guard 针对明确的固定公平概率，不等于归档或认证任意未来统计实现。

3. **P2，已修复：legacy 仅验证已知字段，没有比较整张冻结卡。** 实际在 dual 两张 hot60 卡的 ticket 中增加 unregistered_field，重新计算 prediction_sha256，旧校验仍接受 frozen_forecast_report。额外字段没有影响 D2，但与 spec 的 entire frozen card 承诺不一致。修复在归档 validate_forecast 后再要求 prediction 与归档 forecast 的完整字典相等，反例返回 `FROZEN_FULL_CARD_REPLAY_MISMATCH`。

安全边界的只读核查结果：

- 执行目标来自固定 full-SHA registry 和固定包内文件名；ledger/outcome/workspace 不能指定可执行路径或任意源码。归档 bytes 在 compile/exec 之前经 SHA256 校验；cached replay 也先重读校验 core 与 observed artifact。未知 hash、缺失/篡改 artifact 进入拒绝路径。这里把 repository/package 视为可信安装边界，不是防御能修改 Python 内存、registry、标准库或宿主机的攻击者。
- core_lf/source 与 core_crlf/source 分别是 baseline core.py 的原始 LF 与 CRLF 版本；两个 scorecard artifact 同样逐字节对应原始 baseline；observed_snapshot.source 对应 baseline LF 版本。独立字节核查输出保存在 archive-byte-verification.json。测试没有通过归一化 hash 掩盖原始身份差异。git check-attr 显示五个 source artifact 的 text 属性 unset。
- 归档 observed validator 的 `.core` 导入绑定到隔离包中的归档 model；它不会从当前包导入核心参数或模型。旧 scorecard 的 `.core` 同样隔离，`.convergence` 明确使用此次审过的当前验证 facade；统计导入仅提供来自归档规则的 FAIR_D2。
- 独立游戏六臂 roster、来源一致性、run_id preimage、snapshot、完整模型卡（含 ticket、parameter hash、NULL seed）仍受检查。legacy manifest 的原始 identity preimage 仍按原 run_id 校验，不把旧 manifest 重建成当前 source identity；legacy 全卡现在也确定性重放比较。
- 新建 run 的 orchestration source list 已纳入 closed_loop.py、frozen_replay.py 和五个归档 artifact；这是新 run 的身份绑定，不追改旧 manifest 的 provenance。
- 无 snapshot 的独立游戏 tick 使用只读连接与 query_only，不再执行 GAME_SCHEMA。显式传 snapshot 的接口仍保留 writer transaction，因为同一接口还可创建新 freeze；不能把该接口一概宣称为 OS 强制只读。目标测试比较了正常旧冻结重试前后的证据字节。
- 独立游戏继续遍历该游戏全部本地 roster；legacy 继续要求本地全部 run 的 receipt 后才统计。未知历史 source 或坏 freeze 使处理失败，不以版本筛掉该条记录后缩小分母。本地 roster 不是官方日历覆盖证明。

验证记录：

- 早期反例输出来自本次实际工具运行；不是手写预期结果。共享目录在审查时由主代理并发修复，因此 review-probes-initial.log 的文件名虽含 initial，内容实际已是前两项修复后的中间态，不应把它标成原始 RED。reproduce_review_findings.py 保留了独立反例操作，运行时只改临时副本。
- 一轮过渡态完整目标测试已加载新增 statistics 拒绝测试、而 guard 尚未落盘，得到 11 项中 10 PASS、1 FAIL；它不代表最终 candidate。
- guard 与相关修复落盘后，独立重跑四个关键测试：4 tests / 20.866s / OK；原始输出 review-final-key-tests.log。
- 最终独立执行 `python -B -m unittest research.harness_v46.tests.test_versioned_frozen_replay -v`：**12 tests / 74.781s / OK**，原始输出 review-final-12-tests.log。包括首次 score、原收据重试、同快照配置重试、两个换行版本、observed dependency、缺失/篡改 archive、unknown/mixed source、missing arm、seed/parameter/D2 替换、legacy 额外字段和新 manifest 的 replay runtime/artifact 绑定。
- review-source-hashes-final.json 与 review-source-hashes-final-verified.json 记录测试前后 13 个文件。全部 runtime、测试与五个 artifact 的 hash 均不变；仅 spec 文档在测试过程中补充实现 rulings 后改变，已重新阅读。tracked-diff-reviewed-final.patch 记录最终 tracked diff。仍为 HEAD 861ee53ad172a8ba80bbfb24a2a6597c51c57230 上的未提交 candidate，不将本地测试声称为远端 exact-commit 结果。
- 已复核上述修复，当前审查范围内没有待处理的 P0/P1 发现。此结论仅对应记录 hash 的本地实现和列明的威胁/兼容范围。

剩余限制与明确未验证项：

- 这里只审查本地未提交 candidate，不是已推远端 commit/Actions exact-HEAD 审查；完整回归、Ubuntu/Windows CI 原始日志由主代理单独核实。
- 注册的历史 core/scorecard 是已知 baseline LF/CRLF 对应版本。混合 core/scorer 换行、未知旧 scorer 来源、未来未归档 core 不能声称自动兼容；已有 receipt 不一致会被拒绝而非改写。未来当前 core 退休前仍需新增经过审查的 registry entry。
- 未把历史 per-game ID 解释为完整环境/dependency manifest；没有 retroactive provenance。未来 orchestration、统计算术、Python/SQLite/stdlib 变化不在任意自动兼容承诺中；FAIR_D2 guard 不认证其余统计代码。
- 未做并发文件篡改/进程内 monkeypatch 防御、符号链接竞态、真正掉电恢复、跨平台重新签名或持久宿主执行验证；固定字节 hash 与本地 SQLite 不替代可信执行环境。
- 归档 observed validator 复现原行为，并不认证官方数据、公布时间、官方目标日历、独立 custody、外部 TSA 或独立统计优势。
- 保持 `formal_A=0`、`RESEARCH_VALID=NOT_YET`、`D2_EDGE_CONFIRMED=NO`、`NO_EDGE`。独立 agent 审查通过不能解除上述研究与证据门槛。
