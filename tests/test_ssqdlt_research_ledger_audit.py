"""RED -> GREEN: adversarial verification of GitHub research ledger."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from research.ssqdlt_research_ledger_audit import (
    GateError, load_json, scan_ledger, validate_git_append_only,
    verify_actions_ticks, overall_report,
)

RUN_ID = "43071336351"
SHA = "e94a9839582f18cc405b315b381ab8d399a1ab79"
WORKFLOW_ID = 414968846


def write_json(root: Path, relative: str, value: dict) -> Path:
    file = root / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return file


def forecast(game="SSQ", issue=2026130) -> dict:
    if game == "SSQ":
        f, b, pair = [1, 2, 3, 4, 5, 6], [7], [1, 2]
    else:
        f, b, pair = [1, 2, 3, 4, 5], [7, 8], [1, 2]
    payload = {
        "schema": "SSQDLT_ROLLING_RESEARCH_ISSUE_V1",
        "game": game, "target_issue": issue,
        "source_last_issue": issue - 1,
        "prediction": {"front": f, "back": b, "d2_pair": pair},
        "research_null": {
            "front": f, "back": b, "d2_pair": pair,
            "not_formal_v47_null": True,
        },
        "research_only": True,
        "formal_A": 0, "edge": "NO_EDGE",
        "official_sales_cutoff_verified": False,
        "external_predraw_tsa": "NOT_RUN",
        "paid_model_calls": 0,
    }
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
    return payload


def tick(run_id=RUN_ID, event="push") -> dict:
    return {
        "schema": "SSQDLT_ACTIONS_RESEARCH_TICK_V1",
        "github_run_id": run_id, "github_run_attempt": "1",
        "trigger": event, "workflow_source_commit": SHA,
        "pinned_formula_commit": "a" * 40,
        "report": {
            "schema": "SSQDLT_SHADOW_ROLLING_TICK_V1",
            "status": "RESEARCH_ONLY", "formal_A": 0,
            "edge": "NO_EDGE", "paid_model_calls": 0,
            "results": [
                {"game": "SSQ", "status": "NO_NEW_ISSUE_ALREADY_RECORDED",
                 "formal_A": 0, "edge": "NO_EDGE"},
                {"game": "DLT", "status": "BLOCKED",
                 "formal_A": 0, "edge": "NO_EDGE"},
            ],
        },
    }


def fake_api(run_id=RUN_ID, event="push", *, sha=SHA, conclusion="success",
             status="completed", attempt=1):
    return {
        "id": int(run_id), "workflow_id": WORKFLOW_ID,
        "event": event, "head_branch": "main", "head_sha": sha,
        "run_attempt": attempt, "status": status,
        "conclusion": conclusion,
        "html_url": ("https://github.com/douluo511/Geometry-Lotto-Pro/"
                     "actions/runs/" + run_id),
        "repository": {"full_name": "douluo511/Geometry-Lotto-Pro"},
    }


class LedgerAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_json(self.root, "research/forecasts/SSQ-2026130.json", forecast())
        write_json(self.root, "research/ticks/" + RUN_ID + ".json", tick())

    def test_clean_unscored_research_is_not_scored_as_zero_percent(self):
        result = scan_ledger(self.root)
        self.assertEqual(result["forecast_count"], 1)
        self.assertEqual(result["score_count"], 0)
        self.assertEqual(result["scoreboard"]["SSQ"]["n"], 0)
        self.assertIsNone(result["scoreboard"]["SSQ"]["full_rate"])
        self.assertIsNone(result["scoreboard"]["SSQ"]["d2_rate"])
        self.assertEqual(result["unscored_targets"], {"SSQ": 1, "DLT": 0})
        self.assertEqual(result["tick_count"], 1)

    def test_formal_promotion_and_noncanonical_ball_ticket_fail_closed(self):
        target = self.root / "research/forecasts/SSQ-2026130.json"
        doc = load_json(target)
        doc["formal_A"] = 1
        write_json(self.root, "research/forecasts/SSQ-2026130.json", doc)
        with self.assertRaisesRegex(GateError, "FORMAL"):
            scan_ledger(self.root)
        doc = forecast()
        doc["prediction"]["front"] = [1, 2, 2, 4, 5, 6]
        write_json(self.root, "research/forecasts/SSQ-2026130.json", doc)
        with self.assertRaises(GateError):
            scan_ledger(self.root)

    def test_json_duplicate_keys_and_nan_fail_closed(self):
        target = self.root / "research/forecasts/SSQ-2026130.json"
        for raw in ('{"formal_A":0,"formal_A":1}', '{"x":NaN}',
                    '{"x":Infinity}', '[]'):
            target.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(GateError):
                load_json(target)

    def test_prediction_contents_cannot_be_rehashed_silently(self):
        target = self.root / "research/forecasts/SSQ-2026130.json"
        data = load_json(target)
        data["prediction"]["front"] = [1, 2, 3, 4, 5, 7]
        write_json(self.root, "research/forecasts/SSQ-2026130.json", data)
        with self.assertRaisesRegex(GateError, "HASH"):
            scan_ledger(self.root)

    def test_duplicate_game_issue_in_other_file_is_rejected(self):
        write_json(self.root, "research/forecasts/duplicate.json", forecast())
        with self.assertRaises(GateError):
            scan_ledger(self.root)

    def test_raw_source_bytes_must_match_original_path(self):
        raw = b"<html>raw source \\r\\n</html>"
        h = hashlib.sha256(raw).hexdigest()
        path = ("research/raw/SSQ/issuer-primary/" + h + ".json")
        write_json(self.root, path, {
            "schema": "SSQDLT_SOURCE_RAW_BYTES_V1",
            "game": "SSQ", "source_id": "issuer-primary",
            "claimed_url": "https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous",
            "raw_sha256": h, "size_bytes": len(raw),
            "raw_base64": base64.b64encode(raw).decode(),
            "origin_authenticity": "NOT_INDEPENDENTLY_PROVEN",
        })
        self.assertEqual(scan_ledger(self.root)["raw_count"], 1)
        value = load_json(self.root / path)
        value["raw_base64"] = base64.b64encode(b"tamper").decode()
        write_json(self.root, path, value)
        with self.assertRaisesRegex(GateError, "RAW"):
            scan_ledger(self.root)

    def test_an_orphan_or_false_outcome_score_cannot_be_counted(self):
        score = {
            "schema": "SSQDLT_RESEARCH_SCORE_V1",
            "game": "SSQ", "issue": 2026130, "formal_A": 0, "edge": "NO_EDGE",
            "original_prediction_ledger_record": "f" * 64,
            "scoring": {
                "research_full_hit": 1, "research_d2_hit": 1,
                "research_null_full_hit": 0, "research_null_d2_hit": 0,
            },
        }
        write_json(self.root, "research/scores/SSQ-2026130.json", score)
        with self.assertRaisesRegex(GateError, "FORECAST"):
            scan_ledger(self.root)

    def test_actions_api_distinguishes_push_and_actual_schedule(self):
        current = tick()
        result = verify_actions_ticks(
            [current], lambda rid: fake_api(rid))
        self.assertEqual(result["verified_push_runs"], 1)
        self.assertEqual(result["verified_schedule_runs"], 0)
        self.assertEqual(result["schedule_two_trigger_gate"], "UNVERIFIED")
        a = tick("123456", "schedule")
        b = tick("234567", "schedule")
        controls = {"123456": fake_api("123456", "schedule"),
                    "234567": fake_api("234567", "schedule")}
        confirmed = verify_actions_ticks(
            [a, b], lambda rid: controls[rid])
        self.assertEqual(confirmed["schedule_two_trigger_gate"], "PASS")
        self.assertEqual(confirmed["verified_schedule_runs"], 2)

    def test_actions_api_rejects_forged_workflow_identity_or_unauthenticated_run(self):
        with self.assertRaisesRegex(GateError, "EVENT"):
            verify_actions_ticks([tick()], lambda rid: fake_api(rid, "schedule"))
        with self.assertRaisesRegex(GateError, "SHA"):
            verify_actions_ticks([tick()], lambda rid: fake_api(rid, sha="f"*40))
        with self.assertRaisesRegex(GateError, "NOT_SUCCESS"):
            verify_actions_ticks([tick()], lambda rid: fake_api(
                rid, conclusion="failure"))
        with self.assertRaisesRegex(GateError, "NOT_SUCCESS"):
            verify_actions_ticks([tick()], lambda rid: fake_api(
                rid, status="in_progress", conclusion=None))
        with self.assertRaisesRegex(GateError, "WORKFLOW"):
            verify_actions_ticks([tick()], lambda rid: {
                **fake_api(rid), "workflow_id": 0})

    def test_local_clean_ledger_without_actions_remains_unverified(self):
        receipt = overall_report(self.root, fetcher=None, verify_git=False)
        self.assertEqual(receipt["ledger_integrity"], "PASS")
        self.assertEqual(receipt["actions_api"], "UNVERIFIED")
        self.assertEqual(receipt["schedule_two_trigger_gate"], "UNVERIFIED")
        self.assertEqual(receipt["engineering_pass"], "NOT_YET")
        self.assertEqual(receipt["formal_A"], 0)
        self.assertEqual(receipt["edge"], "NO_EDGE")


class GitHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        def git(*args):
            subprocess.run(["git", "-C", str(self.repo), *args],
                           check=True, capture_output=True)
        self.git = git
        git("init", "-q")
        git("config", "user.email", "ci@example.invalid")
        git("config", "user.name", "CI")
        write_json(self.repo, "research/forecasts/SSQ-2026130.json", forecast())
        git("add", "research")
        git("commit", "-qm", "first immutable forecast")

    def test_actual_git_commit_history_confirms_once_only_creation(self):
        r = validate_git_append_only(self.repo)
        self.assertEqual(r["appended_files"], 1)
        self.assertEqual(r["non_add_commits"], 0)

    def test_modifying_original_then_committing_is_detected_even_if_rehashed(self):
        original = self.repo / "research/forecasts/SSQ-2026130.json"
        altered = load_json(original)
        altered["prediction"]["front"] = [1, 2, 3, 4, 5, 7]
        altered["content_sha256"] = hashlib.sha256(
            json.dumps({k:v for k,v in altered.items() if k!="content_sha256"},
                       ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode()).hexdigest()
        write_json(self.repo, "research/forecasts/SSQ-2026130.json", altered)
        self.git("add", "research")
        self.git("commit", "-qm", "fraudulent changed historical forecast")
        self.assertEqual(scan_ledger(self.repo)["forecast_count"], 1)
        with self.assertRaisesRegex(GateError, "NON_APPEND"):
            validate_git_append_only(self.repo)

    def test_uncommitted_original_edit_is_detected(self):
        path = self.repo / "research/forecasts/SSQ-2026130.json"
        path.write_text(path.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GateError, "DIRTY"):
            validate_git_append_only(self.repo)


if __name__ == "__main__":
    unittest.main()
