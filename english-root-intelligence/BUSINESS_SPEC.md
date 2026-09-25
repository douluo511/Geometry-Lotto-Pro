# English Root Intelligence — Business Content Specification v0.3.0

## Purpose
把“背单词”升级为可验证的词素理解、词族迁移、口语语块与主动练习系统。系统不得为了“看起来会拆”而强行拆词。

## Business hard gates
1. **Scope**: 前缀 / 词根 / 后缀三类词素均覆盖。
2. **Reference catalog**: 至少 252 个去重的 type:morpheme 参考条目。
3. **Active learning modules**: 至少 36 个完整词族；每个至少 3 个真实单词记录与 3 个可练习语块。
4. **Provenance**: 数据包含来源注册表；词源只作为学习线索，不把民间拆词当事实。
5. **Uncertainty**: 找不到高置信词根时必须明确“需要词典确认”，不得生成伪词义。
6. **Speech practice**: Windows EXE 保留本地朗读入口，作为 Shadowing 辅助，不冒充真人语音数据库。
7. **Update integrity**: 一键更新必须 manifest + SHA256 + schema 验证 + 原子替换/回滚。
8. **Regression**: predict / inspect / transport 等基准词必须得到稳定、可解释拆分。

## Sources
- Online Etymology Dictionary — https://www.etymonline.com/
- Merriam-Webster Dictionary — https://www.merriam-webster.com/
- Wiktionary — https://en.wiktionary.org/

来源注册表用于交叉核对词源、含义与词形；本地数据不是这些网站的镜像，也不复制其长篇释义。

## Boundary
词素分析是记忆与理解辅助，不等于每个现代英语词都能可靠地由表面字母机械拆解。低置信时必须保留未知。
