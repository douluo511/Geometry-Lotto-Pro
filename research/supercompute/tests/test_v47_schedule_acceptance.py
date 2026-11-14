"""Reject fake schedule receipts and enforce remote real-run P0 gates."""
import copy
import unittest

from research.supercompute.v47_schedule_acceptance import (
    WORKFLOW_PATH, assess, check_genuine_event,
)


class P0ActualRunEvidenceTests(unittest.TestCase):
    def event(self, run_id=111111, *, generated=False, scored=False,
              inherited=False):
        return {
            "run_id": run_id, "run_attempt": 1, "event": "schedule",
            "branch": "main", "code_sha": "b" * 40,
            "hedge44_generated": [
                {"game": g, "count": 22,
                 "previous_champion_inherited": inherited}
                for g in ("ssq", "dlt")] if generated else [],
            "hedge44_scored": [
                {"game": g, "count": 22}
                for g in ("ssq", "dlt")] if scored else [],
        }

    def api(self, run_id, *, event="schedule", status="completed",
            conclusion="success"):
        return {
            "id": run_id, "run_attempt": 1, "event": event,
            "path": WORKFLOW_PATH, "head_branch": "main",
            "head_sha": "b"*40, "status": status, "conclusion": conclusion,
        }

    def test_require_two_actual_successful_schedules_and_both_scored(self):
        first = self.event(111111, generated=True)
        second = self.event(222222, generated=True, inherited=True, scored=True)
        actual = {111111: self.api(111111), 222222: self.api(222222)}
        result = assess([first, second], lambda run_id: actual[run_id])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["confirmed_count"], 2)
        self.assertEqual(result["confirmed_schedule_run_ids"], [111111, 222222])
        self.assertTrue(all(result["requirements"].values()))
        self.assertEqual(result["windows_host_reboot_test"], "UNVERIFIED")
        self.assertFalse(result["trusted_external_predraw_seal"])

    def test_pr_manual_or_running_github_event_does_not_count(self):
        first = self.event(111111, generated=True)
        other = self.event(222222, generated=True, inherited=True, scored=True)
        for override in (
            self.api(222222, event="workflow_dispatch"),
            self.api(222222, event="pull_request"),
            self.api(222222, status="in_progress", conclusion=None),
            self.api(222222, status="completed", conclusion="failure"),
            {**self.api(222222), "head_branch": "unrelated"},
            {**self.api(222222), "head_sha": "c" * 40},
            {**self.api(222222), "path": ".github/workflows/other.yml"},
            {**self.api(222222), "run_attempt": 2},
        ):
            result = assess([first, other], lambda run_id: (
                self.api(111111) if run_id == 111111 else override))
            self.assertEqual(result["status"], "PENDING", override)
            self.assertLess(result["confirmed_count"], 2)

    def test_count_not_just_two_schedules_requires_frozen_inherited_and_score(self):
        a, b = self.event(111111), self.event(222222)
        api = lambda run_id: self.api(run_id)
        result = assess([a, b], api)
        self.assertEqual(result["confirmed_count"], 2)
        self.assertEqual(result["status"], "PENDING")
        self.assertFalse(result["requirements"][
            "two_games_22_each_frozen_in_genuine_schedule"])
        b["hedge44_generated"] = [
            {"game": "ssq", "count": 22, "previous_champion_inherited": True}]
        b["hedge44_scored"] = [{"game": "dlt", "count": 22}]
        result = assess([a, b], api)
        self.assertEqual(result["status"], "PENDING")

    def test_no_branch_is_pending_no_ledger_and_api_unavailable_not_pass(self):
        result = assess([], lambda rid: self.api(rid))
        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(result["confirmed_count"], 0)
        original = self.event()
        result = assess([original], lambda rid: (
            (_ for _ in ()).throw(TimeoutError("network unavailable"))))
        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(len(result["api_unverified_or_rejected"]), 1)

    def test_invalid_local_claim_cannot_become_real_schedule(self):
        event = self.event()
        for change in (
            {"event": "workflow_dispatch"}, {"branch": "staging"},
            {"run_attempt": 0},
        ):
            alt = copy.deepcopy(event)
            alt.update(change)
            with self.assertRaises(ValueError):
                check_genuine_event(alt, self.api(event["run_id"]))


if __name__ == "__main__":
    unittest.main()
