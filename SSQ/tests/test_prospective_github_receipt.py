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
from glp.prospective_github_receipt import verify_github_freeze_receipt, _TRUSTED_SEED_SHA
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
        self.commit = {
            "sha": GIT_SHA,
            "parents": [{"sha": "c" * 40}],
            "files": [{"filename": PATH, "status": "added"}],
        }
        self.compare = {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "base_commit": {"sha": _TRUSTED_SEED_SHA},
            "merge_base_commit": {"sha": _TRUSTED_SEED_SHA},
            "files": [{"filename": PATH, "status": "added"}],
        }
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if url == f"https://api.github.com/repos/{REPO}/actions/runs/1234":
            body = self.run
        elif url == f"https://api.github.com/repos/{REPO}/commits/{GIT_SHA}":
            body = self.commit
        elif url == f"https://api.github.com/repos/{REPO}/compare/{_TRUSTED_SEED_SHA}...{GIT_SHA}":
            body = self.compare
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
        self.assertEqual(len(remote.requests), 4)
        self.assertEqual(result["exact_run_commit_provenance"]["exact_successful_run_commit"], GIT_SHA)
        self.assertEqual(result["exact_run_commit_provenance"]["new_freeze_path"], PATH)
        self.assertTrue(all(call["allow_redirects"] is False for _, call in remote.requests))

    def test_successful_later_run_cannot_launder_earlier_unverified_freeze(self):
        # Cumulative compare is deceptively valid (2 ahead, 2 added files).
        # The current successful push added OTHER; this issue was added in an
        # earlier, potentially unsuccessful push and must not borrow this run.
        remote = FakeGitHub()
        other = "SSQ/prospective_ledger/freezes/2026101.json"
        remote.compare["ahead_by"] = 2
        remote.compare["files"] = [
            {"filename": PATH, "status": "added"},
            {"filename": other, "status": "added"},
        ]
        remote.commit["files"] = [{"filename": other, "status": "added"}]
        with self.assertRaisesRegex(ValueError, "not added by exact successful"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_bulk_add_commit_cannot_be_authenticated_by_aggregate_file_count(self):
        remote = FakeGitHub()
        other = "SSQ/prospective_ledger/freezes/2026101.json"
        remote.compare["ahead_by"] = 2
        remote.compare["files"] = [
            {"filename": PATH, "status": "added"},
            {"filename": other, "status": "added"},
        ]
        remote.commit["files"] = [
            {"filename": PATH, "status": "added"},
            {"filename": other, "status": "added"},
        ]
        with self.assertRaisesRegex(ValueError, "not added by exact successful"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_wrong_or_merge_commit_metadata_cannot_authenticate_receipt(self):
        for mutation in (
            {"sha": "f" * 40},
            {"parents": []},
            {"parents": [{"sha": "c" * 40}, {"sha": "d" * 40}]},
            {"parents": [{"sha": "not-a-sha"}]},
            {"files": []},
            {"files": [{"filename": PATH, "status": "modified"}]},
            {"files": [{"filename": PATH, "status": "renamed"}]},
        ):
            with self.subTest(mutation=mutation):
                remote = FakeGitHub()
                remote.commit.update(mutation)
                with self.assertRaisesRegex(ValueError, "not added by exact successful"):
                    verify_github_freeze_receipt(
                        run_id=1234, target_issue=ISSUE, client=remote,
                    )

    def test_modified_workflow_or_source_in_prior_branch_commit_fails(self):
        remote = FakeGitHub()
        remote.compare["files"] = [
            {"filename": PATH, "status": "added"},
            {"filename": ".github/workflows/ssq-prospective-freeze.yml", "status": "modified"},
        ]
        remote.compare["ahead_by"] = 2
        with self.assertRaisesRegex(ValueError, "untrusted source/workflow edit"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_malicious_workflow_tamper_then_revert_cannot_hide_extra_commits(self):
        remote = FakeGitHub()
        remote.compare["ahead_by"] = 3
        with self.assertRaisesRegex(ValueError, "not append-only"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_force_rebased_branch_no_longer_descends_from_audited_seed(self):
        remote = FakeGitHub()
        remote.compare["merge_base_commit"]["sha"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "not append-only"):
            verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

    def test_duplicate_same_issue_path_and_renamed_freeze_rejected(self):
        for entry in (
            {"filename": PATH, "status": "renamed"},
            {"filename": "SSQ/prospective_ledger/freezes/2026100.json.bak", "status": "added"},
        ):
            with self.subTest(entry=entry):
                remote = FakeGitHub()
                remote.compare["files"] = [entry]
                with self.assertRaisesRegex(ValueError, "untrusted source/workflow edit"):
                    verify_github_freeze_receipt(run_id=1234, target_issue=ISSUE, client=remote)

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
    def _attempt(self, *, overwrite=False, late=False, changed="", before=None,
                 after=None, forced=False):
        root = Path(self.temp)
        file_path = root / PATH
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(fixture()), encoding="utf-8")
        event_path = root / "github_push_event.json"
        event_path.write_text(json.dumps({
            "before": "c" * 40 if before is None else before,
            "after": GIT_SHA if after is None else after,
            "forced": forced, "created": False, "deleted": False,
        }), encoding="utf-8")
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
            "GITHUB_EVENT_PATH": str(event_path),
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

    def test_multi_commit_push_cannot_launder_unchecked_earlier_freezes(self):
        # Existing check inspects HEAD only: a multi-commit push could hide
        # an earlier Freeze mutation and still look like a one-file HEAD.
        with self.assertRaisesRegex(ValueError, "single-commit"):
            self._attempt(before="d" * 40)

    def test_force_updated_evidence_branch_cannot_qualify_as_witness(self):
        with self.assertRaisesRegex(ValueError, "forced|force"):
            self._attempt(forced=True)

    def test_push_webhook_after_must_match_checked_out_exact_head(self):
        with self.assertRaisesRegex(ValueError, "after|exact head"):
            self._attempt(after="e" * 40)


if __name__ == "__main__":
    unittest.main()
