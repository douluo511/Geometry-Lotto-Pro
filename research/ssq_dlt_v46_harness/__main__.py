"""Research-only CLI. No network fetch, external seal or unattended scheduling."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import ROLES, Ledger, HarnessBlocked, generate, score_research
from research.ssq_dlt_v45.models import RULES, digest


def synthetic_history(game, length=65):
    upper, count, back_upper, back_count = RULES[game]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{
        "game": game, "issue": f"{i+1:05d}",
        "front": sorted(((i * 11 + n * 7) % upper) + 1 for n in range(count)),
        "back": sorted(((i * 5 + n * 3) % back_upper) + 1 for n in range(back_count)),
        "draw_at": (start + timedelta(days=i)).isoformat(),
    } for i in range(length)]


def smoke():
    rows = {}
    for game in ("SSQ", "DLT"):
        forecast = generate(game, "00066", synthetic_history(game),
                            asof="2026-03-15T00:00:00Z",
                            target_draw_at="2026-03-17T00:00:00Z")
        draw = synthetic_history(game)[-1]
        verdict = score_research(forecast, draw["front"], draw["back"])
        rows[game] = {"forecast_sha256": digest(forecast),
                      "model_count": len(forecast["models"]),
                      "d2_random_p0": verdict["p0_d2"],
                      "decision": verdict["decision"]}
    return {"status": "PASS_SYNTHETIC_SMOKE_NOT_LIVE",
            "formal_A": 0, "decision": "NO_EDGE", "games": rows}


def predict(snapshot_path, ledger_path, output_path):
    """Caller-provided snapshot is NOT recognized as official evidence."""
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    output = Path(output_path)
    if output.exists():
        raise HarnessBlocked("OUTPUT_MUST_BE_NEW")
    asof = snapshot["asof"]
    result = {}
    for game in ("SSQ", "DLT"):
        target = snapshot["targets"][game]
        # Local wall time only rejects definitely expired targets; not trusted TSA.
        if datetime.fromisoformat(target["draw_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise HarnessBlocked("TARGET_ALREADY_DRAWN_OR_EXPIRED")
        result[game] = generate(game, target["issue"], snapshot["history"][game],
                                asof=asof, target_draw_at=target["draw_at"])
    receipt = {"status": "SHADOW_ONLY", "snapshot_sha256": digest(snapshot),
               "forecasts": result, "formal_A": 0, "decision": "NO_EDGE",
               "external_timestamp_status": "NOT_RUN", "official_target_admission": "NOT_VERIFIED"}
    text = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2)
    # O_EXCL blocks silent replacement of a previous output.
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        f.write(text + "\n")
    ledger = Ledger(ledger_path)
    try:
        for game, prediction in result.items():
            ledger.append(game + ":" + prediction["issue"] + ":" + digest(snapshot),
                          "SHADOW_FORECAST", prediction)
        ledger.verify()
    finally:
        ledger.close()
    return {"status": "SHADOW_ONLY", "output": str(output),
            "sha256": digest(receipt), "formal_A": 0,
            "warning": "Unverified caller snapshot; no external TSA or formal admission"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    subs.add_parser("roles")
    subs.add_parser("smoke")
    cmd = subs.add_parser("predict")
    cmd.add_argument("--snapshot", required=True)
    cmd.add_argument("--ledger", required=True)
    cmd.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.action == "roles":
        answer = ROLES
    elif args.action == "smoke":
        answer = smoke()
    else:
        answer = predict(args.snapshot, args.ledger, args.output)
    print(json.dumps(answer, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
