"""Research-only SSQ/DLT rolling source/score/next-preview loop.

Never runs formal V4.7, does not claim real cutoff / trusted TSA or jackpot.
Every result requires independent matching *latest-issue* provincial page
alongside the first issuer's full-history table. If either fails, fail closed.
GitHub caller must manage append-only branch push + independent remote reload.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
import re
from pathlib import Path
import urllib.request
from urllib.parse import urlparse

from research.inverse_formula.forward_preview import (
    score_if_future_publication_confirmed,
)
from research.inverse_formula.formula_bank import predict_with_bank, _research_null
from research.inverse_formula.fresh_history import (
    CHINA, SOURCES, parse_official_rows, fetch_official_html, sync_fixture,
)
from research.inverse_formula.independent_experts import digest
from research.inverse_formula.probe import SSQ, DLT, Draw, Game, load_history

CONFIRM_URLS = {
    "SSQ": "https://www.scflcp.com.cn/ssq",
    "DLT": "https://www.gstc.org.cn/wanfa/dlt",
}
MAX_CONFIRM_BYTES = 2_000_000


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _replay_snapshot_targets(ledger: Path) -> dict[tuple[str, int], dict]:
    """Support original 2026-11-11 dual-game receipt and newer per-game files."""
    receipts = {}
    forecasts_dir = ledger / "research" / "forecasts"
    for path in sorted(forecasts_dir.glob("*.json")):
        if not path.is_file() or path.is_symlink():
            raise ValueError("UNSAFE_RESEARCH_RECEIPT_PATH")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") == "SSQDLT_RESEARCH_SNAPSHOT_2026_11_11_V1":
            items = record.get("issued", [])
        elif record.get("schema") == "SSQDLT_ROLLING_RESEARCH_ISSUE_V1":
            items = [record]
        else:
            raise ValueError("UNRECOGNIZED_RESEARCH_LEDGER_SCHEMA")
        for item in items:
            game = item.get("game")
            issue = item.get("target_issue")
            if game not in ("SSQ", "DLT") or type(issue) is not int:
                raise ValueError("INVALID_RESEARCH_ISSUE")
            key = (game, issue)
            if key in receipts:
                raise ValueError("DUPLICATE_RESEARCH_FORECAST_FOR_ISSUE")
            if (item.get("formal_A", record.get("formal_A")) != 0
                    or not isinstance(item.get("prediction"), dict)
                    or not isinstance(item.get("research_null"), dict)):
                raise ValueError("RESEARCH_LEDGER_PROMOTION_OR_MALFORMATION")
            receipts[key] = item
    return receipts


def _save_once(path: Path, value: dict):
    if path.exists() or path.is_symlink():
        raise FileExistsError("refusing to overwrite issued evidence")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2,
                  sort_keys=True, allow_nan=False)
        handle.write("\n")


def verify_independent_latest(
        game: Game, latest: dict, other_text: str) -> None:
    """Demand latest issue, ball sequence and issuer draw date near results.
    This is a conservative textual assertion, NOT publication-time authentication.
    """
    parser = PageText()
    parser.feed(other_text)
    text = re.sub(r"\s+", " ", " ".join(parser.parts))
    issue = str(latest["issue"])
    match = re.search(r"(?<![0-9])" + re.escape(issue) + r"(?![0-9])", text)
    if match is None and game.name == "SSQ":
        # Sichuan publishes recent SSQ draw dates/balls without a visible
        # numeric issue identifier in its public HTML. Require the latest
        # date+ball combination in the leading SSQ announcement, but record
        # that the issue ID itself was not corroborated by this source.
        anchor = text.find("双色球开奖公告")
        if anchor < 0:
            raise ValueError("SECOND_ISSUER_SSQ_ANNOUNCEMENT_MISSING")
        header = text[anchor:anchor + 950]
        day = latest["date"]
        i = header.find(day)
        if i < 0:
            raise ValueError("SECOND_ISSUER_SSQ_DATE_NOT_FOUND")
        after = header[i:i + 190]
    elif match is None:
        raise ValueError("INDEPENDENT_ISSUER_ISSUE_NOT_FOUND")
    else:
        after = text[match.end():match.end() + 1800]
    expected = latest["front"] + latest["back"]
    formatted = r"\s+".join(f"{v:02d}" for v in expected)
    if not re.search(formatted + r"(?![0-9])", after):
        raise ValueError("INDEPENDENT_ISSUER_BALLS_NOT_MATCHED")
    # In the presence of multiple unrelated page content rows, require the
    # sequence to occur close after the target issue. Never hunt entire page.
    if not re.search(
        re.escape(latest["date"]) + "|"
        + re.escape(latest["date"].replace("-", "年", 1).replace("-", "月", 1) + "日"),
        after):
        # A parsed official date might be a publication date, not a draw date.
        # If second issuer hides it, mark blocked rather than infer correctness.
        raise ValueError("INDEPENDENT_ISSUER_DATE_NOT_MATCHED")


def fetch_confirm_text(game: Game, output: Path) -> tuple[str, str]:
    url = CONFIRM_URLS[game.name]
    request = urllib.request.Request(url, headers={
        "User-Agent": "SSQDLT-ResearchReadOnly/1", "Accept": "text/html",
    })
    with urllib.request.urlopen(request, timeout=22) as response:
        if (urlparse(response.geturl()).hostname
                != urlparse(url).hostname):
            raise ValueError("INDEPENDENT_SOURCE_REDIRECTED")
        if response.status != 200:
            raise ValueError("INDEPENDENT_SOURCE_NON200")
        raw = response.read(MAX_CONFIRM_BYTES + 1)
    if len(raw) > MAX_CONFIRM_BYTES:
        raise ValueError("INDEPENDENT_SOURCE_TOO_LARGE")
    output.write_bytes(raw)
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def process_one(game: Game, ledger: Path, output: Path,
                *, first_html: str | None = None,
                independent_html: str | None = None,
                now: datetime | None = None) -> dict:
    """Source-first, target-only research state transition; no purchases."""
    if now is None:
        now = datetime.now(CHINA)
    if now.tzinfo is None:
        raise ValueError("TIMEZONE_AWARE_CLOCK_REQUIRED")
    candidates = _replay_snapshot_targets(ledger)
    work = output / game.name
    work.mkdir(parents=True, exist_ok=True)
    source_url = SOURCES[game.name]
    try:
        if first_html is None:
            first_html, source_sha = fetch_official_html(game)
        else:
            source_sha = hashlib.sha256(first_html.encode("utf-8")).hexdigest()
        (work / "issuer-first.html").write_bytes(first_html.encode("utf-8"))
        last = parse_official_rows(first_html, game)[-1]
        temp_history = work / "merged_research_history.txt"
        original = (Path(__file__).with_name(game.name.lower() + "_2026.txt"))
        sync = sync_fixture(original, game, temp_history, html=first_html, now=now)
        if sync["asof_issue"] != last["issue"]:
            raise ValueError("LATEST_SOURCE_SNAPSHOT_DISAGREES")
        if independent_html is None:
            independent_html, independent_sha = fetch_confirm_text(
                game, work / "issuer-second.html")
        else:
            independent_sha = hashlib.sha256(
                independent_html.encode("utf-8")).hexdigest()
            (work / "issuer-second.html").write_bytes(
                independent_html.encode("utf-8"))
        verify_independent_latest(game, last, independent_html)

        # Reject target reforecasts if any previous issue is still unscored.
        outcomes = {d.issue: d for d in load_history(temp_history, game)[0]}
        planned_scores = []
        for (old_game, target), prediction in candidates.items():
            if old_game != game.name or target > last["issue"]:
                continue
            score_path = ledger / "research" / "scores" / f"{game.name}-{target}.json"
            if score_path.exists():
                continue
            if target != last["issue"]:
                raise ValueError("OLD_PENDING_ISSUE_REQUIRES_INDEPENDENT_AUDIT")
            d = outcomes.get(target)
            if d is None:
                raise ValueError("FORECAST_TARGET_RESULT_MISSING")
            scored = score_if_future_publication_confirmed(
                {**prediction, "lottery": game.name},
                {"issue": target, "front": list(d.front), "back": list(d.back)},
            )
            score = {
                "schema": "SSQDLT_RESEARCH_SCORE_V1",
                "issue": target, "game": game.name,
                "original_prediction_ledger_record": prediction["content_sha256"],
                "issuer_primary_url": source_url,
                "issuer_primary_html_sha256": source_sha,
                "issuer_second_url": CONFIRM_URLS[game.name],
                "issuer_second_html_sha256": independent_sha,
                "scoring": scored,
                "source_trust": ("TWO_ISSUERS_DATE_AND_BALLS_AGREED_ONLY_ISSUE_UNVERIFIED"
                                 if game.name == "SSQ" else "PROVINCIAL_PAGES_AGREED_LATEST_ONLY"),
                "formal_A": 0, "edge": "NO_EDGE",
            }
            planned_scores.append((score_path, score))
        for path, result in planned_scores:
            _save_once(path, result)

        rows, _ = load_history(temp_history, game)
        next_issue = last["issue"] + 1
        if (game.name, next_issue) in candidates:
            outcome = "NO_NEW_ISSUE_ALREADY_RECORDED"
        else:
            rank = predict_with_bank(rows, game)
            if rank["target_issue"] != next_issue:
                raise ValueError("FUTURE_PREDICTION_BOUNDARY_MISMATCH")
            null_ticket, pair = _research_null(next_issue, game)
            payload = {
                "schema": "SSQDLT_ROLLING_RESEARCH_ISSUE_V1",
                "game": game.name, "target_issue": next_issue,
                "source_last_issue": last["issue"],
                "source_last_date_as_reported": last["date"],
                "prediction": {
                    "front": list(rank["prediction"]["front"]),
                    "back": list(rank["prediction"]["back"]),
                    "d2_pair": list(rank["prediction"]["d2_pair"]),
                },
                "research_null": {
                    "front": list(null_ticket[0]), "back": list(null_ticket[1]),
                    "d2_pair": list(pair), "not_formal_v47_null": True,
                },
                "formula_decision_sha256": rank["decision_sha256"],
                "historical_rows": len(rows), "history_sha256": sync["merged_history_sha256"],
                "issuer_primary_url": source_url,
                "issuer_primary_html_sha256": source_sha,
                "issuer_second_url": CONFIRM_URLS[game.name],
                "issuer_second_html_sha256": independent_sha,
                "research_only": True,
                "created_at_local_untrusted": now.astimezone(timezone.utc).isoformat(),
                "formal_A": 0, "edge": "NO_EDGE",
                "official_sales_cutoff_verified": False,
                "external_predraw_tsa": "NOT_RUN",
                "fixed_v47_null_preserved": True,
                "paid_model_calls": 0,
            }
            payload["content_sha256"] = digest(payload)
            target_path = (ledger / "research" / "forecasts" /
                           f"{game.name}-{next_issue}.json")
            _save_once(target_path, payload)
            outcome = "NEW_RESEARCH_PREVIEW_RECORDED"
        return {
            "game": game.name, "status": outcome,
            "asof_issue": last["issue"],
            "target_issue": next_issue,
            "scored_prior_issues": [x[1]["issue"] for x in planned_scores],
            "source_primary_sha256": source_sha,
            "source_secondary_sha256": independent_sha,
            "formal_A": 0, "edge": "NO_EDGE",
        }
    except Exception as exc:
        return {
            "game": game.name, "status": "BLOCKED",
            "error": f"{type(exc).__name__}:{exc}"[:900],
            "formal_A": 0, "edge": "NO_EDGE",
            "new_forecast": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError("output evidence attempt must be new")
    args.output_dir.mkdir(parents=True)
    outcomes = [
        process_one(game, args.ledger, args.output_dir)
        for game in (SSQ, DLT)
    ]
    receipt = {
        "schema": "SSQDLT_SHADOW_ROLLING_TICK_V1",
        "status": "RESEARCH_ONLY", "results": outcomes,
        "recorded_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
        "official_v47_formal_ledger_modified": False,
        "formal_A": 0, "edge": "NO_EDGE", "paid_model_calls": 0,
    }
    _save_once(args.output_dir / "tick.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
