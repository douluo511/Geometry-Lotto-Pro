# Geometry Lotto Pro — SSQ + DLT research and automation

This repository contains two lottery applications and an independent research toolkit.

- `SSQ/` and `DLT/`: game-specific implementations and acceptance tests.
- `research/supercompute/`: offline CPU Monte Carlo simulation, historical walk-forward scoring, reproducible evidence receipts, and P0 unattended-schedule verification.
- `.github/workflows/`: GitHub Actions for these two lotteries, their unattended schedule audits, and the manual research calculator.

Validate the consolidated research tools from the repository root:

    python -m unittest discover -s research/supercompute/tests -p 'test_*.py' -v

See `research/supercompute/README.md` and `research/supercompute/automation/README.md` for detailed commands and limitations.

**Research limits:** Snapshots are not live official draws. Neither the Monte Carlo simulator nor historical model scores show a proven predictive advantage. Formal V4.7 selectors and historical forecast evidence remain separate from this research-only code.

## SSQ + DLT：一键穷举全部 39,146,800 组

[**打开 GitHub Actions 全部组合计算器（Run workflow）**](https://github.com/douluo511/Geometry-Lotto-Pro/actions/workflows/ssqdlt-exhaustive.yml)

1. 打开链接，点击 **Run workflow**。
2. 选择 **Branch: main**、**games: both**、**workers: 4**，再次点击 **Run workflow**。
3. 等该次任务成功，进入其运行页面底部 **Artifacts**，下载 `ssqdlt-all-combinations-<run_id>`；检查 `report.json` 和 `report.sha256`。

程序真正枚举所有合法开奖结果：SSQ `C(33,6)*C(16,1)=17,721,088`，DLT `C(35,5)*C(12,2)=21,425,712`，共 **39,146,800**。它输出精确号码匹配分布、D2 随机基线、分区 SHA-256 和全量验算；**不导出数千万行号码清单**，也不使用过时历史数据做下一期预测。

它是一个独立的研究计算器，**并非下一期中奖号码预测**，不能证明提高中奖概率。原正式 V4.7 的开奖前封存、真实定时运行及开奖后评分仍需另行验收。若看不到按钮，请确认仓库 Actions 已启用且此工作流已经合并到默认分支。

## 11-component V4.7 research extension

The new opt-in model lab adds HOT60, EWMA, ShrinkMix, Pairwise-D2, Challenger, statistical/geometric/physical simulations, frozen research receipts, and M1-M3 checks. It is independent from formal V4.7 and does not assert predictive edge. See [V47_MODEL_LAB.md](research/supercompute/V47_MODEL_LAB.md) for Windows commands, limitations and test coverage.

## V4.7 unified eleven-stage research forecast

The command `python -m research.supercompute.v47_forecast generate` executes HOT60, EWMA, ShrinkMix, Pairwise-D2, an inheritable evolutionary Challenger, statistical/geometric/probability/physical simulations, combined candidate ranking, M1-M3 verification and create-only research freezing. It accepts explicit target issue IDs and supports `--previous` for inherited champion parameters. Both-games instructions: [V47_UNIFIED_11.md](research/supercompute/V47_UNIFIED_11.md). The separate GitHub schedule also preserves prior champion genealogy on its audit ledger branch. Historical snapshots are not live official data.
