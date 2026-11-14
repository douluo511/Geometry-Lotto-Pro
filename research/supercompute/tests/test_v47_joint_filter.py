"""Hard combined include/exclude search; exact mathematics and outcome tests."""
from datetime import date
import hashlib
import math
from pathlib import Path
import tempfile
import unittest

from research.supercompute.v47_joint_filter import (
    construct_joint_search, fair_constraint_probability,
    score_joint_search, select_joint_constraints,
)
from research.supercompute.v47_hedge import fair_pair, score_frozen
from research.supercompute.v47_models import SPECS, canonical, validate_ticket


def dummy_22(game, *, conflict=False):
    maximum, picked, bm, bp = SPECS[game]
    required = [4, 24] if game == "ssq" else [10, 14]
    excluded = [21, 32] if game == "ssq" else [23, 30]
    records = []
    for i in range(1, 12):
        front = sorted(required + [
            n for n in range(1, maximum + 1) if n not in required
        ][:picked - 2])
        back = list(range(1, bp + 1))
        positive = {
            "model_id": f"M{i:02d}+",
            "direction": "subset",
            "prediction": {
                "ticket": {"front": front, "back": back, "dan2": required},
                "marginals": {
                    "front": [0.0] + [
                        .85 if n in required else .14
                        for n in range(1, maximum + 1)],
                    "back": [0.0] + [
                        .5 for _ in range(bm)]},
            }}
        e = [required[0], excluded[1]] if conflict and i == 1 else excluded
        negative = {
            "model_id": f"M{i:02d}-",
            "direction": "disjoint",
            "prediction": {
                "excluded_pair": e,
                "candidate_marginals": {
                    "front": [0.0] + [
                        .85 if n in required else .14
                        for n in range(1, maximum + 1)],
                    "back": [0.0] + [.5] * bm}}}
        records.extend((positive, negative))
    return records, required, excluded


class ExactJointFilterTests(unittest.TestCase):
    def test_both_games_filter_exact_count_and_valid_ranked_full_tickets(self):
        for game in SPECS:
            with self.subTest(game=game):
                records, required, excluded = dummy_22(game)
                result = construct_joint_search(records, game, limit=8)
                self.assertEqual(result["constraints"]["required"], required)
                self.assertEqual(result["constraints"]["excluded"], excluded)
                fm, fp, bm, bp = SPECS[game]
                expected_front = math.comb(fm - 4, fp - 2)
                self.assertEqual(result["retained_front_combinations"], expected_front)
                self.assertEqual(result["original_front_combinations"], math.comb(fm, fp))
                self.assertEqual(result["retained_full_ticket_combinations"],
                                 expected_front * math.comb(bm, bp))
                self.assertAlmostEqual(result["remaining_fraction"],
                                       fair_constraint_probability(game))
                self.assertLess(result["remaining_fraction"], 1)
                self.assertEqual(result["ticket_count"], 8)
                for ticket in result["tickets"]:
                    validate_ticket(ticket, game)
                    self.assertTrue(set(required).issubset(ticket["front"]))
                    self.assertTrue(set(excluded).isdisjoint(ticket["front"]))
                self.assertEqual(len({(tuple(t["front"]), tuple(t["back"]))
                                      for t in result["tickets"]}), 8)
                self.assertEqual(result["edge"], "NO_EDGE")

    def test_conflicting_votes_do_not_create_impossible_hard_constraints(self):
        for game in SPECS:
            records, req, exc = dummy_22(game, conflict=True)
            joint = select_joint_constraints(records, game)
            self.assertEqual(joint["required"], req)
            self.assertEqual(joint["excluded"], exc)
            self.assertIn(req[0], joint["conflict_numbers"])
            self.assertTrue(set(joint["required"]).isdisjoint(joint["excluded"]))
            self.assertTrue(joint["signals_are_correlated"])

    def test_strict_negative_event_requires_both_absent_in_true_draw(self):
        for game in SPECS:
            records, required, excluded = dummy_22(game)
            search = construct_joint_search(records, game)
            example = search["tickets"][0]
            actual = {"front": list(example["front"]), "back": list(example["back"])}
            yes = score_joint_search(search, actual, game)
            self.assertTrue(yes["required_all_appear"])
            self.assertTrue(yes["excluded_all_absent"])
            self.assertTrue(yes["joint_filter_keeps_actual_front"])
            self.assertEqual(yes["exact_jackpot_ticket_hits"], 1)
            one_excluded = sorted((set(example["front"]) -
                                   {next(n for n in example["front"] if n not in required)})
                                  | {excluded[0]})
            actual_partial = {**actual, "front": one_excluded}
            no = score_joint_search(search, actual_partial, game)
            self.assertTrue(no["required_all_appear"])
            self.assertFalse(no["excluded_all_absent"])
            self.assertFalse(no["joint_filter_keeps_actual_front"])
            self.assertEqual(no["exact_jackpot_ticket_hits"], 0)

    def test_exact_probability_for_two_included_and_two_absent(self):
        self.assertEqual(fair_pair("ssq")["disjoint"],
                         math.comb(27, 2) / math.comb(33, 2))
        self.assertEqual(fair_pair("dlt")["disjoint"],
                         math.comb(30, 2) / math.comb(35, 2))
        self.assertEqual(math.comb(33 - 4, 6 - 2), 23751)
        self.assertEqual(math.comb(35 - 4, 5 - 2), 4495)
        for game in SPECS:
            self.assertAlmostEqual(fair_constraint_probability(game),
                                   math.comb(SPECS[game][0] - 4,
                                             SPECS[game][1] - 2) /
                                   math.comb(SPECS[game][0], SPECS[game][1]))
            self.assertGreater(fair_pair(game)["not_subset"],
                               fair_pair(game)["disjoint"])

    def test_legacy_partial_exclusion_cannot_be_mislabeled_strict(self):
        game = "ssq"
        records, required, excluded = dummy_22(game)
        example = {"front": [4, 5, 6, 14, 24, 30], "back": [4],
                   "dan2": required}
        old_source = {
            "game": game, "target_issue": "9999999",
            "models": {
                "M01+": {"direction": "subset", "prediction": {"ticket": example}},
                "M01-": {"direction": "not_subset", "prediction": {
                    "ticket": example, "excluded_pair": [21, 32]}}}}
        frozen = {"schema": "SSQDLT_V47_HEDGE22_FROZEN_V1",
                  "source": old_source}
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "legacy.json"
            raw = canonical(frozen)
            target.write_bytes(raw)
            actual = {"front": [4, 5, 6, 14, 21, 24], "back": [4],
                      "issue": "9999999"}
            scored = score_frozen(target, hashlib.sha256(raw).hexdigest(), actual)
            self.assertFalse(scored["strict_disjoint_verified"])
            self.assertTrue(scored["models"]["M01-"]["legacy_partial_exclusion_success"])
            self.assertFalse(scored["models"]["M01-"][
                "reference_disjoint_success_not_original_objective"])


if __name__ == "__main__":
    unittest.main()
