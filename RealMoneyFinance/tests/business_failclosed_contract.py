"""Counterexamples protect business boundaries; fixtures prove only contracts."""
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.business_validation import CostAssumptions, _observations, _walk_forward, qualify_research
from app.domain import DailyBar
from app.source_tencent import fetch_daily_bars_tencent
from tests.collect_candidate_evidence import main as collect


def bars():
    start = date(2025, 1, 1)
    return [DailyBar("600000", (start + timedelta(days=i)).isoformat(),
                     10 + i / 100, 10.1 + i / 100, 10.2 + i / 100, 9.9 + i / 100,
                     1000 + i, 100000 + i * 100, 1.0, .01 + i / 10000,
                     "synthetic_contract_only", "a" * 64) for i in range(150)]


class BusinessBoundaries(unittest.TestCase):
    def test_final_close_features_cannot_trade_that_close(self):
        rows = bars()
        item = _observations(rows, ("volume",))[0]
        self.assertEqual(item["feature_date"], rows[20].trade_date)
        self.assertEqual(item["entry_date"], rows[21].trade_date)
        self.assertEqual(item["outcome_date"], rows[22].trade_date)
        self.assertAlmostEqual(item["next_return"], rows[22].open / rows[21].open - 1)

    def test_future_features_do_not_change_past_signal(self):
        rows = bars()
        changed = [replace(x, volume=x.volume * 1000) if i > 40 else x for i, x in enumerate(rows)]
        original = [x for x in _observations(rows, ("volume",)) if x["feature_date"] <= rows[40].trade_date]
        altered = [x for x in _observations(changed, ("volume",)) if x["feature_date"] <= rows[40].trade_date]
        self.assertEqual(original, altered)

    def test_continuous_long_pays_buy_and_terminal_sale(self):
        points = [{"feature_date": f"{i:04}", "entry_date": f"{i+1:04}",
                   "outcome_date": f"{i+2:04}", "score": 1.0, "next_return": 0.0}
                  for i in range(80)]
        result = _walk_forward(points, 10)
        self.assertAlmostEqual(sum(result["oos_net_returns"]), -.002)
        self.assertAlmostEqual(result["total_cost_return"], .002)
        self.assertAlmostEqual(result["buy_and_hold_baseline_mean_net_return"], -.002 / 20)

    def test_high_amount_and_qfq_label_do_not_prove_capacity_or_actions(self):
        rows = [replace(x, amount=1e15) for x in bars()]
        got = qualify_research(rows, {"price_adjustment": "qfq", "provider": "synthetic_contract_only"})
        self.assertEqual(got["amount_coverage"], 1)
        self.assertEqual(got["gates"]["liquidity_capacity"], "NOT VERIFIED")
        self.assertEqual(got["gates"]["corporate_action_adjustment"], "NOT VERIFIED")
        self.assertFalse(got["economic_signal_qualified"])
        self.assertFalse(got["capital_deployment_ready"])
        self.assertEqual(got["business_qualification_status"], "NOT VERIFIED")

    def test_missing_turnover_cannot_pass_complete_ablation(self):
        got = qualify_research([replace(x, turnover_rate=None) for x in bars()], {})
        self.assertEqual(got["feature_results"]["turnover_only"]["status"], "NOT VERIFIED")
        self.assertEqual(got["method_gates"]["ablation"], "NOT VERIFIED")

    def test_invalid_cost_or_participation_is_rejected(self):
        for assumptions in (CostAssumptions(slippage_bps_each_side=-1),
                            CostAssumptions(commission_bps_each_side=float("nan")),
                            CostAssumptions(max_participation_rate=0)):
            with self.subTest(assumptions=assumptions), self.assertRaises(ValueError):
                qualify_research(bars(), {}, assumptions)

    def test_duplicate_or_reverse_dates_are_rejected(self):
        rows = bars()
        for malformed in ([*rows[:-1], rows[-2]], list(reversed(rows))):
            with self.assertRaises(ValueError):
                qualify_research(malformed, {})

    def test_unadjusted_tencent_fallback_cannot_claim_qfq(self):
        rows = [[x.trade_date, str(x.open), str(x.close), str(x.high), str(x.low), str(x.volume)]
                for x in bars()[:30]]
        meta = SimpleNamespace(payload_sha256="b"*64, url="https://fixture.invalid", status=200,
                               retrieved_at_unix=0, content_type="application/json", content_type_policy="strict")
        client = SimpleNamespace(get_json=lambda *args, **kwargs: ({"data": {"sh600000": {"day": rows}}}, meta))
        _, got = fetch_daily_bars_tencent(client, "600000", 30)
        self.assertEqual(got["price_adjustment"], "unadjusted")

    def test_legacy_method_pass_does_not_promote_business_manifest(self):
        gate_names = ("cost_slippage_model", "liquidity_capacity", "corporate_action_adjustment",
                      "leakage_safe_time_split", "survivorship_selection_control", "oos_walk_forward",
                      "bootstrap", "ablation", "stability", "multiple_testing_correction")
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SOURCE_SHA": "a"*40}):
            previous = Path.cwd()
            try:
                os.chdir(td)
                Path("business_qualification_evidence.json").write_text(json.dumps({"status": "PASS",
                    "real_market_research_qualification": {"gates": {x: "PASS" for x in gate_names}}}))
                with redirect_stdout(io.StringIO()):
                    collect()
                evidence = json.loads(Path("candidate_manifest.json").read_text())
                self.assertEqual(evidence["business_qualification_status"], "NOT VERIFIED")
                for key in ("cost_slippage_liquidity_corporate_action", "leakage_survivorship_time_splits",
                            "oos_walk_forward_bootstrap_ablation_stability_multiple_testing"):
                    self.assertEqual(evidence["gates"][key], "NOT VERIFIED")
                self.assertEqual(evidence["final_gate"], "FAIL")
            finally:
                os.chdir(previous)


def run_contract() -> dict:
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BusinessBoundaries))
    if not result.wasSuccessful():
        raise AssertionError("business boundary counterexample regression failed")
    return {"status": "PASS", "tests_run": result.testsRun, "scope": "offline contracts only"}


if __name__ == "__main__":
    print(json.dumps(run_contract()))
