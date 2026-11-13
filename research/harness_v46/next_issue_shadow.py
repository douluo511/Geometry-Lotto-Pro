"""One-issue, NON-FORMAL V4.7 research predictions for SSQ and DLT.

Uses exact pinned historical observations through 2026-10-22 / 2026-10-21,
then 9 draw rows each transcribed from the verified public issuer history
tables on 2026-11-13. Original recent HTML is NOT archived in this branch,
so this is not an authenticated 01 intake or a formal predraw seal.
No scheduled automation, random advantage claim, or ticket purchase.
"""
from __future__ import annotations

from datetime import datetime, date, timezone
from hashlib import sha256
from itertools import combinations
from pathlib import Path
import gzip
import json

from . import core
from .d2_challenger_lab import ablation_rank, pick_recency_pair, challenger_contract_sha256

SCHEMA = "V47_ONE_ISSUE_SHADOW_ONLY_V1"
TARGETS = {
    "SSQ": {"issue": "2026131", "draw_date": "2026-11-15",
            "source": "https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous",
            "last_known": "2026130"},
    "DLT": {"issue": "26130", "draw_date": "2026-11-14",
            "source": "https://api.js-lottery.com/wfzq/dlt/data",
            "last_known": "26129"},
}
# Fixed transcription from public lottery-issuer rows, with one overlap row.
# These are source observations NOT model predictions and not trusted seals.
RECENT = {
    "SSQ": [
        ("2026121", "2026-10-22", [2,7,20,24,26,30], [2]),
        ("2026122", "2026-10-25", [1,2,4,17,19,30], [9]),
        ("2026123", "2026-10-27", [4,5,20,21,26,30], [12]),
        ("2026124", "2026-10-29", [3,11,17,22,23,29], [9]),
        ("2026125", "2026-11-01", [4,6,10,15,26,27], [11]),
        ("2026126", "2026-11-03", [9,10,13,22,29,32], [12]),
        ("2026127", "2026-11-05", [13,14,19,25,29,32], [12]),
        ("2026128", "2026-11-08", [5,6,10,25,27,30], [11]),
        ("2026129", "2026-11-10", [3,9,16,20,25,30], [5]),
        ("2026130", "2026-11-12", [1,2,6,16,20,28], [2]),
    ],
    "DLT": [
        ("26120", "2026-10-21", [1,6,10,15,32], [3,4]),
        ("26121", "2026-10-24", [6,8,19,24,25], [1,8]),
        ("26122", "2026-10-26", [2,14,21,22,24], [2,12]),
        ("26123", "2026-10-28", [13,18,19,20,28], [9,11]),
        ("26124", "2026-10-31", [12,14,18,22,27], [1,9]),
        ("26125", "2026-11-02", [12,13,23,25,29], [7,10]),
        ("26126", "2026-11-04", [5,11,17,25,34], [4,6]),
        ("26127", "2026-11-07", [5,6,17,18,27], [3,12]),
        ("26128", "2026-11-09", [3,13,20,25,34], [9,12]),
        ("26129", "2026-11-11", [2,12,14,17,33], [7,8]),
    ],
}
EXTRA_ABLATION = ("HOT30", "HOT120", "P-MARGIN", "P-RESIDUAL")


def _validated_row(game, row):
    issue, day, front, back = row
    spec = core.RULES[game]
    if not (isinstance(issue, str) and issue.isascii() and issue.isdigit()
            and isinstance(day, str) and date.fromisoformat(day).isoformat() == day
            and len(front) == spec["front"] and len(back) == spec["back"]
            and len(set(front)) == len(front) and len(set(back)) == len(back)
            and front == sorted(front) and back == sorted(back)
            and all(1 <= n <= spec["pool"] for n in front)
            and all(1 <= n <= spec["back_pool"] for n in back)):
        raise core.GateError("INVALID_RECENT_ISSUER_TRANSCRIPTION")
    return {"issue": issue, "draw_date": day,
            "front": list(front), "back": list(back)}


def _history(bundle, game):
    prior = bundle[game]
    if not isinstance(prior, list) or len(prior) < 120:
        raise core.GateError("INSUFFICIENT_PINNED_HISTORY")
    new = [_validated_row(game, row) for row in RECENT[game]]
    if prior[-1] != new[0]:
        raise core.GateError("PINNED_OVERLAP_CONFLICT")
    last = prior[-1]
    all_rows = list(prior)
    for row in new[1:]:
        if (int(row["issue"]) != int(last["issue"]) + 1
                or date.fromisoformat(row["draw_date"]) <= date.fromisoformat(last["draw_date"])):
            raise core.GateError("ISSUER_GAP_OR_DATE_ORDER_INVALID")
        all_rows.append(row)
        last = row
    assert last["issue"] == TARGETS[game]["last_known"]
    assert int(TARGETS[game]["issue"]) == int(last["issue"]) + 1
    assert date.fromisoformat(last["draw_date"]) < date.fromisoformat(TARGETS[game]["draw_date"])
    return all_rows


def _ticket(game, issue, model, ranking):
    r = core.RULES[game]
    if len(set(ranking)) != r["pool"] or set(ranking) != set(range(1, r["pool"] + 1)):
        raise core.GateError("INVALID_MODEL_RANKING")
    first5 = ranking[:5]
    front = sorted(ranking[:r["front"]])
    back_perm = core._stable_permutation(
        list(range(1, r["back_pool"] + 1)),
        core.NULL_SEED, game, issue, model, "back"
    )
    back = sorted(back_perm[:r["back"]])
    core._balls(front, r["pool"], r["front"])
    core._balls(back, r["back_pool"], r["back"])
    if not set(first5).issubset(front):
        raise core.GateError("INVALID_FIRST_FIVE")
    return {
        "model": model,
        "primary_d2": first5[:2],
        "ordered_first_five": first5,
        "ticket": {"front": front, "back": back},
    }


def generate():
    input_file = (Path(__file__).parent / "evidence" /
                  "recency_ablation_20261024" / "observations.json.gz")
    original = input_file.read_bytes()
    bundle = json.loads(gzip.decompress(original))
    if set(bundle) != {"SSQ", "DLT"}:
        raise core.GateError("PINNED_BUNDLE_GAMES_MISMATCH")
    if core.digest(bundle) != "3d4399da45529ab458ae926dad682cf01a6a2c4af3e4780bd8bbee6df1c0792c":
        raise core.GateError("PINNED_BUNDLE_SHA_MISMATCH")
    now = datetime.now(timezone.utc)
    issued_at = now.isoformat()
    # Chinese local time is UTC+08; do not substitute this for an independent TSA.
    if now.date() > date(2026, 11, 13):
        raise core.GateError("ONE_ISSUE_TARGET_TOO_OLD_TO_REISSUE")
    result = {
        "schema": SCHEMA,
        "created_at_utc_untrusted": issued_at,
        "formal_A": 0,
        "evidence_class": "SHADOW_RESEARCH_NOT_PREDRAW_VERIFIED",
        "decision": "NO_EDGE",
        "pinned_history_gzip_sha256": sha256(original).hexdigest(),
        "pinned_history_canonical_sha256": core.digest(bundle),
        "core_sha256": core.model_source_sha256(),
        "version": core.VERSION,
        "null_seed_id": core.NULL_SEED,
        "history_appendix_is_raw_source_archived": False,
        "recent_source_evidence": "MANUAL_TRANSCRIPTION_OF_LIVE_ISSUER_TABLE_NOT_ORIGINAL_BYTES",
        "games": {},
    }
    for game in ("SSQ", "DLT"):
        history = _history(bundle, game)
        issue = TARGETS[game]["issue"]
        ctx = {"lottery": game, "target_issue": issue, "draws": history}
        rows = []
        for model in core.MODELS:
            ranking = core._model_ranking(ctx, model)
            item = _ticket(game, issue, model, ranking)
            item["model_parameters_sha256"] = core.digest(core.parameter_contract(model))
            item["model_class"] = "V47_REGISTERED_RESEARCH_ARM"
            rows.append(item)
        for arm in EXTRA_ABLATION:
            rank = ablation_rank(history, game, arm, target_issue=issue)
            item = _ticket(game, issue, "exploratory_" + arm.lower(), rank)
            item["model_class"] = "EXPLORATORY_ABLATION_NOT_REGISTERED_FORMAL"
            rows.append(item)
        recency_pair = pick_recency_pair(history, game)
        fill = core._model_ranking(ctx, "hot60")
        rank = recency_pair + [n for n in fill if n not in recency_pair]
        item = _ticket(game, issue, "exploratory_recency_pair_h45_120", rank)
        item["model_class"] = "EXPLORATORY_NOT_REGISTERED_FORMAL"
        item["challenger_contract_sha256"] = challenger_contract_sha256()
        rows.append(item)
        result["games"][game] = {
            "target_issue": issue,
            "expected_draw_date": TARGETS[game]["draw_date"],
            "latest_training_issue": history[-1]["issue"],
            "latest_training_draw_date": history[-1]["draw_date"],
            "history_count": len(history),
            "history_sha256": core.digest(history),
            "issuer_url": TARGETS[game]["source"],
            "predictions": rows,
        }
    return result


def main():
    value = generate()
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    dest = Path("one-issue-shadow-20261113.json")
    with dest.open("x", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, sort_keys=True, indent=2)
        out.write("\n")
    print("RESULT_SHA256", sha256(dest.read_bytes()).hexdigest())

if __name__ == "__main__":
    main()
