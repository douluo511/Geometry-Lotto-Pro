import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import analyze, format_report


def run():
    r = analyze("对方连续两次要求延后付款，还说我们的报价太高，我不知道他有没有审批权。", "尽快回款并保持合作")
    assert abs(sum(h["score"] for h in r["hypotheses"]) - 1.0) < 0.01
    assert r["information_gain"]
    assert len(r["strategies"]) >= 3
    text = format_report(r)
    for key in ["竞争假设", "策略候选", "逆转验证", "5 Why"]:
        assert key in text
    print("CORE_TEST_PASS")


if __name__ == "__main__":
    run()
