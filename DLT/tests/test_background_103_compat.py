from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from glp.background import background_cycle, launch_background_worker
from glp.constants import (
    BACKGROUND_POLL_SECONDS,
    BACKGROUND_STARTUP_MODE,
    DEFAULT_RESEARCH_DAN_FRONT_COUNT,
    DEFAULT_RESEARCH_DAN_BACK_COUNT,
)
from glp.domain import Draw, Prediction
from glp.engine import make_prediction
from glp.storage import Store
from glp.util import sha256_json


class FakeStore:
    def __init__(self):
        self.draws = [
            Draw("26113", "2026-10-05", (1, 2, 3, 4, 5), (1, 2))
        ]
        self.freezes_by_issue = {}
        self.experiments = []

    def load_draws(self):
        return list(self.draws), sha256_json([d.to_dict() for d in self.draws])

    def freezes(self):
        return list(self.freezes_by_issue.values())

    def append_experiment(self, kind, status, input_hash, code_hash, payload):
        self.experiments.append((kind, status, input_hash, code_hash, payload))
        return len(self.experiments)


class FakeService:
    def __init__(self):
        self.store = FakeStore()
        self.predict_calls = 0
        self.update_calls = 0

    def update(self):
        self.update_calls += 1
        draws, digest = self.store.load_draws()
        return {
            "network_gate": "PASS",
            "crosscheck_status": "PASS",
            "replayed": 0,
            "latest": draws[-1].to_dict(),
            "canonical_hash": digest,
        }

    def predict(self):
        self.predict_calls += 1
        draws, digest = self.store.load_draws()
        target = "26114"
        pred = Prediction(
            prediction_id="fake-prediction",
            target_issue=target,
            target_date="2026-10-07",
            created_at="2026-10-06T00:00:00Z",
            front=[1, 6, 11, 16, 21],
            back=[3, 8],
            front_ranking=list(range(1, 36)),
            back_ranking=list(range(1, 13)),
            dan_state="NULL_DAN",
            edge_state="NO_EDGE",
            research_dan_front=[1, 2],
            research_dan_back=[1],
            canonical_hash=digest,
            model_hash="m" * 64,
            selector_hash="s" * 64,
            score_hash="x" * 64,
            freeze_hash="f" * 64,
        )
        self.store.freezes_by_issue[target] = pred
        return {"prediction": pred.to_dict(), "effect_trace": {}}


class Background103CompatibilityTests(unittest.TestCase):
    def test_frozen_contract_is_30_minutes_manual_reopen_after_login_and_two_dan(self):
        self.assertEqual(BACKGROUND_POLL_SECONDS, 1800)
        self.assertEqual(DEFAULT_RESEARCH_DAN_FRONT_COUNT, 2)
        self.assertEqual(DEFAULT_RESEARCH_DAN_BACK_COUNT, 1)
        self.assertEqual(BACKGROUND_STARTUP_MODE, "manual_app_launch_required_after_login")

    def test_background_cycle_creates_only_missing_next_freeze(self):
        svc = FakeService()
        first = background_cycle(svc)
        second = background_cycle(svc)
        self.assertEqual(first["status"], "PASS")
        self.assertTrue(first["prediction_created"])
        self.assertFalse(second["prediction_created"])
        self.assertEqual(svc.predict_calls, 1)
        self.assertEqual(svc.update_calls, 2)
        self.assertEqual(first["research_dan_front"], [1, 2])

    def test_old_one_dan_freeze_is_never_overwritten_by_two_dan_default(self):
        with tempfile.TemporaryDirectory(prefix="dlt-one-dan-compat-") as td:
            store = Store(Path(td))
            old = Prediction(
                prediction_id="old-one-dan",
                target_issue="26100",
                target_date="2026-08-31",
                created_at="2026-08-30T00:00:00Z",
                front=[1, 2, 3, 4, 5],
                back=[1, 2],
                front_ranking=list(range(1, 36)),
                back_ranking=list(range(1, 13)),
                dan_state="NULL_DAN",
                edge_state="NO_EDGE",
                research_dan_front=[14],
                research_dan_back=[9],
                canonical_hash="c" * 64,
                model_hash="m" * 64,
                selector_hash="s" * 64,
                score_hash="x" * 64,
            )
            frozen = store.freeze(old)
            replacement = Prediction(**{
                **old.to_dict(),
                "prediction_id": "new-two-dan",
                "research_dan_front": [14, 26],
                "freeze_hash": "",
            })
            returned = store.freeze(replacement)
            self.assertEqual(frozen.freeze_hash, returned.freeze_hash)
            self.assertEqual(returned.research_dan_front, [14])
            self.assertEqual(len(store.freezes()), 1)

    def test_two_dan_default_is_hash_bound_in_selector_policy(self):
        source = inspect.getsource(make_prediction)
        self.assertIn("DEFAULT_RESEARCH_DAN_FRONT_COUNT", source)
        self.assertIn("DEFAULT_RESEARCH_DAN_BACK_COUNT", source)

    def test_background_launcher_never_uses_shell(self):
        source = inspect.getsource(launch_background_worker)
        self.assertIn("shell=False", source)
        self.assertIn("DETACHED_PROCESS", source)
        self.assertIn("CREATE_NEW_PROCESS_GROUP", source)


if __name__ == "__main__":
    unittest.main()
