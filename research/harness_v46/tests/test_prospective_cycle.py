"""Prospective two-game SHADOW workflow regression: synthetic fixtures only."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from research.harness_v46 import core
from research.harness_v46 import schedule
from research.harness_v46 import prospective_cycle as cycle
from research.harness_v46.tests.test_core import fixture


class ProspectiveCycleTests(unittest.TestCase):
    def setUp(self):
        self.snaps = {g: fixture(g) for g in ("SSQ", "DLT")}
        self.before = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
        # Tuesday: must not be the old Mon/Wed/Sat JST delivery window.
        self.assertFalse(schedule.due_in_jst(self.before))

    def _results(self):
        return {
            game: {
                "lottery": game, "issue": str(snapshot["target_issue"]),
                "front": list(snapshot["draws"][-2]["front"]),
                "back": list(snapshot["draws"][-2]["back"]),
            }
            for game, snapshot in self.snaps.items()
        }

    def test_manual_run_delivers_exact_frozen_model_numbers_before_cutoff(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "freeze.sqlite3"
            report = cycle.forecast_on_demand(self.snaps, path, now=self.before)
            self.assertEqual(report["schema"], "V47-PROSPECTIVE-SHADOW-FORECAST-1")
            self.assertEqual(report["forecast_source"], "PINNED_IMMUTABLE_LEDGER_ONLY")
            self.assertEqual(report["formal_A"], 0)
            self.assertEqual(report["decision"], "NO_EDGE")
            self.assertEqual(report["freeze_receipt"]["external_tsa"], "NOT_VERIFIED")
            for game in ("SSQ", "DLT"):
                data = report["games"][game]
                self.assertEqual(data["target_issue"], "29999")
                self.assertEqual([x["model"] for x in data["models"]], list(core.MODELS))
                for item in data["models"]:
                    expected = core.forecast(self.snaps[game], item["model"])
                    self.assertEqual(item["primary_d2"], expected["primary_d2"])
                    self.assertEqual(item["candidates_1_to_5"], expected["candidates_1_to_5"])
                    self.assertEqual(item["ticket"], expected["ticket"])
                    self.assertEqual(item["frozen_at_local_untrusted"], self.before.isoformat())
            self.assertEqual(report["games"]["SSQ"]["models"][0]["evidence_class"], "SHADOW")
            self.assertEqual(report["games"]["DLT"]["models"][-1]["model"], "random_null")

    def test_show_and_score_are_readonly_and_repeatable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            output = cycle.forecast_on_demand(self.snaps, path, now=self.before)
            run_id = output["run_id"]
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            first = cycle.frozen_forecast_report(path, run_id)
            second = cycle.frozen_forecast_report(path, run_id)
            self.assertEqual(first, second)
            results = self._results()
            scored = cycle.evaluate_after_draw(path, run_id, results)
            self.assertEqual(scored["outcome_source"], "CALLER_UNVERIFIED")
            self.assertEqual(scored["paired_control"], "SAME_DRAW_RANDOM_NULL")
            self.assertEqual(scored["formal_A"], 0)
            self.assertEqual(scored["decision"], "NO_EDGE")
            self.assertEqual(scored["improvement_policy"],
                             "NEXT_VERSION_ONLY_NEVER_REWRITE_FROZEN_HISTORY")
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            for game in ("SSQ", "DLT"):
                rows = scored["games"][game]["scores"]
                self.assertEqual(set(rows), set(core.MODELS))
                self.assertTrue(all(x["D2"] in (0, 1) for x in rows.values()))
                self.assertEqual(
                    scored["frozen_forecast_reference"][game]["prediction_batch_sha256"],
                    output["games"][game]["prediction_batch_sha256"],
                )
                for model in core.MODELS[:-1]:
                    self.assertEqual(
                        scored["games"][game]["same_draw_d2_delta_vs_null"][model],
                        rows[model]["D2"] - rows["random_null"]["D2"],
                    )

    def test_score_receipt_binds_caller_inputs_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            run_id = cycle.forecast_on_demand(self.snaps, path, now=self.before)["run_id"]
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            observed = self._results()
            scored = cycle.evaluate_after_draw(path, run_id, observed)
            self.assertEqual(scored["scoring_inputs"]["result_bundle"], observed)
            self.assertEqual(
                scored["scoring_inputs"]["result_bundle_sha256"], core.digest(observed)
            )
            self.assertEqual(
                scored["score_receipt_sha256"],
                core.digest({k: v for k, v in scored.items() if k != "score_receipt_sha256"}),
            )
            self.assertEqual(scored, cycle.evaluate_after_draw(path, run_id, observed))
            changed = json.loads(json.dumps(observed))
            front = changed["SSQ"]["front"]
            replacement = next(n for n in range(1, 34) if n not in front)
            changed["SSQ"]["front"] = sorted([replacement] + front[1:])
            changed_report = cycle.evaluate_after_draw(path, run_id, changed)
            self.assertNotEqual(
                changed_report["scoring_inputs"]["result_bundle_sha256"],
                scored["scoring_inputs"]["result_bundle_sha256"],
            )
            self.assertNotEqual(
                changed_report["score_receipt_sha256"], scored["score_receipt_sha256"]
            )
            self.assertEqual(scored["outcome_source"], "CALLER_UNVERIFIED")
            self.assertEqual(scored["formal_A"], 0)
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_invalid_draw_balls_cannot_produce_receipt_or_modify_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            run_id = cycle.forecast_on_demand(self.snaps, path, now=self.before)["run_id"]
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            invalid = self._results()
            invalid["DLT"]["front"][0] = invalid["DLT"]["front"][1]
            with self.assertRaisesRegex(core.GateError, "invalid or noncanonical"):
                cycle.evaluate_after_draw(path, run_id, invalid)
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_wrong_draw_target_does_not_overwrite_original_forecasts(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            run_id = cycle.forecast_on_demand(self.snaps, path, now=self.before)["run_id"]
            original = hashlib.sha256(path.read_bytes()).hexdigest()
            wrong = self._results()
            wrong["DLT"]["issue"] = "30000"
            with self.assertRaisesRegex(core.GateError, "RESULT_ISSUE_DIFFERS"):
                cycle.evaluate_after_draw(path, run_id, wrong)
            self.assertEqual(original, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_partial_or_swapped_draw_results_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            run_id = cycle.forecast_on_demand(self.snaps, path, now=self.before)["run_id"]
            results = self._results()
            with self.assertRaisesRegex(core.GateError, "EXACTLY_TWO_GAME"):
                cycle.evaluate_after_draw(path, run_id, {"SSQ": results["SSQ"]})
            swapped = self._results()
            swapped["SSQ"]["lottery"] = "DLT"
            with self.assertRaisesRegex(core.GateError, "DRAW_RESULT_GAME"):
                cycle.evaluate_after_draw(path, run_id, swapped)

    def test_local_clock_after_cutoff_does_not_create_any_run(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            cutoff = datetime.fromisoformat(self.snaps["SSQ"]["sales_cutoff"])
            with self.assertRaisesRegex(core.GateError, "NO_RETROACTIVE"):
                cycle.forecast_on_demand(self.snaps, path, now=cutoff)
            self.assertFalse(path.exists())

    def test_old_scheduled_window_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            result = schedule.scheduled_once(self.snaps, path, now=self.before)
            self.assertEqual(result["status"], "WAIT_NOT_DELIVERY_WINDOW")
            self.assertFalse(path.exists())

    def test_changed_snapshot_cannot_reissue_same_game_target(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            cycle.forecast_on_demand(self.snaps, path, now=self.before)
            changed = {g: dict(s) for g, s in self.snaps.items()}
            changed["SSQ"]["provenance"] = {"status": "ALTERED_AFTER_FREEZE"}
            with self.assertRaisesRegex(core.GateError, "TARGET_ALREADY_FROZEN"):
                cycle.forecast_on_demand(
                    changed, path, now=self.before + timedelta(minutes=1)
                )
            con = sqlite3.connect(path)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 12)
            con.close()

    def test_missing_model_blocks_show_and_score(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            report = cycle.forecast_on_demand(self.snaps, path, now=self.before)
            con = sqlite3.connect(path)
            # Any external mutation attempt that removes a slot is either blocked
            # by the ledger immutability triggers or detected by read-only replay.
            with self.assertRaises(sqlite3.DatabaseError):
                con.execute(
                    "DELETE FROM predictions WHERE run_id=? AND lottery='SSQ' AND model='hot60'",
                    (report["run_id"],),
                )
            con.rollback()
            con.close()
            cards = cycle.frozen_forecast_report(path, report["run_id"])
            self.assertEqual(len(cards["games"]["SSQ"]["models"]), 6)

    def test_missing_or_non_v47_run_never_generates_new_predictions(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            with self.assertRaisesRegex(core.GateError, "DUAL_GAME_V47"):
                cycle.frozen_forecast_report(path, "manual-cherry-picked-run")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
