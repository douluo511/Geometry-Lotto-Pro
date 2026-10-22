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


## 8. V4.7 RUN_ID CLI guard — 2026-10-22

The single-lottery compatibility CLI now rejects caller-supplied IDs beginning with `V47-` and reports `V47_RUN_ID_REQUIRES_DUAL_GAME_MANIFEST_USE_SCHEDULE`. The canonical V4.7 prefix must come from the dual-game manifest path in `schedule.py`; the older one-game CLI remains SHADOW/compatibility only. This prevents the ordinary CLI from presenting an arbitrary caller string as a manifest-derived V4.7 run identity. It is not a general sandbox against direct Python callers or privileged database access.

Exact-head CI for code HEAD `036aa9f0b12d55758ebf2c88717a37c0358404b1`: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39733193819 — Ubuntu and Windows Server 2022 both passed 37 tests; Ubuntu skipped the Windows-only PowerShell parser test.


## 9. Persisted V4.7 manifest preimage — 2026-10-22

The canonical scheduler now stores the full manifest payload and its SHA256 in an immutable `run_manifests` table inside the same SQLite transaction as the dual-game target guards, forecasts, workflow stages and TSA-request records. Exact retries are idempotent; conflicting manifest payloads fail closed.

Before freezing a prediction under a `V47-` ID, the core now requires a registered manifest, validates the manifest payload hash and ID derivation, and checks that the target game snapshot and model parameter/source identities match the registered manifest. Read-only batch audit also verifies the persisted manifest and per-model identity.

The legacy single-game CLI refuses caller-supplied `V47-` IDs and remains a separate SHADOW compatibility path. This is still local SQLite evidence, not an external timestamp or tamper-proof witness.

Exact-head CI for code HEAD `adee485f4d9b24df3fa4eddac7c63fc2a467e4d1`: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39733607591 — Ubuntu and Windows Server 2022 both passed 39 tests; Ubuntu skipped the Windows-only PowerShell parser test.


## 10. V4.7 follow-up P0: snapshot replay, raw-source custody, and exact D2 arithmetic — 2026-10-22

The following code changes are committed to the existing convergence branch; no new competing PR was created:

1. `6ac7d70009f258c09ec718e721099cd5929ecfc7` — added immutable `run_snapshots` table and `register_snapshot` / `load_registered_snapshot` helpers. The normalized snapshot preimage is now retained rather than only its hash.
2. `39062a4aa939cd2a475e21a7c01aa253c7eb2a18` — the independent six-model batch audit reloads the stored snapshot and calls deterministic `validate_forecast` for each frozen model. It rejects a changed ranking even if a privileged rewrite updates both the prediction payload and local SHA consistently.
3. `e68173192c0981118afce139088df3fff3ddb1fd` — the canonical scheduler registers both SSQ and DLT snapshot preimages in the same transaction before any prediction freezes.
4. `c0067deee9268adf475db4ee8df8a2cfeee12db3` / `19d40d0ba5f537413e5919fe21349fdaf4a4dfa6` — added a standard-library-only statistical arithmetic module and synthetic tests: exact binomial upper-tail test against the known D2 baseline; exact one-sided paired sign/McNemar comparison against same-draw Random NULL; candidate-level intersection-union p-value `max(p_baseline,p_paired_null)`; Holm adjustment over an explicitly enumerated family; exact model-rate interval; and a conservative paired rate-difference interval.
5. `fcdae5699972dfdafad28163f82d9775fc4d9b41` — the RUN manifest now binds `statistics.py` into the orchestration source digest.
6. `fa3c2ba5bab8587fdbb2cf8451886506ca2c5eea` / `b7859d68348bb07ae51ba4afcd749ca92d4600e6` — added immutable raw-source byte custody as a SQLite BLOB with raw SHA256, HTTPS per-game hostname allowlist, as-of bounds, and mandatory metadata/hash binding to the snapshot preimage.

### Critical qualification

The source-artifact helper preserves bytes that a caller supplies; it **does not fetch URLs, parse official source formats, prove that the bytes came from the stated URL, authenticate publication times, or establish that a source is official**. `source_authenticity` remains `NOT_VERIFIED`. The statistical module accepts caller-supplied D2 bits and family mappings; `preregistration_verified=false`, `formal_A=0`, and `NO_EDGE` remain hard-coded. The original 12 hypothesis identities have not been proven to match the new module's caller-supplied family. The unregistered challenger cannot be selected retrospectively.

### Exact observed CI

Code HEAD `d1f2ab42f9e170fcae0c5d98101e4321e18ea804`: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39747892642

- Windows Server 2022: SUCCESS, 54 tests; PowerShell parser test ran.
- Ubuntu: SUCCESS, 54 tests; one Windows-only PowerShell parser test skipped as expected.

The subsequent README/review-document commits are documentation only; always inspect CI at the latest HEAD before treating the branch as current.

### Current status after this tranche

- `ENGINEERING_PASS`: **NOT YET**. Synthetic cross-platform CI passes, but the nine physical P0 acceptance cases and real Windows cold-boot/offline recovery have not all been run.
- `RESEARCH_VALID`: **NO**. No live official dual-source 120+ draw snapshots, independently authenticated result receipts, or verified external pre-cutoff seal.
- `D2_EDGE_CONFIRMED`: **NO / NO_EDGE**. No qualified prospective A sample; no result here is evidence of improved odds.


## 11. V4.7 two-source semantic history comparator — 2026-10-22

Commit `47293f6f1ad30b484d3e801d1f2a3e31901a233d` adds `source_validation.py`. It validates two parsed 120+ draw histories against each other and the registered normalized snapshot; enforces the per-game HTTPS hostname allowlist and distinct official-domain roots; checks unique/increasing issue identifiers, strictly increasing draw times, legal sorted ball ranges, publication <= as-of, and exact semantic agreement. It returns `semantic_agreement=MATCHED` only for matching caller-supplied parsed rows, while keeping `source_origin_authenticity=NOT_VERIFIED`, `official_G01=BLOCKED`, `formal_A=0`, and `NO_EDGE`.

The validator is bound into the V4.7 run identity via `ORCHESTRATION_SOURCE_FILES`. Synthetic test coverage includes matching 140-row histories, 119-row rejection, same-root source rejection, unallowlisted host, duplicate issue, post-as-of publication, disagreement between sources, and source rows that agree with each other but differ from the locked snapshot.

Exact code HEAD `4d9caee14a8b5ab6458094742ec7874a8034a87f`: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39748499053 — Ubuntu SUCCESS, 62 tests (one Windows-only parser test skipped); Windows Server 2022 SUCCESS, 62 tests (PowerShell parser included).

**Remaining P1 gap:** no live official page fetcher/parser has yet produced the two parsed arrays, and the comparator cannot establish that those arrays were actually parsed from the preserved raw bytes. No 120+ official snapshot is accepted. This is a strict validator interface, not G01 completion.


## 12. V4.7 allowlisted raw fetcher — 2026-10-22

Commit `ba497e6944ab7090c402385a9343a02cb399321f` adds `source_fetch.py`; `bc46f0a4d9dd67cab722c7d0c394c0b1c0360dc9` binds it into the RUN_ID orchestration source hash; `72cea071b6d0ef518294af4c41b197065baa0dd4` adds mocked HTTP tests; `51de08dc90da6599772a5a86366ef2f358070baf` asserts the fetcher remains in the source-hash list.

The fetcher performs HTTPS GET only on the per-game allowlist, validates every redirect against the same allowlist, limits response bytes to 25 MB, preserves raw bytes and SHA256, records final URL/content type and the HTTP Last-Modified header separately, and marks the local fetched-at clock untrusted. It deliberately returns `published_at=None`; it does not treat an HTTP header as authoritative page publication time. Network/parser errors fail closed.

Exact CI run for code HEAD `51de08dc90da6599772a5a86366ef2f358070baf`: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39749449435 — Ubuntu SUCCESS, 70 tests (one Windows-only PowerShell parser test skipped); Windows Server 2022 SUCCESS, 70 tests (PowerShell parser included).

**Still NOT_RUN:** no live request to any official lottery site was made by this code change, and no source-specific parser exists. The fetcher only provides a safer raw-byte acquisition primitive; G00/G01 remain BLOCKED until live responses, parser output, 120+ history agreement, actual cutoff, and provenance are independently verified.


## 13. Raw fetch HTTP-status reporting regression — 2026-10-22

- `52bc0cc26a2b589ff1e24815a70134a9d7719212` now preserves an HTTP error code (for example 403) as `SOURCE_HTTP_STATUS_NOT_200:<code>` instead of collapsing every HTTP error into a generic fetch failure.
- `69543ec9e63e1a84d9c37fc3fdf30efe6011643c` adds the HTTPError regression test.
- Exact CI: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39749904945 — Ubuntu SUCCESS, 71 tests (one Windows-only PowerShell parser test skipped); Windows Server 2022 SUCCESS, 71 tests.
- This remains mocked-network evidence only; no live official source request or parser acceptance occurred.


## 12. Live official-history intake: first attempt and corrective pass — 2026-10-22

A one-shot read-only GitHub Actions workflow was added at `.github/workflows/v47-live-official-intake.yml`. It is triggered only by changing `research/harness_v46/LIVE_INTAKE_TRIGGER.json`, has `contents: read` permissions, uploads raw intake artifacts for 30 days, and never predicts or purchases tickets.

### First real network attempt

Run #39752241618: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39752241618

Observed:
- DLT national source: both configured header profiles returned HTTP 567.
- SSQ intake stopped on a non-200 response before trying the second history source.
- The resulting bundle had no raw response bytes, exposing a real evidence-loss defect in the intake adapter.
- Both games remained BLOCKED; target admission BLOCKED; formal A=0; NO_EDGE.

### Corrective code now in branch

- `official_intake.py` attempts the two source histories independently; a failed first source no longer prevents the second attempt.
- Non-200 bodies are captured as diagnostic artifacts with actual status, raw SHA256, URL/root, parser version and local untrusted fetch time; they are never parsed as draw records.
- The DLT Requests redirect wrapper is root-bound and captures non-200 responses before the game parser rejects them.
- Partial collection output preserves any successful source history and every available raw diagnostic artifact in a `SOURCE_FETCH_PARTIAL` bundle. Such a bundle has zero consensus rows and cannot pass official-history admission.
- Added offline tests for HTTP 567 preservation, cross-root redirect rejection and source parser raw-body reparse.

Latest synthetic CI after these changes: Run #39753091719, Ubuntu and Windows Server 2022 SUCCESS, 87 tests per platform (Ubuntu skips one Windows-only PowerShell parser test): https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39753091719

A second live attempt was triggered on HEAD `4b5a9b064967f2a6a03f60775cae3d43195a452d`: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39753171769. Its final result must be inspected before claiming any source was captured or cross-checked.

### Non-negotiable boundary

Even a successful `HISTORY_CROSSCHECK_PASS` is historical source evidence only. Target issue, sales cutoff, draw schedule, publication time and external TSA are separate gates. No live official dual-source 120+ history has yet been admitted as of this review entry; do not change G00/G01 or the three top-level verdicts without exact-run evidence.


## 14. Independent live-evidence review: DLT chronology quarantine and SSQ Hebei fallback — 2026-10-22

**This section supersedes earlier optimistic interpretations of DLT HISTORY_CROSSCHECK_PASS.**
Do not treat the quantity of primary-history rows as the independently agreed overlap count.

### Run #39754959885 — third actual live intake

Workflow: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39754959885
Artifact: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39754959885/artifacts/12415656424

- DLT: Jiangsu 2,934 rows, latest 26120; Gansu 20 rows, latest 26120; **only 20 issue IDs agreed across independent roots**. National Sporttery requests returned HTTP 567 in both configured profiles. Third-run output mistakenly labelled 2,934 primary rows as "consensus_draws" and HISTORY_CROSSCHECK_PASS; this conflated primary-only and independently verified history.
- SSQ: Shanghai 2,078 rows, latest 2026120; CWL national HTTP 403. Shanghai-only history is not a two-source 120+ history.
- 2016 DLT Jiangsu raw dates contain reproducible anomalies: 16003 = 2016-01-07 (Thursday, historical reporting indicates Wednesday 2016-01-06), 16004 = 2016-01-11 (historical reporting indicates Saturday 2016-01-09), while 16005 is also dated 2016-01-11. Original raw bodies are retained without modification. Independently inspect official documents, including https://www.sport.gov.cn/n20001280/n20745751/n20767297/c21206580/content.html (16004 drawn Jan 9) and https://yntc8.cn/news/2016010742904.html (16003 drawn Jan 6); these web documents are corroboration, **not a replacement for authenticated original draw-source capture**.

### Code and audit response

- Enforce strictly increasing draw dates and quarantine DLT chronology anomalies before source-history admission; report issue/date/reason rather than silently accepting or overwriting a bad date.
- Distinguish HISTORY_CROSSCHECK_LIMITED (1–119 independently matched issues) from HISTORY_CROSSCHECK_PASS (>=120 matched issues). "consensus_draws" now contains **only independently matched rows**; "primary_history_draws" contains the larger primary-only unverified historical set.
- Add official provincial Hebei SSQ latest-result fallback with its homepage + official announcement, both independently parsed from preserved response bytes. This route is latest-only and cannot pass the 120+ history gate.
- Deduplicate identical SHA-addressed HTTP retry bodies on disk while preserving all response receipts, and validate source IDs before writing paths.
- No artificial correction to source history, no substitution of third-party lottery pages for original official evidence, and no upgrades to G00/G01, statistical sample eligibility, or official draw cutoff verification.

### Run #39758011787 — fourth actual live intake

Workflow: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39758011787
Artifact: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39758011787/artifacts/12417055858

- SSQ HISTORY_CROSSCHECK_LIMITED: Shanghai 2,078 history rows; Hebei homepage + announcement agree on **one** latest issue, 2026120, 2026-10-20, red 13/14/16/18/20/31, blue 03. CWL HTTP 403. Independent overlap=1; full dual-source 120+ admission BLOCKED.
- DLT SOURCE_FETCH_PARTIAL: Jiangsu raw 30 HTTP-200 pages received and retained but quarantined due two calendar anomalies above. Gansu 20 valid recent rows; national two HTTP-567 bodies retained. No independently admitted full historical set.
- Actual output overall exit=failure by design: any lottery lacking full 120+ admission keeps the workflow red. Both official target admissions BLOCKED, external TSA NOT_RUN, formal A=0 and NO_EDGE.

### Exact CI after calendar gate and Hebei fallback

Run #39758256554 (HEAD 75a553a28fbf1240b3b6137faa553ed50b3d0ae5):
https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39758256554
Ubuntu SUCCESS, 95 tests (one Windows-only PowerShell parser test skipped);
Windows Server 2022 SUCCESS, 95 tests. Unit/CI success is *synthetic gate evidence* only, not live full-history success or real Windows fault-injection acceptance.

**Independent next action:** obtain a trustworthy second full SSQ historical publisher and a DLT full source not HTTP-blocked, or reconcile the Jiangsu dated issues using independently preserved, authenticated originals with explicit versioned exception receipts. Rerun the chronology+raw-page gate, require 120+ actual cross-source overlapping issues, then separately verify sales cutoff, pre-draw TSA and read-only replay. No manual data correction or prospective-A backfill is allowed.

Unchanged verdicts: ENGINEERING_PASS=NOT_YET (real Windows physical P0 incomplete); RESEARCH_VALID=NO; D2_EDGE_CONFIRMED=NO; formal A=0; NO_EDGE.

## 10. test2 raw-byte evidence admission gap — 2026-10-22

An independent review of `official_intake.validate_worker_payload` found that a
worker payload could report `raw_reparse_status=PASS` and matching self-declared
draw digests despite containing an empty `raw_artifacts` list. With two such
claimed sources, the historical cross-check could report `HISTORY_CROSSCHECK_PASS`
without retaining any actual HTTP response bytes. A second variant could retain
only an HTTP error body while claiming successful draw replay.

The isolated research hardening patch rejects both variants when a source is
eligible for cross-source comparison: a claimed replay now requires at least
one preserved artifact with nonempty HTTP 200 response bytes. Regression tests
cover SSQ and DLT. This closes **only** the raw-free-replay loophole; it does
not independently authenticate official source identity, prove that retained
bytes actually decode to the claimed rows, validate a target/cutoff or create
external TSA evidence. The existing worker-side reparse remains necessary, and
the G00/G01 gates remain BLOCKED until genuine independent verification.
