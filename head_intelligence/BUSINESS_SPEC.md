# Head Intelligence — Business Content Specification v0.3.0

## Purpose
把“看信息”变成可审计的信息判断链：多官方源 → 原始证据 → 去重 → 时效 → 主题 → 交叉来源 → 决策相关性 → 快照。

## Business hard gates
- 至少 4 个独立官方信息源族。
- 当前官方源覆盖：Federal Reserve、SEC、BLS、BEA。
- 每个网络文档保存 HTTP、Content-Type、payload hash、抓取时间。
- 更新必须全部启用源成功才为 PASS；部分失败不得用旧缓存伪装实时成功。
- 去重后每条信息保留来源质量、时效、主题、相关性和跨来源主题印证数量。
- 排序必须可解释；不把“分数高”冒充事实真伪。
- 快照失败时不得覆盖上一份已知良好快照。
- 高级分析必须暴露 source health 和 snapshot，不只显示结论。

## Sources
Federal Reserve Board RSS; U.S. SEC press-release RSS; U.S. Bureau of Labor Statistics RSS; U.S. Bureau of Economic Analysis news-release RSS.

## Boundary
系统帮助判断信息的重要性、时效和证据来源，不替用户决定政治立场、投资动作或事实争议结论。
