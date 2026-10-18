"""Synthetic-only D2 replay equivalence and chronology/fault tests."""
import copy
import hashlib
import itertools
import random
import unittest
from collections import Counter
from pathlib import Path

from research.ssq_dlt_v45 import models, study_engine as engine


def synthetic_history(game="SSQ", size=240, seed=7301):
    rng = random.Random(seed)
    upper, count, back_upper, back_count = models.RULES[game]
    return [{"game": game, "issue": str(2000001 + i),
             "draw_date": f"synthetic-date-{i:05}",
             "front": rng.sample(range(1, upper + 1), count),
             "back": rng.sample(range(1, back_upper + 1), back_count)}
            for i in range(size)]


def independent_residual(history, upper):
    recent = history[-60:]
    singles = Counter(n for row in recent for n in row["front"])
    pairs = Counter(pair for row in recent
                    for pair in itertools.combinations(sorted(row["front"]), 2))
    observed = len(recent)
    return list(min(itertools.combinations(range(1, upper + 1), 2),
                    key=lambda pair: (
                        -(pairs[pair] * observed - singles[pair[0]] * singles[pair[1]]),
                        -pairs[pair], -(singles[pair[0]] + singles[pair[1]]), pair)))


class StudyEngineTest(unittest.TestCase):
    def assert_originals_equal(self, game, issue, history, seed=models.DEFAULT_SEED):
        original = models.generate(game, issue, history, seed=seed)
        actual = engine.predict_d2_all(game, issue, history, seed=seed)
        self.assertEqual(set(actual), set(engine.STUDY_MODEL_VERSIONS))
        for model in models.MODEL_VERSIONS:
            self.assertEqual(actual[model], original["models"][model]["primary_d2"],
                             (game, len(history), seed, model))
        self.assertEqual(actual[engine.CANDIDATE_MODEL],
                         independent_residual(history, models.RULES[game][0]))

    def test_existing_five_exactly_match_original_at_many_prefixes(self):
        for game in models.RULES:
            history = synthetic_history(game)
            for size in (0, 1, 2, 19, 20, 59, 60, 61, 119, 120, 121, 239, 240):
                with self.subTest(game=game, size=size):
                    self.assert_originals_equal(game, "2001000", history[:size])

    def test_null_seed_and_unassigned_domains_match_original(self):
        for game in models.RULES:
            history = synthetic_history(game, size=73)
            for issue in ("2001000", "2001001", "UNASSIGNED"):
                for seed in (0, 1, 71, models.DEFAULT_SEED):
                    with self.subTest(game=game, issue=issue, seed=seed):
                        self.assert_originals_equal(game, issue, history, seed)

    def test_all_ties_use_fixed_ascending_rule_and_exact_residual(self):
        for game in models.RULES:
            self.assert_originals_equal(game, "2001000", [])
            actual = engine.predict_d2_all(game, "2001000", [])
            for name in engine.STUDY_MODEL_VERSIONS:
                if name != models.NULL_MODEL:
                    self.assertEqual(actual[name], [1, 2])
            upper, count, _, back_count = models.RULES[game]
            # Equal marginals and many exact integer residual ties.
            history = [{"game": game, "issue": str(2000001 + i),
                        "front": [1 + (i + j) % upper for j in range(count)],
                        "back": list(range(1, back_count + 1))}
                       for i in range(upper * 4)]
            for size in (60, upper * 2, upper * 4):
                self.assert_originals_equal(game, "2001000", history[:size])

    def test_walk_forward_reuses_only_prefix_and_copies_outcomes(self):
        for game in models.RULES:
            history = synthetic_history(game, size=145)
            saved = copy.deepcopy(history)
            actual = engine.walk_forward(game, history, start=120, stop=128)
            self.assertEqual(history, saved)
            self.assertEqual(len(actual), 8)
            for index, row in enumerate(actual, 120):
                self.assertEqual(row["training_size"], index)
                self.assertEqual(row["training_end_issue"], history[index - 1]["issue"])
                self.assertEqual(row["issue"], history[index]["issue"])
                self.assertEqual(row["draw_date"], history[index]["draw_date"])
                self.assertEqual(row["predictions"], engine.predict_d2_all(
                    game, history[index]["issue"], history[:index]))
                self.assertEqual(row["draw_front"], history[index]["front"])
            actual[0]["draw_front"].clear()
            actual[0]["predictions"][models.PRIMARY_MODEL].clear()
            self.assertEqual(history, saved)

    def test_target_and_all_future_outcome_mutations_cannot_change_prediction(self):
        for game in models.RULES:
            history = synthetic_history(game, size=180)
            base = engine.walk_forward(game, history, start=120, stop=136)
            changed = copy.deepcopy(history)
            upper = models.RULES[game][0]
            for row in changed[130:]:
                row["front"] = [upper + 1 - n for n in row["front"]]
            mutated = engine.walk_forward(game, changed, start=120, stop=136)
            for index in range(11):
                self.assertEqual(base[index]["predictions"], mutated[index]["predictions"])
            self.assertEqual(base[10]["issue"], changed[130]["issue"])
            self.assertNotEqual(base[10]["draw_front"], mutated[10]["draw_front"])

    def test_prefix_predictions_do_not_use_embedded_statistics(self):
        history = synthetic_history(size=130)
        expected = engine.walk_forward("SSQ", history, start=120)
        for row in history:
            row["embedded_statistics"] = {"D2": [32, 33], "hit_rate": 1.0}
        self.assertEqual(engine.walk_forward("SSQ", history, start=120), expected)

    def test_duplicate_missing_order_wrong_game_illegal_seed_and_future_fail(self):
        history = synthetic_history(size=125)
        duplicate = copy.deepcopy(history)
        duplicate[60]["issue"] = duplicate[59]["issue"]
        wrong_game = copy.deepcopy(history)
        wrong_game[1]["game"] = "DLT"
        illegal_number = copy.deepcopy(history)
        illegal_number[1]["front"][0] = True
        for value in (duplicate, list(reversed(history)), wrong_game, illegal_number):
            with self.subTest(value=value[1]), self.assertRaises(models.ModelBlocked):
                engine.walk_forward("SSQ", value)
        for seed in (-1, True, "1"):
            with self.subTest(seed=seed), self.assertRaises(models.ModelBlocked):
                engine.walk_forward("SSQ", history, seed=seed)
        for issue in (history[-1]["issue"], history[0]["issue"]):
            with self.assertRaisesRegex(models.ModelBlocked, "F01"):
                engine.predict_d2_all("SSQ", issue, history)
        # Numeric skips are not asserted to be complete official periods here.
        # The caller's source/admission audit must establish the exact issue set.
        history.pop(60)
        self.assertEqual(len(engine.walk_forward("SSQ", history)), 4)

    def test_bounds_fail_closed_and_empty_range_is_legal(self):
        history = synthetic_history(size=121)
        for start, stop in ((True, None), (-1, None), (122, None), (120, 119),
                            (120, True), (120, 122)):
            with self.subTest(start=start, stop=stop), self.assertRaises(models.ModelBlocked):
                engine.walk_forward("SSQ", history, start=start, stop=stop)
        self.assertEqual(engine.walk_forward("SSQ", history, start=121), [])
        first = engine.walk_forward("SSQ", history, start=0, stop=1)[0]
        self.assertEqual(first["training_size"], 0)
        self.assertIsNone(first["training_end_issue"])

    def test_roster_source_sha_and_candidate_cannot_replace_formal_slots(self):
        registry = engine.study_registry()
        self.assertEqual(registry["existing_model_source_sha256"], models.source_sha256())
        self.assertEqual(registry["study_engine_source_sha256"],
                         hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest())
        self.assertEqual(len(registry["models"]), 6)
        self.assertEqual(registry["models"][engine.CANDIDATE_MODEL], "1.0.0")
        self.assertEqual(registry["candidate"]["window"], 60)
        self.assertFalse(registry["candidate"]["parameters_tuned"])
        self.assertEqual((registry["formal_A"], registry["decision"]), (0, "NO_EDGE"))
        self.assertFalse(registry["asof_publication_verified"])
        registry["models"].clear()
        self.assertEqual(len(engine.study_registry()["models"]), 6)
        self.assertEqual(len(models.registry()["models"]), 5)
        self.assertFalse(set(engine.MODEL_IDS) & {
            "M04", "M05-1", "M05-2", "M05-3", "M05-4", "M05-5", "M06", "M07"})
        with self.assertRaises(TypeError):
            engine.STUDY_MODEL_VERSIONS["M04"] = "1.0.0"


if __name__ == "__main__":
    unittest.main()
