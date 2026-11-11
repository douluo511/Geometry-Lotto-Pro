"""Two-game, future-issue-only research preview with hard separation from V4.7.

Uses existing deterministic reverse-formula bank, not a proven lottery edge.
Source identifiers below are manual contemporaneous provenance claims verified
against public provincial draw pages; they are NOT authenticated source bytes or
trusted predraw timestamps. Neither this file nor its result can enter formal A.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from research.inverse_formula.formula_bank import predict_with_bank, _research_null
from research.inverse_formula.probe import SSQ, DLT, Draw, Game, load_history
from research.inverse_formula.independent_experts import digest

ROOT = Path(__file__).resolve().parent
MODEL_PATHS = (
    "research/inverse_formula/formula_bank.py",
    "research/inverse_formula/reverse_search.py",
    "research/inverse_formula/probe.py",
    "research/inverse_formula/forward_preview.py",
)
LATEST_DRAW = {
    "SSQ": {
        "issue": 2026129, "date": "2026-11-10",
        "front": [3, 9, 16, 20, 25, 30], "back": [5],
        "issuer_sources": [
            "https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous",
            "https://www.qhflcp.cn/report/SSQ_WinMessage.aspx",
        ],
        "target_issue": 2026130,
        "scheduled_draw_date_unverified": "2026-11-12",
    },
    "DLT": {
        "issue": 26129, "date": "2026-11-11",
        "front": [2, 12, 14, 17, 33], "back": [7, 8],
        "issuer_sources": [
            "https://www.js-lottery.com/cms/post-148233.html",
            "https://www.gstc.org.cn/wanfa/dlt",
        ],
        "target_issue": 26130,
        "scheduled_draw_date_unverified": "2026-11-14",
    },
}


def candidate_history(game: Game, recorded: dict, *,
                      base: Path = ROOT) -> tuple[list[Draw], str, str]:
    original, source_sha = load_history(base / (game.name.lower() + "_2026.txt"), game)
    if type(recorded.get("issue")) is not int or (
            type(recorded.get("target_issue")) is not int
            or recorded["target_issue"] != recorded["issue"] + 1):
        raise ValueError("target must be one issue after known historical outcome")
    latest = Draw(recorded["issue"], tuple(recorded["front"]), tuple(recorded["back"]))
    if len(original) < 90 or len(set(d.issue for d in original)) != len(original):
        raise ValueError("inadequate or duplicated research history")
    if original[-1].issue == latest.issue:
        if original[-1] != latest:
            raise ValueError("latest official issue conflicts with original fixture")
        rows = original
        suffix = "EXISTING_FIXTURE_MATCHED_LATEST"
    elif original[-1].issue + 1 == latest.issue:
        rows = original + [latest]
        suffix = "APPENDED_MANUALLY_CORROBORATED_LATEST_TO_COPY"
    else:
        raise ValueError("missing or future research history; refuse to backfill")
    if any(rows[i].issue != rows[i - 1].issue + 1 for i in range(1, len(rows))):
        raise ValueError("non-contiguous historical research input")
    if rows[-1].issue != recorded["target_issue"] - 1:
        raise ValueError("future target result already present or wrong issue")
    return rows, source_sha, suffix


def score_if_future_publication_confirmed(
        issued: dict, confirmed: dict) -> dict:
    """Strict arithmetic only; EXTERNAL postdraw authenticity remains UNVERIFIED."""
    game = SSQ if issued["lottery"] == "SSQ" else DLT if issued["lottery"] == "DLT" else None
    if game is None or type(issued.get("target_issue")) is not int:
        raise ValueError("unknown game or target issue")
    if (type(confirmed.get("issue")) is not int
            or confirmed["issue"] != issued["target_issue"]):
        raise ValueError("outcome issue does not match sealed target")
    front, back = tuple(confirmed["front"]), tuple(confirmed["back"])
    if (len(front) != game.front_pick or len(back) != game.back_pick
            or tuple(sorted(set(front))) != front
            or tuple(sorted(set(back))) != back
            or any(type(n) is not int or not 1 <= n <= game.front_max for n in front)
            or any(type(n) is not int or not 1 <= n <= game.back_max for n in back)):
        raise ValueError("malformed result, duplicate number, or out of pool")
    prediction = issued["prediction"]
    f, b, d2 = prediction["front"], prediction["back"], prediction["d2_pair"]
    if len(d2) != 2 or not set(d2).issubset(f):
        raise ValueError("illegal or retroactively changed D2")
    n = issued["research_null"]
    expected_ticket, expected_pair = _research_null(issued["target_issue"], game)
    if (tuple(n["front"]), tuple(n["back"]), tuple(n["d2_pair"])) != (
            expected_ticket[0], expected_ticket[1], expected_pair):
        raise ValueError("research random control changed")
    return {
        "game": game.name, "issue": issued["target_issue"],
        "research_full_hit": int(tuple(f) == front and tuple(b) == back),
        "research_d2_hit": int(set(d2).issubset(front)),
        "research_front_hits": len(set(f) & set(front)),
        "research_back_hits": len(set(b) & set(back)),
        "research_null_full_hit": int(tuple(n["front"]) == front and
                                      tuple(n["back"]) == back),
        "research_null_d2_hit": int(set(n["d2_pair"]).issubset(front)),
        "issuer_outcome_authentication": "UNVERIFIED_BY_THIS_FUNCTION",
        "formal_a": 0, "research_status": "NO_EDGE",
    }


def forecast_research(game: Game, recorded: dict, *,
                      base: Path = ROOT) -> dict:
    rows, old_sha, suffix = candidate_history(game, recorded, base=base)
    decision = predict_with_bank(rows, game)
    ticket = decision["prediction"]
    if (decision["asof_issue"] != recorded["issue"]
            or decision["target_issue"] != recorded["target_issue"]):
        raise ValueError("formula used a non-matching history cutoff")
    null_ticket, pair = _research_null(recorded["target_issue"], game)
    raw_code_hashes = {}
    code_base = Path(__file__).resolve().parents[2]
    for rel in MODEL_PATHS:
        raw_code_hashes[rel] = hashlib.sha256((code_base / rel).read_bytes()).hexdigest()
    data = {
        "schema": "SSQDLT_RESEARCH_FORWARD_V1",
        "lottery": game.name, "target_issue": recorded["target_issue"],
        "prior_confirmed_issue": recorded["issue"],
        "prior_confirmed_draw_date": recorded["date"],
        "prior_confirmed_draw": {
            "front": recorded["front"], "back": recorded["back"]
        },
        "scheduled_draw_date_not_sales_cutoff": recorded["scheduled_draw_date_unverified"],
        "historical_fixture_sha256": old_sha,
        "historical_in_memory_rows": len(rows),
        "additional_history_handling": suffix,
        "historical_memory_fingerprint": digest([asdict(d) for d in rows]),
        "issuer_result_reference_urls": list(recorded["issuer_sources"]),
        "issuer_page_raw_bytes_authenticated": False,
        "official_target_and_cutoff_verified": False,
        "independent_predraw_timestamp_approved": False,
        "research_only": True,
        "formal_a": 0,
        "research_status": "NO_EDGE",
        "paid_model_calls": 0,
        "formula_identity": "research.inverse_formula.formula_bank.predict_with_bank",
        "formula_source_sha256": raw_code_hashes,
        "formula_decision_sha256": decision["decision_sha256"],
        "selected_formula_ids": [x["formula_id"] for x in decision["selected_formulas"]],
        "candidate_count": decision["candidate_count"],
        "prediction": {
            "front": list(ticket["front"]), "back": list(ticket["back"]),
            "d2_pair": list(ticket["d2_pair"]),
        },
        "research_null": {
            "front": list(null_ticket[0]), "back": list(null_ticket[1]),
            "d2_pair": list(pair),
            "not_formal_v47_null": True,
        },
        "limitations": (
            "Historically reviewed research fixture; formula weights selected "
            "using those outcomes; no corrected prospective evidence of edge. "
            "Research copy is not the frozen V4.7 producer roster."
        ),
    }
    data["content_sha256"] = digest(data)
    return data


def run() -> dict:
    results = {
        game.name: forecast_research(game, LATEST_DRAW[game.name])
        for game in (SSQ, DLT)
    }
    return {
        "schema": "SSQDLT_TWO_GAME_RESEARCH_PREVIEW_V1",
        "created_utc_local_untrusted": datetime.now(timezone.utc).isoformat(),
        "target_issue_pair": {
            g: results[g]["target_issue"] for g in ("SSQ", "DLT")
        },
        "forecasts": results,
        "all_present_outcomes_scored": False,
        "model_prospective_edge_verified": False,
        "formal_a": 0,
        "no_edge": True,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists():
        raise FileExistsError("forecasts are write-once; cannot overwrite")
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2,
                           sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({
        name: {k: value[k] for k in (
            "target_issue", "content_sha256", "prediction", "research_null")}
        for name, value in result["forecasts"].items()
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
