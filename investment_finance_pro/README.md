# Investment Finance Pro — MVP

这是投资金融系统的第一版可运行原型，目标不是输出“神奇买卖点”，而是先闭合以下链路：

**真实网络数据 → 数据校验 → 指标重算 → 研究排序 → 状态审计 → 一键修复 → Windows EXE**

## 主界面

两行两列四入口：

- 投资机会
- 一键更新
- 一键修复
- 高级分析

## 当前真实数据源

- Stooq：SPY / QQQ / AAPL / MSFT / NVDA / GOOGL / AMZN 日线历史
- FRED：美国 10 年期国债收益率 DGS10、联邦基金有效利率 DFF

数据源均通过 HTTPS 实时请求，不内置假行情。任何请求失败都会显示为 PARTIAL / FAILED，不允许把旧缓存冒充最新数据。

## 当前研究模型

当前只提供一个透明的研究排序，用 20 日动量、20 日波动和 60 日回撤生成观察顺序。

**它被明确标记为 UNVALIDATED_RESEARCH_RANK，不是买卖建议，也不声称存在可交易优势。**

后续只有通过 Walk-forward、untouched holdout、benchmark、交易成本、滑点、look-ahead、survivorship bias、bootstrap、ablation、multiple testing 和 regime stability 后，模型才允许升级状态。

## 本地运行

Python 3.11+：

```bash
python investment_finance_pro/app.py
```

确定性自检：

```bash
python investment_finance_pro/app.py --self-test --report self_test.json
```

真实网络 smoke test：

```bash
python investment_finance_pro/app.py --network-smoke --report network_smoke.json
```

## Windows EXE

GitHub Actions 在 Windows 上：

1. 运行源码确定性自检
2. 运行真实网络 Stooq + FRED smoke test
3. 用 PyInstaller 构建单文件 GUI EXE
4. 对构建后的 EXE 再运行确定性自检
5. 对构建后的 EXE 再运行真实网络 smoke test
6. 只有全部通过才上传 EXE artifact

版本：0.1.0-mvp
