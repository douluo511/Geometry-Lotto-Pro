"""Offline P0 contract tests: persistence, idempotency, tamper, restart."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from research.supercompute.automation.runner import REL, record, verify


def env(run_id="101", trigger="schedule"):
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "douluo511/Geometry-Lotto-Pro",
        "GITHUB_EVENT_NAME": trigger,
        "GITHUB_RUN_ID": run_id,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "a" * 40,
    }


class P0LedgerTests(unittest.TestCase):
    def test_write_reopen_and_idempotent_rerun(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = record(root, env())
            self.assertEqual(first["scheduled_observed"], 1)
            self.assertEqual(verify(root, "101")["count"], 1)
            again = record(root, env())
            self.assertEqual(again["action"], "ALREADY_RECORDED")
            self.assertEqual(verify(root)["count"], 1)
            self.assertEqual(len(list((root / REL / "events").glob("*.json"))), 1)

    def test_schedule_distinct_from_manual(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record(root, env("101", "workflow_dispatch"))
            self.assertEqual(verify(root)["scheduled_observed"], 0)
            record(root, env("102"))
            record(root, env("103"))
            result = verify(root, "103")
            self.assertEqual(result["count"], 3)
            self.assertEqual(result["scheduled_observed"], 2)

    def test_restart_after_failed_precommit_uses_remote_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "worktree"
            remote = Path(temp) / "persisted_remote_copy"
            record(root, env("101"))
            shutil.copytree(root, remote)
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                record(root, env("102"), inject_failure=True)
            self.assertEqual(verify(remote)["count"], 1)
            resumed = record(remote, env("102"))
            self.assertEqual(resumed["restored_previous_events"], 1)
            self.assertEqual(verify(remote, "102")["count"], 2)
            self.assertEqual(record(remote, env("102"))["action"], "ALREADY_RECORDED")

    def test_tampered_receipt_aborts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record(root, env())
            file = next((root / REL / "events").glob("*.json"))
            receipt = json.loads(file.read_text())
            receipt["paid_api_calls"] = 1
            file.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify(root)

    def test_orphan_and_unapproved_events_abort(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / REL / "events" / "anything.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "orphaned"):
                verify(root)
        with tempfile.TemporaryDirectory() as temp:
            invalid = env()
            invalid["GITHUB_EVENT_NAME"] = "pull_request"
            with self.assertRaisesRegex(ValueError, "approved trigger"):
                record(Path(temp), invalid)


if __name__ == "__main__":
    unittest.main()
