"""Counterexamples protect business boundaries; fixtures prove only contracts."""
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, timedelta
import io
import json
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.business_validation import CostAssumptions, _holdout_power_analysis, _observations, _walk_forward, qualify_research
from app.domain import DailyBar, validate_market_rows
from app.source_tencent import fetch_daily_bars_tencent
from app.source_tencent_full import fetch_daily_bars_tencent_full
from app.source_eastmoney import fetch_daily_bars as fetch_daily_bars_eastmoney
from app.source_yahoo import fetch_daily_bars_yahoo
from app.source_cost_rules import parse_official_cost_rules
from tests.contract_gate import FakeClient, FakeTencentClient, FakeTencentFullClient, FakeYahooClient
from tests.collect_candidate_evidence import main as collect, final_acceptance


def bars(count=150):
    start = date(2025, 1, 1)
    return [DailyBar("600000", (start + timedelta(days=i)).isoformat(),
                     10 + i / 100, 10.1 + i / 100, 10.2 + i / 100, 9.9 + i / 100,
                     1000 + i, 100000 + i * 100, 1.0, .01 + i / 10000,
                     "synthetic_contract_only", "a" * 64) for i in range(count)]


class BusinessBoundaries(unittest.TestCase):
    def test_official_regulatory_cost_rules_are_partial_evidence_only(self):
        parsed = parse_official_cost_rules(
            "<html>A股 经手费 成交金额的0.00341%（双向）</html>",
            "<html>证券交易，税率为成交金额的千分之一。</html>",
            "<html>自2023年8月28日起，证券交易印花税实施减半征收。</html>",
        )
        self.assertEqual(parsed["status"], "PASS")
        self.assertAlmostEqual(parsed["exchange_handling_fee_bps_each_side"], 0.341)
        self.assertAlmostEqual(parsed["sell_stamp_tax_bps"], 5.0)
        got = qualify_research(bars(), {"provider": "synthetic_contract_only"})
        self.assertEqual(got["gates"]["cost_slippage_model"], "NOT VERIFIED")

    def test_official_stamp_tax_date_allows_html_spacing(self):
        parsed = parse_official_cost_rules(
            "<html>0.00341%</html>",
            "<html>千分之一</html>",
            "<html>证券交易印花税实施减半征收，自 2023 年 8 月 28 日 起执行。</html>",
        )
        self.assertEqual(parsed["status"], "PASS")
        self.assertEqual(parsed["sell_stamp_tax_bps"], 5.0)

    def test_incomplete_official_cost_rule_page_fails_closed(self):
        parsed = parse_official_cost_rules(
            "<html>missing current rate</html>",
            "<html>证券交易，税率为成交金额的千分之一。</html>",
            "<html>自2023年8月28日起，证券交易印花税实施减半征收。</html>",
        )
        self.assertEqual(parsed["status"], "NOT VERIFIED")
        self.assertFalse(parsed["checks"]["sse_a_share_handling_fee_0_00341_percent_each_side"])

    def test_insufficient_real_holdout_power_is_not_a_business_pass(self):
        rows = []
        for i, row in enumerate(bars(300)):
            price = 100 + 10 * math.sin(i)
            rows.append(replace(row, open=price, close=price * 1.001,
                                high=price * 1.02, low=price * .98,
                                volume=1_000_000 + (i % 15) * 10_000))
        got = qualify_research(rows, {"qualification_scope": "production_real_network"})
        self.assertEqual(got["holdout_power_analysis"]["status"], "PASS")
        self.assertFalse(got["holdout_power_analysis"]["power_sufficient"])
        self.assertEqual(got["method_gates"]["oos_walk_forward"], "PASS")
        self.assertEqual(got["gates"]["oos_walk_forward"], "NOT VERIFIED")

    def test_checklist_pass_requires_full_qualification_and_formal_release(self):
        production = {x: "PASS" for x in (
            "positive_production_update", "repository_independence",
            "real_release_n_to_n_plus_1", "formal_release_redownload_same_hash")}
        engineering = {"status": "PASS", "gate_statuses": production}
        business = {"status": "PASS", "gate_statuses": {"required_business": "PASS"}}
        self.assertEqual(final_acceptance(engineering, business, False), "FAIL")
        for gate in production:
            with self.subTest(gate=gate):
                missing = {**production, gate: "NOT VERIFIED"}
                self.assertEqual(final_acceptance({"status": "PASS", "gate_statuses": missing}, business, True), "FAIL")
        self.assertEqual(final_acceptance(engineering, {"status": "PASS", "gate_statuses": {"required": "NOT VERIFIED"}}, True), "FAIL")
        self.assertEqual(final_acceptance(engineering, business, True), "PASS")

    def test_non_finite_market_rows_cannot_reach_qualification(self):
        for field in ("open", "close", "high", "low", "volume", "amount", "pct_change", "turnover_rate"):
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_market_rows([replace(row, **{field: value}) if i == 20 else row
                                          for i, row in enumerate(bars())])

    def test_all_production_adapters_reject_non_finite_prices(self):
        cases = (
            (FakeClient, fetch_daily_bars_eastmoney, "eastmoney"),
            (FakeTencentClient, fetch_daily_bars_tencent, "tencent"),
            (FakeTencentFullClient, fetch_daily_bars_tencent_full, "full"),
            (FakeYahooClient, fetch_daily_bars_yahoo, "yahoo"),
        )
        for cls, fetcher, kind in cases:
            client = cls()
            method = "get_jsonp_object" if kind == "full" else "get_json"
            original = getattr(client, method)
            def corrupted(*args, _original=original, _kind=kind, **kwargs):
                obj, meta = _original(*args, **kwargs)
                if _kind == "eastmoney":
                    parts = obj["data"]["klines"][20].split(",")
                    parts[1] = "nan"
                    obj["data"]["klines"][20] = ",".join(parts)
                elif _kind == "yahoo":
                    obj["chart"]["result"][0]["indicators"]["quote"][0]["open"][20] = float("nan")
                else:
                    obj["data"]["sh600000"]["qfqday"][20][1] = "nan"
                return obj, meta
            setattr(client, method, corrupted)
            with self.subTest(provider=kind), self.assertRaises(ValueError):
                fetcher(client, "600000", 40)

    def test_full_tencent_raw_fallback_cannot_claim_qfq(self):
        client = FakeTencentFullClient()
        original = client.get_jsonp_object
        def raw_response(*args, **kwargs):
            obj, meta = original(*args, **kwargs)
            stock = obj["data"]["sh600000"]
            stock["day"] = stock.pop("qfqday")
            return obj, meta
        client.get_jsonp_object = raw_response
        _, meta = fetch_daily_bars_tencent_full(client, "600000", 40)
        self.assertEqual(meta["price_adjustment"], "unadjusted")

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

    def test_holdout_power_target_is_explicit_and_does_not_promote_synthetic_evidence(self):
        got = qualify_research(
            bars(),
            {"provider": "synthetic_contract_only", "qualification_scope": "offline_contract"},
        )
        power = got["holdout_power_analysis"]
        # This fixture intentionally produces a degenerate all-cash OOS path.
        # The method must fail closed instead of fabricating power evidence.
        self.assertEqual(power["status"], "NOT VERIFIED")
        self.assertIn("holdout", power["reason"])
        self.assertEqual(got["gates"]["oos_walk_forward"], "NOT VERIFIED")
        # Independently verify the frozen power calculation on finite,
        # non-degenerate returns; executing the method is not signal promotion.
        direct = _holdout_power_analysis([(-1 if i % 2 else 1) * 0.01 for i in range(160)])
        self.assertEqual(direct["status"], "PASS")
        self.assertIn(direct["decision"], {"SUFFICIENT", "INSUFFICIENT"})
        self.assertGreater(direct["minimum_detectable_mean_return"], 0)
        self.assertIsInstance(direct["power_sufficient"], bool)

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

    def test_individual_business_passes_count_without_promoting_final(self):
        gate_names = ("cost_slippage_model", "liquidity_capacity", "corporate_action_adjustment",
                      "leakage_safe_time_split", "survivorship_selection_control", "oos_walk_forward",
                      "bootstrap", "ablation", "stability", "multiple_testing_correction")
        acceptance_text = (Path(__file__).resolve().parents[1] / "ACCEPTANCE_CONTRACT.json").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SOURCE_SHA": "a"*40}):
            previous = Path.cwd()
            try:
                os.chdir(td)
                Path("ACCEPTANCE_CONTRACT.json").write_text(acceptance_text, encoding="utf-8")
                Path("business_qualification_evidence.json").write_text(json.dumps({
                    "status": "PASS",
                    "real_market_research_qualification": {
                        "business_qualification_status": "NOT VERIFIED",
                        "gates": {x: "PASS" for x in gate_names},
                        "capital_deployment_ready": False,
                    },
                }))
                with redirect_stdout(io.StringIO()):
                    collect()
                evidence = json.loads(Path("candidate_manifest.json").read_text())
                self.assertEqual(evidence["business_qualification_status"], "NOT VERIFIED")
                self.assertEqual(evidence["business_completion"]["status"], "NOT VERIFIED")
                expected_pass = (
                    "cost_slippage_calibration", "liquidity_capacity", "corporate_action_point_in_time",
                    "leakage_point_in_time", "survivorship_precommitted_universe",
                    "walk_forward_holdout_power", "dependence_aware_bootstrap", "ablation_replication",
                    "regime_stability", "multiple_testing_search_family",
                )
                for key in expected_pass:
                    self.assertEqual(
                        evidence["business_completion"]["gate_statuses"][key],
                        "PASS",
                    )
                self.assertLess(evidence["business_completion"]["percent"], 100.0)
                self.assertEqual(evidence["final_gate"], "FAIL")
            finally:
                os.chdir(previous)


    def test_explicit_rejection_counts_as_completed_qualification_decision(self):
        acceptance_text = (Path(__file__).resolve().parents[1] / "ACCEPTANCE_CONTRACT.json").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SOURCE_SHA": "a"*40}):
            previous = Path.cwd()
            try:
                os.chdir(td)
                Path("ACCEPTANCE_CONTRACT.json").write_text(acceptance_text, encoding="utf-8")
                Path("business_qualification_evidence.json").write_text(json.dumps({
                    "status": "PASS",
                    "real_market_research_qualification": {
                        "method_execution_status": "PASS",
                        "business_qualification_status": "NOT VERIFIED",
                        "diagnostic_thresholds_met": False,
                        "economic_signal_qualified": False,
                        "capital_deployment_ready": False,
                        "gates": {},
                        "feature_results": {},
                    },
                }))
                with redirect_stdout(io.StringIO()):
                    collect()
                evidence = json.loads(Path("candidate_manifest.json").read_text())
                self.assertEqual(
                    evidence["business_completion"]["gate_statuses"]["economic_signal_qualification_decision"],
                    "PASS",
                )
                self.assertFalse(evidence["economic_signal_qualified"])
                self.assertEqual(evidence["final_gate"], "FAIL")
            finally:
                os.chdir(previous)

    def test_missing_explicit_signal_decision_stays_not_verified(self):
        acceptance_text = (Path(__file__).resolve().parents[1] / "ACCEPTANCE_CONTRACT.json").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SOURCE_SHA": "a"*40}):
            previous = Path.cwd()
            try:
                os.chdir(td)
                Path("ACCEPTANCE_CONTRACT.json").write_text(acceptance_text, encoding="utf-8")
                Path("business_qualification_evidence.json").write_text(json.dumps({
                    "status": "PASS",
                    "real_market_research_qualification": {
                        "method_execution_status": "PASS",
                        "capital_deployment_ready": False,
                        "gates": {},
                        "feature_results": {},
                    },
                }))
                with redirect_stdout(io.StringIO()):
                    collect()
                evidence = json.loads(Path("candidate_manifest.json").read_text())
                self.assertEqual(
                    evidence["business_completion"]["gate_statuses"]["economic_signal_qualification_decision"],
                    "NOT VERIFIED",
                )
            finally:
                os.chdir(previous)


    def test_missing_individual_business_gate_stays_not_verified(self):
        acceptance_text = (Path(__file__).resolve().parents[1] / "ACCEPTANCE_CONTRACT.json").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SOURCE_SHA": "a"*40}):
            previous = Path.cwd()
            try:
                os.chdir(td)
                Path("ACCEPTANCE_CONTRACT.json").write_text(acceptance_text, encoding="utf-8")
                Path("business_qualification_evidence.json").write_text(json.dumps({
                    "status": "PASS",
                    "real_market_research_qualification": {
                        "method_execution_status": "PASS",
                        "business_qualification_status": "NOT VERIFIED",
                        "diagnostic_thresholds_met": False,
                        "economic_signal_qualified": False,
                        "capital_deployment_ready": False,
                        "gates": {"bootstrap": "PASS"},
                        "feature_results": {},
                    },
                }))
                with redirect_stdout(io.StringIO()):
                    collect()
                evidence = json.loads(Path("candidate_manifest.json").read_text())
                statuses = evidence["business_completion"]["gate_statuses"]
                self.assertEqual(statuses["dependence_aware_bootstrap"], "PASS")
                self.assertEqual(statuses["walk_forward_holdout_power"], "NOT VERIFIED")
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

