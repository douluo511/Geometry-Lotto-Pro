"""P0 remote Actions verification never mistakes a mock ledger for scheduled evidence."""
import json
import tempfile
import unittest
from pathlib import Path

from research.supercompute.automation.acceptance import assess, selected_receipts
from research.supercompute.automation.runner import REL, record, verify

SHA = "a" * 40


def environment(run_id, trigger="schedule"):
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "douluo511/Geometry-Lotto-Pro",
        "GITHUB_EVENT_NAME": trigger,
        "GITHUB_RUN_ID": str(run_id),
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": SHA,
    }


def github_run(run_id, event="schedule", *,
               status="completed", conclusion="success"):
    return {
        "id": int(run_id),
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "head_branch": "main",
        "head_sha": SHA,
        "workflow_id": 414851175,
        "path": ".github/workflows/ssqdlt-p0-scheduler.yml",
        "run_attempt": 1,
    }


class RemoteAcceptanceTests(unittest.TestCase):
    def snapshots(self, actions):
        root = tempfile.TemporaryDirectory()
        path = Path(root.name)
        for run_id, trigger in actions:
            record(path, environment(run_id, trigger))
        state = verify(path)
        receipts = selected_receipts(path, state, max_scheduled=6)
        return root, path, state, receipts

    def test_two_real_remote_confirmed_schedules_with_recovery_pass(self):
        temp, root, state, receipts = self.snapshots([
            (101, "schedule"), (102, "schedule"),
        ])
        try:
            report = assess(state, receipts, {
                "101": github_run(101), "102": github_run(102),
            })
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["confirmed_scheduled_completed"], 2)
            self.assertTrue(report["remote_restore_observed"])
            self.assertEqual(report["latest_recorded_run_id"], "102")
            self.assertEqual(report["provider"], "GITHUB_ACTIONS")
            self.assertFalse(report["prospective_lottery_cycle_verified"])
        finally:
            temp.cleanup()

    def test_inprogress_second_schedule_is_not_completed_pass(self):
        temp, _, state, receipts = self.snapshots([
            (101, "schedule"), (102, "schedule"),
        ])
        try:
            report = assess(state, receipts, {
                "101": github_run(101),
                "102": github_run(102, status="in_progress", conclusion=None),
            })
            self.assertEqual(report["status"], "UNVERIFIED")
            self.assertEqual(report["confirmed_scheduled_completed"], 1)
        finally:
            temp.cleanup()

    def test_manual_dispatch_cannot_be_counted_as_schedule(self):
        temp, _, state, receipts = self.snapshots([
            (101, "workflow_dispatch"), (102, "schedule"),
            (103, "workflow_dispatch"),
        ])
        try:
            runs = {
                "101": github_run(101, "workflow_dispatch"),
                "102": github_run(102),
                "103": github_run(103, "workflow_dispatch"),
            }
            report = assess(state, receipts, runs)
            self.assertEqual(report["confirmed_scheduled_completed"], 1)
            self.assertEqual(report["status"], "UNVERIFIED")
        finally:
            temp.cleanup()

    def test_no_self_attested_git_receipt_is_accepted_without_api(self):
        temp, _, state, receipts = self.snapshots([(101, "schedule")])
        try:
            with self.assertRaisesRegex(ValueError, "missing verified Actions"):
                assess(state, receipts, {})
        finally:
            temp.cleanup()

    def test_event_or_workflow_identity_disagreement_fails_closed(self):
        temp, _, state, receipts = self.snapshots([(101, "schedule")])
        try:
            invalid = github_run(101, "push")
            with self.assertRaisesRegex(ValueError, "event mismatch"):
                assess(state, receipts, {"101": invalid})
            invalid = github_run(101)
            invalid["head_sha"] = "b" * 40
            with self.assertRaisesRegex(ValueError, "code identity"):
                assess(state, receipts, {"101": invalid})
            invalid = github_run(101)
            invalid["workflow_id"] = 0
            with self.assertRaisesRegex(ValueError, "workflow identity"):
                assess(state, receipts, {"101": invalid})
        finally:
            temp.cleanup()

    def test_completed_failure_never_counts_as_success(self):
        temp, _, state, receipts = self.snapshots([
            (101, "schedule"), (102, "schedule"),
        ])
        try:
            report = assess(state, receipts, {
                "101": github_run(101, status="completed", conclusion="failure"),
                "102": github_run(102),
            })
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["confirmed_scheduled_completed"], 1)
        finally:
            temp.cleanup()

    def test_tampered_ledger_fails_before_network(self):
        temp, root, state, receipts = self.snapshots([(101, "schedule")])
        try:
            event_path = next((root / REL / "events").glob("*.json"))
            event = json.loads(event_path.read_text())
            event["trigger"] = "workflow_dispatch"
            event_path.write_text(json.dumps(event))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify(root)
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
