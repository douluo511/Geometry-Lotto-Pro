"""Synthetic algorithm/fault evidence only; no official or formal admission."""
import copy
import itertools
import json
import unittest

from research.ssq_dlt_v45.competition import (
    CompetitionBlocked, evaluate_registered, holm_adjust, make_plan,
    paired_exact_one_sided,
)
from research.ssq_dlt_v45.models import (
    MODEL_VERSIONS, NULL_MODEL, PRIMARY_MODEL, REGISTRY_SHA256,
    RULES, ModelBlocked, digest, generate, registry, validate_prediction,
)


def history(game="SSQ"):
    count = RULES[game][1]
    return [{"game": game, "issue": str(2026001 + i),
             "front": list(range(i + 1, i + count + 1)),
             "back": [i + 1] if game == "SSQ" else [i + 1, i + 2]}
            for i in range(5)]


def competition_fixture(game="SSQ"):
    issues = ["2026101", "2026102", "2026103"]
    plan = make_plan(game, issues, "2026-08-01T00:00:00Z", "synthetic-independent-A")
    front_count = RULES[game][1]
    rows = []
    for index, issue in enumerate(issues):
        prediction = generate(game, issue, [])
        rows.append({"game": game, "issue": issue, "prediction": prediction,
                     "frozen_at": f"2026-08-{index + 2:02}T00:00:00Z",
                     "draw_at": f"2026-08-{index + 2:02}T13:15:00Z",
                     "draw_front": list(range(index + 1, index + front_count + 1)),
                     "draw_back": [1] if game == "SSQ" else [1, 2]})
    freezes = {row["issue"]: digest(row["prediction"]) for row in rows}
    return rows, plan, freezes


def evaluate(rows=None, plan=None, freezes=None, game="SSQ", plan_sha=None):
    base_rows, base_plan, base_freezes = competition_fixture(game)
    rows = base_rows if rows is None else rows
    plan = base_plan if plan is None else plan
    freezes = base_freezes if freezes is None else freezes
    return evaluate_registered(game, rows, plan, freezes,
                               plan_sha256=digest(plan) if plan_sha is None else plan_sha)


class ResearchModelsTest(unittest.TestCase):
    def test_fixed_registry_is_copy_and_isolated_from_formal_eight(self):
        value = registry()
        self.assertEqual(digest(value), REGISTRY_SHA256)
        value["models"].clear()
        self.assertEqual(len(registry()["models"]), 5)
        self.assertTrue(all(model.startswith("R45-") for model in MODEL_VERSIONS))
        self.assertFalse(set(MODEL_VERSIONS) & {
            "M04", "M05-1", "M05-2", "M05-3", "M05-4", "M05-5", "M06", "M07"})

    def test_all_games_explicit_d1_d5_and_legal_single_tickets(self):
        for game, rule in RULES.items():
            with self.subTest(game=game):
                prediction = generate(game, "2026101", history(game))
                validate_prediction(prediction)
                self.assertEqual(prediction["admission"], "RESEARCH_ONLY")
                self.assertEqual((prediction["formal_A"], prediction["decision"]), (0, "NO_EDGE"))
                self.assertEqual(prediction["primary_d2"], prediction["models"][PRIMARY_MODEL]["dan"]["2"])
                for model in prediction["models"].values():
                    for k in range(1, 6):
                        self.assertEqual(len(set(model["dan"][str(k)])), k)
                    self.assertEqual(len(model["ticket"]["front"]), rule[1])
                    self.assertEqual(len(model["ticket"]["back"]), rule[3])
                    self.assertTrue(set(model["primary_d2"]).issubset(model["ticket"]["front"]))
                self.assertEqual(json.loads(json.dumps(prediction)), prediction)

    def test_fixed_seed_null_is_reproducible_and_issue_domain_separated(self):
        a = generate("SSQ", "2026101", history())
        self.assertEqual(a, generate("SSQ", "2026101", history()))
        b = generate("SSQ", "2026102", history())
        c = generate("SSQ", "2026101", history(), seed=10)
        self.assertNotEqual(a["models"][NULL_MODEL], b["models"][NULL_MODEL])
        self.assertNotEqual(a["models"][NULL_MODEL], c["models"][NULL_MODEL])
        # Independent per-k streams are not silently replaced by D5 prefixes.
        null = a["models"][NULL_MODEL]["dan"]
        self.assertNotEqual(null["2"], null["5"][:2])

    def test_pairwise_d2_is_selected_as_a_pair_instead_of_marginal_prefix(self):
        fronts = [[1, 2, 3, 4, 5, 6]] * 2 + [[1, 7, 8, 9, 10, 11]] * 3 + [[2, 12, 13, 14, 15, 16]] * 3
        rows = [{"game": "SSQ", "issue": str(2026001 + i), "front": front, "back": [1]}
                for i, front in enumerate(fronts)]
        output = generate("SSQ", "2026101", rows)["models"]
        self.assertEqual(output["R45-HOT60"]["dan"]["2"], [1, 2])
        self.assertEqual(output[PRIMARY_MODEL]["dan"]["2"], [1, 7])
        self.assertEqual(output[PRIMARY_MODEL]["primary_d2"], [1, 7])

    def test_unassigned_is_explicitly_untargeted_research_preview(self):
        prediction = generate("SSQ", "UNASSIGNED", history())
        self.assertEqual(prediction["target_status"], "UNASSIGNED_PREVIEW")
        self.assertEqual(prediction["formal_A"], 0)
        with self.assertRaises(CompetitionBlocked):
            make_plan("SSQ", ["UNASSIGNED"], "2026-08-01T00:00:00Z", "series")

    def test_F01_future_and_target_issue_injected_into_history(self):
        for issue in ("2026101", "2026102"):
            rows = history()
            rows[-1]["issue"] = issue
            with self.subTest(issue=issue), self.assertRaisesRegex(ModelBlocked, "F01"):
                generate("SSQ", "2026101", rows)

    def test_duplicate_unsorted_wrong_game_and_bad_numbers_fail_closed(self):
        cases = []
        rows = history(); rows[1]["issue"] = rows[0]["issue"]; cases.append(rows)
        cases.append(list(reversed(history())))
        rows = history(); rows[0]["game"] = "DLT"; cases.append(rows)
        rows = history(); rows[0]["front"][0] = True; cases.append(rows)
        rows = history(); rows[0]["back"] = [17]; cases.append(rows)
        rows = history(); rows[0]["front"] = [1, 1, 3, 4, 5, 6]; cases.append(rows)
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ModelBlocked):
                generate("SSQ", "2026101", rows)
        for bad in (True, -1, "20261018", 1.2):
            with self.subTest(seed=bad), self.assertRaises(ModelBlocked):
                generate("SSQ", "2026101", [], seed=bad)

    def test_post_hoc_primary_and_eight_slot_replacement_fail_closed(self):
        for mutation in ("primary", "global", "formal", "identity", "version", "promotion"):
            p = generate("SSQ", "2026101", [])
            if mutation == "primary": p["models"][PRIMARY_MODEL]["primary_d2"] = [30, 31]
            if mutation == "global": p["primary_d2"] = [30, 31]
            if mutation == "formal": p["models"]["M05-1"] = p["models"].pop(PRIMARY_MODEL)
            if mutation == "identity": del p["models"][NULL_MODEL]
            if mutation == "version": p["models"][PRIMARY_MODEL]["version"] = "after-draw"
            if mutation == "promotion": p["formal_A"] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ModelBlocked):
                validate_prediction(p)


class ResearchCompetitionTest(unittest.TestCase):
    def test_fair_pair_baselines_by_exhaustive_combinations(self):
        for game, (upper, count, _, _) in RULES.items():
            fixed_draw = set(range(1, count + 1))
            all_pairs = list(itertools.combinations(range(1, upper + 1), 2))
            wins = sum(set(pair).issubset(fixed_draw) for pair in all_pairs)
            expected = 15 / 528 if game == "SSQ" else 10 / 595
            self.assertEqual(wins / len(all_pairs), expected)
            self.assertEqual(evaluate(game=game)["D2_random_p0"], expected)

    def test_exact_paired_discordant_tail_and_invalid_counts(self):
        self.assertEqual(paired_exact_one_sided(0, 0), 1)
        self.assertEqual(paired_exact_one_sided(2, 0), 0.25)
        self.assertEqual(paired_exact_one_sided(2, 2), 0.6875)
        self.assertAlmostEqual(paired_exact_one_sided(1000, 0), 2.0 ** -1000)
        for pair in ((True, 1), (-1, 2), (1.5, 2)):
            with self.subTest(pair=pair), self.assertRaises(CompetitionBlocked):
                paired_exact_one_sided(*pair)

    def test_holm_stepdown_monotonic_adjustments(self):
        adjusted = holm_adjust({"d": 0.9, "c": 0.03, "b": 0.02, "a": 0.01})
        for key, value in {"a": 0.04, "b": 0.06, "c": 0.06, "d": 0.9}.items():
            self.assertAlmostEqual(adjusted[key], value)
        self.assertEqual(holm_adjust({"a": 0.0, "b": 1.0}), {"a": 0.0, "b": 1.0})
        for bad in ({}, {"a": float("nan")}, {"a": True}, {"a": 1.01}):
            with self.subTest(bad=bad), self.assertRaises(CompetitionBlocked):
                holm_adjust(bad)

    def test_complete_same_issue_rectangle_and_independent_manual_replay(self):
        rows, plan, freezes = competition_fixture()
        output = evaluate(rows=list(reversed(rows)), plan=plan, freezes=freezes)
        self.assertEqual(output["n"], 3)
        self.assertEqual((output["formal_A"], output["decision"], output["formal_winner"]), (0, "NO_EDGE", None))
        self.assertTrue(output["formal_12_family"].startswith("BLOCKED"))
        for comparison in output["pairwise_vs_null"]:
            pairs = [(set(row["prediction"]["models"][comparison["model"]]["dan"]["2"]).issubset(row["draw_front"]),
                      set(row["prediction"]["models"][NULL_MODEL]["dan"]["2"]).issubset(row["draw_front"]))
                     for row in rows]
            wins = sum(a and not b for a, b in pairs)
            losses = sum(b and not a for a, b in pairs)
            self.assertEqual((comparison["wins"], comparison["losses"]), (wins, losses))
            self.assertEqual(comparison["ties"], 3 - wins - losses)
            self.assertEqual(comparison["p_one_sided"], paired_exact_one_sided(wins, losses))

    def test_missing_duplicate_and_extra_issue_fail_closed(self):
        rows, plan, freezes = competition_fixture()
        cases = [rows[:2], rows + [copy.deepcopy(rows[0])]]
        duplicate = copy.deepcopy(rows); duplicate[1]["issue"] = duplicate[0]["issue"]; cases.append(duplicate)
        for bad in cases:
            with self.subTest(count=len(bad)), self.assertRaises(CompetitionBlocked):
                evaluate(rows=bad, plan=plan, freezes=freezes)

    def test_prediction_sha_and_plan_sha_tampering_fail_closed(self):
        rows, plan, freezes = competition_fixture()
        rows[0]["prediction"]["history_size"] = 100000
        with self.assertRaisesRegex(CompetitionBlocked, "AFTER_FREEZE"):
            evaluate(rows=rows, plan=plan, freezes=freezes)
        with self.assertRaisesRegex(CompetitionBlocked, "PLAN_HASH"):
            evaluate(plan_sha="0" * 64)
        plan["primary_model"] = NULL_MODEL
        with self.assertRaisesRegex(CompetitionBlocked, "PLAN_REPLACED"):
            evaluate(plan=plan)

    def test_null_seed_cannot_change_between_preregistered_issues(self):
        rows, plan, freezes = competition_fixture()
        rows[1]["prediction"] = generate("SSQ", rows[1]["issue"], [], seed=123)
        freezes[rows[1]["issue"]] = digest(rows[1]["prediction"])
        with self.assertRaisesRegex(CompetitionBlocked, "NULL_SEED_CHANGED"):
            evaluate(rows=rows, plan=plan, freezes=freezes)

    def test_model_source_code_change_invalidates_affected_evidence(self):
        rows, plan, freezes = competition_fixture()
        rows[1]["prediction"]["model_source_sha256"] = "0" * 64
        freezes[rows[1]["issue"]] = digest(rows[1]["prediction"])
        with self.assertRaisesRegex(CompetitionBlocked, "MODEL_SOURCE"):
            evaluate(rows=rows, plan=plan, freezes=freezes)

    def test_F01_late_freeze_fake_timezone_and_post_draw_plan_rejected(self):
        for mutation in ("late", "naive", "plan_after", "duplicate_draw"):
            rows, plan, freezes = competition_fixture()
            if mutation == "late": rows[0]["frozen_at"] = rows[0]["draw_at"]
            if mutation == "naive": rows[0]["frozen_at"] = "2026-08-02T00:00:00"
            if mutation == "plan_after": plan["registered_at"] = "2026-08-30T00:00:00Z"
            if mutation == "duplicate_draw": rows[1]["draw_at"] = rows[0]["draw_at"]; rows[1]["frozen_at"] = rows[0]["frozen_at"]
            with self.subTest(mutation=mutation), self.assertRaises(CompetitionBlocked):
                evaluate(rows=rows, plan=plan, freezes=freezes)

    def test_embedded_statistics_do_not_override_recomputed_replay(self):
        rows, plan, freezes = competition_fixture()
        expected = evaluate(rows=rows, plan=plan, freezes=freezes)
        for row in rows:
            row["embedded_statistics"] = {"D2_full": 150, "n": 152, "A": 152}
        actual = evaluate(rows=rows, plan=plan, freezes=freezes)
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
