"""Four-area variable-count interval research and chronological acceptance."""
import itertools
import math
import unittest

from research.supercompute.v47_interval_search import (
    ZONES, build_constraints, calibrate_profiles, construct_interval_search,
    legal_area_count, model_evidence, profile_grid, score_interval_search,
)
from research.supercompute.v47_models import SPECS, validate_ticket


def dummy_22(game):
    fm, fp, bm, bp = SPECS[game]
    req = [4, 30] if game == "ssq" else [10, 14]
    excludes = [8, 21] if game == "ssq" else [30, 31]
    front = sorted(req + [x for x in range(1, fm + 1) if x not in req][:fp - 2])
    back = [4] if game == "ssq" else [9, 12]
    result = []
    for i in range(1, 12):
        plus, minus = {}, {}
        plus["model_id"] = f"M{i:02d}+"
        plus["direction"] = "subset"
        plus["prediction"] = {
            "ticket": {"front": front, "back": back, "dan2": req},
            "marginals": {
                "front": [0.0] + [.84 if n in req else .15 for n in range(1, fm + 1)],
                "back": [0.0] + [.9 if n in back else .1 for n in range(1, bm + 1)],
            }}
        minus["model_id"] = f"M{i:02d}-"
        minus["direction"] = "disjoint"
        minus["prediction"] = {
            "excluded_pair": excludes,
            "candidate_marginals": {
                "front": [0.0] + [.85 if n in req else .12
                                   for n in range(1, fm + 1)],
                "back": [0.0] + [.86 if n in back else .11
                                  for n in range(1, bm + 1)]}}
        result.extend((plus, minus))
    return result


def fake_draw(game, front=None, back=None, issue="100"):
    fm, fp, bm, bp = SPECS[game]
    return {"issue": issue,
            "front": front or list(range(1, fp + 1)),
            "back": back or list(range(1, bp + 1))}


class AdaptiveIntervalResearchTests(unittest.TestCase):
    def test_zone_boundaries_cover_all_four_areas_exactly_once(self):
        for game in SPECS:
            fm, fp, bm, bp = SPECS[game]
            for area, maximum in (("front", fm), ("back", bm)):
                assigned = [n for lo, hi in ZONES[game][area]
                            for n in range(lo, hi + 1)]
                self.assertEqual(assigned, list(range(1, maximum + 1)))
                self.assertEqual(len(ZONES[game][area]), 3)

    def test_variable_counts_and_zero_constraints(self):
        for game in SPECS:
            fm, fp, bm, bp = SPECS[game]
            profiles = list(profile_grid(game))
            self.assertGreater(len(profiles), 20)
            self.assertIn(dict(front_include=0, front_exclude=0,
                               back_include=0, back_exclude=0), profiles)
            self.assertIn(dict(front_include=1, front_exclude=3,
                               back_include=0, back_exclude=2), profiles)
            self.assertEqual(legal_area_count(fm, fp, 0, 0), math.comb(fm, fp))
            self.assertEqual(legal_area_count(bm, bp, 0, 0), math.comb(bm, bp))
            self.assertEqual(legal_area_count(fm, fp, 2, 2),
                             math.comb(fm - 4, fp - 2))
            self.assertEqual(legal_area_count(bm, bp, bp, 2), 1)
            with self.assertRaises(ValueError):
                legal_area_count(fm, fp, fp + 1, 0)
            with self.assertRaises(ValueError):
                legal_area_count(fm, fp, 0, fm - fp + 1)

    def test_evidence_contains_11_plus_11_and_back_exclusion_is_only_proxy(self):
        for game in SPECS:
            evidence = model_evidence(dummy_22(game), game)
            for area in ("front", "back"):
                self.assertEqual(sum(evidence[area]["positive"].values()),
                                 22 if area == "front" else 11 * SPECS[game][3])
                self.assertEqual(sum(evidence[area]["negative"].values()), 22)
            profile = dict(front_include=2, front_exclude=2,
                           back_include=1, back_exclude=2)
            areas = build_constraints(evidence, game, profile)
            for area in ("front", "back"):
                self.assertFalse(set(areas[area]["required"]) &
                                 set(areas[area]["excluded"]))
                self.assertEqual(len(areas[area]["zones"]), 3)
            self.assertFalse(areas["back"]["negative_area_independently_trained"])

    def test_joint_full_area_search_exact_combinatorial_counts(self):
        for game in SPECS:
            with self.subTest(game=game):
                records = dummy_22(game)
                fm, fp, bm, bp = SPECS[game]
                profile = dict(front_include=2, front_exclude=3,
                               back_include=1, back_exclude=2)
                result = construct_interval_search(records, game, profile)
                expected = (math.comb(fm - 5, fp - 2) *
                            math.comb(bm - 3, bp - 1))
                self.assertEqual(result["retained_full_ticket_combinations"], expected)
                self.assertEqual(result["original_full_ticket_combinations"],
                                 math.comb(fm, fp) * math.comb(bm, bp))
                self.assertEqual(result["ticket_count"], 8)
                for ticket in result["tickets"]:
                    validate_ticket(ticket, game)
                    for area in ("front", "back"):
                        self.assertTrue(set(result["areas"][area]["required"])
                                        .issubset(ticket[area]))
                        self.assertFalse(set(result["areas"][area]["excluded"]) &
                                         set(ticket[area]))
                self.assertEqual(result["edge"], "NO_EDGE")
                self.assertEqual(result["back_exclusion_training"],
                                 "UNVERIFIED_PROXY_NOT_INDEPENDENT_M_MINUS")

    def test_zero_constraints_also_searchable_not_spurious_certainty(self):
        for game in SPECS:
            profile = dict(front_include=0, front_exclude=0,
                           back_include=0, back_exclude=0)
            result = construct_interval_search(dummy_22(game), game, profile)
            self.assertEqual(result["retained_fraction"], 1.0)
            self.assertEqual(len(result["tickets"]), 8)
            for area in ("front", "back"):
                self.assertEqual(result["areas"][area]["required"], [])
                self.assertEqual(result["areas"][area]["excluded"], [])

    def test_no_hindsight_during_profile_selection(self):
        for game in SPECS:
            records = dummy_22(game)
            profile = dict(front_include=2, front_exclude=2,
                           back_include=1, back_exclude=1)
            report = construct_interval_search(records, game, profile)
            t = report["tickets"][0]
            first = fake_draw(game, list(t["front"]), list(t["back"]), "101")
            second = fake_draw(game, list(t["front"]), list(t["back"]), "102")
            last = fake_draw(game, issue="103")
            folds = [{"records": records, "actual": row}
                     for row in (first, second, last)]
            base = calibrate_profiles(folds, game)
            changed_last = fake_draw(game, issue="103",
                                     front=list(range(
                                         SPECS[game][0] - SPECS[game][1] + 1,
                                         SPECS[game][0] + 1)),
                                     back=list(range(
                                         SPECS[game][2] - SPECS[game][3] + 1,
                                         SPECS[game][2] + 1)))
            folds[-1] = {"records": records, "actual": changed_last}
            modified = calibrate_profiles(folds, game)
            self.assertEqual(base["profile"], modified["profile"])
            self.assertEqual(base["train_folds"], modified["train_folds"])
            self.assertEqual(base["profiles_considered"], modified["profiles_considered"])
            self.assertTrue(base["validation_independent_of_selection"])
            self.assertFalse(base["multiple_comparisons_adjusted"])
            self.assertEqual(base["edge"], "NO_EDGE")

    def test_partial_exclusion_in_any_area_is_failure(self):
        for game in SPECS:
            profile = dict(front_include=2, front_exclude=2,
                           back_include=0, back_exclude=2)
            report = construct_interval_search(dummy_22(game), game, profile)
            winning = report["tickets"][0]
            valid = score_interval_search(report, winning, game)
            self.assertTrue(valid["all_area_constraints_survived"])
            self.assertEqual(valid["exact_full_jackpot_hits"], 1)
            excluded = report["areas"]["back"]["excluded"][0]
            modified = {**winning, "back": sorted(
                [excluded] + [x for x in winning["back"] if x != excluded][
                    :SPECS[game][3] - 1])}
            # For SSQ blue, substitute the only actual back ball.
            bad = score_interval_search(report, modified, game)
            self.assertFalse(bad["areas"]["back"]["excluded_all_absent"])
            self.assertFalse(bad["all_area_constraints_survived"])
            self.assertEqual(bad["exact_full_jackpot_hits"], 0)

    def test_topk_additive_ranking_matches_full_brute_force(self):
        # Tight constraints make exhaustive reference practical.
        for game in SPECS:
            records = dummy_22(game)
            profile = dict(front_include=3, front_exclude=4,
                           back_include=SPECS[game][3], back_exclude=1)
            result = construct_interval_search(records, game, profile)
            evidence = model_evidence(records, game)
            front = result["areas"]["front"]
            allowed = (n for n in range(1, evidence["front"]["maximum"] + 1)
                       if n not in front["excluded"] and n not in front["required"])
            need = evidence["front"]["picked"] - len(front["required"])
            ranked = []
            for tail in itertools.combinations(list(allowed), need):
                vals = tuple(sorted(front["required"] + list(tail)))
                score = sum(math.log(max(1e-9, evidence["front"]["score"][n]))
                            for n in vals)
                ranked.append((score, vals))
            ranked.sort(key=lambda x: (-x[0], x[1]))
            top8_front = {tuple(t["front"]) for t in result["tickets"]}
            self.assertTrue(top8_front.issubset({x[1] for x in ranked[:8]}))


if __name__ == "__main__":
    unittest.main()
