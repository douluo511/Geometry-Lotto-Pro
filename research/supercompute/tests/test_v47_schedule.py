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
                                     "models": {"RANDOM_NULL": {"n": 2}}}}
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


if __name__ == "__main__":
    unittest.main()
