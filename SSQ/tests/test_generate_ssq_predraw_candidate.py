"""Mocked generator contracts. Never report synthetic draws as Real Network PASS."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
from glp.domain import CanonicalDataset, Draw
from glp.util import sha256_json
from tools import generate_ssq_predraw_candidate as gen

SHA = "a" * 40
DRAW = Draw("2026118", "2026-10-08", (1, 2, 3, 4, 5, 6), (7,))
TODAY = date(2026, 10, 8)
FUTURE = "2026-10-11"


def fake_data(*, crosscheck="PASS", valid_hash=True, latest=DRAW, raw="PENDING_PERSISTENCE"):
    draws = [latest]
    digest = sha256_json([d.to_dict() for d in draws]) if valid_hash else "b" * 64
    ds = CanonicalDataset(
        draws, digest, [], 2, crosscheck,
    )
    ev = {
        "crosscheck_status": crosscheck,
        "raw_response_status": raw,
        "verification": "MOCKED_QUORUM_UNIT_ONLY",
        "source_receipts": [],
    }
    return lambda: (ds, ev)


def fake_prediction(date_text=FUTURE, *, dan_state="NULL_DAN"):
    return SimpleNamespace(
        target_date=date_text,
        to_dict=lambda: {
            "target_issue": "2026119", "target_date": date_text,
            "canonical_hash": sha256_json([DRAW.to_dict()]),
            "edge_state": "NO_EDGE", "dan_state": dan_state,
        },
    )


class CandidateGenerationContracts(unittest.TestCase):
    def test_unit_fixture_never_qualifies_future_draw_or_model(self):
        with patch.object(gen, "make_prediction", return_value=(fake_prediction(), {})):
            result = gen.generate(
                source_commit=SHA, today_china=TODAY,
                canonical_builder=fake_data(),
            )
        self.assertEqual(result["model_source_commit"], SHA)
        self.assertEqual(result["prediction"]["target_date"], FUTURE)
        self.assertEqual(result["scientific_decision"]["qualified_replays"], 0)
        self.assertEqual(result["scientific_decision"]["min_prospective_required"], 120)
        self.assertFalse(result["scientific_decision"]["promotion_authorized"])

    def test_no_same_day_or_past_target_freeze(self):
        for value in ("2026-10-08", "2026-10-07"):
            with self.subTest(value=value):
                with patch.object(gen, "make_prediction", return_value=(fake_prediction(value), {})):
                    with self.assertRaisesRegex(ValueError, "already on/past"):
                        gen.generate(
                            source_commit=SHA, today_china=TODAY,
                            canonical_builder=fake_data(),
                        )

    def test_crosscheck_and_persistable_raw_contract_fail_closed(self):
        for kwargs in ({"crosscheck": "FAIL"}, {"raw": "UNVERIFIED"}, {"valid_hash": False}):
            with self.subTest(kwargs=kwargs):
                with patch.object(gen, "make_prediction", return_value=(fake_prediction(), {})):
                    with self.assertRaises(ValueError):
                        gen.generate(
                            source_commit=SHA, today_china=TODAY,
                            canonical_builder=fake_data(**kwargs),
                        )

    def test_stale_official_history_rejected_not_repaired_with_fake_latest(self):
        old = Draw("2026113", "2026-09-29", DRAW.front, DRAW.back)
        with patch.object(gen, "make_prediction", return_value=(fake_prediction(), {})):
            with self.assertRaisesRegex(ValueError, "stale"):
                gen.generate(
                    source_commit=SHA, today_china=TODAY,
                    canonical_builder=fake_data(latest=old),
                )

    def test_no_predictive_certification_without_prospective_samples(self):
        with patch.object(gen, "make_prediction", return_value=(fake_prediction(dan_state="CERTIFIED_DAN"), {})):
            with self.assertRaisesRegex(ValueError, "unsupported production promotion"):
                gen.generate(
                    source_commit=SHA, today_china=TODAY,
                    canonical_builder=fake_data(),
                )

    def test_unknown_model_commit_rejected_before_reaching_official_source(self):
        with self.assertRaisesRegex(ValueError, "exact GitHub source commit"):
            gen.generate(
                source_commit="not-a-real-sha",
                today_china=TODAY,
                canonical_builder=lambda: (_ for _ in ()).throw(AssertionError("network unexpectedly called")),
            )


if __name__ == "__main__":
    unittest.main()
