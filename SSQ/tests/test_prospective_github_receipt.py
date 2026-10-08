"""Offline red-team tests for SSQ read-only server-backed prospective receipt.

Fake GitHub responses below test CONTRACT ONLY. They never count as
independently fetched real pre-draw evidence or production qualification.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from glp.prospective_github_receipt import verify_github_freeze_receipt
from glp.util import sha256_json


ISSUE = "2026100"
GIT_SHA = "a" * 40
REPO = "douluo511/Geometry-Lotto-Pro"
BRANCH = "evidence/ssq-prospective-freezes"
PATH = f"SSQ/prospective_ledger/freezes/{ISSUE}.json"
WORKFLOW = ".github/workflows/ssq-prospective-freeze.yml@refs/heads/" + BRANCH


def fixture():
    prediction = {
        "target_issue": ISSUE, "target_date": "2026-10-11",
        "created_at": "2026-09-30T10:00:00Z",
        "canonical_hash": "1" * 64,
        "score_hash": "2" * 64,
        "model_hash": "3" * 64,
        "selector_hash": "4" * 64,
        "edge_state": "NO_EDGE", "dan_state": "NULL_DAN",
        "front_ranking": {"numbers": list(range(1, 34))},
        "back_ranking": {"numbers": list(range(1, 17))},
        "front": list(range(1, 7)), "back": [1],
    }
    prediction["prediction_id"] = sha256_json({
        "score_hash": prediction["score_hash"],
        "created_for": ISSUE,
    })[:32]
    core = {
        "prediction_id": prediction["prediction_id"],
        "target_issue": prediction["target_issue"],
        "target_date": prediction["target_date"],
        "canonical_hash": prediction["canonical_hash"],
        "model_hash": prediction["model_hash"],
        "selector_hash": prediction["selector_hash"],
        "score_hash": prediction["score_hash"],
        "edge_state": "NO_EDGE", "dan_state": "NULL_DAN",
    }
    prediction["freeze_hash"] = sha256_json(core)
    return {
        "schema": "ssq-prospective-freeze-v1",
        "model_source_commit": "b" * 40,
        "prediction": prediction,
        "claimed_provenance_verified": True,  # attacker controlled, always ignored
    }


class FakeGitHub:
    def __init__(self, freeze=None):
        self.freeze = fixture() if freeze is None else freeze
        self.run = {
            "id": 1234,
            "repository": {"full_name": REPO},
            "event": "push",
            "head_branch": BRANCH,
            "path": WORKFLOW,
            "status": "completed",
            "conclusion": "success",
            "head_sha": GIT_SHA,
            "created_at": "2026-10-01T10:00:00Z",
        }
        self.file_override = None
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if url == f"https://api.github.com/repos/{REPO}/actions/runs/1234":
            body = self.run
        elif url == f"https://api.github.com/repos/{REPO}/contents/{PATH}?ref={GIT_SHA}":
            raw = json.dumps(self.freeze, ensure_ascii=False, sort_keys=True).encode("utf-8")
            sha = hashlib.sha1(
                b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
            ).hexdigest()
            body = self.file_override if self.file_override is not None else {
                "type": "file",
                "path": PATH,
                "encoding": "base64",
                "content": base64.b64encode(raw).decode("ascii"),
                "sha": sha, "size": len(raw),
            }
        else:
            raise AssertionError("unapproved Github API endpoint: " + url)
        return SimpleNamespace(content=json.dumps(body).encode("utf-8"), url=url)


class ReadOnlyGitHubReceiptTests(unittest.TestCase):
    def test_immutable_sha_and_github_server_time_are_checked_but_cannot_promote(self):
        remote = FakeGitHub()
        result = verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)
        self.assertEqual(result["verified_scope"], "PRE_DRAW_EXISTENCE_CANDIDATE_ONLY")
        self.assertEqual(result["qualified_count"], 0)
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["official_outcome_verified"])
        self.assertEqual(result["production_rho"], 0.0)
        self.assertEqual(len(remote.requests), 2)
        self.assertTrue(all(call["allow_redirects"] is False for _, call in remote.requests))

    def test_unapproved_branch_or_dispatch_or_repository_fails_closed(self):
        for key, value in (
            ("head_branch", "research/not-ledger"),
            ("event", "workflow_dispatch"),
            ("path", "other-workflow"),
            ("repository", {"full_name": "attacker/Geometry-Lotto-Pro"}),
            ("head_sha", "a" * 39),
        ):
            with self.subTest(key=key):
                remote = FakeGitHub()
                remote.run[key] = value
                with self.assertRaisesRegex(ValueError, "authorized|immutable"):
                    verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_github_run_created_after_target_china_draw_day_is_rejected(self):
        remote = FakeGitHub()
        remote.run["created_at"] = "2026-10-10T16:01:00Z"
        with self.assertRaisesRegex(ValueError, "after draw-day cutoff"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_edited_freeze_json_with_unmodified_github_blob_sha_is_rejected(self):
        remote = FakeGitHub()
        raw = json.dumps(remote.freeze, sort_keys=True).encode("utf-8")
        forged = copy.deepcopy(remote.freeze)
        forged["prediction"]["front"] = [3, 4, 5, 6, 7, 8]
        fake = json.dumps(forged, sort_keys=True).encode("utf-8")
        honest_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        remote.file_override = {
            "type": "file", "path": PATH, "encoding": "base64",
            "content": base64.b64encode(fake).decode("ascii"),
            "sha": honest_sha, "size": len(fake),
        }
        with self.assertRaisesRegex(ValueError, "blob content SHA"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_even_consistently_rehashed_invalid_numbers_cannot_pass(self):
        remote = FakeGitHub()
        remote.freeze["prediction"]["front_ranking"]["numbers"] = list(range(2, 35))
        with self.assertRaisesRegex(ValueError, "ranking permutation"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_false_date_and_backdated_prediction_timestamp_fail(self):
        remote = FakeGitHub()
        remote.freeze["prediction"]["created_at"] = "2026-10-06T10:00:00Z"
        with self.assertRaisesRegex(ValueError, "after draw-day cutoff"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)
        remote2 = FakeGitHub()
        remote2.freeze["prediction"]["target_date"] = "2026-10-01"
        with self.assertRaisesRegex(ValueError, "after draw-day cutoff"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote2)



class PushOnlyFreezeRedTeamTests(unittest.TestCase):
    def _attempt(self, *, overwrite=False, late=False, changed=""):
        root = Path(self.temp)
        file_path = root / PATH
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(fixture()), encoding="utf-8")
        fake = FakeGitHub()
        fake.run["status"] = "in_progress"
        fake.run["head_sha"] = GIT_SHA
        if late:
            fake.run["created_at"] = "2026-10-11T08:00:00Z"

        from tools import ssq_prospective_push_gate as push

        def command(args, **_kwargs):
            if args[1] == "rev-parse":
                return GIT_SHA + "\n"
            if args[1] == "show":
                return "c" * 40 + "\n"
            if args[1] == "diff-tree":
                return (changed or PATH) + "\n"
            raise AssertionError(f"unexpected git operation: {args}")

        env = {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF_NAME": BRANCH,
            "GITHUB_SHA": GIT_SHA,
            "GITHUB_RUN_ID": "1234",
        }
        with (
            patch.object(push, "ROOT", root),
            patch.object(push, "NetClient", return_value=fake),
            patch.object(push.subprocess, "check_output", side_effect=command),
            patch.object(push.subprocess, "run", return_value=SimpleNamespace(
                returncode=0 if overwrite else 1
            )),
            patch.dict(os.environ, env),
        ):
            return push.main()

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.temp = self.dir.name

    def tearDown(self):
        self.dir.cleanup()

    def test_live_push_contract_candidate_only(self):
        self.assertEqual(self._attempt(), 0)

    def test_existing_freeze_overwrite_rejected(self):
        with self.assertRaisesRegex(ValueError, "overwrites prohibited"):
            self._attempt(overwrite=True)

    def test_bulk_or_unrelated_edit_rejected(self):
        with self.assertRaisesRegex(ValueError, "one issue-specific JSON"):
            self._attempt(changed=PATH + "\nSSQ/SSQ/glp/engine.py")

    def test_push_after_draw_day_rejected(self):
        with self.assertRaisesRegex(ValueError, "after draw-day cutoff"):
            self._attempt(late=True)


if __name__ == "__main__":
    unittest.main()
