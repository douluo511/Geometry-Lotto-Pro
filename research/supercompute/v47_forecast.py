"""Generate, freeze and retrospectively score 11-component research candidates.

Example (snapshot only, NOT live issuer verification):
python -m research.supercompute.v47_forecast generate --game both \
  --ssq-target EXPLICIT_ISSUE --dlt-target EXPLICIT_ISSUE \
  --output research-output/unified.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from research.supercompute.v47_cli import load_snapshot
from research.supercompute.v47_integrated import (
    freeze_result, run_all, score_result,
)
from research.supercompute.v47_models import SPECS, canonical, m1_math
from research.supercompute.v47_registry import execute_eleven


def _previous(path, game):
    if path is None:
        return None
    payload = json.loads(path.read_bytes())
    if payload.get("schema") == "SSQDLT_V47_UNIFIED_FROZEN_V1":
        payload = payload["source"]
    if payload.get("schema") == "SSQDLT_V47_UNIFIED_RUN_V1":
        payload = payload["games"][game]
    if payload.get("schema") != "SSQDLT_V47_UNIFIED_11_V1" or payload.get("game") != game:
        raise ValueError("prior champion game/schema mismatch")
    return payload["evolution"]["champion"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    gen = commands.add_parser("generate", help="run all 11 research stages")
    gen.add_argument("--game", choices=(*SPECS, "both"), required=True)
    gen.add_argument("--ssq-data", type=Path,
                     default=Path("SSQ/SSQ/resources/official_seed.json"))
    gen.add_argument("--dlt-data", type=Path,
                     default=Path("DLT/src/resources/official_seed.json"))
    gen.add_argument("--ssq-target", default=None)
    gen.add_argument("--dlt-target", default=None)
    gen.add_argument("--seed", type=int, default=2026)
    gen.add_argument("--generations", type=int, default=2)
    gen.add_argument("--validation", type=int, default=6)
    gen.add_argument("--holdout", type=int, default=3)
    gen.add_argument("--mc-trials", type=int, default=300)
    gen.add_argument("--physics-steps", type=int, default=30)
    gen.add_argument("--previous", type=Path, default=None)
    gen.add_argument("--output", type=Path, required=True)
    gen.add_argument("--freeze-dir", type=Path, default=None)

    score = commands.add_parser("score", help="score independently supplied actual")
    score.add_argument("--frozen", type=Path, required=True)
    score.add_argument("--sha256", required=True)
    score.add_argument("--actual", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.action == "score":
        actual = json.loads(args.actual.read_text(encoding="utf-8"))
        print(json.dumps(score_result(args.frozen, args.sha256, actual),
                         ensure_ascii=False))
        return
    games = tuple(SPECS) if args.game == "both" else (args.game,)
    reports = {}
    for game in games:
        target = getattr(args, game + "_target")
        if not target:
            raise ValueError("--" + game + "-target is mandatory")
        source = getattr(args, game + "_data")
        rows, digest = load_snapshot(source, game)
        report = run_all(rows, game, target, seed=args.seed,
                         generations=args.generations, validation=args.validation,
                         holdout=args.holdout, mc_trials=args.mc_trials,
                         physics_steps=args.physics_steps,
                         previous_champion=_previous(args.previous, game))
        # Run eleven independently fitted model objects in the same execution,
        # not a checklist of five selectors and six helper functions.
        report["independent_11"] = execute_eleven(
            rows, game, seed=args.seed, generations=args.generations,
            validation=args.validation, holdout=args.holdout,
            mc_trials=args.mc_trials, physics_steps=args.physics_steps,
            previous_champion=_previous(args.previous, game))
        all_checks = report["independent_11"].get("validation_all_11")
        if (not isinstance(all_checks, dict)
                or all_checks.get("model_count") != 11
                or len(all_checks.get("models", {})) != 11
                or all_checks.get("uses_future_draws") is not False):
            raise ValueError("M2/M3 evaluation missing for some models")
        report["validation"]["M2"] = {
            name: evidence["m2"] for name, evidence in all_checks["models"].items()}
        report["validation"]["M3"] = {
            name: evidence["m3"] for name, evidence in all_checks["models"].items()}
        report["full_model_validation"] = all_checks["status"]
        # One named, independently computed ticket for EACH of the eleven
        # executable models. Never replace these with three fused alternatives.
        model_evidence = report["independent_11"]["models"]
        ordered = sorted(model_evidence.items(), key=lambda kv: kv[1]["number"])
        if len(ordered) != 11 or [v["number"] for _, v in ordered] != list(range(1, 12)):
            raise ValueError("expected exactly eleven independent model outputs")
        grouped = []
        for model_name, execution in ordered:
            ticket = dict(execution["prediction"]["ticket"])
            ticket["model_number"] = execution["number"]
            ticket["model_name"] = model_name
            ticket["after_issue"] = str(rows[-1]["issue"])
            ticket["source"] = "INDEPENDENT_MODEL_PREDICTION"
            grouped.append(ticket)
        if grouped[-1]["model_name"] != "M1_M2_M3_Validation":
            raise ValueError("eleventh final validation model missing")
        report["proposed_tickets"] = grouped
        report["ticket_count"] = 11
        report["per_model_ticket_contract"] = "ONE_ROW_PER_MODEL"
        report["validation"]["M1"] = [m1_math(rows, game, ticket)
                                      for ticket in grouped]
        report["primary_candidate_source"] = "M1_M2_M3_Validation"
        report["snapshot_file_sha256"] = digest
        reports[game] = report
    payload = {"schema": "SSQDLT_V47_UNIFIED_RUN_V1",
               "games": reports, "edge": "NO_EDGE",
               "formal_prediction": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as fh:
        fh.write(canonical(payload))
    frozen = {}
    if args.freeze_dir:
        for game in games:
            path = args.freeze_dir / (game + "-" + reports[game]["target_issue"]
                                      + "-v47-unified.json")
            frozen[game] = freeze_result(path, reports[game])
    print(json.dumps({"status": "GENERATED",
                      "output": str(args.output),
                      "frozen": frozen,
                      "source_is_live_verified": False,
                      "games": {game: {"target": reports[game]["target_issue"],
                                       "history_asof": reports[game]["history_last_issue"],
                                       "tickets": reports[game]["proposed_tickets"],
                                       "model_lineage": reports[game]["independent_11"]["models"]["Challenger"]["fit"]["champion_id"],
                                       "eleven_independent_models": reports[game]["independent_11"]["model_count"],
                                       "ticket_count": reports[game]["ticket_count"],
                                       "m2_model_count": len(reports[game]["validation"]["M2"]),
                                       "m3_model_count": len(reports[game]["validation"]["M3"]),
                                       "model11_prediction": reports[game]["independent_11"]["final_candidate"]}
                                for game in games}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
