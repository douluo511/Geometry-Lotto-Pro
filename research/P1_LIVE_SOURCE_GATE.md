# SSQ＋DLT V4.7 P1: 原始官方数据入口与阻断证明（独立草稿）

**范围**：只接入现有 V4.7 `official_intake.py` / `audit_intake_bundle.py`（PR #467、固定源码提交 `27c519ec0ad251a9d86ebc3452277b158930299e`）。本分支不会改变正式 V4.7 六组筛选器、Random NULL、冻结账本，也不会生成真实预测。

## 唯一入口、行为和验收

`.github/workflows/ssqdlt-p1-source-evidence.yml` 实现两阶段：

1. Ubuntu、Windows 执行独立的八项 fail-closed 协议测试：双彩种必需、审批位始终为零、拒绝伪造的来源审计、拒绝不可信代码 SHA、重复键及非有限数字。
2. Ubuntu 对双色球和大乐透的官方来源执行**真实网络**采集，保存原始响应（包括 HTTP 非 200 错误体）；独立二次审计字节 SHA、路径安全和原始清单；原样归档 `live-evidence/intake.json`、`live-evidence/intake-audit.json`、`live-evidence/raw/`、执行日志及 `p1-execution.json`。

源历史数据取不到、格式冲突、HTTP 故障、字节/清单不一致时必须保持阻断；不能静默补缺或制造目标期号。即使**原始字节**审计通过，也明确输出：

- `status = RAW_CUSTODY_PASS_TARGET_BLOCKED`
- `official_source_authenticity = NOT_VERIFIED`
- `official_target_and_cutoff = BLOCKED`
- `trusted_predraw_seal = NOT_RUN`
- `formal_A = 0`
- `p1_forecast_gate = UNVERIFIED`
- `edge = NO_EDGE`

HTTP 字节审计 PASS 与真实源可信/时效/停售校验 PASS **不是一回事**。真实官方认可必须独立核验来源独立性、语义一致性、权威停售时刻、未来目标与 TSA。当前不予授权预测。

## GitHub Action 的职责边界

- 使用只读权限，固定旧版代码 SHA，绝不调用任何付费模型（`paid_model_calls = 0`）。
- 启动测试后才接入真实 HTTP 采集，支持原始失败记录留存。
- `workflow_dispatch` 是人工诊断，不是无人值守定时；当前 Draft PR 上的 PR CI 不构成正式托管部署。
- GitHub artifact 会到期，**不是**持久的不可篡改账本。后续 P2 需要明确持久存储/访问控制并验证真实计划触发。
- 如上游被防护页面阻挡而没有完整字节证据，CI 应红灯；不得用虚构数据把红灯变绿。
- 这是一个独立的数据入口 Sidecar，不增加第四个 Harness，不触及 PR #467 长期源码分支，也不改正式官方账本。

本轮验收只认 GitHub 的**实际**完整流水线 job/日志/产物 ID。不得凭 Draft PR 存在宣称 G00/G01 或端到端预测完成。
