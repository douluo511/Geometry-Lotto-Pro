from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from pathlib import Path

from glp.constants import (
    BACKGROUND_POLL_SECONDS,
    BACKGROUND_STARTUP_MODE,
    DEFAULT_RESEARCH_DAN_FRONT_COUNT,
    DEFAULT_RESEARCH_DAN_BACK_COUNT,
    PROMOTION_POLICY,
)
from glp.domain import Draw, Prediction
from glp.engine import model_identity
from glp.prospective import (
    BEHAVIOR_PATHS,
    ProspectiveLedger,
    _require_pre_draw_freeze,
    _behavior_hash_from_files,
    run_prospective_cycle,
)
from glp.util import next_draw_date, next_issue, parse_date, sha256_json


# Trigger-path regression: test-only changes must not alter the production behavior fingerprint.
# This second marker exists only to exercise the repaired workflow parser/trigger path.
SOURCE_A = "1" * 40
SOURCE_B = "2" * 40


def _draws(count: int = 245) -> list[Draw]:
    start = date(2026, 1, 1)
    out = []
    for i in range(count):
        d = start + timedelta(days=i)
        front = tuple(sorted((((i * 5 + j * 7) % 35) + 1 for j in range(5))))
        if len(set(front)) != 5:
            front = (1, 8, 15, 22, 29)
        back = tuple(sorted((((i * 3 + j * 5) % 12) + 1 for j in range(2))))
        if len(set(back)) != 2:
            back = (2, 9)
        out.append(
            Draw(
                issue=f"26{i + 1:03d}",
                draw_date=d.isoformat(),
                front=front,
                back=back,
            )
        )
    return out


class FakeBuilder:
    def __init__(self):
        self.calls = 0

    def __call__(self, draws, canonical_hash, _court):
        self.calls += 1
        ident = model_identity()
        target_issue = next_issue(draws[-1].issue, draws[-1].draw_date)
        target_date = next_draw_date(parse_date(draws[-1].draw_date)).isoformat()
        front_ranking = list(range(1, 36))
        back_ranking = list(range(1, 13))
        score_hash = sha256_json(
            {"front": front_ranking, "back": back_ranking, "call": self.calls}
        )
        pred = Prediction(
            prediction_id=sha256_json([canonical_hash, target_issue, self.calls])[:20],
            target_issue=target_issue,
            target_date=target_date,
            created_at="2026-09-03T00:00:00+00:00",
            front=[1, 2, 3, 4, 5],
            back=[1, 2],
            front_ranking=front_ranking,
            back_ranking=back_ranking,
            dan_state="NULL_DAN",
            edge_state="NO_EDGE",
            research_dan_front=[1, 2],
            research_dan_back=[1],
            canonical_hash=canonical_hash,
            model_hash=ident["model_hash"],
            selector_hash=ident["selector_hash"],
            score_hash=score_hash,
            note="test research only",
        )
        return pred, {"test_builder_call": self.calls}


class ProspectiveProtocolTests(unittest.TestCase):
    def setUp(self):
        # Synthetic draws end in early September. The frozen test clock is before
        # their next target; tests never turn old draws into genuine live evidence.
        clock = patch("glp.prospective.utc_now", return_value="2026-09-03T00:00:00Z")
        clock.start()
        self.addCleanup(clock.stop)

    def test_china_civil_day_boundary_is_conservative(self):
        _require_pre_draw_freeze(
            registered_at="2026-09-04T15:59:59Z",
            prediction_created_at="2026-09-04T15:59:58Z",
            target_date="2026-09-05",
        )
        with self.assertRaisesRegex(ValueError, "late/post-draw"):
            _require_pre_draw_freeze(
                registered_at="2026-09-04T16:00:00Z",
                prediction_created_at="2026-09-04T15:59:59Z",
                target_date="2026-09-05",
            )

    def test_prediction_claimed_future_creation_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "after registration"):
            _require_pre_draw_freeze(
                registered_at="2026-09-03T00:00:00Z",
                prediction_created_at="2026-09-03T00:00:01Z",
                target_date="2026-09-05",
            )

    def test_outdated_history_cannot_register_target_already_past(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        with tempfile.TemporaryDirectory() as td:
            with patch("glp.prospective.utc_now", return_value="2026-09-10T00:00:00Z"):
                with self.assertRaisesRegex(ValueError, "late/post-draw"):
                    run_prospective_cycle(
                        draws, canonical, ledger_root=Path(td),
                        source_commit=SOURCE_A, prediction_builder=FakeBuilder(),
                    )

    def test_edited_and_rehashed_late_freeze_cannot_enter_replay(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=FakeBuilder(),
            )
            target = first["freeze"]["target_issue"]
            path = root / "cohorts" / first["cohort"]["cohort_id"] / "freezes" / f"{target}.json"
            row = json.loads(path.read_text(encoding="utf-8"))
            row["registered_at"] = row["target_date"] + "T00:00:00Z"
            row.pop("record_hash")
            row["record_hash"] = sha256_json(row)
            path.write_text(json.dumps(row), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "late/post-draw"):
                ProspectiveLedger(root).freeze_records()

    def test_registered_predictions_require_complete_unique_rankings_and_dan_alignment(self):
        from dataclasses import replace
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        valid, _ = FakeBuilder()(draws, canonical, None)
        cases = (
            ("duplicate_front_ranking", replace(valid, front_ranking=[1, 1] + list(range(3, 36))), "front ranking"),
            ("short_back_ranking", replace(valid, back_ranking=list(range(1, 12))), "back ranking"),
            ("wrong_front_dan", replace(valid, research_dan_front=[4, 5]), "front research dan"),
            ("wrong_back_dan", replace(valid, research_dan_back=[9]), "back research dan"),
            ("invalid_front", replace(valid, front=[1, 1, 3, 4, 5]), "front combination"),
            ("wrong_issue", replace(valid, target_issue="26999"), "target issue/date"),
            ("wrong_date", replace(valid, target_date="2026-09-12"), "target issue/date"),
        )
        for case, prediction, expected in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as td:
                    ledger = ProspectiveLedger(Path(td))
                    with self.assertRaisesRegex(ValueError, expected):
                        ledger.register_freeze(
                            prediction, draws=draws,
                            canonical_hash=canonical, source_commit=SOURCE_A,
                        )

    def test_rehashed_forged_ranking_in_saved_freeze_still_fails(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=FakeBuilder(),
            )
            target = first["freeze"]["target_issue"]
            path = root / "cohorts" / first["cohort"]["cohort_id"] / "freezes" / f"{target}.json"
            row = json.loads(path.read_text(encoding="utf-8"))
            row["prediction"]["front_ranking"] = [1] * 35
            row["record_hash"] = sha256_json({k: v for k, v in row.items() if k != "record_hash"})
            path.write_text(json.dumps(row), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "front ranking"):
                ProspectiveLedger(root).freeze_records()

    def test_rehashed_forged_replay_scores_and_hits_do_not_qualify(self):
        import copy
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=FakeBuilder(),
            )
            target = first["freeze"]["target_issue"]
            actual = Draw(target, first["freeze"]["target_date"], (1, 6, 11, 16, 21), (1, 7))
            more = draws + [actual]
            second = run_prospective_cycle(
                more, sha256_json([d.to_dict() for d in more]),
                ledger_root=root, source_commit=SOURCE_A, prediction_builder=FakeBuilder(),
            )
            self.assertEqual(second["status"]["valid_replays"], 1)
            replay_path = root / "cohorts" / first["cohort"]["cohort_id"] / "replays" / f"{target}.json"
            original = json.loads(replay_path.read_text(encoding="utf-8"))
            for mutation in ("inflated_score", "fake_hits", "wrong_actual"):
                with self.subTest(mutation=mutation):
                    forged = copy.deepcopy(original)
                    if mutation == "inflated_score":
                        forged["front_gain_vs_random"] = 1.0
                    elif mutation == "fake_hits":
                        forged["replay"]["front_hit_count"] += 1
                    else:
                        forged["actual"]["front"] = [2, 7, 12, 17, 22]
                    forged.pop("record_hash")
                    forged["record_hash"] = sha256_json(forged)
                    replay_path.write_text(json.dumps(forged), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "recomputed"):
                        ProspectiveLedger(root).replay_records()
            replay_path.write_text(json.dumps(original), encoding="utf-8")
            self.assertEqual(len(ProspectiveLedger(root).replay_records()), 1)

    def test_service_dependency_is_part_of_behavior_identity(self):
        self.assertIn("src/glp/service.py", BEHAVIOR_PATHS)
        before = _behavior_hash_from_files({
            "src/glp/background.py": "a" * 64,
            "src/glp/service.py": "b" * 64,
        })
        after = _behavior_hash_from_files({
            "src/glp/background.py": "a" * 64,
            "src/glp/service.py": "c" * 64,
        })
        self.assertNotEqual(before, after)

    def test_cohort_is_bound_to_current_103_behavior_baseline(self):
        self.assertEqual(BACKGROUND_POLL_SECONDS, 1800)
        self.assertEqual(BACKGROUND_STARTUP_MODE, "manual_app_launch_required_after_login")
        self.assertEqual(DEFAULT_RESEARCH_DAN_FRONT_COUNT, 2)
        self.assertEqual(DEFAULT_RESEARCH_DAN_BACK_COUNT, 1)
        self.assertEqual(
            PROMOTION_POLICY["research_dan_front_count"],
            DEFAULT_RESEARCH_DAN_FRONT_COUNT,
        )
        self.assertEqual(
            PROMOTION_POLICY["research_dan_back_count"],
            DEFAULT_RESEARCH_DAN_BACK_COUNT,
        )

    def test_same_target_freeze_is_immutable_and_idempotent(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        builder = FakeBuilder()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=builder,
            )
            freeze_path = (
                root / "cohorts" / first["cohort"]["cohort_id"] / "freezes"
                / f"{first['freeze']['target_issue']}.json"
            )
            before = freeze_path.read_bytes()
            second = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=builder,
            )
            after = freeze_path.read_bytes()
            self.assertEqual(before, after)
            self.assertEqual(first["freeze"]["record_hash"], second["freeze"]["record_hash"])
            self.assertEqual(second["status"]["freeze_count"], 1)

    def test_docs_only_source_commit_change_does_not_reset_cohort(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        builder = FakeBuilder()
        same_behavior = "a" * 64
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A,
                behavior_hash_override=same_behavior,
                prediction_builder=builder,
            )
            second = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_B,
                behavior_hash_override=same_behavior,
                prediction_builder=builder,
            )
            self.assertEqual(first["cohort"]["cohort_id"], second["cohort"]["cohort_id"])
            self.assertEqual(first["freeze"]["record_hash"], second["freeze"]["record_hash"])
            self.assertEqual(first["freeze"]["source_commit"], SOURCE_A)
            self.assertEqual(second["freeze"]["source_commit"], SOURCE_A)
            index = __import__("json").loads((root / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index.get("reset_count", 0), 0)
            self.assertEqual(len(index["cohort_history"]), 0)

    def test_behavior_identity_change_resets_to_new_zero_replay_cohort(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        builder = FakeBuilder()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A,
                behavior_hash_override="a" * 64,
                prediction_builder=builder,
            )
            second = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_B,
                behavior_hash_override="b" * 64,
                prediction_builder=builder,
            )
            self.assertNotEqual(first["cohort"]["cohort_id"], second["cohort"]["cohort_id"])
            self.assertEqual(second["status"]["valid_replays"], 0)
            index = __import__("json").loads((root / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["reset_count"], 1)
            self.assertEqual(len(index["cohort_history"]), 1)

    def test_post_draw_registration_is_rejected(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        ident = model_identity()
        latest = draws[-1]
        pred = Prediction(
            prediction_id="late",
            target_issue=latest.issue,
            target_date=latest.draw_date,
            created_at="2026-10-06T00:00:00+00:00",
            front=[1, 2, 3, 4, 5],
            back=[1, 2],
            front_ranking=list(range(1, 36)),
            back_ranking=list(range(1, 13)),
            dan_state="NULL_DAN",
            edge_state="NO_EDGE",
            research_dan_front=[1, 2],
            research_dan_back=[1],
            canonical_hash=canonical,
            model_hash=ident["model_hash"],
            selector_hash=ident["selector_hash"],
            score_hash="a" * 64,
        )
        with tempfile.TemporaryDirectory() as td:
            ledger = ProspectiveLedger(Path(td))
            with self.assertRaisesRegex(ValueError, "late/post-draw"):
                ledger.register_freeze(
                    pred, draws=draws, canonical_hash=canonical, source_commit=SOURCE_A
                )

    def test_future_freeze_replays_only_after_actual_arrives(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        builder = FakeBuilder()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=builder,
            )
            self.assertEqual(first["status"]["valid_replays"], 0)
            target_issue = first["freeze"]["target_issue"]
            target_date = first["freeze"]["target_date"]
            actual = Draw(target_issue, target_date, (1, 6, 11, 16, 21), (1, 7))
            draws2 = draws + [actual]
            canonical2 = sha256_json([d.to_dict() for d in draws2])
            second = run_prospective_cycle(
                draws2, canonical2, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=builder,
            )
            self.assertEqual(second["status"]["valid_replays"], 1)
            self.assertIn(target_issue, second["new_replays"])
            self.assertNotEqual(second["freeze"]["target_issue"], target_issue)

    def test_rehashed_internally_consistent_false_actual_fails_against_official(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=FakeBuilder(),
            )
            target = first["freeze"]["target_issue"]
            target_date = first["freeze"]["target_date"]
            fake = Draw(target, target_date, (2, 7, 12, 17, 22), (2, 8))
            real = Draw(target, target_date, (1, 6, 11, 16, 21), (1, 7))
            ledger = ProspectiveLedger(root)
            ledger.replay_available(draws + [fake])
            # The fake replay is internally self-consistent and SHA-bound:
            # the previous validation would incorrectly count it.
            self.assertEqual(len(ledger.replay_records()), 1)
            with self.assertRaisesRegex(ValueError, "differs from live official canonical"):
                ledger.qualification(official_draws=draws + [real])
            with self.assertRaisesRegex(ValueError, "differs from live official canonical"):
                ledger.status(official_draws=draws + [real])

    def test_30_replay_gate_requires_official_actuals_and_never_self_promotes(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ProspectiveLedger(Path(td))
            ledger.activate(SOURCE_A)
            official = _draws(30)
            positive = [
                {
                    "target_issue": d.issue,
                    "actual": d.to_dict(),
                    "front_gain_vs_random": 0.2,
                    "back_gain_vs_random": 0.2,
                }
                for d in official
            ]
            ledger.replay_records = lambda _cohort=None: positive[:29]
            not_ready = ledger.qualification(official_draws=official)
            self.assertEqual(not_ready["decision"], "NOT_READY")
            self.assertEqual(not_ready["valid_replays"], 29)
            self.assertFalse(not_ready["promotion_authorized"])

            ledger.replay_records = lambda _cohort=None: positive
            no_source = ledger.qualification()
            self.assertEqual(no_source["decision"], "NOT_READY")
            self.assertEqual(no_source["reason"], "OFFICIAL_ACTUALS_NOT_BOUND")
            self.assertEqual(no_source["valid_replays"], 0)
            self.assertEqual(no_source["unverified_replay_files"], 30)

            # Artificial contract inputs exercise the statistical threshold,
            # not real draw performance or a production edge verdict.
            qualified = ledger.qualification(official_draws=official)
            self.assertEqual(qualified["decision"], "PROSPECTIVE_EDGE_CANDIDATE")
            self.assertEqual(qualified["valid_replays"], 30)
            self.assertFalse(qualified["promotion_authorized"])
            self.assertEqual(qualified["production_rho"], 0.0)


if __name__ == "__main__":
    unittest.main()
