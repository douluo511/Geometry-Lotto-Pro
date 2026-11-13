# 2026-11-13 核验时点：SSQ / DLT 全模型研究候选

每彩种14条可运行模型（含2条随机对照）+2条物理ABSTAIN。NO_EDGE；不自动投注。
D2为注册的两枚红球/前区号码；杀号是可能误杀的低排位候选，没有任何保证。
旧超算D2沿用母体口径：已排序前区票的最小两个数。其随机对照未注册杀号。

## SSQ 2026131，中国开奖日期 2026-11-15
官方最新已开奖 2026130；来源 https://www.swlc.net.cn/。
只代表 2026-11-13T12:34:51Z 的核验；UNOPENED_AT_EXECUTION_DATE_RECHECK_OFFICIAL_SOURCE。
验证区选型 **ewma**；两个物理模型都拒绝预测。

| 模型 | 红球/前区 | 蓝球/后区 | D2候选 | 杀号3码候选 | 状态 |
|---|---|---|---|---|---|
| hot60 | 04 05 06 14 24 30 | 04 | 24 04 | 03 08 32 | RESEARCH_CANDIDATE |
| ewma | 04 06 20 22 25 30 | 01 | 30 20 | 07 08 33 | RESEARCH_CANDIDATE |
| shrinkmix | 04 06 14 22 24 30 | 06 | 14 06 | 03 21 29 | RESEARCH_CANDIDATE |
| pairwise_d2 | 04 05 06 14 24 30 | 04 | 24 30 | 03 08 32 | RESEARCH_CANDIDATE |
| challenger | 04 13 22 24 25 30 | 04 | 24 30 | 08 21 26 | RESEARCH_CANDIDATE |
| random_null | 02 08 11 14 18 26 | 11 | 26 11 | 17 19 25 | RESEARCH_CANDIDATE / 随机对照 |
| hot30 | 04 13 14 20 22 30 | 11 | 30 04 | 08 21 33 | RESEARCH_CANDIDATE |
| hot120 | 04 13 22 24 25 30 | 09 | 30 24 | 08 21 26 | RESEARCH_CANDIDATE |
| pair_margin | 04 05 06 14 24 30 | 09 | 24 30 | 03 08 32 | RESEARCH_CANDIDATE |
| pair_residual | 04 11 14 22 24 30 | 14 | 11 22 | 03 08 32 | RESEARCH_CANDIDATE |
| recency_pair_h45_120 | 04 05 13 14 24 30 | 04 | 13 14 | 03 08 32 | RESEARCH_CANDIDATE |
| supercompute_hot60 | 04 05 06 14 24 30 | 04 | 04 05 | 03 08 32 | RESEARCH_CANDIDATE |
| supercompute_ewma30 | 04 13 14 22 24 30 | 04 | 04 13 | 07 08 21 | RESEARCH_CANDIDATE |
| supercompute_random_null | 10 18 24 31 32 33 | 05 | 10 18 | — | RESEARCH_CANDIDATE / 随机对照 |
| physical_exit_order | — | — | — | — | ABSTAIN |
| physical_ball_group | — | — | — | — | ABSTAIN |

验证选定模型的旧测试杀号误杀 178/392=45.41%；95% Wilson 40.55%–50.36%。
公平随机排除3码误杀率 46.39%。

## DLT 26130，中国开奖日期 2026-11-14
官方最新已开奖 26129；来源 https://www.shsportslottery.com/dlt/kjgg.html。
只代表 2026-11-13T12:34:51Z 的核验；UNOPENED_AT_EXECUTION_DATE_RECHECK_OFFICIAL_SOURCE。
验证区选型 **recency_pair_h45_120**；两个物理模型都拒绝预测。

| 模型 | 红球/前区 | 蓝球/后区 | D2候选 | 杀号3码候选 | 状态 |
|---|---|---|---|---|---|
| hot60 | 03 10 14 25 26 | 01 02 | 14 10 | 30 31 34 | RESEARCH_CANDIDATE |
| ewma | 06 12 14 17 25 | 06 09 | 25 12 | 16 30 31 | RESEARCH_CANDIDATE |
| shrinkmix | 10 14 29 32 33 | 08 10 | 14 29 | 16 28 31 | RESEARCH_CANDIDATE |
| pairwise_d2 | 03 10 14 25 26 | 01 12 | 10 26 | 30 31 34 | RESEARCH_CANDIDATE |
| challenger | 03 10 12 14 26 | 07 08 | 14 26 | 16 30 31 | RESEARCH_CANDIDATE |
| random_null | 02 05 07 15 21 | 03 11 | 15 21 | 22 23 26 | RESEARCH_CANDIDATE / 随机对照 |
| hot30 | 02 03 06 14 25 | 04 07 | 14 06 | 23 30 31 | RESEARCH_CANDIDATE |
| hot120 | 03 10 12 14 26 | 01 03 | 26 10 | 16 30 31 | RESEARCH_CANDIDATE |
| pair_margin | 03 10 14 25 26 | 01 07 | 10 26 | 30 31 34 | RESEARCH_CANDIDATE |
| pair_residual | 04 10 14 25 26 | 05 07 | 04 10 | 30 31 34 | RESEARCH_CANDIDATE |
| recency_pair_h45_120 | 10 12 14 25 26 | 01 03 | 12 14 | 30 31 34 | RESEARCH_CANDIDATE |
| supercompute_hot60 | 03 10 14 25 26 | 09 12 | 03 10 | 30 31 34 | RESEARCH_CANDIDATE |
| supercompute_ewma30 | 03 10 12 14 25 | 09 12 | 03 10 | 23 30 31 | RESEARCH_CANDIDATE |
| supercompute_random_null | 04 05 19 23 34 | 01 05 | 04 05 | — | RESEARCH_CANDIDATE / 随机对照 |
| physical_exit_order | — | — | — | — | ABSTAIN |
| physical_ball_group | — | — | — | — | ABSTAIN |

验证选定模型的旧测试杀号误杀 215/564=38.12%；95% Wilson 34.21%–42.20%。
公平随机排除3码误杀率 37.97%。

全部历史比较见 report.md / analysis.json。真正未参与选型测试 n=0，BLOCKED；不能把历史冠军称为可靠预测冠军。
SHA及公开GitHub提交只记录本次内容，未认证全历史来源，也不是第三方可信预售封存。
