# Geometry Lotto Pro DLT — Business / Scientific Specification v2.3.0

## Purpose
这是可审计的彩票研究系统，不是必中系统。业务价值是：真实开奖数据 → 候选模型池 → 时间顺序样本外验证 → 随机基准/证伪 → False-Edge Firewall → 明确 NO_EDGE / NULL_DAN 或有证据的研究状态。

## Data-source contract
- Primary：江苏省体育彩票管理中心 DLT 历史页。
- Secondary：甘肃省体育彩票管理中心 DLT 历史页。
- Primary + Secondary 必须实时成功、最新期一致、至少 10 个共同期号逐期一致。
- 全国接口只作为 Supplemental cross-check；若 WAF 拒绝，必须记录 FAIL，绝不把失败转换成 PASS。
- 可信历史基线只能由连续的 Primary+Secondary 双官方共识向前推进。

## Scientific hard gates
- DLT 规则：前区 1–35 选 5，后区 1–12 选 2。
- 候选池：frequency / recency / gap / transition / pair / geometry state / geometry transition / ensemble。
- 时间顺序 Walk-forward，不允许 future leakage。
- untouched holdout 不参与 challenger 选择。
- Bootstrap + permutation + Holm，多时代 Leave-One-Era-Out。
- Remove / Shuffle / Random ablation；无增益路径可标 DEAD_PATH。
- Null-world FPR + synthetic null worlds。
- Dual Final Confirmation。
- Dan Firewall：Wilson95 下界 + 多窗口/多模型/多 seed 覆盖 + rank support。
- 无稳定增益时必须输出 NO_EDGE / NULL_DAN，不能为了“更准”继续调参追历史。

## Release rule
业务/科学门与工程母版硬门全部 PASS，且 Exact EXE、Physical GUI Click、Same Hash、Final Gate 都针对同一二进制，才允许发布。
