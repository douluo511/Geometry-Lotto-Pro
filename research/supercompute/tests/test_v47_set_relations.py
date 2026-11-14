"""SSQ/DLT mathematical semantics: 属于/不属于/包含于/完全排除.

Prevent 'not a subset' (one missing) from being passed as 'disjoint'
(all missing); trace each individual number. Tests run for both lotteries
and BOTH front/back zones.
"""
import unittest

from research.supercompute.v47_set_relations import (
    evaluate_relation, score_model_relation,
)
from research.supercompute.v47_hedge import score_one
from research.supercompute.v47_interval_search import score_constraints, score_interval_search
from research.supercompute.v47_joint_filter import score_joint_search
from research.supercompute.v47_models import SPECS


DRAW = {
    "ssq": {"front": [4, 13, 14, 22, 24, 30], "back": [4]},
    "dlt": {"front": [3, 10, 12, 14, 26], "back": [9, 12]},
}


class SetRelationsAcceptance(unittest.TestCase):
    def test_four_event_truth_table_for_each_area(self):
        for game, actual in DRAW.items():
            for area in ("front", "back"):
                with self.subTest(game=game, area=area):
                    present = actual[area][0]
                    maximum = SPECS[game][0 if area == "front" else 2]
                    absent = next(n for n in range(1, maximum + 1)
                                  if n not in actual[area])
                    included = evaluate_relation(game, area, [present], actual)
                    self.assertEqual(included["element_membership"],
                                     [{"number": present, "belongs": True,
                                       "not_belongs": False}])
                    self.assertTrue(included["contained"])
                    self.assertFalse(included["disjoint"])
                    self.assertFalse(included["not_contained"])
                    self.assertEqual(included["m_plus_success"], True)
                    self.assertEqual(included["m_minus_success"], False)
                    not_included = evaluate_relation(game, area, [absent], actual)
                    self.assertTrue(not_included["not_contained"])
                    self.assertTrue(not_included["disjoint"])
                    self.assertFalse(not_included["m_plus_success"])
                    self.assertTrue(not_included["m_minus_success"])
                    mixed = evaluate_relation(game, area, [absent, present], actual)
                    self.assertTrue(mixed["not_contained"])
                    self.assertFalse(mixed["disjoint"])
                    self.assertTrue(mixed["partial_absence_not_full_exclusion"])
                    self.assertFalse(mixed["m_minus_success"])
                    self.assertEqual(mixed["members"], [present])
                    self.assertEqual(mixed["nonmembers"], [absent])

    def test_two_absent_exclusions_all_zero_hits(self):
        for game, actual in DRAW.items():
            for area in ("front", "back"):
                maxnum = SPECS[game][0 if area == "front" else 2]
                excluded = [n for n in range(1, maxnum + 1)
                            if n not in actual[area]][:2]
                out = score_model_relation(game, "disjoint", excluded,
                                           actual, area)
                self.assertTrue(out["success"])
                self.assertEqual(out["member_count"], 0)
                self.assertEqual(out["nonmember_count"], 2)
                self.assertTrue(out["not_contained"])
                self.assertTrue(out["disjoint"])
                self.assertFalse(out["partial_absence_not_full_exclusion"])

    def test_zero_constraints_are_vacuous_not_model_success(self):
        for game, actual in DRAW.items():
            for area in ("front", "back"):
                r = evaluate_relation(game, area, [], actual)
                self.assertTrue(r["contained"])
                self.assertTrue(r["disjoint"])
                self.assertFalse(r["not_contained"])
                self.assertTrue(r["vacuous_when_empty"])
                self.assertFalse(r["active_constraint"])
                self.assertIsNone(r["m_plus_success"])
                self.assertIsNone(r["m_minus_success"])
                with self.assertRaises(ValueError):
                    score_model_relation(game, "disjoint", [], actual, area)
                with self.assertRaises(ValueError):
                    score_model_relation(game, "subset", [], actual, area)

    def test_legacy_partial_non_subset_must_be_rejected(self):
        for game in DRAW:
            with self.assertRaises(ValueError):
                score_model_relation(game, "not_subset", [1], DRAW[game])
            with self.assertRaises(ValueError):
                score_model_relation(game, "nonmember", [1], DRAW[game])

    def test_out_of_universe_duplicates_and_invalid_area_are_rejected(self):
        for game, actual in DRAW.items():
            for area in ("front", "back"):
                maximum = SPECS[game][0 if area == "front" else 2]
                for selected in ([0], [-1], [maximum + 1],
                                 [True], [1, 1], [1.0], "1"):
                    with self.subTest(game=game, area=area, selected=selected):
                        with self.assertRaises(ValueError):
                            evaluate_relation(game, area, selected, actual)
            with self.assertRaises(ValueError):
                evaluate_relation(game, "blue_not_a_real_area", [1], actual)

    def test_existing_eleven_plus_minus_models_use_shared_semantics(self):
        for game, actual in DRAW.items():
            front = actual["front"]
            selected = front[:2]
            positive = {"direction": "subset",
                        "prediction": {"ticket": {
                            "front": front, "back": actual["back"],
                            "dan2": selected}}}
            pos = score_one(positive, actual, game)
            self.assertTrue(pos["subset_event"])
            self.assertEqual(pos["included_membership"]["members"], selected)
            absent = next(n for n in range(1, SPECS[game][0] + 1)
                          if n not in front)
            negative = {"direction": "disjoint", "prediction": {
                "ticket": {"front": front, "back": actual["back"],
                           "dan2": selected},
                "excluded_pair": [selected[0], absent]}}
            scored = score_one(negative, actual, game)
            self.assertEqual(scored["excluded_hits"], 1)
            self.assertFalse(scored["negative_event_disjoint"])
            self.assertTrue(scored["excluded_membership"]["not_contained"])
            self.assertFalse(scored["excluded_membership"]["m_minus_success"])
            negative["prediction"]["excluded_pair"] = [absent, absent + 1]
            self.assertTrue(score_one(negative, actual, game)[
                "negative_event_disjoint"])

    def test_four_area_joint_scoring_reports_partial_failure(self):
        for game, actual in DRAW.items():
            front = actual["front"]
            back = actual["back"]
            fm, fp, bm, bp = SPECS[game]
            absent_front = next(n for n in range(1, fm + 1) if n not in front)
            absent_back = next(n for n in range(1, bm + 1) if n not in back)
            areas = {
                "front": {"required": [front[0]],
                          "excluded": [front[1], absent_front]},
                "back": {"required": [],
                         "excluded": [absent_back]}}
            scored = score_constraints(areas, actual, game)
            self.assertFalse(scored["all_area_constraints_survived"])
            self.assertTrue(scored["areas"]["front"][
                "negative_partial_not_subset_is_not_m_minus_success"])
            self.assertEqual(scored["areas"]["front"]["excluded_hits"], 1)
            self.assertTrue(scored["areas"]["back"]["vacuous_include"])
            self.assertIsNone(scored["areas"]["back"][
                "positive_membership"]["m_plus_success"])
            self.assertTrue(scored["areas"]["back"]["excluded_all_absent"])
            search = {"game": game, "areas": areas,
                      "tickets": [actual],
                      "retained_full_ticket_combinations": 100}
            # A frozen ticket that violates its own exclusion constraint
            # must be rejected, even if it happens to match the draw.
            with self.assertRaises(ValueError):
                score_interval_search(search, actual, game)

    def test_front_only_legacy_joint_scoring_remains_strict(self):
        for game, actual in DRAW.items():
            front = actual["front"]
            absent = next(n for n in range(1, SPECS[game][0] + 1)
                          if n not in front)
            other = next(n for n in range(1, SPECS[game][0] + 1)
                         if n not in front and n != absent)
            legal_front = sorted((set(front) - {front[1]}) | {other})
            search = {"game": game,
                      "constraints": {
                          "required": [front[0]],
                          "excluded": [front[1], absent]},
                      "tickets": [{"front": legal_front,
                                   "back": list(actual["back"])}],
                      "fair_probability_constraints_all_correct": .2}
            result = score_joint_search(search, actual, game)
            self.assertTrue(result["positive_membership"]["contained"])
            self.assertTrue(result["negative_membership"]["not_contained"])
            self.assertFalse(result["negative_membership"]["disjoint"])
            self.assertTrue(result[
                "negative_partial_not_subset_is_not_m_minus_success"])
            self.assertFalse(result["joint_filter_keeps_actual_front"])
            self.assertEqual(result["exact_jackpot_ticket_hits"], 0)
            search["tickets"] = [actual]
            with self.assertRaises(ValueError):
                score_joint_search(search, actual, game)


if __name__ == "__main__":
    unittest.main()
