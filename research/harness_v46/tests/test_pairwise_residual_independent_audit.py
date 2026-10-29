"""Isolated adversarial P-COMBINED vs P-MARGIN audit on frozen public history.

Research only. Historical labels are already public. No authenticated as-of,
trusted predraw TSA, complete future roster, official admission or formal edge.
Never changes the registered six models, fixed Random NULL or ledger.
"""
from __future__ import annotations

import gzip
import json
import unittest
from collections import Counter
from itertools import combinations
from pathlib import Path

from research.harness_v46 import core, d2_challenger_lab as lab, statistics

ROOT = Path(__file__).resolve().parents[1] / "evidence" / "recency_ablation_20261024"
FROZEN_MANIFEST_SHA = "5620b85c521b03f67ac9066858a7f739b3e1e4eb82a2beda17fed91f838ce9b1"
FROZEN_INPUT_SHA = "3d4399da45529ab458ae926dad682cf01a6a2c4af3e4780bd8bbee6df1c0792c"


def independent_integer_pair(history, game, component):
    """Re-derive pair scores using integers, independent of FLOAT core scoring.

    Multiply P-COMBINED by n*k*(n+tau), a positive constant:
    (count_a+count_b)*k*(n+tau) + pair_count*n*k
      - count_a*count_b*(k-1).
    Components are marginal count sum and centered co-occurrence numerator.
    """
    n, tau = 120, 200
    k = core.RULES[game]["front"]
    pool = core.RULES[game]["pool"]
    tail = history[-n:]
    counts = Counter(ball for d in tail for ball in d["front"])
    pair_counts = Counter(pair for d in tail for pair in combinations(d["front"], 2))
    chosen, greatest = None, None
    for a, b in combinations(range(1, pool + 1), 2):
        margin = (counts[a] + counts[b]) * k * (n + tau)
        residual = pair_counts[(a, b)] * n * k - counts[a] * counts[b] * (k - 1)
        score = (margin + residual if component == "P-COMBINED" else
                 margin if component == "P-MARGIN" else residual)
        # Ascending combinations and strict > preserve lexicographic tie-break.
        if greatest is None or score > greatest:
            chosen, greatest = [a, b], score
    return chosen


class PairwiseResidualIndependentAudit(unittest.TestCase):
    def test_frozen_historical_test_split_independent_pair_score_and_increment(self):
        bundle = json.loads(gzip.decompress((ROOT / "observations.json.gz").read_bytes()))
        manifest = json.loads(gzip.decompress((ROOT / "frozen_manifest.json.gz").read_bytes()))
        unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        self.assertEqual(manifest["manifest_sha256"], FROZEN_MANIFEST_SHA)
        self.assertEqual(core.digest(unsigned), FROZEN_MANIFEST_SHA)
        self.assertEqual(manifest["input_bundle_sha256"], FROZEN_INPUT_SHA)
        self.assertEqual(core.digest(bundle), FROZEN_INPUT_SHA)
        splits = lab._validate_ablation_bundle(bundle)
        self.assertEqual(splits, manifest["splits"])

        report = {
            "experiment": "PAIRWISE_RESIDUAL_INDEPENDENT_HISTORICAL_TEST_V1",
            "manifest_sha256": FROZEN_MANIFEST_SHA,
            "input_bundle_sha256": FROZEN_INPUT_SHA,
            "data_class": "PUBLIC_HISTORICAL_DATE_ONLY",
            "split": "FROZEN_HISTORICAL_TEST_ONLY",
            "null_seed_id": core.NULL_SEED,
            "games": {},
            "prospective_verified": False,
            "formal_A": 0,
            "decision": "NO_EDGE",
        }
        for game in ("SSQ", "DLT"):
            draws = bundle[game]
            start, stop = splits[game]["test"]
            counts = {arm: 0 for arm in ("P-COMBINED", "P-MARGIN", "P-RESIDUAL", "NULL")}
            same_margin = same_residual = different_margin = margin_wins = margin_losses = 0
            null_wins = null_losses = 0
            for i in range(start, stop):
                prior, target = draws[i - 120:i], draws[i]
                pred = {}
                for arm in ("P-COMBINED", "P-MARGIN", "P-RESIDUAL"):
                    independently = independent_integer_pair(prior, game, arm)
                    observed = (core._model_ranking({
                        "lottery": game, "draws": prior, "target_issue": target["issue"]
                    }, "pairwise_d2")[:2] if arm == "P-COMBINED"
                                else lab.ablation_rank(prior, game, arm)[:2])
                    self.assertEqual(observed, independently,
                                     msg=f"{game} issue={target['issue']} arm={arm}")
                    pred[arm] = independently
                pred["NULL"] = core._model_ranking({
                    "lottery": game, "draws": prior, "target_issue": target["issue"]
                }, "random_null")[:2]
                actual = set(target["front"])
                hits = {arm: int(set(pair).issubset(actual)) for arm, pair in pred.items()}
                for arm in counts:
                    counts[arm] += hits[arm]
                same_margin += set(pred["P-COMBINED"]) == set(pred["P-MARGIN"])
                same_residual += set(pred["P-COMBINED"]) == set(pred["P-RESIDUAL"])
                different_margin += set(pred["P-COMBINED"]) != set(pred["P-MARGIN"])
                margin_wins += hits["P-COMBINED"] > hits["P-MARGIN"]
                margin_losses += hits["P-COMBINED"] < hits["P-MARGIN"]
                null_wins += hits["P-COMBINED"] > hits["NULL"]
                null_losses += hits["P-COMBINED"] < hits["NULL"]
            n = stop - start
            fair = core.RULES[game]["d2"]
            report["games"][game] = {
                "n": n,
                "fair_d2": fair,
                "d2_hits": counts,
                "d2_rates": {k: v / n for k, v in counts.items()},
                "combined_same_pair_as_margin": same_margin,
                "combined_same_pair_as_residual": same_residual,
                "combined_differs_from_margin": different_margin,
                "combined_vs_margin_wins": margin_wins,
                "combined_vs_margin_losses": margin_losses,
                "combined_vs_null_wins": null_wins,
                "combined_vs_null_losses": null_losses,
                "combined_rate_ci95_exploratory": list(statistics.clopper_pearson(counts["P-COMBINED"], n)),
                "p_exact_one_sided_vs_fair_exploratory": statistics.exact_binomial_upper_tail(counts["P-COMBINED"], n, fair),
                "p_exact_paired_vs_margin_exploratory": statistics.exact_binomial_upper_tail(
                    margin_wins, margin_wins + margin_losses, .5),
                "p_exact_paired_vs_null_exploratory": statistics.exact_binomial_upper_tail(
                    null_wins, null_wins + null_losses, .5),
            }
        print("PAIRWISE_RESIDUAL_AUDIT_JSON=" + json.dumps(report, sort_keys=True, separators=(",", ":")))
        self.assertFalse(report["prospective_verified"])
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["decision"], "NO_EDGE")


if __name__ == "__main__":
    unittest.main()
