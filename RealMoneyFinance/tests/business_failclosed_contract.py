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
from app.source_corporate_actions import fetch_share_bonus_events, verify_corporate_action_lineage
from app.source_eastmoney import fetch_daily_bars as fetch_daily_bars_eastmoney
from app.source_yahoo import fetch_daily_bars_yahoo
from tests.contract_gate import FakeClient, FakeTencentClient, FakeTencentFullClient, FakeYahooClient
from tests.collect_candidate_evidence import main as collect, final_acceptance


def bars(count=150):
    start = date(2025, 1, 1)
    return [DailyBar("600000", (start + timedelta(days=i)).isoformat(),
                     10 + i / 100, 10.1 + i / 100, 10.2 + i / 100, 9.9 + i / 100,
                     1000 + i, 100000 + i * 100, 1.0, .01 + i / 10000,
                     "synthetic_contract_only", "a" * 64) for i in range(count)]


class BusinessBoundaries(unittest.TestCase):
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

    def test_full_tencent_adjustment_identity_fails_closed_on_wrong_key(self):
        client = FakeTencentFullClient()
        original = client.get_jsonp_object
        def raw_response(*args, **kwargs):
            obj, meta = original(*args, **kwargs)
            stock = obj["data"]["sh600000"]
            stock["day"] = stock.pop("qfqday")
            return obj, meta
        client.get_jsonp_object = raw_response
        with self.assertRaises(ValueError):
            fetch_daily_bars_tencent_full(client, "600000", 40, adjustment="qfq")

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

    def test_corporate_action_source_schema_and_notice_lineage(self):
        class FakeCorporateClient:
            def get_json(self, url, params, headers=None):
                self.url = url
                self.params = params
                meta = SimpleNamespace(
                    status=200,
                    payload_sha256="e" * 64,
                    retrieved_at_unix=5.0,
                    url=url,
                )
                return {
                    "result": {
                        "data": [{
                            "SECURITY_CODE": "600000",
                            "PLAN_NOTICE_DATE": "2026-05-01 00:00:00",
                            "EX_DIVIDEND_DATE": "2026-06-01 00:00:00",
                            "PRETAX_BONUS_RMB": 1.5,
                            "BONUS_RATIO": 0,
                            "TRANSFER_RATIO": 0,
                            "ASSIGN_PROGRESS": "实施",
                        }]
                    }
                }, meta
        client = FakeCorporateClient()
        events, meta = fetch_share_bonus_events(client, "600000")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["plan_notice_date"], "2026-05-01")
        self.assertEqual(events[0]["ex_dividend_date"], "2026-06-01")
        self.assertEqual(meta["payload_sha256"], "e" * 64)
        self.assertEqual(client.params["reportName"], "RPT_SHAREBONUS_DET")

    def _valid_corporate_action_evidence(self):
        raw = bars(150)
        change_index = 80
        qfq = []
        for i, row in enumerate(raw):
            factor = 0.9 if i < change_index else 1.0
            qfq.append(replace(
                row,
                open=row.open * factor,
                close=row.close * factor,
                high=row.high * factor,
                low=row.low * factor,
                raw_sha256="b" * 64,
            ))
        event = {
            "symbol": "600000",
            "plan_notice_date": raw[change_index - 10].trade_date,
            "ex_dividend_date": raw[change_index].trade_date,
            "pretax_bonus_rmb": 1.0,
            "bonus_ratio": 0.0,
            "transfer_ratio": 0.0,
            "assign_progress": "implemented",
        }
        return verify_corporate_action_lineage(
            qfq,
            raw,
            [event],
            {"provider": "tencent_public_full_kline", "price_adjustment": "qfq", "payload_sha256": "b" * 64},
            {"provider": "tencent_public_full_kline", "price_adjustment": "unadjusted", "payload_sha256": "c" * 64},
            {"provider": "eastmoney_share_bonus_datacenter", "payload_sha256": "d" * 64},
        )

    def test_corporate_action_requires_independent_event_and_factor_lineage(self):
        evidence = self._valid_corporate_action_evidence()
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["point_in_time_lineage"], "PASS")
        self.assertEqual(evidence["verified_event_count"], 1)
        self.assertEqual(evidence["unexplained_factor_changes"], 0)
        self.assertEqual(evidence["matched_events"][0]["calendar_days_after_ex_date"], 0)
        self.assertEqual(
            evidence["matched_events"][0]["factor_change"]["trade_date"],
            evidence["matched_events"][0]["event"]["ex_dividend_date"],
        )

        got = qualify_research(
            bars(300),
            {"provider": "production_fixture", "qualification_scope": "production_real_network", "price_adjustment": "qfq"},
            corporate_action_evidence=evidence,
        )
        self.assertEqual(got["gates"]["corporate_action_adjustment"], "PASS")
        self.assertEqual(got["gates"]["leakage_safe_time_split"], "NOT VERIFIED")
        self.assertFalse(got["capital_deployment_ready"])

    def test_corporate_action_bad_or_missing_pit_evidence_fails_closed(self):
        evidence = self._valid_corporate_action_evidence()
        broken = {**evidence, "event_payload_sha256": "short"}
        got = qualify_research(
            bars(300),
            {"provider": "production_fixture", "qualification_scope": "production_real_network", "price_adjustment": "qfq"},
            corporate_action_evidence=broken,
        )
        self.assertEqual(got["gates"]["corporate_action_adjustment"], "NOT VERIFIED")

        got = qualify_research(
            bars(300),
            {"provider": "production_fixture", "qualification_scope": "production_real_network", "price_adjustment": "qfq"},
            corporate_action_evidence={**evidence, "unexplained_factor_changes": 1},
        )
        self.assertEqual(got["gates"]["corporate_action_adjustment"], "NOT VERIFIED")

        forged_cases = [
            {**evidence, "source_providers": {"qfq": "fake", "raw": "fake", "events": "fake"}},
            {**evidence, "qfq_payload_sha256": "z" * 64},
            {**evidence, "raw_payload_sha256": evidence["qfq_payload_sha256"]},
            {**evidence, "matched_events": []},
            {**evidence, "unexplained_changes": [{"trade_date": "2026-01-01"}]},
            {**evidence, "significant_factor_changes": evidence["verified_event_count"] + 1},
            {**evidence, "overlap_rows": 59},
            {**evidence, "factor_detection_method": "legacy_daily_ratio"},
            {**evidence, "factor_estimator": "close_only_ratio"},
            {**evidence, "factor_window_sessions": 1},
            {**evidence, "price_tick": 0.05},
        ]
        for forged in forged_cases:
            with self.subTest(forged=forged):
                got = qualify_research(
                    bars(300),
                    {"provider": "production_fixture", "qualification_scope": "production_real_network",
                     "price_adjustment": "qfq"},
                    corporate_action_evidence=forged,
                )
                self.assertEqual(got["gates"]["corporate_action_adjustment"], "NOT VERIFIED")

        matched = evidence["matched_events"][0]
        duplicate = {
            **evidence,
            "verified_event_count": 2,
            "significant_factor_changes": 2,
            "matched_events": [matched, matched],
        }
        forged_detail_cases = [
            duplicate,
            {**evidence, "matched_events": [{**matched, "calendar_days_after_ex_date": 7}]},
            {**evidence, "matched_events": [{**matched, "event": {**matched["event"], "symbol": "000001"}}]},
            {**evidence, "matched_events": [{**matched, "event": {**matched["event"], "pretax_bonus_rmb": 0.0,
                                                                  "bonus_ratio": 0.0, "transfer_ratio": 0.0}}]},
            {**evidence, "matched_events": [{**matched, "factor_change": {**matched["factor_change"],
                                                                          "effective_threshold": matched["factor_change"]["relative_change"] + 0.01}}]},
        ]
        for forged in forged_detail_cases:
            with self.subTest(detail_forged=forged):
                got = qualify_research(
                    bars(300),
                    {"provider": "production_fixture", "qualification_scope": "production_real_network",
                     "price_adjustment": "qfq"},
                    corporate_action_evidence=forged,
                )
                self.assertEqual(got["gates"]["corporate_action_adjustment"], "NOT VERIFIED")

        got = qualify_research(
            bars(300),
            {"provider": "production_fixture", "qualification_scope": "production_real_network",
             "price_adjustment": "unadjusted"},
            corporate_action_evidence=evidence,
        )
        self.assertEqual(got["gates"]["corporate_action_adjustment"], "NOT VERIFIED")

        got = qualify_research(
            bars(300),
            {"provider": "production_fixture", "qualification_scope": "production_real_network",
             "price_adjustment": "qfq", "symbol": "000001"},
            corporate_action_evidence=evidence,
        )
        self.assertEqual(got["gates"]["corporate_action_adjustment"], "NOT VERIFIED")

    def test_corporate_action_rounding_jitter_is_not_a_persistent_shift(self):
        raw = bars(150)
        qfq = []
        for row in raw:
            factor = 0.90
            # Model provider cent rounding independently on adjusted prices.
            qfq.append(replace(
                row,
                open=round(row.open * factor, 2),
                close=round(row.close * factor, 2),
                high=round(row.high * factor, 2),
                low=round(row.low * factor, 2),
                raw_sha256="b" * 64,
            ))
        evidence = verify_corporate_action_lineage(
            qfq, raw, [],
            {"provider": "tencent_public_full_kline", "price_adjustment": "qfq", "payload_sha256": "b" * 64},
            {"provider": "tencent_public_full_kline", "price_adjustment": "unadjusted", "payload_sha256": "c" * 64},
            {"provider": "eastmoney_share_bonus_datacenter", "payload_sha256": "d" * 64},
        )
        self.assertEqual(evidence["significant_factor_changes"], 0)
        self.assertEqual(evidence["unexplained_factor_changes"], 0)
        self.assertEqual(evidence["status"], "NOT VERIFIED")
        self.assertEqual(evidence["factor_detection_method"], "persistent_median_regime_shift_v1")
        self.assertEqual(evidence["factor_estimator"], "median_ohlc_ratio_v1")

    def test_corporate_action_unexplained_persistent_shift_stays_nonpass(self):
        raw = bars(150)
        qfq = []
        for i, row in enumerate(raw):
            factor = 0.90 if i < 80 else 0.93
            qfq.append(replace(
                row,
                open=round(row.open * factor, 2),
                close=round(row.close * factor, 2),
                high=round(row.high * factor, 2),
                low=round(row.low * factor, 2),
                raw_sha256="b" * 64,
            ))
        evidence = verify_corporate_action_lineage(
            qfq, raw, [],
            {"provider": "tencent_public_full_kline", "price_adjustment": "qfq", "payload_sha256": "b" * 64},
            {"provider": "tencent_public_full_kline", "price_adjustment": "unadjusted", "payload_sha256": "c" * 64},
            {"provider": "eastmoney_share_bonus_datacenter", "payload_sha256": "d" * 64},
        )
        self.assertGreaterEqual(evidence["significant_factor_changes"], 1)
        self.assertGreaterEqual(evidence["unexplained_factor_changes"], 1)
        self.assertEqual(evidence["status"], "NOT VERIFIED")

    def test_mixed_symbol_rows_fail_before_corporate_action_qualification(self):
        rows = bars(150)
        rows[80] = replace(rows[80], symbol="000001")
        with self.assertRaises(ValueError):
            qualify_research(
                rows,
                {"provider": "production_fixture", "qualification_scope": "production_real_network",
                 "price_adjustment": "qfq"},
                corporate_action_evidence=self._valid_corporate_action_evidence(),
            )

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

