"""Run research-only 11-component SSQ/DLT experiments, never formal V4.7."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from research.supercompute.v47_models import (
    MODELS, SPECS, backtest, candidates, canonical, evolve, freeze,
    geometry_state, m1_math, monte_carlo, physics_toy, score_frozen,
    validate_history,
)


def load_snapshot(path, game):
    raw = Path(path).read_bytes()
    obj = json.loads(raw)
    if str(obj.get("game", "")).lower() != game:
        raise ValueError("game mismatch")
    rows = obj["draws"]
    validate_history(rows, game)
    if len(rows) < 121:
        raise ValueError("not enough history")
    return rows, hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="past-only retrospective research")
    run.add_argument("--game", choices=(*SPECS, "both"), required=True)
    run.add_argument("--ssq-data", type=Path, default=Path("SSQ/SSQ/resources/official_seed.json"))
    run.add_argument("--dlt-data", type=Path, default=Path("DLT/src/resources/official_seed.json"))
    run.add_argument("--periods", type=int, default=30)
    run.add_argument("--trials", type=int, default=10000)
    run.add_argument("--seed", type=int, default=2026)
    run.add_argument("--output", type=Path, required=True)

    prep = sub.add_parser("freeze", help="create-only research candidate receipt")
    prep.add_argument("--game", choices=SPECS, required=True)
    prep.add_argument("--data", type=Path, required=True)
    prep.add_argument("--model", choices=MODELS, required=True)
    prep.add_argument("--target-issue", required=True)
    prep.add_argument("--seed", type=int, default=2026)
    prep.add_argument("--output", type=Path, required=True)

    score = sub.add_parser("score", help="score supplied result; not issuer-verified")
    score.add_argument("--receipt", type=Path, required=True)
    score.add_argument("--sha256", required=True)
    score.add_argument("--actual", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "run":
        games = ("ssq", "dlt") if args.game == "both" else (args.game,)
        result = {}
        for game in games:
            path = args.ssq_data if game == "ssq" else args.dlt_data
            rows, digest = load_snapshot(path, game)
            benchmark = backtest(rows, game, args.periods, args.seed)
            champion = benchmark["challenger_selected_before_test"]["parameters"]
            examples = {name: candidates(rows, game, name,
                        champion if name == "Challenger" else None,
                        limit=3, seed=args.seed) for name in MODELS}
            result[game] = {
                "history_source_sha256": digest,
                "source_status": "REPOSITORY_HISTORICAL_NOT_LIVE_VERIFIED",
                "m1": m1_math(rows, game, examples["HOT60"][0]),
                "geometry": geometry_state(rows, game),
                "models": benchmark,
                "monte_carlo": monte_carlo(game, args.trials, args.seed),
                "uncalibrated_physics": physics_toy(game, args.seed),
                "hypothetical_candidates": examples,
            }
        report = {"schema": "SSQDLT_11_COMPONENT_RESEARCH_V1",
                  "games": result, "edge": "NO_EDGE", "formal_prediction": False}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as f:
            f.write(canonical(report))
        print(json.dumps({"output": str(args.output),
                          "games": list(result), "edge": "NO_EDGE"}))

    elif args.command == "freeze":
        rows, _ = load_snapshot(args.data, args.game)
        opts = (evolve(rows, args.game, args.seed)["parameters"]
                if args.model == "Challenger" else None)
        receipt = freeze(args.output, rows, args.game, args.model,
                         args.target_issue, opts, args.seed)
        print(json.dumps({**receipt, "formal_prediction": False}))
    else:
        actual = json.loads(args.actual.read_text(encoding="utf-8"))
        print(json.dumps(score_frozen(args.receipt, actual, args.sha256)))


if __name__ == "__main__":
    main()
