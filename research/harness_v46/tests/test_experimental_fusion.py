"""Fail-closed test contract for EXPERIMENTAL V4.7 fusion (never formal A).

The six registered model identities and immutable NULL are not modified.
Geometry is drawn from actual game-engine isolated subprocesses. Physics
has strictly ZERO influence until real machine parameters are validated.
"""
from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
import unittest
import subprocess
import sys
import tempfile
from pathlib import Path

from research.harness_v46 import core
from research.harness_v46.research_stack import (
    _geometry_subprocess, run_synthetic_stack, synthetic_fixture,
)
from research.harness_v46.experimental_fusion import (
    FUSION_ID, audit_research_candidate, build_research_candidate,
    freeze_research_candidate, score_frozen_research_candidate,
)


class ExperimentalFusionTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(core.MODELS, (
            "hot60", "ewma", "shrinkmix", "pairwise_d2", "challenger",
            "random_null",
        ))

    def test_two_game_fusion_ranks_legal_tickets_with_real_original_geometry(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                snapshot = synthetic_fixture(game, seed=314)
                geo = _geometry_subprocess(snapshot, game)
                fused = build_research_candidate(snapshot, geo)
                rules = core.RULES[game]
                self.assertEqual(fused["model"], FUSION_ID)
                self.assertFalse(fused["formal_a_eligible"])
                self.assertFalse(fused["physical_forecast_supported"])
                self.assertEqual(fused["physical_signal_weight"], 0.0)
                self.assertEqual(fused["edge"], "NO_EDGE")
                self.assertEqual(fused["status"], "UNREGISTERED_SYNTHETIC_RESEARCH_ONLY")
                self.assertEqual(fused["primary_d2"], fused["candidates_1_to_5"][:2])
                self.assertEqual(len(fused["ticket"]["front"]), rules["front"])
                self.assertEqual(len(fused["ticket"]["back"]), rules["back"])
                self.assertEqual(fused["ticket"]["front"], sorted(set(fused["ticket"]["front"])))
                self.assertEqual(fused["ticket"]["back"], sorted(set(fused["ticket"]["back"])))
                self.assertEqual(len(fused["ranked_front"]), rules["pool"])
                self.assertEqual(fused["model_families"], ["registered_five_statistical", "two_real_geometry_components"])
                self.assertTrue(audit_research_candidate(snapshot, geo, fused))

    def test_exact_replay_and_no_lookahead_or_certified_calibration(self):
        snap = synthetic_fixture("SSQ", seed=971)
        geo = _geometry_subprocess(snap, "SSQ")
        a = build_research_candidate(snap, geo)
        b = build_research_candidate(snap, geo)
        self.assertEqual(a, b)
        self.assertEqual(a["snapshot_sha256"], core.digest(snap))
        self.assertEqual(a["prospective_calibration"], "NOT_RUN")
        self.assertNotIn("probability_of_winning", a)
        self.assertNotIn("observed_draw_result", a)

    def test_reject_unauthenticated_geometry_or_missing_real_rankings(self):
        snap = synthetic_fixture("DLT", seed=37)
        geo = _geometry_subprocess(snap, "DLT")
        for forged in [
            dict(geo, source_engine="SSQ"),
            dict(geo, real_machine_geometry_observed=True),
            dict(geo, status="OFFICIAL_VERIFIED"),
            dict(geo, geometry_rankings={}),
        ]:
            with self.subTest(forged=str(list(forged.keys()))):
                with self.assertRaises(ValueError):
                    build_research_candidate(snap, forged)
        bad = deepcopy(geo)
        bad["geometry_rankings"]["front"]["geometry_state"] = [1] * 35
        with self.assertRaises(ValueError):
            build_research_candidate(snap, bad)

    def test_physics_diagnostic_cannot_change_fusion_candidate(self):
        snap = synthetic_fixture("SSQ", seed=48)
        geo = _geometry_subprocess(snap, "SSQ")
        candidate = build_research_candidate(snap, geo)
        mutated = dict(geo, physics={"pressure": 999999, "number": 3})
        self.assertEqual(candidate, build_research_candidate(snap, mutated))
        with self.assertRaises(ValueError):
            build_research_candidate(snap, geo, physical_weight=.01)

    def test_combination_search_is_comparison_signal_but_not_real_probability(self):
        snap = synthetic_fixture("DLT", seed=51)
        geo = _geometry_subprocess(snap, "DLT", complete_space=True)
        candidate = build_research_candidate(snap, geo)
        self.assertTrue(candidate["full_space_search_used"])
        self.assertEqual(candidate["full_space_provenance"], "EXISTING_GAME_ENGINE_SYNTHETIC_ONLY")
        self.assertEqual(set(candidate["comparison_fullspace_best"]), {"front", "back"})
        self.assertTrue(audit_research_candidate(snap, geo, candidate))
        with self.assertRaises(ValueError):
            build_research_candidate(snap, dict(geo, complete_space={
                "front": {"best_synthetic_scored_combination": [1, 1]},
            }))

    def test_fusion_receipt_replays_from_immutable_in_memory_bytes(self):
        snap = synthetic_fixture("SSQ", seed=73)
        geo = _geometry_subprocess(snap, "SSQ")
        candidate = build_research_candidate(snap, geo)
        db = sqlite3.connect(":memory:")
        try:
            h = freeze_research_candidate(db, "SYNTHETIC-SINGLE", snap, geo, candidate)
            self.assertEqual(len(h), 64)
            draw = {"lottery": "SSQ", "issue": snap["target_issue"],
                    "front": [1, 2, 3, 4, 5, 6], "back": [1]}
            r = score_frozen_research_candidate(db, "SYNTHETIC-SINGLE", snap, geo, draw)
            self.assertEqual(r["frozen_sha256"], h)
            self.assertIn("D2", r["score"])
            self.assertFalse(r["official_draw_admitted"])
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM synthetic_experimental_forecasts")
            forged = dict(draw, issue="bad")
            with self.assertRaises(core.GateError):
                score_frozen_research_candidate(db, "SYNTHETIC-SINGLE", snap, geo, forged)
        finally:
            db.close()

    def test_fusion_does_not_change_original_forecasts_or_random_null(self):
        snapshot = synthetic_fixture("SSQ", seed=141)
        before = {m: core.forecast(snapshot, m) for m in core.MODELS}
        build_research_candidate(snapshot, _geometry_subprocess(snapshot, "SSQ"))
        after = {m: core.forecast(snapshot, m) for m in core.MODELS}
        self.assertEqual(before, after)

    def test_unified_research_stack_runs_fusion_and_frozen_future_comparison(self):
        report = run_synthetic_stack(seed=17, trials=500, steps=3)
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["edge"], "NO_EDGE")
        for game in ("SSQ", "DLT"):
            row = report["games"][game]
            self.assertEqual(row["research_fusion"]["model"], FUSION_ID)
            self.assertEqual(row["walk_forward"]["experimental_frozen"], 2)
            self.assertEqual(row["walk_forward"]["experimental_scored"], 2)
            self.assertEqual(row["walk_forward"]["frozen_predictions"], 12)
            self.assertEqual(row["walk_forward"]["scores_computed"], 12)
            self.assertEqual(row["walk_forward"]["experimental_against_random_null"]["status"],
                             "TOO_FEW_SYNTHETIC_ISSUES_NO_EDGE_CLAIM")
            self.assertFalse(row["research_fusion"]["physical_forecast_supported"])

    def test_cli_can_write_create_only_research_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fusion-research.json"
            cmd = [
                sys.executable, "-m", "research.harness_v46.research_stack",
                "--synthetic", "--seed", "82", "--trials", "80",
                "--steps", "2", "--report-file", str(out),
            ]
            first = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            self.assertEqual(first.returncode, 0, first.stderr[-600:])
            stored = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(stored, json.loads(first.stdout))
            self.assertEqual(stored["status"], "SYNTHETIC_RESEARCH_ONLY")
            self.assertEqual(stored["formal_A"], 0)
            second = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("BLOCKED", second.stderr)
            self.assertEqual(stored, json.loads(out.read_text(encoding="utf-8")))


        snap = synthetic_fixture("SSQ", seed=81)
        geo = _geometry_subprocess(snap, "SSQ")
        snap["provenance"]["status"] = "OFFICIAL_VERIFIED"
        with self.assertRaisesRegex(ValueError, "SYNTHETIC"):
            build_research_candidate(snap, geo)


if __name__ == "__main__":
    unittest.main()
