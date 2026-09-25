# Geometry Lotto Pro SSQ — Business / Scientific Specification v8.5.0

## Purpose
双色球模块的业务价值不是“保证中奖”，而是把历史数据、候选模型和严格证伪流程做成可审计研究系统。任何模型只有在预注册时间顺序 OOS/holdout、随机基准、泄漏哨兵、消融、Null-world、稳定性和双确认后仍有重复排序增益，才允许提升 edge_state；否则必须保持 NO_EDGE / NULL_DAN。

## Business hard gates
1. **Game contract**: 红球 1–33 选 6；蓝球 1–16 选 1。
2. **Official-source lineage**: 中国福利彩票发行管理中心主源 + 上海福彩 + 河北福彩官方页面，来源冲突 fail closed。
3. **History integrity**: canonical data 必须有 hash、日期单调、期号与号码范围验证。
4. **Model inventory**: frequency / recency / gap / transition / pair / geometry state / geometry transition / ensemble 全部进入验证池，不等于全部进入最终生产优势。
5. **Pre-registered science**: walk-forward >=1200，prospective >=120，>=3 eras，alpha<=0.01，bootstrap/permutation、Holm、300 null worlds。
6. **False-edge firewall**: Remove / Shuffle / Random-replace 消融；泄漏哨兵；双半确认；Wilson/覆盖率/排名支持。
7. **Prediction semantics**: 未证明优势时不得输出 CERTIFIED_DAN 或暗示更高中奖概率。
8. **Post-draw governance**: Freeze 与 Audit 隔离，Replay 不允许改写开奖前 Freeze。
9. **User boundary**: 界面明确研究性质，不承诺必中。

## Completion rule
工程母版所有硬门 PASS + 本业务门 PASS，才允许最终 SSQ EXE 发布。
