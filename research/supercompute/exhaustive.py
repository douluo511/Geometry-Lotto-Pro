"""Actually enumerate every legal SSQ/DLT outcome once, without replacement.

Research-only exact combinatorial experiment. This is NOT a prediction, an
infinite-power lottery solver, an authenticated official draw, or ticket sales.

Memory is bounded: no multi-gigabyte list of tickets is created. Each legal
front/back ticket is visited and folded into an exact hit histogram, and the
stream of ticket bytes gets a SHA256 per disjoint first-front-number partition.
The result is identical with one or four CPU workers.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import time

# Do not import historical formula files; full-space probabilities do not
# depend on which issue or any past results. This avoids target leakage.
SPECS = {"ssq": (33, 6, 16, 1), "dlt": (35, 5, 12, 2)}
MAX_WORKERS = 4


def _comb(n: int, k: int) -> int:
    return math.comb(n, k) if 0 <= k <= n else 0


def canonical_reference(spec):
    _, fp, _, bp = spec
    return {"front": list(range(1, fp + 1)),
            "back": list(range(1, bp + 1)),
            "d2": [1, 2]}


def check_reference(reference, spec):
    """Reject illegal test vectors; the reference is not an endorsed forecast."""
    fm, fp, bm, bp = spec
    if not isinstance(reference, dict):
        raise ValueError("reference must be a mapping")
    for field, length, max_ball in (
        ("front", fp, fm), ("back", bp, bm), ("d2", 2, fm)
    ):
        balls = reference.get(field)
        if (not isinstance(balls, list) or len(balls) != length
                or any(type(x) is not int or not 1 <= x <= max_ball
                       for x in balls)
                or balls != sorted(set(balls))):
            raise ValueError("invalid or noncanonical reference " + field)
    if not set(reference["d2"]).issubset(reference["front"]):
        raise ValueError("D2 must come from reference front")
    return reference


def exact_histogram(spec):
    """Independent closed-form reference for every exact front/back match bin."""
    fm, fp, bm, bp = spec
    hist = {}
    for f_hits in range(fp + 1):
        for b_hits in range(bp + 1):
            fronts = _comb(fp, f_hits) * _comb(fm - fp, fp - f_hits)
            backs = _comb(bp, b_hits) * _comb(bm - bp, bp - b_hits)
            hist[f"{f_hits}/{b_hits}"] = fronts * backs
    return hist


def _partition(args):
    """A prefix group is disjoint from every other prefix group.

    Every possible ticket with smallest front ball == first occurs once.
    Hasher sees all front/back ticket bytes in canonical lexicographic order.
    """
    first, spec, reference = args
    fm, fp, bm, bp = spec
    ref_front = set(reference["front"])
    ref_back = set(reference["back"])
    p0, p1 = reference["d2"]
    backs = [
        (bytes(back), len(ref_back.intersection(back)))
        for back in combinations(range(1, bm + 1), bp)
    ]
    back_count = math.comb(bm, bp)
    counts = [0] * ((fp + 1) * (bp + 1))
    observed = d2_hits = 0
    hasher = hashlib.sha256()
    for tail in combinations(range(first + 1, fm + 1), fp - 1):
        front = (first,) + tail
        f = sum(ball in ref_front for ball in front)
        d2 = p0 in front and p1 in front
        head = bytes(front)
        base = f * (bp + 1)
        for back_bytes, b in backs:
            # No sampling; one visit and hash update for EACH combination.
            hasher.update(head + back_bytes)
            counts[base + b] += 1
            observed += 1
        if d2:
            d2_hits += back_count
    expected = _comb(fm - first, fp - 1) * back_count
    if observed != expected:
        raise RuntimeError("PARTITION_COUNT_MISMATCH")
    return {
        "first_front_ball": first,
        "visited": observed,
        "d2_hits": d2_hits,
        "ticket_stream_sha256": hasher.hexdigest(),
        "counts": counts,
    }


def enumerate_game(game, *, workers=4, spec=None, reference=None):
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError("workers must be 1..4")
    if spec is None:
        if game not in SPECS:
            raise ValueError("unknown game (test fixture is explicit only)")
        spec = SPECS[game]
    fm, fp, bm, bp = spec
    if not (2 <= fp <= fm <= 255 and 1 <= bp <= bm <= 255):
        raise ValueError("unsupported test game / invalid lottery rules")
    source = ("SYNTHETIC_CANONICAL_NO_PREDICTION"
              if reference is None else "USER_PROVIDED_TEST_VECTOR_NOT_PREDICTION")
    reference = check_reference(
        canonical_reference(spec) if reference is None else reference, spec)
    firsts = range(1, fm - fp + 2)
    args = [(first, spec, reference) for first in firsts]
    start = time.perf_counter()
    if workers == 1:
        rows = list(map(_partition, args))
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            rows = list(executor.map(_partition, args))
    hsize = (fp + 1) * (bp + 1)
    tally = [sum(row["counts"][i] for row in rows) for i in range(hsize)]
    observed = sum(row["visited"] for row in rows)
    predicted = math.comb(fm, fp) * math.comb(bm, bp)
    histogram = {
        f"{f}/{b}": tally[f * (bp + 1) + b]
        for f in range(fp + 1) for b in range(bp + 1)
    }
    expected_hist = exact_histogram(spec)
    d2 = sum(row["d2_hits"] for row in rows)
    d2_expected = math.comb(fm - 2, fp - 2) * math.comb(bm, bp)
    full = histogram[f"{fp}/{bp}"]
    if (len(rows) != fm - fp + 1
            or observed != predicted
            or sum(histogram.values()) != predicted
            or histogram != expected_hist
            or d2 != d2_expected
            or full != 1):
        raise RuntimeError("EXHAUSTIVE_COMBINATORIAL_CROSSCHECK_FAILED")
    # Fixed first-ball partition boundaries make the certificate insensitive
    # to process count. The per-partition SHA fingerprints every visited ticket.
    partition_digest = hashlib.sha256(json.dumps(
        [[row["first_front_ball"], row["visited"],
          row["ticket_stream_sha256"]] for row in rows],
        separators=(",", ":")).encode("ascii")).hexdigest()
    return {
        "lottery": game,
        "rules": {"front_pool": fm, "front_pick": fp,
                  "back_pool": bm, "back_pick": bp},
        "reference_ticket": {**reference, "source": source},
        "enumerated_outcomes": observed,
        "expected_outcomes": predicted,
        "entire_space_exhausted": True,
        "all_unique": True,
        "enumeration_mode": "EXACT_EACH_TICKET_VISITED_ONCE_NOT_MONTE_CARLO",
        "histogram_key": "front_matches/back_matches",
        "histogram": histogram,
        "full_ticket_matches": full,
        "full_ticket_probability": full / predicted,
        "d2_matches": d2,
        "d2_probability": d2 / predicted,
        "d2_exact_numerator": d2,
        "d2_exact_denominator": predicted,
        "partitions": [
            {k: v for k, v in row.items() if k != "counts"} for row in rows
        ],
        "partition_digest_sha256": partition_digest,
        "duration_seconds": round(time.perf_counter() - start, 3),
        "formal_A": 0, "edge": "NO_EDGE",
        "meaning": (
            "These are all possible tickets under uniform fair-draw rules. "
            "Even full enumeration cannot reveal the actual future outcome."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=("ssq", "dlt", "both", "test"),
                        default="both")
    parser.add_argument("--workers", choices=(1, 2, 4), type=int, default=4)
    parser.add_argument("--out", type=Path,
                        default=Path("ssqdlt-exhaustive-output"))
    parser.add_argument("--test-small", action="store_true",
                        help="ONLY for automated small-universe test")
    cfg = parser.parse_args(argv)
    if cfg.game == "test" and not cfg.test_small:
        raise ValueError("test requires --test-small")
    if cfg.test_small and cfg.game != "test":
        raise ValueError("--test-small cannot replace a real exhaustiveness run")
    if cfg.game == "test":
        tasks = [("TEST", (7, 3, 4, 2))]
    else:
        names = ("ssq", "dlt") if cfg.game == "both" else (cfg.game,)
        tasks = [(name, SPECS[name]) for name in names]
    output = {}
    for name, spec in tasks:
        output[name.lower()] = enumerate_game(
            name, workers=cfg.workers, spec=spec)
    total = sum(x["enumerated_outcomes"] for x in output.values())
    report = {
        "schema": "SSQDLT_EXHAUSTIVE_OUTCOMES_V1",
        "created_at_utc_untrusted": datetime.now(timezone.utc).isoformat(),
        "github_source_sha": os.environ.get("GITHUB_SHA", "LOCAL_UNVERIFIED"),
        "paid_api_calls": 0,
        "workers": cfg.workers,
        "games": output,
        "total_enumerated_outcomes": total,
        "total_exact_combination_count": sum(
            math.comb(a, b) * math.comb(c, d) for _, (a, b, c, d) in tasks),
        "no_history_required": True,
        "no_target_draw_known": True,
        "hypothetical_reference_only": True,
        "formal_A": 0, "edge": "NO_EDGE",
        "release": "RESEARCH_ONLY_NOT_OFFICIAL_V47_NOT_A_WON_TICKET",
    }
    if total != report["total_exact_combination_count"]:
        raise RuntimeError("BOTH_GAMES_COUNT_MISMATCH")
    cfg.out.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(report, ensure_ascii=False,
                      sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    (cfg.out / "report.json").write_bytes(raw)
    h = hashlib.sha256(raw).hexdigest()
    (cfg.out / "report.sha256").write_text(h + "  report.json\n", encoding="ascii")
    print(json.dumps({
        "report_sha256": h, "total_outcomes": total,
        "enumerated": {k: v["enumerated_outcomes"] for k, v in output.items()},
        "edge": "NO_EDGE", "formal_A": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
