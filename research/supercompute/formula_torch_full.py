"""Optional full-formula PyTorch backend with CPU/CUDA exact-ticket parity.

No actual lottery history, prediction or scoring output is stored by this
module. CUDA is disabled rather than silently pretending to run on a GPU
when the device is not available. A fair lottery is not made predictable
by GPU acceleration.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

import numpy as np

from research.supercompute import auto_discovery as legacy
from research.supercompute import formula_acceleration as cpu
from research.supercompute.engine import SPECS

try:
    import torch
    from torch.nn.functional import one_hot
except ImportError:
    torch = None
    one_hot = None

PROTOCOL = "FORMULA_GPU_FULL_PIPELINE_SYNTHETIC_ONLY_V1"
MAX_BATCH = 64
DEFAULT_MEMORY_MIB = 256


def torch_available(device="cpu"):
    if torch is None:
        return False
    if device == "cpu":
        return True
    if device == "cuda":
        return bool(torch.cuda.is_available())
    return False


def _device(device):
    if device not in ("cpu", "cuda"):
        raise ValueError("only CPU or CUDA are supported")
    if torch is None:
        if device == "cuda":
            raise RuntimeError("GPU_UNVERIFIED: PyTorch is not installed")
        raise RuntimeError("PyTorch unavailable")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("GPU_UNVERIFIED: CUDA device unavailable")
    return torch.device(device)


def _sync(device):
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _raw_atom(name, area, issues):
    size, width = area.shape
    if name == "ISSUE":
        return torch.cat((torch.zeros(1, device=area.device, dtype=torch.int64),
                          issues + 1)).unsqueeze(1).expand(size + 1, width)
    if name not in cpu.ATOMS or not name.startswith("LAG"):
        raise ValueError("invalid expression atom")
    lag = int(name[3:])
    out = torch.zeros((size + 1, width), device=area.device, dtype=torch.int64)
    out[lag:] = area[:size + 1 - lag] - 1
    return out


def _required_bytes(batch, n, width, modulus):
    # Four full copies: onehot, prefix, gathered left & right/predictions,
    # plus a conservative safety margin for backend temporary allocation.
    return int(batch * (n + 1) * width * modulus * 8 * 4 +
               batch * (n + 1) * width * 8 * 8)


def evaluate_torch_grid(rows, game, targets, expressions, *,
                        device="cpu", batch_size=12, max_temp_mib=DEFAULT_MEMORY_MIB):
    """Batch complete formulas, residual fitting and deterministic ticket completion.

    For every target t, the residual mode uses only j in [max(5,t-W),t).
    Row t is deliberately never an argument to the choice for target t.
    """
    selected_device = _device(device)
    if (game not in SPECS or not 1 <= len(expressions) <= len(cpu.GRAMMAR)
            or type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH
            or type(max_temp_mib) is not int or not 16 <= max_temp_mib <= 2048):
        raise ValueError("invalid model, batch or memory budget")
    if len({x["id"] for x in expressions}) != len(expressions):
        raise ValueError("duplicate formula identities")
    for expr in expressions:
        if expr["id"] not in cpu.FORMULA_BY_ID or cpu.FORMULA_BY_ID[expr["id"]] != expr:
            raise ValueError("unknown or mutated formula")
    cpu._validate_rows(rows, game)
    ts = list(targets)
    if not ts or len(set(ts)) != len(ts) or any(
            type(t) is not int or not 70 <= t <= len(rows) for t in ts):
        raise ValueError("invalid chronological target identities")
    # Establish all legal shapes before allocating a CUDA tensor.
    spec = SPECS[game]
    n = len(rows)
    planned = max(_required_bytes(min(batch_size, len(expressions)),
                                  n, spec[i + 1], spec[i])
                  for i in (0, 2))
    if planned > max_temp_mib * 1048576:
        raise MemoryError("formula GPU/CPU temporary memory budget exceeded")
    if selected_device.type == "cuda":
        free_bytes, total_bytes = torch.cuda.mem_get_info(selected_device)
        if planned > int(0.55 * free_bytes):
            raise MemoryError("insufficient available CUDA device memory")

    issues = torch.tensor(
        [int(row["issue"]) for row in rows],
        dtype=torch.int64, device=selected_device)
    indices = torch.tensor(ts, dtype=torch.int64, device=selected_device)
    widths = {
        "front": torch.tensor([row["front"] for row in rows],
                              dtype=torch.int64, device=selected_device),
        "back": torch.tensor([row["back"] for row in rows],
                             dtype=torch.int64, device=selected_device),
    }
    output = {}
    for first in range(0, len(expressions), batch_size):
        batch = expressions[first:first + batch_size]
        windows = torch.tensor(
            [expr["window"] for expr in batch],
            device=selected_device, dtype=torch.int64)
        area_result = {}
        for area in ("front", "back"):
            draws = widths[area]
            modulus = spec[0] if area == "front" else spec[2]
            atoms = {name: _raw_atom(name, draws, issues) for name in cpu.ATOMS}
            raw_exprs = []
            for expr in batch:
                a = atoms[expr["left"]]
                op = expr["op"]
                if op == "ATOM":
                    values = a
                elif op == "DOUBLE":
                    values = 2 * a
                else:
                    b = atoms[expr["right"]]
                    if op == "ADD":
                        values = a + b
                    elif op == "SUB":
                        values = a - b
                    elif op == "MUL":
                        values = a * b
                    else:
                        raise ValueError("unregistered operator")
                raw_exprs.append(values % modulus)
            raw = torch.stack(raw_exprs, dim=0)
            residue = (
                draws.unsqueeze(0) - 1 - raw[:, :n, :]
            ) % modulus
            # Historical cumulative histogram, with prefix[0]=zero.
            histogram = one_hot(residue, num_classes=modulus).to(torch.int64)
            prefix = torch.cat((
                torch.zeros((len(batch), 1, draws.shape[1], modulus),
                            device=selected_device, dtype=torch.int64),
                torch.cumsum(histogram, dim=1),
            ), dim=1)
            begins = torch.maximum(
                torch.tensor(cpu.MIN_LAG, device=selected_device),
                indices.unsqueeze(0) - windows.unsqueeze(1),
            )
            gather_dims = (len(batch), len(ts), draws.shape[1], modulus)
            count_begin = torch.gather(
                prefix, dim=1,
                index=begins[:, :, None, None].expand(gather_dims))
            count_end = prefix.index_select(dim=1, index=indices)
            # argmax returns lowest residue index on ties, as original V1.
            offsets = torch.argmax(count_end - count_begin, dim=3)
            projected = 1 + (raw.index_select(1, indices) + offsets) % modulus
            area_result[area] = projected.to("cpu").tolist()
            del raw, residue, histogram, prefix, count_begin, count_end
        # Identical CPU ticket de-duplication and deterministic SHA tie-breaker.
        for i, expr in enumerate(batch):
            tickets = []
            for j, target in enumerate(ts):
                ticket = {}
                for area, maximum, count in (("front", spec[0], spec[1]),
                                              ("back", spec[2], spec[3])):
                    balls = legacy.complete_balls(
                        area_result[area][i][j], maximum, count,
                        game=game, asof=str(rows[target - 1]["issue"]),
                        formula_id=expr["id"], area=area)
                    ticket[area] = sorted(balls)
                    if area == "front":
                        ticket["d2_pair"] = sorted(balls[:2])
                tickets.append(ticket)
            output[expr["id"]] = tickets
    _sync(selected_device)
    return output


def _clock(fn, device="cpu", repeats=3):
    elapsed = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        if device == "cuda" and torch is not None:
            torch.cuda.synchronize()
        elapsed.append(time.perf_counter() - start)
    return result, {
        "median_seconds": round(statistics.median(elapsed), 6),
        "min_seconds": round(min(elapsed), 6),
        "max_seconds": round(max(elapsed), 6),
        "repetitions": repeats,
    }


def benchmark(game="ssq", *, history=190, targets=8,
              formula_count=72, repeats=3, batch_size=12):
    """End-to-end synthetic comparison, including host↔device + completion."""
    if (game not in SPECS or not 150 <= history <= 500 or
            not 4 <= targets <= 30 or not 2 <= repeats <= 7 or
            not 1 <= formula_count <= len(cpu.GRAMMAR)):
        raise ValueError("invalid synthetic GPU benchmark workload")
    rows = cpu.synthetic_rows(game, n=history)
    ts = list(range(history - targets, history))
    exprs = cpu.GRAMMAR[:formula_count]
    reference, base = _clock(
        lambda: cpu.evaluate_grid(rows, game, ts, exprs, backend="numpy"), repeats=repeats)
    if torch is None:
        return {
            "protocol": PROTOCOL, "game": game, "numpy": base,
            "torch_cpu": "NOT_INSTALLED", "cuda": "UNVERIFIED",
            "gpu_improves_full_pipeline": "UNVERIFIED",
            "all_outputs_equal": "NOT_TESTED_WITH_TORCH",
            "real_draws_used": False, "formal_A": 0, "edge": "NO_EDGE",
        }
    # First call may create runtime kernels; do not include it in warmed batch.
    warm = evaluate_torch_grid(rows, game, ts, exprs[:1], device="cpu",
                               batch_size=batch_size)
    observed_cpu, cpu_result = _clock(
        lambda: evaluate_torch_grid(
            rows, game, ts, exprs, device="cpu", batch_size=batch_size),
        repeats=repeats)
    if dict(reference) != observed_cpu:
        raise AssertionError("PyTorch CPU output differs from canonical NumPy")
    gpu_result = "UNVERIFIED_NO_CUDA_HARDWARE"
    gpu_better = "UNVERIFIED"
    if torch.cuda.is_available():
        # Actual CUDA dispatch, full source transfer and CPU completion included.
        evaluate_torch_grid(
            rows, game, ts, exprs[:1], device="cuda", batch_size=batch_size)
        observed_cuda, gpu_result = _clock(
            lambda: evaluate_torch_grid(
                rows, game, ts, exprs, device="cuda", batch_size=batch_size),
            device="cuda", repeats=repeats)
        if observed_cuda != observed_cpu:
            raise AssertionError("CUDA and CPU ticket predictions disagree")
        gpu_better = bool(
            gpu_result["median_seconds"] < base["median_seconds"] and
            gpu_result["median_seconds"] < cpu_result["median_seconds"])
    return {
        "protocol": PROTOCOL, "game": game, "synthetic_history": history,
        "synthetic_targets": targets, "formula_count": formula_count,
        "numpy_end_to_end": base,
        "torch_cpu_end_to_end": cpu_result,
        "cuda_end_to_end": gpu_result,
        "gpu_improves_full_pipeline": gpu_better,
        "cpu_parity": "PASS",
        "gpu_parity": ("PASS" if isinstance(gpu_better, bool)
                       else "UNVERIFIED"),
        "real_draws_used": False, "formal_A": 0,
        "prediction_hit_rate_improved": "UNVERIFIED", "edge": "NO_EDGE",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game", choices=("ssq", "dlt", "both"), default="both")
    p.add_argument("--history", type=int, default=190)
    p.add_argument("--targets", type=int, default=8)
    p.add_argument("--formulas", type=int, default=72)
    p.add_argument("--repeats", type=int, default=3)
    opt = p.parse_args(argv)
    for game in (("ssq", "dlt") if opt.game == "both" else (opt.game,)):
        result = benchmark(game, history=opt.history, targets=opt.targets,
                           formula_count=opt.formulas, repeats=opt.repeats)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
