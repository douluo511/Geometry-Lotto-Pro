from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/"app.py").read_text(encoding="utf-8")
assert "Stock AI Pro 4.3" in text
for tab in ["今日Top20","股票诊断","三套组合","回测","估值与成本","模型审计","研发闭环","证据链","系统健康"]: assert tab in text
assert "from stock_ai.config import ROOT,CODE_ROOT" in text
print("APP CONTRACT TEST PASS")
