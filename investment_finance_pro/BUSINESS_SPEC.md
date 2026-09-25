# Investment Finance Pro — Business Content Specification v0.3.0

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
Yahoo Chart（市场行情）；U.S. Treasury（官方利率）；FRED（宏观时间序列）；SEC Company Facts（官方申报事实）。

## Boundary
研究排名不是买卖建议，不保证收益。估值代理仅是一个维度，不能单独形成投资结论。
