"""Independent, read-only Git / GitHub Actions acceptance for SSQ＋DLT research.

It does not import or approve any prediction algorithm, certify an upstream
lottery source, or modify the frozen V4.7 Random NULL.  It checks the independent
Git history and Actions identities around the already-deployed research loop.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

class GateError(ValueError):
    """A mandatory evidence check is missing, ambiguous or contradicted."""

REPO = "douluo511/Geometry-Lotto-Pro"
WORKFLOW_ID = 414968846
TICK_SCHEMA = "SSQDLT_ACTIONS_RESEARCH_TICK_V1"
SCORE_SCHEMA = "SSQDLT_RESEARCH_SCORE_V1"
FROZEN_SCHEMA = "SSQDLT_RESEARCH_SNAPSHOT_2026_11_11_V1"
ROLLING_SCHEMA = "SSQDLT_ROLLING_RESEARCH_ISSUE_V1"
REGEX_SHA256 = re.compile(r"^[a-f0-9]{64}$")
REGEX_GIT_SHA = re.compile(r"^[a-f0-9]{40}$")
PATH_RE = re.compile(r"^[A-Za-z0-9._/+\\-]+$")
RECEIPT_FOLDERS = ("forecasts", "scores", "raw", "ticks")
GAME = {"SSQ": (33, 6, 16, 1), "DLT": (35, 5, 12, 2)}
SOURCES = {
    "SSQ": {
        "issuer-primary": "https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous",
        "issuer-secondary": "https://www.scflcp.com.cn/ssq",
    },
    "DLT": {
        "issuer-primary": "https://api.js-lottery.com/wfzq/dlt/data",
        "issuer-secondary": "https://www.gstc.org.cn/wanfa/dlt",
    },
}
MAX_JSON_BYTES = 16_000_000
MAX_RAW_BYTES = 2_000_000


def deny(code: str) -> None:
    raise GateError(code)


def _no_duplicate(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            deny("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _no_nonfinite(value):
    deny("NONFINITE_JSON_CONSTANT:" + str(value))


def load_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        deny("MISSING_OR_SYMLINK_RECEIPT")
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_JSON_BYTES:
            deny("OVERSIZED_JSON_RECEIPT")
        parsed = json.loads(raw.decode("utf-8"),
                            object_pairs_hook=_no_duplicate,
                            parse_constant=_no_nonfinite)
        if not isinstance(parsed, dict):
            deny("JSON_ROOT_NOT_OBJECT")
        return parsed
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateError("INVALID_JSON:" + str(exc)[:180]) from exc


def _sha256(value) -> bool:
    return isinstance(value, str) and bool(REGEX_SHA256.fullmatch(value))


def _sha40(value) -> bool:
    return isinstance(value, str) and bool(REGEX_GIT_SHA.fullmatch(value))


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _paths(root: Path):
    # Reject an entire research/ symlink before walking children. Checking
    # only research/forecasts would miss the ancestor symlink escape.
    if (root.is_symlink() or (root / "research").is_symlink()):
        deny("SYMLINK_RESEARCH_ROOT")
    for folder in RECEIPT_FOLDERS:
        directory = root / "research" / folder
        if directory.is_symlink():
            deny("SYMLINK_RESEARCH_DIRECTORY")
        if not directory.exists():
            continue
        for item in sorted(directory.rglob("*")):
            if item.is_symlink():
                deny("SYMLINK_RESEARCH_RECEIPT")
            if item.is_dir():
                continue
            rel = item.relative_to(root).as_posix()
            if not item.is_file() or not PATH_RE.fullmatch(rel) or item.suffix != ".json":
                deny("UNEXPECTED_RESEARCH_PATH:" + rel[:200])
            yield rel, item


def _ticket(ticket: dict, game: str) -> None:
    if not isinstance(ticket, dict):
        deny("INVALID_TICKET_OBJECT")
    mf, kf, mb, kb = GAME[game]
    for field, pool, size in (("front", mf, kf), ("back", mb, kb),
                              ("d2_pair", mf, 2)):
        values = ticket.get(field)
        if (not isinstance(values, list)
                or len(values) != size
                or any(type(n) is not int or n < 1 or n > pool for n in values)
                or values != sorted(set(values))):
            deny("ILLEGAL_OR_NONCANONICAL_" + game + "_" + field.upper())
    if not set(ticket["d2_pair"]).issubset(ticket["front"]):
        deny("D2_PAIR_OUTSIDE_PRIMARY_TICKET")


def _forecast_item(item: dict, *, legacy: bool) -> tuple[str, int]:
    game, issue = item.get("game"), item.get("target_issue")
    if game not in GAME or type(issue) is not int or issue <= 0:
        deny("INVALID_FORECAST_IDENTITY")
    if (not _sha256(item.get("content_sha256"))
            or (legacy and "formal_A" in item and
                (type(item["formal_A"]) is not int or item["formal_A"] != 0))
            or (not legacy and (type(item.get("formal_A")) is not int
                                or item["formal_A"] != 0))):
        # The immutable 2026 dual-game envelope holds formal_A at its root,
        # unlike later create-only per-game forecasts. Never rewrite it.
        deny("FORMAL_PROMOTION_OR_BAD_FORECAST_HASH")
    _ticket(item.get("prediction"), game)
    _ticket(item.get("research_null"), game)
    if not legacy:
        if (item.get("schema") != ROLLING_SCHEMA
                or item.get("edge") != "NO_EDGE"
                or item.get("research_only") is not True
                or item.get("official_sales_cutoff_verified") is not False
                or item.get("external_predraw_tsa") != "NOT_RUN"
                or item.get("paid_model_calls") != 0
                or item.get("source_last_issue") != issue - 1
                or item["research_null"].get("not_formal_v47_null") is not True):
            deny("FORMAL_OR_FUTURE_BOUNDARY_BYPASS")
        unsigned = {k: v for k, v in item.items() if k != "content_sha256"}
        actual = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
        if actual != item["content_sha256"]:
            deny("FORECAST_CONTENT_HASH_CHANGED")
    return game, issue


def scan_ledger(ledger: Path) -> dict:
    """Scan every research receipt, including losses; never mutate the ledger."""
    ledger = Path(ledger)
    paths = list(_paths(ledger))
    inventory = {folder: [] for folder in RECEIPT_FOLDERS}
    for rel, path in paths:
        inventory[rel.split("/")[1]].append((rel, path))

    forecasts: dict[tuple[str, int], dict] = {}
    legacy_count = 0
    for rel, path in inventory["forecasts"]:
        value = load_json(path)
        if value.get("schema") == FROZEN_SCHEMA:
            legacy_count += 1
            if (value.get("formal_A") != 0 or value.get("fixed_v47_random_null_used") is True
                    or value.get("predictive_edge_proven") is True
                    or value.get("evidence_class") not in (None,
                            "SHADOW_RESEARCH_NOT_FORMAL_V47")):
                deny("LEGACY_FORMAL_PROMOTION_ATTEMPT")
            items = value.get("issued")
            if (not isinstance(items, list) or len(items) != 2
                    or {x.get("game") for x in items if isinstance(x, dict)}
                    != {"SSQ", "DLT"}):
                deny("INCOMPLETE_OR_DUPLICATE_LEGACY_FORECAST")
        elif value.get("schema") == ROLLING_SCHEMA:
            items = [value]
        else:
            deny("UNKNOWN_FORECAST_RECORD_SCHEMA")
        for item in items:
            game, issue = _forecast_item(
                item, legacy=value.get("schema") == FROZEN_SCHEMA)
            if value.get("schema") == ROLLING_SCHEMA and path.name != (
                    game + "-" + str(issue) + ".json"):
                deny("FORECAST_FILE_ISSUE_MISMATCH")
            identity = (game, issue)
            if identity in forecasts:
                deny("DUPLICATE_RESEARCH_FORECAST:" + game + str(issue))
            forecasts[identity] = item

    raw_count = 0
    raw_lookup: set[tuple[str, str, str]] = set()
    for rel, path in inventory["raw"]:
        parts = rel.split("/")
        if len(parts) != 5 or parts[0:2] != ["research", "raw"]:
            deny("BAD_RAW_SOURCE_PATH")
        _, _, game, channel, filename = parts
        if game not in SOURCES or channel not in SOURCES[game]:
            deny("UNKNOWN_RAW_SOURCE_IDENTITY")
        hash_from_path = filename.removesuffix(".json")
        value = load_json(path)
        if (value.get("schema") != "SSQDLT_SOURCE_RAW_BYTES_V1"
                or value.get("game") != game
                or value.get("source_id") != channel
                or value.get("claimed_url") != SOURCES[game][channel]
                or value.get("origin_authenticity") != "NOT_INDEPENDENTLY_PROVEN"
                or not _sha256(hash_from_path)
                or value.get("raw_sha256") != hash_from_path):
            deny("RAW_SOURCE_ENVELOPE_OR_PATH_CHANGED")
        try:
            data = base64.b64decode(value["raw_base64"], validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise GateError("RAW_BASE64_INVALID") from exc
        if (len(data) > MAX_RAW_BYTES or type(value.get("size_bytes")) is not int
                or len(data) != value["size_bytes"]
                or hashlib.sha256(data).hexdigest() != hash_from_path):
            deny("RAW_BYTES_OR_HASH_CHANGED")
        raw_lookup.add((game, channel, hash_from_path))
        raw_count += 1

    scoreboard = {
        game: {"n": 0, "full_hits": 0, "d2_hits": 0,
               "research_null_full_hits": 0,
               "research_null_d2_hits": 0,
               "d2_paired_wins": 0, "d2_paired_losses": 0}
        for game in GAME
    }
    scored: set[tuple[str, int]] = set()
    for rel, path in inventory["scores"]:
        value = load_json(path)
        game, issue = value.get("game"), value.get("issue")
        if (game not in GAME or type(issue) is not int
                or path.name != game + "-" + str(issue) + ".json"
                or value.get("schema") != SCORE_SCHEMA
                or type(value.get("formal_A")) is not int
                or value["formal_A"] != 0 or value.get("edge") != "NO_EDGE"):
            deny("INVALID_STORED_SCORE_IDENTITY")
        key = (game, issue)
        if (key not in forecasts
                or forecasts[key]["content_sha256"]
                != value.get("original_prediction_ledger_record")):
            deny("SCORE_ORIGINAL_FORECAST_REFERENCE_CHANGED")
        if key in scored:
            deny("DUPLICATE_SCORE")
        for channel, hkey in (
            ("issuer-primary", "issuer_primary_html_sha256"),
            ("issuer-secondary", "issuer_second_html_sha256"),
        ):
            raw_sha = value.get(hkey)
            if not _sha256(raw_sha) or (game, channel, raw_sha) not in raw_lookup:
                deny("SCORE_MISSING_BOUND_ORIGINAL_HTTP")
        scoring = value.get("scoring")
        if not isinstance(scoring, dict):
            deny("MISSING_SCORE_VECTOR")
        for k in ("research_full_hit", "research_d2_hit",
                  "research_null_full_hit", "research_null_d2_hit"):
            if type(scoring.get(k)) is not int or scoring[k] not in (0, 1):
                deny("INVALID_SCORE_BIT:" + k)
        s = scoreboard[game]
        s["n"] += 1
        s["full_hits"] += scoring["research_full_hit"]
        s["d2_hits"] += scoring["research_d2_hit"]
        s["research_null_full_hits"] += scoring["research_null_full_hit"]
        s["research_null_d2_hits"] += scoring["research_null_d2_hit"]
        s["d2_paired_wins"] += int(
            scoring["research_d2_hit"] == 1 and
            scoring["research_null_d2_hit"] == 0)
        s["d2_paired_losses"] += int(
            scoring["research_d2_hit"] == 0 and
            scoring["research_null_d2_hit"] == 1)
        scored.add(key)

    tick_receipts = []
    for rel, path in inventory["ticks"]:
        value = load_json(path)
        if (value.get("schema") != TICK_SCHEMA
                or not path.stem.isdecimal()
                or value.get("github_run_id") != path.stem
                or not isinstance(value.get("github_run_attempt"), str)
                or not value["github_run_attempt"].isdecimal()
                or int(value["github_run_attempt"]) < 1
                or value.get("trigger") not in ("push", "schedule", "workflow_dispatch")
                or not _sha40(value.get("workflow_source_commit"))
                or not _sha40(value.get("pinned_formula_commit"))):
            deny("INVALID_GITHUB_TICK_RECORD")
        report = value.get("report")
        if (not isinstance(report, dict)
                or report.get("schema") != "SSQDLT_SHADOW_ROLLING_TICK_V1"
                or report.get("status") != "RESEARCH_ONLY"
                or type(report.get("formal_A")) is not int
                or report["formal_A"] != 0
                or report.get("edge") != "NO_EDGE"
                or report.get("paid_model_calls") != 0):
            deny("TICK_FORMAL_PROMOTION_OR_MALFORMATION")
        results = report.get("results")
        if (not isinstance(results, list) or len(results) != 2
                or {x.get("game") for x in results if isinstance(x, dict)}
                   != {"SSQ", "DLT"}):
            deny("TICK_INCOMPLETE_TWO_GAME_ROSTER")
        for entry in results:
            if (type(entry.get("formal_A")) is not int
                    or entry["formal_A"] != 0
                    or entry.get("edge") != "NO_EDGE"
                    or entry.get("status") not in (
                        "BLOCKED", "NO_NEW_ISSUE_ALREADY_RECORDED",
                        "NEW_RESEARCH_PREVIEW_RECORDED")):
                deny("TICK_NONCANONICAL_GAME_RESULT")
        tick_receipts.append(value)

    for game, s in scoreboard.items():
        n = s["n"]
        s["full_rate"] = s["full_hits"] / n if n else None
        s["d2_rate"] = s["d2_hits"] / n if n else None
        s["research_null_d2_rate"] = s["research_null_d2_hits"] / n if n else None
        s["comparison_control"] = "RESEARCH_NULL_NOT_FROZEN_V47"
        s["eligible_formal_samples"] = 0

    full_inventory = hashlib.sha256()
    for rel, path in paths:
        encoded = rel.encode("utf-8")
        raw = path.read_bytes()
        full_inventory.update(len(encoded).to_bytes(4, "big"))
        full_inventory.update(encoded)
        full_inventory.update(hashlib.sha256(raw).digest())

    return {
        "status": "PASS_RESEARCH_CONSISTENCY_ONLY",
        "forecast_count": len(forecasts),
        "legacy_combined_documents": legacy_count,
        "legacy_full_prediction_hash_rerender": "UNVERIFIED",
        "score_count": len(scored),
        "raw_count": raw_count,
        "tick_count": len(tick_receipts),
        "unscored_targets": {
            game: sum(g == game for g, _ in forecasts) - scoreboard[game]["n"]
            for game in GAME
        },
        "scoreboard": scoreboard,
        "all_research_receipt_bytes_sha256": full_inventory.hexdigest(),
        "_ticks": tick_receipts,
    }


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=True, timeout=45)
        return completed.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateError("GIT_HISTORY_UNAVAILABLE:" + str(exc)[:220]) from exc


def validate_git_append_only(ledger: Path) -> dict:
    """Verify full Git ancestry, not just the current file hashes."""
    root = Path(ledger)
    if _git(root, "rev-parse", "--is-shallow-repository").strip() != "false":
        deny("SHALLOW_LEDGER_HISTORY_CANNOT_PROVE_APPEND_ONLY")
    patterns = ["research/" + part for part in RECEIPT_FOLDERS]
    if _git(root, "status", "--porcelain", "--untracked-files=all",
            "--", *patterns).strip():
        deny("DIRTY_LEDGER_CHECKOUT")
    tracked = _git(root, "ls-files", "--cached", "--", *patterns).splitlines()
    if not tracked:
        deny("NO_TRACKED_RESEARCH_EVIDENCE")
    if any(not PATH_RE.fullmatch(p) or not p.endswith(".json") for p in tracked):
        deny("BAD_TRACKED_RESEARCH_PATH")
    disk = sorted(rel for rel, _ in _paths(root))
    if sorted(tracked) != disk:
        deny("TRACKED_LEDGER_FILE_SET_CHANGED")
    changes = _git(root, "log", "--no-renames", "--format=",
                   "--name-status", "--", *patterns)
    additions = Counter()
    bad = []
    for line in changes.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2 or parts[0] != "A":
            bad.append(line[:170])
            continue
        additions[parts[1]] += 1
    if bad or any(additions.get(path) != 1 for path in tracked):
        deny("NON_APPEND_GIT_HISTORY:" + str(bad[:4])[:300])
    return {"status": "PASS", "appended_files": len(tracked),
            "non_add_commits": len(bad),
            "ledger_head_sha": _git(root, "rev-parse", "HEAD").strip(),
            "git_history_mode": "FULL_REPOSITORY_ANCESTRY_NOT_EXTERNAL_WORM"}


def verify_actions_ticks(ticks: list[dict], fetcher) -> dict:
    """Each saved trigger must match the actual GitHub Actions REST event."""
    seen = set()
    counts = Counter()
    evidence = []
    for tick in ticks:
        run_id = tick["github_run_id"]
        if run_id in seen:
            deny("DUPLICATE_GITHUB_ACTIONS_RUN_ID")
        seen.add(run_id)
        try:
            run = fetcher(run_id)
        except Exception as exc:
            raise GateError("ACTIONS_FETCH_UNVERIFIED:" + str(exc)[:180]) from exc
        if not isinstance(run, dict) or type(run.get("id")) is not int or (
                run["id"] != int(run_id)):
            deny("GITHUB_API_RUN_ID_MISMATCH")
        if run.get("workflow_id") != WORKFLOW_ID:
            deny("GITHUB_API_WORKFLOW_ID_MISMATCH")
        if (run.get("repository", {}).get("full_name") != REPO
                or run.get("head_branch") != "main"):
            deny("GITHUB_API_REPOSITORY_OR_BRANCH_MISMATCH")
        if run.get("head_sha") != tick["workflow_source_commit"]:
            deny("GITHUB_API_SOURCE_SHA_MISMATCH")
        if run.get("event") != tick["trigger"]:
            deny("GITHUB_API_EVENT_MISMATCH")
        if type(run.get("run_attempt")) is not int or (
                run["run_attempt"] != int(tick["github_run_attempt"])):
            deny("GITHUB_API_RUN_ATTEMPT_MISMATCH")
        if (run.get("status") != "completed"
                or run.get("conclusion") != "success"):
            deny("GITHUB_API_RUN_NOT_SUCCESS")
        url = "https://github.com/" + REPO + "/actions/runs/" + run_id
        if run.get("html_url") != url:
            deny("GITHUB_API_RUN_URL_MISMATCH")
        counts[tick["trigger"]] += 1
        evidence.append({
            "run_id": run_id, "event": run["event"],
            "head_sha": run["head_sha"],
            "run_attempt": run["run_attempt"], "run_url": url,
        })
    return {
        "status": "PASS" if ticks else "UNVERIFIED_NO_TICKS",
        "api_verified_tick_count": len(ticks),
        "verified_push_runs": counts["push"],
        "verified_dispatch_runs": counts["workflow_dispatch"],
        "verified_schedule_runs": counts["schedule"],
        "schedule_two_trigger_gate": "PASS" if counts["schedule"] >= 2
                                    else "UNVERIFIED",
        "actions_evidence": evidence,
    }


def _fetch_github_run(run_id: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        deny("GITHUB_TOKEN_MISSING_ACTIONS_API_UNVERIFIED")
    url = ("https://api.github.com/repos/" + REPO +
           "/actions/runs/" + run_id)
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "SSQDLT-ReadOnly-Ledger-Auditor-v1",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            deny("GITHUB_ACTIONS_API_NON_200")
        data = response.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        deny("GITHUB_ACTIONS_API_OVERSIZED")
    try:
        return json.loads(data.decode("utf-8"),
                          object_pairs_hook=_no_duplicate,
                          parse_constant=_no_nonfinite)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateError("BAD_GITHUB_API_RUN_JSON") from exc


def overall_report(ledger: Path, *, fetcher=None, verify_git=False) -> dict:
    scanned = scan_ledger(ledger)
    ticks = scanned.pop("_ticks")
    git_result = validate_git_append_only(ledger) if verify_git else None
    actions = verify_actions_ticks(ticks, fetcher) if fetcher is not None else None
    return {
        "schema": "SSQDLT_INDEPENDENT_RESEARCH_LEDGER_AUDIT_V1",
        "ledger_integrity": "PASS",
        "git_append_only_history": git_result if git_result else "UNVERIFIED",
        "actions_api": actions["status"] if actions else "UNVERIFIED",
        "schedule_two_trigger_gate": (
            actions["schedule_two_trigger_gate"] if actions else "UNVERIFIED"),
        "verified_schedule_runs": actions["verified_schedule_runs"] if actions else 0,
        "verified_push_runs": actions["verified_push_runs"] if actions else 0,
        "verified_dispatch_runs": actions["verified_dispatch_runs"] if actions else 0,
        "actions_evidence": actions["actions_evidence"] if actions else [],
        "inventory": scanned,
        "engineering_pass": "NOT_YET",
        "research_valid": "NOT_YET",
        "formal_A": 0,
        "edge": "NO_EDGE",
        "limits": [
            "Original combined forecast hashes require original full preview artifact; their exact preview equivalence is UNVERIFIED.",
            "Git full ancestry and Actions API are neither independent RFC3161 predraw timestamps nor immutable external WORM evidence.",
            "Research-only source bytes are not independently authenticated official draw/sales cutoff.",
            "Actual formal six-arm V4.7 predraw/score loop and Windows physical cold restart still NOT_VERIFIED.",
            "Two proven schedule events prove scheduler triggers only, not predictive edge or complete draw-cycle.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--check-git-history", action="store_true")
    ap.add_argument("--check-actions-api", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    try:
        result = overall_report(
            args.ledger,
            fetcher=_fetch_github_run if args.check_actions_api else None,
            verify_git=args.check_git_history,
        )
        code = 0
    except (GateError, OSError, TypeError, KeyError) as exc:
        result = {
            "schema": "SSQDLT_INDEPENDENT_RESEARCH_LEDGER_AUDIT_V1",
            "ledger_integrity": "FAIL",
            "status": "BLOCKED", "blocker": str(exc)[:500],
            "schedule_two_trigger_gate": "UNVERIFIED",
            "engineering_pass": "NOT_YET",
            "research_valid": "NOT_YET",
            "formal_A": 0, "edge": "NO_EDGE",
        }
        code = 2
    body = json.dumps(result, ensure_ascii=False, indent=2,
                      sort_keys=True, allow_nan=False) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as file:
            file.write(body)
    print(body)
    return code


if __name__ == "__main__":
    sys.exit(main())
