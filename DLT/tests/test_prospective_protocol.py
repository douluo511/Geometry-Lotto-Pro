from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from glp.domain import Draw, Prediction
from glp.engine import model_identity
from glp.prospective import ProspectiveLedger, run_prospective_cycle
from glp.util import next_draw_date, next_issue, parse_date, sha256_json


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
            created_at=f"2026-10-06T00:00:{self.calls:02d}+00:00",
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

    def test_identity_change_resets_to_new_zero_replay_cohort(self):
        draws = _draws()
        canonical = sha256_json([d.to_dict() for d in draws])
        builder = FakeBuilder()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_A, prediction_builder=builder,
            )
            second = run_prospective_cycle(
                draws, canonical, ledger_root=root,
                source_commit=SOURCE_B, prediction_builder=builder,
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

    def test_30_replay_gate_is_hard_and_never_self_promotes(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = ProspectiveLedger(Path(td))
            ledger.activate(SOURCE_A)
            positive = {
                "front_gain_vs_random": 0.2,
                "back_gain_vs_random": 0.2,
            }
            ledger.replay_records = lambda _cohort=None: [dict(positive) for _ in range(29)]
            not_ready = ledger.qualification()
            self.assertEqual(not_ready["decision"], "NOT_READY")
            self.assertFalse(not_ready["promotion_authorized"])
            self.assertEqual(not_ready["production_rho"], 0.0)

            ledger.replay_records = lambda _cohort=None: [dict(positive) for _ in range(30)]
            qualified = ledger.qualification()
            self.assertEqual(qualified["decision"], "PROSPECTIVE_EDGE_CANDIDATE")
            self.assertFalse(qualified["promotion_authorized"])
            self.assertEqual(qualified["production_rho"], 0.0)


if __name__ == "__main__":
    unittest.main()
