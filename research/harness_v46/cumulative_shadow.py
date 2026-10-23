"""V4.7 read-only cumulative SHADOW D2 review over exact frozen dual-game runs.

Caller-provided results are not authenticated official outcomes. No eligible
formal samples, claim of edge, or mutation of predictions is produced here.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from . import prospective_cycle as cycle
from .core import MODELS, RULES, GateError, canon, digest, dt, load_registered_snapshot
from .statistics import FAIR_D2, clopper_pearson

SCHEMA = "V47-SHADOW-D2-CUMULATIVE-1"


def _review_claimed_result_times(database, run_id, results):
    """Check declared chronology only; do not authenticate claimed draw time."""
    if not isinstance(results, dict) or set(results) != set(RULES):
        raise GateError("EXACTLY_TWO_UNVERIFIED_OUTCOMES_REQUIRED")
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        for game in sorted(RULES):
            row = results[game]
            if (not isinstance(row, dict)
                    or set(row) != {"lottery", "issue", "front", "back", "drawn_at"}
                    or row.get("lottery") != game
                    or not isinstance(row.get("issue"), str)):
                raise GateError("STRICT_CLAIMED_OUTCOME_SCHEMA_REQUIRED")
            snap = load_registered_snapshot(connection, run_id, game)
            if row["issue"] != str(snap["target_issue"]):
                raise GateError("CLAIMED_OUTCOME_TARGET_MISMATCH")
            try:
                claimed = dt(row["drawn_at"])
            except (TypeError, ValueError) as exc:
                raise GateError("INVALID_CLAIMED_DRAW_TIME") from exc
            if claimed < dt(snap["target_draw_at"]):
                raise GateError("CLAIMED_RESULT_BEFORE_TARGET_DRAW")
    finally:
        connection.close()


def cumulative_shadow_review(cycles):
    """Calculate paired descriptive hit rates for every unchanged model.

    Input: [{"database": path, "run_id": V47-run, "results":
            {"SSQ": {lottery, issue, front, back, drawn_at},
             "DLT": {lottery, issue, front, back, drawn_at}}}, ...]
    All scoreboards are recomputed from frozen rows on demand; input cannot
    provide a D2 bit or pick a winning model after seeing the result.
    """
    if not isinstance(cycles, list) or not cycles:
        raise GateError("NONEMPTY_PROSPECTIVE_CYCLES_REQUIRED")
    seen_runs, seen_targets = set(), set()
    identities = {}
    observations = {game: [] for game in RULES}
    for index, item in enumerate(cycles):
        if not isinstance(item, dict) or set(item) != {"database", "run_id", "results"}:
            raise GateError("STRICT_CUMULATIVE_INPUT_REQUIRED")
        database, run_id, results = item["database"], item["run_id"], item["results"]
        if (not isinstance(database, str) or not database
                or not isinstance(run_id, str) or not run_id.startswith("V47-")):
            raise GateError("INVALID_CUMULATIVE_RUN_IDENTITY")
        if run_id in seen_runs:
            raise GateError("DUPLICATE_RUN_IN_CUMULATIVE_REVIEW")
        seen_runs.add(run_id)
        # A local database path cannot be mistaken for a trustworthy witness.
        _review_claimed_result_times(database, run_id, results)
        frozen = cycle.frozen_forecast_report(database, run_id)
        scores = cycle.evaluate_after_draw(database, run_id, results)
        if (scores.get("formal_A") != 0 or scores.get("decision") != "NO_EDGE"
                or scores.get("outcome_source") != "CALLER_UNVERIFIED"
                or frozen.get("independently_trusted_predraw_seal") is not False):
            raise GateError("UNVERIFIED_RUN_CANNOT_ASSERT_FORMAL_EVIDENCE")
        for game in sorted(RULES):
            target = frozen["games"][game]["target_issue"]
            # Leading zeros / Unicode decimal digits cannot add another draw.
            target_key = (game, int(target))
            if target_key in seen_targets:
                raise GateError("DUPLICATE_LOTTERY_TARGET_ACROSS_RUNS")
            seen_targets.add(target_key)
            per_model = frozen["games"][game]["models"]
            if [m.get("model") for m in per_model] != list(MODELS):
                raise GateError("FROZEN_MODEL_REGISTRY_CHANGED")
            by_model = scores["games"][game]["scores"]
            if set(by_model) != set(MODELS):
                raise GateError("INCOMPLETE_PAIRWISE_OUTCOME_VECTOR")
            d2_bits = {}
            for model_rec in per_model:
                model = model_rec["model"]
                identity = {
                    "model_version": model_rec["model_version"],
                    "parameters_sha256": model_rec["parameters_sha256"],
                    "model_source_sha256": model_rec["model_source_sha256"],
                }
                key = (game, model)
                if key in identities and identities[key] != identity:
                    raise GateError("MIXED_MODEL_VERSIONS_IN_ONE_COHORT")
                identities.setdefault(key, identity)
                if (model_rec["primary_d2"] != model_rec["candidates_1_to_5"][:2]
                        or len(model_rec["primary_d2"]) != 2
                        or any(type(n) is not int for n in model_rec["primary_d2"])):
                    raise GateError("INVALID_FROZEN_PRIMARY_D2")
                bit = by_model[model].get("D2")
                if type(bit) is not int or bit not in (0, 1):
                    raise GateError("INVALID_FROZEN_D2_RESULT_BIT")
                d2_bits[model] = bit
            if (scores["games"][game]["prediction_batch_sha256"]
                    != frozen["games"][game]["prediction_batch_sha256"]):
                raise GateError("FROZEN_BATCH_CHANGED_DURING_CUMULATIVE_REVIEW")
            observations[game].append({
                "run_id": run_id,
                "issue": target,
                "frozen_batch_sha256": frozen["games"][game]["prediction_batch_sha256"],
                "result_claim_sha256": digest(results[game]),
                "main_d2_hit_bits": d2_bits,
                "claimed_drawn_at_untrusted": results[game]["drawn_at"],
                "source_class": "CALLER_UNVERIFIED",
            })
    summary = {}
    for game in sorted(RULES):
        drawn = sorted(observations[game], key=lambda v: (int(v["issue"]), v["run_id"]))
        n = len(drawn)
        null_hits = sum(x["main_d2_hit_bits"]["random_null"] for x in drawn)
        models = {}
        for model in MODELS:
            hits = sum(x["main_d2_hit_bits"][model] for x in drawn)
            wins = sum(x["main_d2_hit_bits"][model] == 1
                       and x["main_d2_hit_bits"]["random_null"] == 0 for x in drawn)
            losses = sum(x["main_d2_hit_bits"][model] == 0
                         and x["main_d2_hit_bits"]["random_null"] == 1 for x in drawn)
            models[model] = {
                "draws": n,
                "d2_hits": hits,
                "d2_rate": hits / n,
                "d2_rate_ci95_descriptive": list(clopper_pearson(hits, n)),
                "fair_random_d2_baseline": FAIR_D2[game],
                "observed_minus_fair": hits / n - FAIR_D2[game],
                "same_draw_null_d2_hits": null_hits,
                "paired_wins_vs_null": wins,
                "paired_losses_vs_null": losses,
                "observed_minus_null": (hits - null_hits) / n,
                "model_identity": identities[(game, model)],
            }
        summary[game] = {"draws": n, "models": models, "observations": drawn}
    report = {
        "schema": SCHEMA,
        "games": summary,
        "unique_two_game_runs": len(seen_runs),
        "official_result_source": "CALLER_UNVERIFIED",
        "official_data_admission": "BLOCKED",
        "independently_trusted_predraw_seal": False,
        "preregistration_verified": False,
        "formal_A": 0,
        "decision": "NO_EDGE",
        "status": "SHADOW_DESCRIPTIVE_ONLY",
    }
    report["report_sha256_local_untrusted"] = digest(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="V4.7 cumulative SHADOW D2 review")
    parser.add_argument("--cycles-json", required=True, help="JSON list of frozen runs and caller outcomes")
    args = parser.parse_args(argv)
    try:
        rows = json.loads(Path(args.cycles_json).read_text(encoding="utf-8"))
        print(json.dumps(cumulative_shadow_review(rows), ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (GateError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
