"""Falsifiable date-only retrospective ablations; synthetic draws, never edge evidence."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from fractions import Fraction
from itertools import combinations
from math import comb
from unittest import TestCase

from research.harness_v46 import core, d2_challenger_lab as lab


ARMS = ("HOT30", "HOT60", "HOT120", "EWMA", "P-MARGIN", "P-RESIDUAL",
        "P-COMBINED", "NULL")
SCOPES = ("train", "validation", "test", "all")
COMPARISONS = (("P-COMBINED", "P-MARGIN"), ("P-COMBINED", "P-RESIDUAL"),
               ("P-RESIDUAL", "P-MARGIN"), ("HOT30", "HOT60"),
               ("HOT120", "HOT60"), ("EWMA", "HOT60"),
               ("P-MARGIN", "HOT60"), ("P-RESIDUAL", "HOT60"),
               ("P-COMBINED", "HOT60"))


def invented_bundle(size=130, *, constant=False):
    """Legal observations with deliberately nonconsecutive issues: no calendar claim."""
    bundle = {}
    for game, pool, k, back_pool, back_k in (("SSQ", 33, 6, 16, 1),
                                            ("DLT", 35, 5, 12, 2)):
        rows = []
        for i in range(size):
            front = list(range(1, k + 1)) if constant else sorted(
                {(i * 7 + j * 5) % pool + 1 for j in range(k)})
            rows.append({"issue": str(2000001 + i * 2),
                         "draw_date": (date(2020, 1, 1) + timedelta(days=i * 3)).isoformat(),
                         "front": front, "back": list(range(1, back_k + 1))})
        bundle[game] = rows
    return bundle


def fraction_pair(history, game, component):
    """Independent exact-rational oracle; never calls lab/core scoring helpers."""
    pool, k = (33, 6) if game == "SSQ" else (35, 5)
    recent = history[-120:]
    singles, together = Counter(), Counter()
    for row in recent:
        singles.update(row["front"])
        together.update(combinations(row["front"], 2))
    scores = {}
    for a, b in combinations(range(1, pool + 1), 2):
        marginal = Fraction(singles[a] + singles[b], 120)
        expected = Fraction(singles[a] * singles[b] * (k - 1), 120 * k)
        residual = (together[(a, b)] - expected) / 320
        scores[(a, b)] = {"P-MARGIN": marginal, "P-RESIDUAL": residual,
                           "P-COMBINED": marginal + residual}[component]
    return min(scores, key=lambda pair: (-scores[pair], pair))


class RecencyAblationTests(TestCase):
    def api(self, name):
        function = getattr(lab, name, None)
        self.assertTrue(callable(function), f"missing date-only research behavior: {name}")
        return function

    def prepare(self, bundle):
        return self.api("prepare_ablation_study")(bundle)

    def evaluate(self, bundle, manifest):
        return self.api("evaluate_ablation_study")(
            bundle, manifest, expected_manifest_sha256=manifest["manifest_sha256"])

    def test_pair_components_match_independent_fraction_oracle_and_hot60_filler(self):
        rank = self.api("ablation_rank")
        for game, history in invented_bundle(140).items():
            counts = Counter(ball for row in history[-60:] for ball in row["front"])
            hot = sorted(range(1, 34 if game == "SSQ" else 36),
                         key=lambda ball: (-counts[ball], ball))
            for arm in ("P-MARGIN", "P-RESIDUAL", "P-COMBINED"):
                pair = fraction_pair(history, game, arm)
                self.assertEqual(rank(history, game, arm),
                                 list(pair) + [ball for ball in hot if ball not in pair])

    def test_fixed_arms_reproduce_incumbents_and_distinct_hot_windows(self):
        rank = self.api("ablation_rank")
        for game, history in invented_bundle(145).items():
            snapshot = {"lottery": game, "draws": history, "target_issue": "2099999"}
            for arm, incumbent in (("HOT60", "hot60"), ("EWMA", "ewma"),
                                    ("P-COMBINED", "pairwise_d2"), ("NULL", "random_null")):
                self.assertEqual(rank(history, game, arm, target_issue="2099999"),
                                 core._model_ranking(snapshot, incumbent))
            for arm, window in (("HOT30", 30), ("HOT120", 120)):
                counts = Counter(ball for row in history[-window:] for ball in row["front"])
                want = sorted(range(1, 34 if game == "SSQ" else 36),
                              key=lambda ball: (-counts[ball], ball))
                self.assertEqual(rank(history, game, arm), want)

    def test_numeric_pair_ties_and_null_require_real_target_issue(self):
        rank = self.api("ablation_rank")
        history = invented_bundle(125, constant=True)["SSQ"][:120]
        for arm in ARMS[:-1]:
            self.assertEqual(rank(history, "SSQ", arm)[:5], [1, 2, 3, 4, 5])
        with self.assertRaises(core.GateError):
            rank(history, "SSQ", "NULL")
        for bad in ("hot30", "UNREGISTERED", ""):
            with self.assertRaises(core.GateError):
                rank(history, "SSQ", bad)
        with self.assertRaises(core.GateError):
            rank(history[:119], "SSQ", "HOT30")

    def test_null_preserves_issue_spelling_even_when_numeric_identity_matches(self):
        rank = self.api("ablation_rank")
        history = invented_bundle(125)["DLT"][:120]
        a = rank(history, "DLT", "NULL", target_issue="07001")
        b = rank(history, "DLT", "NULL", target_issue="7001")
        self.assertNotEqual(a[:2], b[:2])
        self.assertEqual(a, core._model_ranking({"lottery": "DLT", "draws": history,
                                                "target_issue": "07001"}, "random_null"))

    def test_preparation_counts_every_train_validation_target_and_ties_in_fixed_order(self):
        manifest = self.prepare(invented_bundle(125, constant=True))
        for game in ("SSQ", "DLT"):
            self.assertEqual(manifest["splits"][game], {
                "warmup": [0, 120], "train": [120, 123], "validation": [123, 124],
                "test": [124, 125], "all": [120, 125]})
            self.assertEqual(manifest["prepared_target_indices"][game], [120, 121, 122, 123])
            self.assertEqual(manifest["selection"][game], {
                "arm": "HOT30", "validation_d2_hits": 1, "validation_n": 1})
        self.assertEqual(len(manifest["manifest_sha256"]), 64)
        self.assertEqual(set(manifest["source_sha256"]), {"lab", "core", "statistics"})
        self.assertEqual(manifest["completeness"], "NOT_VERIFIED")
        self.assertEqual(manifest["sequence"], "observed-row-contiguous")

    def test_holm_family_is_explicit_complete_and_scope_specific(self):
        manifest = self.prepare(invented_bundle(125))
        want = set()
        for game in ("SSQ", "DLT"):
            for scope in SCOPES:
                want.update(f"{game}:{scope}:{arm}:joint" for arm in ARMS[:-1])
                want.update(f"{game}:{scope}:{left}>{right}:paired" for left, right in COMPARISONS)
        self.assertEqual(len(manifest["family_ids"]), 128)
        self.assertEqual(set(manifest["family_ids"]), want)
        self.assertEqual(len(want), 128)

    def test_test_outcomes_cannot_change_prepared_selection_or_prepared_rows(self):
        original = invented_bundle(130)
        altered = deepcopy(original)
        for rows in altered.values():
            for row in rows[128:]:
                row["front"] = list(range(1, len(row["front"]) + 1))
        left, right = self.prepare(original), self.prepare(altered)
        self.assertEqual(left["selection"], right["selection"])
        self.assertEqual(left["prepared_rows_sha256"], right["prepared_rows_sha256"])
        self.assertNotEqual(left["input_bundle_sha256"], right["input_bundle_sha256"])

    def test_future_suffix_does_not_change_predictions_at_or_before_mutated_target(self):
        original = invented_bundle(130)
        altered = deepcopy(original)
        for rows in altered.values():
            for row in rows[128:]:
                row["front"] = list(range(1, len(row["front"]) + 1))
        a = self.evaluate(original, self.prepare(original))
        b = self.evaluate(altered, self.prepare(altered))
        for left, right in zip(a["rows"], b["rows"]):
            if left["draw_index"] <= 128:
                self.assertEqual(left["rankings"], right["rankings"])
                self.assertEqual(left["training_prefix_sha256"], right["training_prefix_sha256"])

    def test_evaluation_emits_full_targets_d1_to_d5_prefix_custody_and_scope_denominators(self):
        bundle = invented_bundle(130)
        report = self.evaluate(bundle, self.prepare(bundle))
        self.assertEqual(len(report["rows"]), 20)
        for game in ("SSQ", "DLT"):
            rows = [row for row in report["rows"] if row["lottery"] == game]
            self.assertEqual([row["draw_index"] for row in rows], list(range(120, 130)))
            self.assertEqual([row["scope"] for row in rows], ["train"] * 6 + ["validation"] * 2 + ["test"] * 2)
            for row in rows:
                i = row["draw_index"]
                self.assertEqual(row["training_end_index"], i - 1)
                self.assertEqual(row["training_prefix_sha256"], core.digest(bundle[game][:i]))
                actual = set(bundle[game][i]["front"])
                self.assertEqual(set(row["rankings"]), set(ARMS))
                for arm in ARMS:
                    ranking = row["rankings"][arm]
                    self.assertEqual(len(ranking), 5)
                    self.assertEqual(row["pairs"][arm], ranking[:2])
                    self.assertEqual(row["top5_hits"][arm], len(actual.intersection(ranking)))
                    self.assertEqual(row["all_hit"][arm], {
                        f"D{d}": int(set(ranking[:d]).issubset(actual)) for d in range(1, 6)})
            for scope, n in (("train", 6), ("validation", 2), ("test", 2), ("all", 10)):
                stats = report["statistics"][game][scope]
                self.assertEqual(set(stats["arms"]), set(ARMS))
                for arm in ARMS:
                    self.assertEqual(stats["arms"][arm]["n"], n)
                    expected = sum(row["all_hit"][arm]["D2"] for row in rows
                                   if scope == "all" or row["scope"] == scope)
                    self.assertEqual(stats["arms"][arm]["d2_hits"], expected)
                self.assertEqual(len(stats["comparisons"]), 9)
                self.assertEqual(len(stats["correlations"]), 28)
        self.assertEqual(len(report["holm_adjusted_p"]), 128)
        self.assertEqual(report["decision"], "NO_EDGE")
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["D2_EDGE_CONFIRMED"], "NO")
        self.assertEqual(report["ENGINEERING_PASS"], "NOT_YET")
        self.assertEqual(report["RESEARCH_VALID"], "NOT_YET")
        self.assertFalse(report["qualified_prospective"])

    def test_paired_arithmetic_and_correlation_match_hand_calculated_vectors(self):
        paired = self.api("_ablation_paired_statistics")
        # 3 wins, 1 loss, 1 tie; P[Bin(4,.5)>=3] = 5/16.
        result = paired([1, 1, 1, 0, 0], [0, 0, 0, 1, 0])
        self.assertEqual((result["n"], result["wins"], result["losses"]), (5, 3, 1))
        self.assertAlmostEqual(result["p_exact_paired"], 5 / 16, places=14)
        self.assertAlmostEqual(result["rate_difference"], 2 / 5)
        lo, hi = result["rate_difference_ci95_conservative"]
        self.assertLess(lo, 2 / 5)
        self.assertGreater(hi, 2 / 5)
        phi = self.api("_ablation_phi")
        self.assertEqual(phi([1, 0, 1, 0], [1, 0, 1, 0]), 1.0)
        self.assertEqual(phi([1, 0, 1, 0], [0, 1, 0, 1]), -1.0)
        self.assertEqual(phi([1, 1, 0, 0], [1, 0, 1, 0]), 0.0)
        self.assertIsNone(phi([1, 1], [0, 1]))
        with self.assertRaises(core.GateError):
            paired([], [])

    def test_perfect_synthetic_counts_have_exact_fair_tail_and_cp_boundary(self):
        bundle = invented_bundle(125, constant=True)
        report = self.evaluate(bundle, self.prepare(bundle))
        for game, p in (("SSQ", Fraction(15, 528)), ("DLT", Fraction(10, 595))):
            for scope, n in (("train", 3), ("validation", 1), ("test", 1), ("all", 5)):
                stats = report["statistics"][game][scope]["arms"]["HOT30"]
                self.assertEqual(stats["d2_hits"], n)
                self.assertEqual(stats["d2_rate"], 1)
                self.assertAlmostEqual(stats["p_exact_vs_fair"], float(p ** n), places=14)
                self.assertAlmostEqual(stats["d2_ci95"][0], 0.025 ** (1 / n), places=12)
                self.assertEqual(stats["d2_ci95"][1], 1)
                self.assertEqual(stats["p_joint"], max(stats["p_exact_vs_fair"], stats["p_exact_paired_vs_null"]))
        self.assertEqual(report["decision"], "NO_EDGE")

    def test_frozen_manifest_requires_external_recorded_digest(self):
        bundle = invented_bundle(125)
        manifest = self.prepare(bundle)
        evaluate = self.api("evaluate_ablation_study")
        with self.assertRaises((TypeError, core.GateError)):
            evaluate(bundle, manifest)
        with self.assertRaises(core.GateError):
            evaluate(bundle, manifest, expected_manifest_sha256="0" * 64)

    def test_rehashed_selection_family_split_seed_and_source_forgery_fail_closed(self):
        bundle = invented_bundle(125)
        manifest = self.prepare(bundle)
        evaluate = self.api("evaluate_ablation_study")
        for kind in ("selection", "family", "split", "seed", "source", "extra"):
            forged = deepcopy(manifest)
            if kind == "selection":
                forged["selection"]["SSQ"]["arm"] = "EWMA" if forged["selection"]["SSQ"]["arm"] != "EWMA" else "HOT30"
            elif kind == "family":
                forged["family_ids"].pop()
            elif kind == "split":
                forged["splits"]["SSQ"]["test"][0] -= 1
            elif kind == "seed":
                forged["contract"]["null_seed"] = "forged-seed"
            elif kind == "source":
                forged["source_sha256"]["core"] = "0" * 64
            else:
                forged["invented_attestation"] = True
            forged["manifest_sha256"] = core.digest({key: value for key, value in forged.items()
                                                      if key != "manifest_sha256"})
            with self.subTest(kind=kind), self.assertRaises(core.GateError):
                evaluate(bundle, forged, expected_manifest_sha256=forged["manifest_sha256"])

    def test_changed_input_and_changed_runtime_parameters_fail_closed(self):
        bundle = invented_bundle(125)
        manifest = self.prepare(bundle)
        changed = deepcopy(bundle)
        changed["SSQ"][-1]["front"] = [1, 2, 3, 4, 5, 6]
        with self.assertRaises(core.GateError):
            self.evaluate(changed, manifest)
        # A runtime seed alteration must not silently preserve the frozen result.
        old = core.NULL_SEED
        try:
            core.NULL_SEED = "deliberately-changed-runtime-seed"
            with self.assertRaises(core.GateError):
                self.evaluate(bundle, manifest)
        finally:
            core.NULL_SEED = old

    def test_date_only_schema_rejects_invalid_or_ambiguous_observations(self):
        prepare = self.api("prepare_ablation_study")
        for kind in ("alias", "unicode", "duplicate_date", "bad_date", "missing_front",
                     "missing_back", "missing_issue", "missing_draw_date", "short_front", "bool_ball",
                     "out_of_order", "short", "one_game", "timestamp_invented"):
            bad = invented_bundle(125)
            row = bad["SSQ"][3]
            if kind == "alias":
                row["issue"] = "0" + bad["SSQ"][2]["issue"]
            elif kind == "unicode":
                row["issue"] = "２０２０００１"
            elif kind == "duplicate_date":
                row["draw_date"] = bad["SSQ"][2]["draw_date"]
            elif kind == "bad_date":
                row["draw_date"] = "2020-02-30"
            elif kind.startswith("missing_"):
                del row[kind[8:]]
            elif kind == "short_front":
                row["front"].pop()
            elif kind == "bool_ball":
                row["front"][0] = True
            elif kind == "out_of_order":
                bad["SSQ"][2], bad["SSQ"][3] = bad["SSQ"][3], bad["SSQ"][2]
            elif kind == "short":
                bad["SSQ"] = bad["SSQ"][:124]
            elif kind == "one_game":
                del bad["DLT"]
            else:
                row["published_at"] = row["draw_date"] + "T00:00:00Z"
            with self.subTest(kind=kind), self.assertRaises(core.GateError):
                prepare(bad)

    def test_missing_calendar_issue_is_not_certified_as_complete(self):
        # Issue numbers intentionally increase by two: no official calendar was supplied.
        manifest = self.prepare(invented_bundle(125))
        self.assertEqual(manifest["sequence"], "observed-row-contiguous")
        self.assertEqual(manifest["completeness"], "NOT_VERIFIED")
