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
from research.supercompute.v47_models import SPECS, canonical


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
                                       "model_lineage": reports[game]["evolution"]["champion_id"]}
                                for game in games}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
