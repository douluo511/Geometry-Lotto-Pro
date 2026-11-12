"""Algorithm equivalence, adversarial leakage and synthetic performance tests."""
from __future__ import annotations

from copy import deepcopy
import os
import unittest

from research.supercompute import auto_discovery as old
from research.supercompute import formula_acceleration as fast
from research.supercompute import formula_benchmark as bench


class FormulaAccelerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ssq = fast.synthetic_rows("ssq", n=180)
        cls.dlt = fast.synthetic_rows("dlt", n=180)
        cls.legacy = tuple(old.GRAMMAR)
        cls.preview = cls.legacy[:6]

    def test_extended_grammar_312_deduplicated_and_legacy_subset(self):
        self.assertEqual(len(fast.GRAMMAR), 312)
        self.assertEqual(len({x["id"] for x in fast.GRAMMAR}), 312)
        self.assertEqual(len(old.GRAMMAR), 72)
        for expr in old.GRAMMAR:
            self.assertEqual(expr, fast.FORMULA_BY_ID[expr["id"]])
        self.assertTrue(any(x["left"] == "LAG5" for x in fast.GRAMMAR))
        self.assertTrue(any(x["window"] == 64 for x in fast.GRAMMAR))

    def test_numpy_same_72_formula_semantics_as_v1_for_both_games(self):
        for game, rows in (("ssq", self.ssq), ("dlt", self.dlt)):
            targets = [128, 140, 179]
            grid = fast.evaluate_grid(
                rows, game, targets, expressions=self.legacy, backend="numpy")
            self.assertEqual(len(grid), 72)
            for expr in self.legacy:
                for i, t in enumerate(targets):
                    self.assertEqual(
                        grid[expr["id"]][i],
                        old.candidate(rows[:t], game, expr),
                        f"{game}:{expr['id']}:{t}",
                    )

    def test_numba_warm_and_numpy_parity_or_optional_fallback(self):
        for game, rows in (("ssq", self.ssq), ("dlt", self.dlt)):
            exprs = fast.GRAMMAR[::33]
            targets = [151, 177, 180]
            baseline = fast.evaluate_grid(
                rows, game, targets, exprs, backend="numpy")
            if fast.njit is None:
                with self.assertRaisesRegex(RuntimeError, "Numba"):
                    fast.evaluate_grid(
                        rows, game, targets, exprs, backend="numba")
            else:
                jit = fast.evaluate_grid(
                    rows, game, targets, exprs, backend="numba")
                self.assertEqual(baseline, jit)

    def test_snapshot_scoped_cache_no_leakage_or_cross_game_reuse(self):
        base = fast.PrefixMatrix(self.ssq, "ssq", cache_entries=8)
        expr = self.legacy[0]
        first = base.predict(expr, [152], backend="numpy")
        self.assertGreater(base.cache_misses, 0)
        second = base.predict(expr, [152], backend="numpy")
        self.assertEqual(first, second)
        self.assertGreater(base.cache_hits, 0)
        mutated = deepcopy(self.ssq)
        mutated[152]["front"] = [1, 2, 3, 4, 5, 6]
        mutated[152]["back"] = [1]
        mutated[179]["front"] = [3, 4, 5, 6, 7, 8]
        next_matrix = fast.PrefixMatrix(mutated, "ssq")
        self.assertNotEqual(base.source_sha256, next_matrix.source_sha256)
        self.assertEqual(first, next_matrix.predict(expr, [152]))
        # Modifying caller memory after constructing the matrix cannot change it.
        original = base.predict(expr, [153])
        self.ssq[152]["front"] = [2, 3, 4, 5, 6, 7]
        self.assertEqual(original, base.predict(expr, [153]))
        self.assertLessEqual(len(base.cache), 8)

    def test_hard_memory_and_invalid_inputs_block(self):
        expr = self.legacy[0]
        rows = fast.synthetic_rows("ssq", n=150)
        with self.assertRaises(MemoryError):
            fast.PrefixMatrix(rows, "ssq", max_temp_mib=1).predict(
                expr, [120], backend="numpy") if False else self._large_buffer()
        with self.assertRaises(ValueError):
            fast.evaluate_grid(rows, "ssq", [130], self.preview, workers=0)
        with self.assertRaises(ValueError):
            fast.evaluate_grid(rows, "ssq", [130, 130], self.preview)
        with self.assertRaises(ValueError):
            fast.evaluate_grid(rows, "ssq", [151], self.preview)
        with self.assertRaises(ValueError):
            fast.evaluate_grid(rows, "ssq", [1], self.preview)
        changed = deepcopy(rows)
        changed[5]["front"][0] = changed[5]["front"][1]
        with self.assertRaises(ValueError):
            fast.PrefixMatrix(changed, "ssq")
        with self.assertRaises(ValueError):
            fast.PrefixMatrix(rows, "ssq", cache_entries=999)
        changed = dict(expr, id="NOT_REGISTERED")
        with self.assertRaises(ValueError):
            fast.PrefixMatrix(rows, "ssq").predict(changed, [125])

    @staticmethod
    def _large_buffer():
        rows = fast.synthetic_rows("ssq", n=20000)
        matrix = fast.PrefixMatrix(rows, "ssq", max_temp_mib=1)
        matrix.predict(fast.GRAMMAR[0], [19000], backend="numpy")

    def test_windows_spawn_two_processes_match_serial(self):
        if (os.cpu_count() or 1) < 2:
            self.skipTest("only one CPU")
        rows = fast.synthetic_rows("dlt", n=170)
        exprs = self.legacy[:8]
        targets = [137, 169]
        serial = fast.evaluate_grid(rows, "dlt", targets, exprs, workers=1)
        parallel = fast.evaluate_grid(rows, "dlt", targets, exprs, workers=2)
        self.assertEqual(serial, parallel)
        self.assertEqual(list(serial), list(parallel))

    def test_budget_limited_search_and_frozen_holdout_have_no_formal_edge(self):
        rows = fast.synthetic_rows("ssq", n=160)
        report = fast.bounded_formula_search(
            rows, "ssq", [140, 141], seconds=0.05,
            max_temp_mib=16, backend="numba", chunk_size=8)
        self.assertTrue(1 <= report["candidates_evaluated"] <= 312)
        self.assertEqual(report["candidates_evaluated"] % 8, 0)
        self.assertTrue(report["no_holdout_outcomes_used"])
        self.assertEqual(report["formal_A"], 0)
        self.assertTrue(report["cpu_seconds"] >= 0)
        for game in ("ssq", "dlt"):
            cohort = fast.synthetic_rows(game, n=190)
            r = fast.holdout_evaluate(
                cohort, game, validation=20, holdout=20,
                expressions=tuple(x for x in fast.GRAMMAR if x["window"] == 8), backend="numpy")
            self.assertEqual(r["holdout"], 20)
            self.assertEqual(r["expressions_scanned"], 78)
            self.assertEqual(len(r["selected_formula_ids"]), 8)
            self.assertEqual(r["edge"], "NO_EDGE")
            self.assertEqual(r["prospective_scored"], 0)
            counts = r["aggregates_only"]
            paired = r["paired_same_issue"]
            self.assertEqual(
                paired["model_only"] + paired["null_only"] + paired["both"] +
                paired["neither"], 20)
            self.assertEqual(
                paired["model_only"] + paired["both"],
                counts["model"]["d2_hits"])
            self.assertEqual(
                paired["null_only"] + paired["both"],
                counts["research_null"]["d2_hits"])
            self.assertEqual(r["formal_A"], 0)
            self.assertEqual(r["source"], "CALLER_SUPPLIED_OFFLINE_ONLY")

    def test_holdout_cannot_select_based_on_future_outcome(self):
        rows = fast.synthetic_rows("dlt", n=190)
        limited = tuple(x for x in fast.GRAMMAR if x["window"] == 8)
        frozen = fast.training_rank(
            rows[:170], "dlt", list(range(150, 170)),
            expressions=limited)
        changed = deepcopy(rows)
        for i in range(170, len(changed)):
            changed[i]["front"] = [1, 2, 3, 4, 5]
            changed[i]["back"] = [1, 2]
        frozen_again = fast.training_rank(
            changed[:170], "dlt", list(range(150, 170)),
            expressions=limited)
        self.assertEqual(frozen, frozen_again)
        self.assertEqual(len(frozen["selection"]), 8)
        self.assertFalse(frozen["tuning_d2"])

    def test_synthetic_benchmark_and_optional_gpu_probe_do_not_output_tickets(self):
        r = bench.benchmark("ssq", rows_count=145, target_count=4)
        self.assertEqual(r["parity"], "PASS")
        self.assertEqual(r["formula_count"], 72)
        self.assertEqual(r["expanded_formula_count"], 312)
        self.assertGreater(r["baseline_python"]["seconds"], 0)
        self.assertGreater(r["vectorized_numpy"]["seconds"], 0)
        self.assertFalse(r["real_draw_data_processed"])
        self.assertFalse(r["real_prediction_created"])
        self.assertNotIn("tickets", r)
        gpu = bench.gpu_probe()
        self.assertIn("gpu", gpu)
        self.assertIn("worth_using", gpu)

    def test_wilson_and_unverified_baseline_theory(self):
        self.assertEqual(fast.wilson(0, 10)[0], 0)
        self.assertGreater(fast.wilson(10, 10)[0], 0.5)
        self.assertAlmostEqual(
            old.chance("ssq")["dan2_probability"], 15 / 528)
        self.assertAlmostEqual(
            old.chance("dlt")["dan2_probability"], 10 / 595)


if __name__ == "__main__":
    unittest.main()
