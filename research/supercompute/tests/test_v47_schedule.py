"""Offline regression tests for genuine-schedule receipt semantics."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research.supercompute.automation import v47_schedule as s
from research.supercompute.v47_models import canonical

SHA = "a" * 40


def example_report():
    return {"schema": "SSQDLT_11_COMPONENT_RESEARCH_V1",
            "formal_prediction": False, "edge": "NO_EDGE",
            "games": {g: {"source_status": "REPOSITORY_HISTORICAL_NOT_LIVE_VERIFIED",
                          "models": {"edge": "NO_EDGE",
                                     "strictly_past_only": True,
                                     "independent_test_tail": True,
                                     "models": {name: {"n": 2} for name in ("HOT60", "EWMA", "ShrinkMix", "Pairwise-D2", "Challenger")}}}
                      for g in ("ssq", "dlt")}}


def fake_run(run_id, success=True):
    return {"id": run_id, "event": "schedule", "status": "completed" if success else "in_progress",
            "conclusion": "success" if success else None,
            "head_branch": "main", "head_sha": SHA,
            "path": s.WORKFLOW + "@refs/heads/main",
            "repository": {"full_name": s.REPO}}


class TestV47UnattendedSchedule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ledger = self.base / "worktree"
        self.ledger.mkdir()
        self.report = self.base / "out.json"
        self.report.write_bytes(canonical(example_report()))

    def register(self, run_id):
        return s.record(self.ledger, self.report, run_id, 1, SHA, "schedule")

    def test_empty_ledger_clean(self):
        state = s.verify(self.ledger)
        self.assertEqual(state["count"], 0)
        self.assertEqual(state["last_hash"], s.ZERO)

    def test_append_two_chain_and_run_id(self):
        self.register(101)
        result = self.register(102)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["run_ids"], [101, 102])
        self.assertEqual(s.verify(self.ledger, expected_run_id=101)["status"], "PASS")

    def test_manual_disallowed(self):
        with self.assertRaises(ValueError):
            s.record(self.ledger, self.report, 101, 1, SHA, "workflow_dispatch")
        self.assertEqual(s.verify(self.ledger)["count"], 0)

    def test_duplicate_run_disallowed(self):
        self.register(101)
        with self.assertRaises(ValueError):
            self.register(101)
        self.assertEqual(s.verify(self.ledger)["count"], 1)

    def test_tampered_report_or_receipt_disallowed(self):
        self.register(101)
        report_file = self.ledger / s.LEDGER / "reports" / "101.json"
        report_file.write_bytes(report_file.read_bytes() + b"tampered")
        with self.assertRaises(ValueError):
            s.verify(self.ledger)

    def test_missing_history_is_detected(self):
        self.register(101)
        self.register(102)
        event = self.ledger / s.LEDGER / "events" / "00000001-101.json"
        event.unlink()
        with self.assertRaises(ValueError):
            s.verify(self.ledger)

    def test_remote_restart_from_prior_committed_copy(self):
        self.register(101)
        restored = self.base / "restored"
        shutil.copytree(self.ledger, restored)
        s.record(restored, self.report, 102, 1, SHA, "schedule")
        self.assertEqual(s.verify(self.ledger)["count"], 1)
        self.assertEqual(s.verify(restored)["count"], 2)

    def test_independent_external_audit_two_complete(self):
        self.register(101)
        self.register(102)
        with patch.object(s, "github_run", side_effect=lambda run_id, token: fake_run(run_id)):
            status = s.audit(self.ledger, "token-for-test")
        self.assertEqual(status["status"], "PASS")
        self.assertEqual(status["scheduled_completed_success_count"], 2)
        self.assertTrue(status["prior_remote_prefix_recovered"])
        self.assertFalse(status["trusted_predraw_seal_verified"])

    def test_one_not_completed_cannot_pass(self):
        self.register(101)
        self.register(102)
        with patch.object(s, "github_run",
                          side_effect=lambda run_id, token: fake_run(run_id, success=run_id == 101)):
            status = s.audit(self.ledger, "token-for-test")
        self.assertEqual(status["status"], "UNVERIFIED")
        self.assertEqual(status["scheduled_completed_success_run_ids"], [101])

    def test_untrusted_report_fail_closed(self):
        payload = example_report()
        payload["edge"] = "EDGE_PROVEN"
        self.report.write_bytes(canonical(payload))
        with self.assertRaises(ValueError):
            self.register(101)
        self.assertEqual(s.verify(self.ledger)["count"], 0)


    def test_unified_champion_cross_run_persistence(self):
        req = ["1:HOT60", "2:EWMA", "3:ShrinkMix", "4:Pairwise-D2",
               "5:Challenger", "6:statistics", "7:combination_freeze_score",
               "8:geometry", "9:probability_simulation",
               "10:uncalibrated_physics", "11:M1_M2_M3"]
        models = {k: [{"front": [1, 2, 3, 4, 5], "back": [1, 2]}]
                  for k in ("HOT60", "EWMA", "ShrinkMix", "Pairwise-D2", "Challenger")}
        payload = {"schema": "SSQDLT_V47_UNIFIED_RUN_V1", "edge": "NO_EDGE",
                   "formal_prediction": False,
                   "games": {g: {"game": g, "requirement_modules": req,
                                  "model_family_tickets": models,
                                  "proposed_tickets": [{"front": [1, 2, 3, 4, 5]}] * 3,
                                  "edge": "NO_EDGE", "formal_prediction": False,
                                  "evolution": {"uses_future_draws": False}}
                             for g in ("ssq", "dlt")}}
        from research.supercompute.v47_registry import REGISTRY
        for game, report in payload["games"].items():
            report["history_sha256"] = "synthetic-test-history-hash"
            report["independent_11"] = {
                "schema": "SSQDLT_V47_11_INDEPENDENT_MODELS_V1",
                "model_count": 11, "independent_modules": True,
                "history_sha256": "synthetic-test-history-hash",
                "formal_prediction": False,
                "models": {m.label: {
                    "status": "EXECUTED", "fit": {"training": "synthetic"},
                    "prediction": {"ticket": {"front": [1], "back": [2]}}}
                    for m in REGISTRY}}
        for game, report in payload["games"].items():
            sample = ({"front": [1, 2, 3, 4, 5, 6], "back": [1], "dan2": [1, 2]}
                      if game == "ssq"
                      else {"front": [1, 2, 3, 4, 5], "back": [1, 2], "dan2": [1, 2]})
            report["proposed_tickets"] = []
            report["ticket_count"] = 11
            report["per_model_ticket_contract"] = "ONE_ROW_PER_MODEL"
            record = {
                "m2": {"test": "exact_binomial_fair_d2"},
                "m3": {"calibration_method": "heldout_shrink_to_fair",
                       "training_samples": 10, "independent_test_samples": 5}}
            all_results = {model.label: record for model in REGISTRY}
            report["independent_11"]["validation_all_11"] = {
                "model_count": 11, "status": "PASS",
                "uses_future_draws": False, "models": all_results}
            report["full_model_validation"] = "PASS"
            report["validation"] = {
                "M2": {k: v["m2"] for k, v in all_results.items()},
                "M3": {k: v["m3"] for k, v in all_results.items()}}
            for index, model in enumerate(REGISTRY, 1):
                ticket = dict(sample, model_number=index, model_name=model.label)
                report["proposed_tickets"].append(ticket)
                report["independent_11"]["models"][model.label]["prediction"]["ticket"] = dict(sample)
        s.check_unified_report(payload)
        incomplete = json.loads(json.dumps(payload))
        incomplete["games"]["ssq"]["independent_11"]["models"].pop("Geometry")
        with self.assertRaises(ValueError):
            s.check_unified_report(incomplete)
        prior = self.base / "unified.json"
        prior.write_bytes(canonical(payload))
        s.record(self.ledger, self.report, 101, 1, SHA, "schedule",
                 unified_report_path=prior)
        latest = self.ledger / s.LEDGER / "latest_unified.json"
        self.assertEqual(latest.read_bytes(), canonical(payload))
        restored = self.base / "recovered"
        shutil.copytree(self.ledger, restored)
        s.record(restored, self.report, 102, 1, SHA, "schedule",
                 unified_report_path=prior)
        self.assertEqual(s.verify(restored)["count"], 2)
        self.assertTrue((restored / s.LEDGER / "reports" / "102-unified.json").exists())
        latest.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            s.verify(self.ledger)

    def test_reject_missing_unified_stages(self):
        bad = self.base / "bad-unified.json"
        bad.write_bytes(canonical({"schema": "SSQDLT_V47_UNIFIED_RUN_V1",
                                   "games": {"ssq": {}, "dlt": {}},
                                   "edge": "NO_EDGE", "formal_prediction": False}))
        with self.assertRaises(ValueError):
            s.record(self.ledger, self.report, 101, 1, SHA, "schedule",
                     unified_report_path=bad)
        self.assertEqual(s.verify(self.ledger)["count"], 0)


    def test_current_report_requires_exactly_five_families(self):
        payload = example_report()
        s.check_report(payload)
        for game in ("ssq", "dlt"):
            payload["games"][game]["models"]["models"].pop("Challenger")
        with self.assertRaises(ValueError):
            s.check_report(payload)
        # Historical archived records remain readable without changing hash receipts.
        s.check_report(payload, allow_legacy_archive=True)



if __name__ == "__main__":
    unittest.main()
