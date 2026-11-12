"""Synthetic-only CPU/GPU and cProfile benchmark: no lottery data in CI.

Run: python -m research.supercompute.formula_benchmark --game both
Reports aggregate timings and function names only, never candidate numbers.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import math
import os
import platform
import pstats
import time
import tracemalloc

import numpy as np

from research.supercompute import auto_discovery as v1
from research.supercompute import formula_acceleration as accel


def timed(func):
    tracemalloc.start()
    t0 = time.perf_counter()
    output = func()
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return output, {"seconds": round(elapsed, 6),
                    "peak_python_alloc_mib": round(peak / 1048576, 4)}


def profile_bottleneck(fn):
    profiler = cProfile.Profile()
    profiler.enable()
    fn()
    profiler.disable()
    buff = io.StringIO()
    pstats.Stats(profiler, stream=buff).strip_dirs().sort_stats(
        "cumulative").print_stats(6)
    # Names/timings only; function arguments and values are never profiled.
    return buff.getvalue().splitlines()[-9:]


def gpu_probe():
    """Torch CPU/GPU *kernel probe*; not equivalent to end-to-end search."""
    try:
        import torch
    except ImportError:
        return {"torch": "NOT_INSTALLED", "gpu": "UNVERIFIED",
                "worth_using": "UNKNOWN_NO_GPU_BENCHMARK"}
    result = {
        "torch": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "gpu": "UNVERIFIED",
        "worth_using": "UNKNOWN_NO_GPU_BENCHMARK",
    }
    src = np.random.default_rng(413).integers(
        0, 200, size=(32768, 32), dtype=np.int64)
    np_start = time.perf_counter()
    numpy_result = np.remainder(src * 3 + 7, 35)
    result["numpy_cpu_kernel_seconds"] = round(time.perf_counter() - np_start, 6)
    def measure(device):
        t0 = time.perf_counter()
        x = torch.from_numpy(src).to(device)
        if device == "cuda":
            torch.cuda.synchronize()
        transfer = time.perf_counter() - t0
        for _ in range(3):
            y = (x * 3 + 7) % 35
            if device == "cuda":
                torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(4):
            y = (x * 3 + 7) % 35
        if device == "cuda":
            torch.cuda.synchronize()
        kernel = (time.perf_counter() - start) / 4
        t0 = time.perf_counter()
        check = y.to("cpu").numpy()
        if device == "cuda":
            torch.cuda.synchronize()
        back = time.perf_counter() - t0
        if not np.array_equal(check, numpy_result):
            raise AssertionError("GPU kernel numerical parity failed")
        return {
            "initial_copy_seconds": round(transfer, 6),
            "steady_kernel_seconds": round(kernel, 6),
            "copy_back_seconds": round(back, 6),
            "total_copy_plus_kernel_seconds": round(transfer + kernel + back, 6),
        }
    result["torch_cpu_probe"] = measure("cpu")
    if torch.cuda.is_available():
        try:
            result["torch_cuda_probe"] = measure("cuda")
            result["gpu"] = "KERNEL_PROBED_ONLY"
            result["worth_using"] = (
                "BENCHMARK_COMPARISON_ONLY_NOT_FULL_FORMULA_ENGINE")
        except (RuntimeError, AssertionError) as exc:
            result["gpu"] = "FAILED_KERNEL_CHECK"
            result["error_kind"] = type(exc).__name__
    return result


def benchmark(game, *, rows_count=180, target_count=8, parallel=False,
              gpu=False):
    rows = accel.synthetic_rows(game, n=rows_count)
    targets = list(range(rows_count - target_count, rows_count))
    expressions = tuple(v1.GRAMMAR)
    def reference():
        return {
            expr["id"]: [v1.candidate(rows[:t], game, expr)
                         for t in targets]
            for expr in expressions
        }
    def numpy():
        return accel.evaluate_grid(
            rows, game, targets, expressions,
            backend="numpy", workers=1)
    legacy, baseline = timed(reference)
    vectorized, fast = timed(numpy)
    if legacy != vectorized:
        raise AssertionError("optimized 72-formula baseline parity mismatch")
    result = {
        "game": game, "workload": "DETERMINISTIC_SYNTHETIC_ONLY",
        "n_history": rows_count, "targets": target_count,
        "formula_count": len(expressions),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "baseline_python": baseline,
        "vectorized_numpy": fast,
        "numpy_speedup_over_reference": round(
            baseline["seconds"] / max(fast["seconds"], 1e-12), 3),
        "parity": "PASS",
        "top_python_baseline_functions": profile_bottleneck(
            lambda: [v1.candidate(rows[:t], game, expr)
                     for expr in expressions[:4] for t in targets]),
    }
    if accel.njit is None:
        result["numba"] = "NOT_INSTALLED"
    else:
        # First call may compile OR load an existing disk JIT cache.
        _, compile_measure = timed(lambda: accel.evaluate_grid(
            rows, game, targets, expressions[:1],
            backend="numba", workers=1))
        warmed, jit = timed(lambda: accel.evaluate_grid(
            rows, game, targets, expressions,
            backend="numba", workers=1))
        if warmed != legacy:
            raise AssertionError("Numba parity mismatch")
        result["numba_first_invocation_possible_compile_or_cache_load"] = compile_measure
        result["numba_warm"] = jit
        result["numba_speedup_over_reference"] = round(
            baseline["seconds"] / max(jit["seconds"], 1e-12), 3)
    if parallel and os.cpu_count() and os.cpu_count() >= 2:
        parallel_result, ptime = timed(lambda: accel.evaluate_grid(
            rows, game, targets, expressions, backend="numpy",
            workers=2))
        if parallel_result != legacy:
            raise AssertionError("ProcessPool spawn parity mismatch")
        result["spawn_two_processes"] = ptime
        result["spawn_speedup_over_reference"] = round(
            baseline["seconds"] / max(ptime["seconds"], 1e-12), 3)
    result["expanded_formula_count"] = len(accel.GRAMMAR)
    _, expanded = timed(lambda: accel.evaluate_grid(
        rows, game, targets, accel.GRAMMAR,
        backend="numba" if accel.njit is not None else "numpy",
        workers=1))
    result["expanded_grammar_benchmark"] = expanded
    result["expanded_tickets_per_second_synthetic"] = round(
        len(accel.GRAMMAR) * target_count /
        max(expanded["seconds"], 1e-12), 2)
    if gpu:
        result["torch_optional_gpu_probe"] = gpu_probe()
    result.update({
        "real_draw_data_processed": False,
        "real_prediction_created": False,
        "formal_A": 0, "edge": "NO_EDGE",
        "live_prediction_edge_validated": False,
    })
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game", choices=("ssq", "dlt", "both"), default="both")
    p.add_argument("--history", type=int, default=180)
    p.add_argument("--targets", type=int, default=8)
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--gpu", action="store_true")
    args = p.parse_args(argv)
    if not 130 <= args.history <= 500 or not 4 <= args.targets <= 30:
        p.error("bounded synthetic benchmark only")
    games = ("ssq", "dlt") if args.game == "both" else (args.game,)
    for game in games:
        report = benchmark(
            game, rows_count=args.history, target_count=args.targets,
            parallel=args.parallel, gpu=args.gpu)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
