# SSQ＋DLT 研究证据链：独立 GitHub 验收与交付记录（2026-11-11）

## 本次交付，不是预测成功声明

唯一目标仍然是 [Issue #468](https://github.com/douluo511/Geometry-Lotto-Pro/issues/468)。
现有唯一正式 V4.7 研究 Harness、固定 Random NULL、六组正式预测、官方冻结账本未改动；本次仅补充可独立执行的**研究账本**审计。不能把研究账本的 SHADOW 票升级为有独立 RFC3161 封存的正式事前票。未经未来验证不能宣称提高中奖率。

### 唯一审核入口

- [Draft PR #472](https://github.com/douluo511/Geometry-Lotto-Pro/pull/472)
- 研究预测运行主工作流：[main/.github/workflows/ssqdlt-research-loop.yml](https://github.com/douluo511/Geometry-Lotto-Pro/blob/main/.github/workflows/ssqdlt-research-loop.yml)（已注册，有两次真实 `push`，但 **没有** `schedule` 验收）
- 新独立审计流：`.github/workflows/ssqdlt-research-ledger-independent-audit.yml`（**Draft PR，尚未部署到 main**；合并并经独立评审后，才能通过 `workflow_run: completed` 在每次真实研究循环完成后独立审计）
- 独立审计实现：`research/ssqdlt_research_ledger_audit.py`（Python 3.11 标准库，无付费模型，无随机选号计算）
- 攻击测试：`tests/test_ssqdlt_research_ledger_audit.py`

### 实际执行：有 RED，也有 GREEN

- RED [GitHub Actions #43074133152](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/43074133152)：先提交验收测试，缺少审计实现时 `ModuleNotFoundError`，CI 正确红灯。
- RED [GitHub Actions #43074713885](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/43074713885)：已完成 13 项双系统测试，但针对**真实** GitHub 账本发现首期双彩种旧协议把 `formal_A` 放在外层；不能要求历史快照新增字段或重写原始票。真实远端核验红灯后修复了审计器，而不是修改旧账本。
- GREEN [GitHub Actions #43074987506](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/43074987506)：双系统各 14 项对抗测试 PASS、独立远端冷恢复与完整 Git 添加历史、固定旧版历史评分重放、Actions REST 身份核验均 PASS。注意：此为修复后**加入最新目录 symlink 攻击测试之前**的绿灯；最新提交仍需以 exact-head CI 为准。

### 真实独立验收发现（上次完整绿色基线）

- 远端研究证据 branch `ssqdlt-research-ledger-v1`：`bd86fd0e555895aa695c3be3d989887bdd52d0df`。
- 已存原始文件：**8 个只追加**（**1** 个双彩种预测快照、**5** 个原始网页证据、**2** 个研究循环 tick）；历史中未检测到旧文件 M、D、R。
- 研究预测：SSQ 2026130，DLT 26130，各一组；已评分样本 SSQ 0 / DLT 0；因此**两种彩票真实未来命中率不可计算**，不能写成零命中率。
- 独立 GitHub Actions REST 交叉核对：`43069944964` 与 `43071336351` 均为 `push`，源码 SHA 与账本声称一致，都是成功完成；**实际 `schedule` 事件 = 0**。
- 账本全部 8 份证据文件原始字节集合指纹：`c13deb78d84a5d04f3e76df67371e9823c7ef2cd5b829b2a442aaf76c805b8d7`。
- 独立固定评分复盘：`PASS_RESEARCH_REPLAY_NOT_FORMAL`；仍有未出结果的目标期，不把它们算作失败或成功期。
- 首期旧研究快照是 Git 一次追加且外部流水线可定位，但其 `content_sha256` 依赖**原始完整历史模型收据**；审计器没有重建其全部原始字段，因此声明 `legacy_full_prediction_hash_rerender=UNVERIFIED`，不能对这部分做过度保证。

### 最新 exact-head 预期操作（PR 合并前做审阅）

在 GitHub PR #472 的 Checks 里确认 Ubuntu、Windows 测试及 `fresh-remote-independent-audit` 三个 job 均成功；下载已归档的 `independent-research-evidence.json` 与 `pinned-research-replay.json`。如有真实目标开奖，必须首先由官方来源核实，已有冻结预测通过不可改动的创建时间才允许计分。失败、超时或网页被反爬拦截不能删除历史分母，也不能倒填缺失期。

只读本地重现方法（需要完整 Git 提交历史、GitHub API 只读 token 才能验证触发）：

```powershell
git clone --branch ssqdlt-research-ledger-v1 --single-branch https://github.com/douluo511/Geometry-Lotto-Pro.git ssqdlt-ledger-audit
# 在 PR #472 的审核源码副本中运行：
python -m research.ssqdlt_research_ledger_audit --ledger ssqdlt-ledger-audit --check-git-history --check-actions-api --out p0-p2-review.json
```

上述命令只读，不会买票、修改任何预测或合并 PR。无 API 权限时保持 `actions_api=UNVERIFIED`，不能声称真实 schedule PASS。

### 仍未完成的正式主工程

| 验收项 | 结果 |
|---|---|
| 研究账本文件/历史/两次 push 运行证据 | 已验证 |
| GitHub 两次真实定时 schedule 触发及自动复原 | **UNVERIFIED** |
| 正式 V4.7 六臂双彩种原始数据 G00/G01 交叉验证 | **BLOCKED** |
| 权威下期号和最早停售时间独立验证 | **BLOCKED** |
| RFC3161 外部可信时间戳 + 完整正式开奖前封存 | **UNVERIFIED** |
| 正式开奖后只读评分、连续真实闭环 | **UNVERIFIED** |
| Windows 真实冷启动/任务计划/无人值守恢复 | **UNVERIFIED** |
| 独立第三方工程代码复核 | **REVIEW_NOT_VERIFIED** |
| ENGINEERING_PASS | **NOT_YET** |
| RESEARCH_VALID | **NOT_YET** |
| D2_EDGE_CONFIRMED | **NO** |
| formal_A | **0** |
| 科学判断 | **NO_EDGE** |

**下一环唯一优先事项**：验证主研究循环实际 `schedule` 触发与失败恢复，且保持所有预测 SHA、真实开奖号、全局样本分母的不可回写性。不能利用官方数据语义冲突或本地时间倒推“已事前预测”。