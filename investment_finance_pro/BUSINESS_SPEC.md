# Investment Finance Pro — Business Content Specification v0.4.0

## Purpose
用真实市场与官方宏观/公司事实建立研究闭环，而不是单纯猜涨跌。生产输出必须把市场趋势、波动/回撤、估值代理、利率环境和压力情景分开呈现。

## Business hard gates
- 市场行情：真实日线，记录来源、HTTP、时间与 payload hash。
- 官方宏观：U.S. Treasury 10Y + FRED effective fed funds。
- 公司事实：SEC Company Facts，至少能取得一只真实公司最近 10-K 年度 EPS。
- Engine 自己拥有 metrics / valuation / scenario / rank，不再把生产计算代理给 legacy_backend。
- 风险至少包括年化波动、60 日最大回撤、-10%/-20% 压力情景。
- 估值只标为年度 EPS P/E proxy，不冒充完整 DCF/内在价值。
- 排名固定 UNVALIDATED_RESEARCH_RANK，除非未来独立 OOS/holdout 证明优势。
- 任一生产数据源失败必须显式 PARTIAL/FAILED，不能用缓存伪装实时 PASS。

## Sources
- Yahoo Chart + Stooq 独立交叉核对（市场行情）；正常 PASS 要求两者在最近共同交易日无重大冲突。
- Yahoo 不可用时允许 Stooq 作为可用 fallback，但单源 fallback 只能形成 PARTIAL，不得成为 live PASS。
- U.S. Treasury（官方 10Y 利率）；FRED DFF（官方/权威宏观时间序列）；SEC Company Facts（官方申报事实）。
- 所有生产源必须执行 freshness 检查、HTTP/Content-Type/结构校验并保留逐次网络 ledger 与 raw payload hash。

## Boundary
研究排名不是买卖建议，不保证收益。估值代理仅是一个维度，不能单独形成投资结论。


## Scientific validation firewall
- 研究排序默认且持续为 UNVALIDATED_RESEARCH_RANK。
- 科学门按时间顺序执行 OOS；未来数据不得进入当期评分。
- 必须同时执行等权基线、随机基线、交易成本压力、Bootstrap、Permutation、双半段 holdout、泄漏哨兵与组件消融。
- 科学门 PASS 只表示验证协议完整执行，不表示存在可交易优势。
- 即使出现候选信号，promotion_allowed 仍为 false；没有独立预注册确认链就不得升级为 VALIDATED_EDGE。
- NO_EDGE / UNVALIDATED 是允许且诚实的生产研究结论。

## Snapshot fail-closed rule
PARTIAL / FAILED 更新不得覆盖上一份 known-good PASS 快照；可在本次结果中显示诊断，但不能伪装成最新成功快照。

## Action boundary
系统不得把研究排序输出包装成 BUY / SELL / STRONG BUY / STRONG SELL，也不得保证收益。用户自行作出投资决策。
