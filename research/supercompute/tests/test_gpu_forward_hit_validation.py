"""Synthetic-only adversarial full GPU and private hit-rate validation tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute import formula_acceleration as cpu
from research.supercompute import formula_torch_full as gpu
from research.supercompute import private_hit_validation as hits


class FullPipelineGpuParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows_ssq = cpu.synthetic_rows("ssq", n=185)
        cls.rows_dlt = cpu.synthetic_rows("dlt", n=185)
        cls.exprs = tuple(cpu.GRAMMAR[i] for i in range(0, 312, 31))

    def test_numpy_cpu_exact_ticket_parity_for_both_games(self):
        if not gpu.torch_available("cpu"):
            self.skipTest("PyTorch not installed; CPU Torch parity UNVERIFIED")
        for game, rows in (("ssq", self.rows_ssq), ("dlt", self.rows_dlt)):
            targets = [155, 178, 185]
            baseline = cpu.evaluate_grid(
                rows, game, targets, self.exprs, backend="numpy")
            observed = gpu.evaluate_torch_grid(
                rows, game, targets, self.exprs,
                device="cpu", batch_size=4)
            self.assertEqual(dict(baseline), observed)

    def test_gpu_cannot_be_falsely_claimed_when_unavailable(self):
        if not gpu.torch_available("cuda"):
            with self.assertRaisesRegex(RuntimeError, "GPU_UNVERIFIED"):
                gpu.evaluate_torch_grid(
                    self.rows_ssq, "ssq", [180], self.exprs[:2],
                    device="cuda")
        else:
            # A machine WITH CUDA must run real device execution and parity.
            baseline = cpu.evaluate_grid(
                self.rows_ssq, "ssq", [179, 185], self.exprs[:8])
            observed = gpu.evaluate_torch_grid(
                self.rows_ssq, "ssq", [179, 185], self.exprs[:8],
                device="cuda", batch_size=4)
            self.assertEqual(dict(baseline), observed)

    def test_target_outcome_and_future_cannot_affect_same_prediction(self):
        if not gpu.torch_available("cpu"):
            self.skipTest("PyTorch unavailable")
        a = self.rows_dlt
        t = 174
        before = gpu.evaluate_torch_grid(
            a, "dlt", [t], self.exprs[:6], device="cpu")
        b = deepcopy(a)
        for i in range(t, len(b)):
            b[i]["front"] = [1, 2, 3, 4, 5]
            b[i]["back"] = [1, 2]
        after = gpu.evaluate_torch_grid(
            b, "dlt", [t], self.exprs[:6], device="cpu")
        self.assertEqual(before, after)

    def test_device_validation_and_bounded_temp_alloc(self):
        with self.assertRaises(ValueError):
            gpu.evaluate_torch_grid(
                self.rows_ssq, "ssq", [185], self.exprs, device="tpu")
        if not gpu.torch_available("cpu"):
            self.skipTest("PyTorch unavailable")
        with self.assertRaises(MemoryError):
            gpu.evaluate_torch_grid(
                self.rows_ssq, "ssq", [185], cpu.GRAMMAR[:64],
                batch_size=64, max_temp_mib=16)
        with self.assertRaises(ValueError):
            gpu.evaluate_torch_grid(
                self.rows_ssq, "ssq", [185, 185], self.exprs[:2])

    def test_full_synthetic_pipeline_benchmark_does_not_report_real_edge(self):
        r = gpu.benchmark(
            "ssq", history=155, targets=4, formula_count=18, repeats=2)
        self.assertEqual(r["edge"], "NO_EDGE")
        self.assertEqual(r["formal_A"], 0)
        self.assertFalse(r["real_draws_used"])
        self.assertNotIn("candidate", r)
        if gpu.torch_available("cpu"):
            self.assertEqual(r["cpu_parity"], "PASS")
            self.assertIn("median_seconds", r["torch_cpu_end_to_end"])
        if not gpu.torch_available("cuda"):
            self.assertEqual(r["gpu_improves_full_pipeline"], "UNVERIFIED")


class PrivateHistoricalPairedTests(unittest.TestCase):
    def test_private_hit_aggregates_and_paired_matching(self):
        a = cpu.synthetic_rows("ssq", 260)
        b = cpu.synthetic_rows("dlt", 260)
        result = hits.compare_both(
            a, b, validation=20, holdout=20,
            backend="numpy", expanded=False)
        self.assertEqual(result["predeclared_family_size"], 4)
        self.assertEqual(result["formal_A"], 0)
        self.assertEqual(result["edge"], "NO_EDGE")
        self.assertFalse(result["predictive_improvement_verified"])
        self.assertEqual(set(result["games"]), {"ssq", "dlt"})
        for game, game_result in result["games"].items():
            self.assertEqual(game_result["holdout_count"], 20)
            self.assertEqual(game_result["expanded_formula_count"], 78)
            self.assertEqual(game_result["formal_A"], 0)
            self.assertEqual(
                set(game_result["arms"]),
                {"FORMULA_V3", "FORMULA_V2", "FROZEN_RESEARCH_NULL"})
            for paired in game_result["comparisons"].values():
                self.assertEqual(paired["n"], 20)
                self.assertEqual(
                    sum(paired[k] for k in (
                        "first_only", "second_only", "both", "neither")), 20)
                self.assertGreaterEqual(
                    paired["holm_four_test_exploratory"],
                    paired["p_exact_two_sided_exploratory"])

    def test_private_input_cannot_be_in_git_or_be_corrupt(self):
        with self.assertRaisesRegex(ValueError, "OUTSIDE"):
            hits.load_private(hits.ROOT / "SSQ/SSQ/resources/official_seed.json",
                              "ssq")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text('{"game":"ssq","draws":[],"draws":[]}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                hits.load_private(path, "ssq")
            path.write_text('{"game":"ssq","draws":[]}')
            with self.assertRaises(ValueError):
                hits.load_private(path, "ssq")

    def test_private_synthetic_fixture_recognized_but_never_authenticated(self):
        rows = cpu.synthetic_rows("ssq", n=130)
        day = date(2026, 1, 1)
        for i, r in enumerate(rows):
            r["draw_date"] = (day + timedelta(days=i)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "historical.json"
            path.write_text(json.dumps(
                {"game": "ssq", "draws": rows}), encoding="utf-8")
            actual, status = hits.load_private(path, "ssq")
            self.assertEqual(actual, rows)
            self.assertEqual(status["record_count"], 130)
            self.assertEqual(
                status["official_source_authentication"],
                "UNVERIFIED_CALLER_SUPPLIED")


if __name__ == "__main__":
    unittest.main()
