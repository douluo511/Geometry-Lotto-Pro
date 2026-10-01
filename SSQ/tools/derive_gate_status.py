"""Derive only the SSQ release gates that current-run artifacts actually prove.

Unimplemented evidence contracts remain PENDING.  This deliberately prevents a
build or an EXE smoke check from manufacturing a full-system Final Gate PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from release_gate_22 import HARD_GATES

REQUIRED_EXE_CHECKS = frozenset({
    "self", "integrity-tamper", "offline-failclosed", "corrupt-repair",
    "update", "science", "random-world-101", "random-world-202",
    "random-world-303", "predict", "audit", "gui", "maintenance",
    "unicode-path-no-python-path", "default-gui-launch", "reproducible-build",
})

# A nonempty subset, truthy string (including "FAIL"), or bool-as-int count
# must not turn a partial/static report into an acceptance PASS.
REQUIRED_BUSINESS_CHECKS = frozenset({
    "business_game_contract", "business_official_sources", "business_four_entries",
    "business_model_inventory", "business_walk_forward", "business_statistics",
    "business_ablation", "business_leakage_and_confirmation",
    "business_freeze_audit_isolation", "business_no_overclaim",
})
REPRO_WORKSPACE_KEYS = (
    "primary_dist", "rebuild_dist",
    "primary_workpath", "rebuild_workpath",
    "primary_specpath", "rebuild_specpath",
)


def _repro_workspace_isolated(check: Any) -> bool:
    if not isinstance(check, dict) or check.get("workspace_isolated") is not True:
        return False
    paths = check.get("workspace_paths")
    if not isinstance(paths, dict) or any(
        not isinstance(paths.get(key), str) or not paths.get(key).strip()
        for key in REPRO_WORKSPACE_KEYS
    ):
        return False
    normalized = {key: paths[key].strip().replace("\\", "/").lower()
                  for key in REPRO_WORKSPACE_KEYS}
    return bool(
        normalized["primary_dist"] != normalized["rebuild_dist"]
        and normalized["primary_workpath"] != normalized["rebuild_workpath"]
        and normalized["primary_specpath"] != normalized["rebuild_specpath"]
    )


REQUIRED_NETCLIENT_CHECKS = frozenset({
    "https_only", "timeout_pair_required", "429_retry_then_success",
    "separate_connect_read_timeout", "https_redirect_downgrade_fail_closed",
    "retry_cap_exception_fail_closed", "retry_after_hard_cap",
    "raw_payload_evidence", "wrong_content_type_fail_closed",
    "empty_payload_fail_closed", "streaming_body_limit_fail_closed",
    "total_operation_deadline_fail_closed",
})

EXPECTED_INDEPENDENT_REPOSITORY = "douluo511/Geometry-Lotto-Pro-SSQ"

_GATE_PROMOTION_POLICY = {
    "schema": "false-edge-firewall-v8",
    "min_walk_forward": 1200,
    "min_prospective": 120,
    "min_era_count": 3,
    "alpha": 0.01,
    "min_front_recall_gain": 0.04,
    "min_back_recall_gain": 0.03,
    "min_bootstrap_lower": 0.0,
    "min_null_percentile": 0.95,
    "max_null_world_fpr": 0.05,
    "min_wilson_lower": 0.50,
    "min_model_coverage": 0.60,
    "min_rank_support": 0.60,
    "min_confirmation_n": 120,
    "windows": [30, 60, 120, 240],
    "seeds": [17, 43, 97, 193, 389],
    "ablation_modes": ["remove", "shuffle", "random_replace"],
    "bootstrap_rounds": 1999,
    "permutation_rounds": 2000,
    "null_worlds": 300,
}
_GATE_SCIENCE_NAMES = (
    "Walk-forward OOS",
    "Random Baseline",
    "Bootstrap",
    "Permutation + Holm Reality Check",
    "Temporal LOEO",
    "Ablation Remove/Shuffle/Random",
    "Leakage Sentinel",
    "Null-world FPR",
    "Untouched Holdout",
    "Dual Final Confirmation",
    "Wilson/Coverage/Rank Support",
    "Prospective Replay",
)

_GATE_CHINA_TZ = timezone(timedelta(hours=8))
_GATE_SSQ_DRAW_WEEKDAYS = frozenset({1, 3, 6})
_GATE_FRESHNESS_POLICY_SOURCES = {
    "rule": "https://zhs.mof.gov.cn/zhengcefabu/201404/t20140421_1069579.htm",
    "2025": "https://zhs.mof.gov.cn/zhengcefabu/202412/t20241206_3949123.htm",
    "2026": "https://www.mof.gov.cn/gp/xxgkml/zhs/202512/t20251225_3980248.htm",
}
_GATE_MARKET_CLOSURES = {
    2025: (
        (date(2025, 1, 27), date(2025, 2, 5)),
        (date(2025, 10, 1), date(2025, 10, 4)),
    ),
    2026: (
        (date(2026, 2, 14), date(2026, 2, 23)),
        (date(2026, 10, 1), date(2026, 10, 4)),
    ),
}


def _expected_gate_latest_completed_draw_day(today: date) -> date:
    if today.year not in _GATE_MARKET_CLOSURES:
        raise ValueError(f"no frozen official freshness calendar for {today.year}")
    cursor = today - timedelta(days=1)
    for _ in range(40):
        ranges = _GATE_MARKET_CLOSURES.get(cursor.year)
        if ranges is None:
            raise ValueError(f"no frozen official freshness calendar for {cursor.year}")
        closed = any(start <= cursor <= end for start, end in ranges)
        if cursor.weekday() in _GATE_SSQ_DRAW_WEEKDAYS and not closed:
            return cursor
        cursor -= timedelta(days=1)
    raise ValueError("could not independently resolve latest completed SSQ draw day")
EXPECTED_GITHUB_SERVER_URL = "https://github.com"


def _repository_independence_proof() -> tuple[str, dict[str, Any]]:
    actual_repository = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    actual_server = str(os.environ.get("GITHUB_SERVER_URL") or "").rstrip("/")
    github_actions = str(os.environ.get("GITHUB_ACTIONS") or "").lower() == "true"
    checks = {
        "github_actions": github_actions,
        "repository_exact": actual_repository == EXPECTED_INDEPENDENT_REPOSITORY,
        "server_exact": actual_server == EXPECTED_GITHUB_SERVER_URL,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return status, {
        "status": status,
        "expected_repository": EXPECTED_INDEPENDENT_REPOSITORY,
        "actual_repository": actual_repository,
        "expected_server_url": EXPECTED_GITHUB_SERVER_URL,
        "actual_server_url": actual_server,
        "checks": checks,
        "source": "GitHub Actions immutable environment",
    }


def _release_context_proof() -> tuple[str, dict[str, Any]]:
    event = str(os.environ.get("GITHUB_EVENT_NAME") or "").strip()
    ref = str(os.environ.get("GITHUB_REF") or "").strip()
    repository = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    github_actions = str(os.environ.get("GITHUB_ACTIONS") or "").lower() == "true"
    checks = {
        "github_actions": github_actions,
        "independent_repository": repository == EXPECTED_INDEPENDENT_REPOSITORY,
        "event_is_release_capable": event in {"push", "workflow_dispatch"},
        "frozen_main_ref": ref == "refs/heads/main",
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return status, {
        "status": status,
        "event": event,
        "ref": ref,
        "repository": repository,
        "required_ref": "refs/heads/main",
        "allowed_events": ["push", "workflow_dispatch"],
        "checks": checks,
        "rule": "Portfolio FINAL may only originate from the independent repository frozen main branch",
    }


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_current_report(
    evidence: Path, filename: str, schema: str | None = None
) -> dict[str, Any]:
    report = _read(evidence / filename)
    if not isinstance(report, dict) or not report:
        raise ValueError(f"{filename} is missing or malformed")
    if schema is not None and report.get("schema") != schema:
        raise ValueError(f"{filename} has the wrong schema")
    if (report.get("status") != "PASS"
            or report.get("github_sha") != os.environ.get("GITHUB_SHA")
            or report.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")):
        raise ValueError(f"{filename} is not a PASS bound to the current run")
    return report


def _require_exact_result(evidence: Path, name: str, exe_hash: str) -> dict[str, Any]:
    report = _read(evidence / f"{name}.json")
    if (not isinstance(report, dict) or report.get("status") != "PASS"
            or report.get("scope") != name or report.get("game") != "SSQ"
            or report.get("platform") != "win32"
            or report.get("github_sha") != os.environ.get("GITHUB_SHA")
            or report.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or report.get("exe_sha256") != exe_hash
            or report.get("final_release_gate") != "PENDING"):
        raise ValueError(f"exact-EXE {name} result is not current-run/hash bound")
    return report


def _require_source_result(
    evidence: Path, filename: str, scope: str
) -> dict[str, Any]:
    report = _read(evidence / filename)
    if (not isinstance(report, dict) or report.get("status") != "PASS"
            or report.get("scope") != scope
            or report.get("github_sha") != os.environ.get("GITHUB_SHA")
            or report.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")):
        raise ValueError(f"{filename} is not a current-run source PASS for {scope}")
    return report


def _rederive_court_hash(court: dict[str, Any]) -> str:
    declared = court.get("court_hash")
    if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
        raise ValueError("evidence court hash is missing or malformed")
    payload = dict(court)
    payload.pop("court_hash", None)
    computed = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if computed != declared:
        raise ValueError("evidence court hash does not match independently canonicalized court")
    return computed


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is not a real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} is non-finite")
    return number


def _exact_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} is not a nonnegative integer")
    return value


def _rederive_promotion_decision(court: dict[str, Any]) -> dict[str, Any]:
    policy = court.get("pre_registered_policy")
    if policy != _GATE_PROMOTION_POLICY:
        raise ValueError("science promotion policy differs from the frozen gate policy")

    tests = court.get("model_tests")
    reality = court.get("reality_check")
    loeo = court.get("loeo")
    ablation = court.get("ablation")
    null_world = court.get("null_world")
    holdout = court.get("untouched_holdout")
    dual = court.get("dual_final_confirmation")
    support = court.get("support_gate")
    walk = court.get("walk_forward")
    if not all(isinstance(x, dict) for x in (
        tests, reality, loeo, ablation, null_world, holdout, dual, support, walk
    )):
        raise ValueError("science promotion evidence sections are incomplete")

    primary = tests.get("research_ensemble")
    reality_primary = reality.get("research_ensemble")
    primary_boot = primary.get("bootstrap") if isinstance(primary, dict) else None
    holdout_boot = holdout.get("bootstrap")
    if not all(isinstance(x, dict) for x in (primary, reality_primary, primary_boot, holdout_boot)):
        raise ValueError("science promotion primary/bootstrap evidence is incomplete")

    n = _exact_nonnegative_int(primary.get("n"), "research ensemble OOS n")
    front_gain = _finite_number(primary.get("front_recall_gain"), "front recall gain")
    back_gain = _finite_number(primary.get("back_recall_gain"), "back recall gain")
    combined_gain = _finite_number(primary.get("combined_gain"), "combined gain")
    primary_lower = _finite_number(primary_boot.get("lower95"), "development bootstrap lower95")
    holdout_lower = _finite_number(holdout_boot.get("lower95"), "holdout bootstrap lower95")
    holdout_p = _finite_number(holdout.get("permutation_p"), "holdout permutation p")
    false_positive_rate = _finite_number(null_world.get("false_positive_rate"), "null-world FPR")
    observed_percentile = _finite_number(null_world.get("observed_percentile"), "null-world percentile")
    leakage = _exact_nonnegative_int(walk.get("leakage_violations"), "walk-forward leakage violations")
    top_leakage = _exact_nonnegative_int(court.get("leakage_violations"), "court leakage violations")
    if leakage != top_leakage:
        raise ValueError("science leakage counters disagree")

    prospective_n = _exact_nonnegative_int(court.get("prospective_n"), "prospective count")
    prospective_selector_consistent = court.get("prospective_selector_consistent")
    if not isinstance(prospective_selector_consistent, bool):
        raise ValueError("prospective selector consistency is not boolean")

    predictive_pass = (
        n >= _GATE_PROMOTION_POLICY["min_walk_forward"]
        and front_gain > _GATE_PROMOTION_POLICY["min_front_recall_gain"]
        and back_gain > _GATE_PROMOTION_POLICY["min_back_recall_gain"]
        and primary_lower > _GATE_PROMOTION_POLICY["min_bootstrap_lower"]
        and reality_primary.get("reject_null") is True
    )
    loeo_pass = loeo.get("passed") is True
    holdout_pass = (
        holdout_lower > 0
        and 0 <= holdout_p <= _GATE_PROMOTION_POLICY["alpha"]
    )
    leakage_pass = leakage == 0
    null_pass = (
        0 <= false_positive_rate <= _GATE_PROMOTION_POLICY["max_null_world_fpr"]
        and observed_percentile >= _GATE_PROMOTION_POLICY["min_null_percentile"]
    )
    dual_pass = dual.get("passed") is True
    ablation_pass = ablation.get("passed") is True
    edge_proven = all((
        predictive_pass, loeo_pass, holdout_pass, dual_pass,
        ablation_pass, leakage_pass, null_pass,
    ))
    support_pass = support.get("passed") is True
    certified_dan = (
        edge_proven
        and support_pass
        and prospective_n >= _GATE_PROMOTION_POLICY["min_prospective"]
        and prospective_selector_consistent
    )

    expected_decisions = {
        "Walk-forward OOS": "ACCEPT_EDGE" if predictive_pass else "REJECT_EDGE",
        "Random Baseline": "ABOVE_BASELINE" if combined_gain > 0 else "NOT_ABOVE_BASELINE",
        "Bootstrap": "ACCEPT_EDGE" if primary_lower > 0 else "REJECT_EDGE",
        "Permutation + Holm Reality Check": (
            "ACCEPT_EDGE" if reality_primary.get("reject_null") is True else "REJECT_EDGE"
        ),
        "Temporal LOEO": "SUPPORT_EDGE" if loeo_pass else "REJECT_EDGE",
        "Ablation Remove/Shuffle/Random": "ACCEPT_EDGE" if ablation_pass else "REJECT_EDGE",
        "Leakage Sentinel": "ACCEPT" if leakage_pass else "REJECT_EDGE",
        "Null-world FPR": "ACCEPT_EDGE" if null_pass else "REJECT_EDGE",
        "Untouched Holdout": "ACCEPT_EDGE" if holdout_pass else "REJECT_EDGE",
        "Dual Final Confirmation": "ACCEPT_EDGE" if dual_pass else "REJECT_EDGE",
        "Wilson/Coverage/Rank Support": "ACCEPT_DAN" if support_pass else "REJECT_DAN",
        "Prospective Replay": (
            "ACCEPT_DAN"
            if prospective_n >= _GATE_PROMOTION_POLICY["min_prospective"]
            else "REJECT_DAN"
        ),
    }
    rows = court.get("gates")
    if not isinstance(rows, list) or len(rows) != len(_GATE_SCIENCE_NAMES):
        raise ValueError("science court does not contain the exact 12 named checks")
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("name") not in _GATE_SCIENCE_NAMES:
            raise ValueError("science court contains an unknown or malformed named check")
        name = row["name"]
        if name in by_name:
            raise ValueError("science court contains a duplicate named check")
        by_name[name] = row
    if tuple(row.get("name") for row in rows) != _GATE_SCIENCE_NAMES:
        raise ValueError("science court named-check order differs from the frozen contract")
    for name, expected in expected_decisions.items():
        row = by_name[name]
        expected_status = "PASS" if name != "Leakage Sentinel" or leakage_pass else "FAIL"
        if row.get("status") != expected_status or row.get("decision") != expected:
            raise ValueError(f"science named check {name} contradicts independent statistics")

    expected_software = "PASS" if all(row.get("status") == "PASS" for row in rows) else "FAIL"
    expected_edge_state = "EDGE_PROVEN" if edge_proven else "NO_EDGE"
    expected_dan_state = "CERTIFIED_DAN" if certified_dan else "NULL_DAN"
    expected_weights = {
        "uniform_baseline": 0.0 if certified_dan else 1.0,
        "research_ensemble": 1.0 if certified_dan else 0.0,
    }
    lifecycle = court.get("lifecycle")
    final = court.get("final_validation")
    if (court.get("software_verdict") != expected_software
            or court.get("edge_state") != expected_edge_state
            or court.get("dan_state") != expected_dan_state
            or court.get("decision") != ("ACCEPT_EDGE" if edge_proven else "REJECT_EDGE")
            or court.get("production_weights") != expected_weights
            or not isinstance(lifecycle, dict)
            or lifecycle.get("Champion") != (
                "research_ensemble" if certified_dan else "uniform_baseline"
            )
            or not isinstance(final, dict)
            or final.get("status") != expected_software
            or final.get("hard_fail_count") != sum(
                1 for row in rows if row.get("status") == "FAIL"
            )
            or final.get("edge_proven") is not edge_proven
            or final.get("dan_certified") is not certified_dan):
        raise ValueError("science promotion result contradicts independently re-derived decision")

    return {
        "edge_proven": edge_proven,
        "dan_certified": certified_dan,
        "predictive_pass": predictive_pass,
        "loeo_pass": loeo_pass,
        "holdout_pass": holdout_pass,
        "dual_pass": dual_pass,
        "ablation_pass": ablation_pass,
        "leakage_pass": leakage_pass,
        "null_pass": null_pass,
        "support_pass": support_pass,
        "prospective_n": prospective_n,
    }


def _verify_science_contract(report: dict[str, Any]) -> dict[str, Any]:
    court = report.get("result")
    if not isinstance(court, dict):
        raise ValueError("science result has no evidence court")
    court_hash = _rederive_court_hash(court)
    promotion = _rederive_promotion_decision(court)
    final = court.get("final_validation")
    walk = court.get("walk_forward")
    policy = court.get("pre_registered_policy")
    gates = court.get("gates")
    five_why = court.get("five_why")
    reverse = court.get("reverse_validation")
    if (court.get("software_verdict") != "PASS"
            or not isinstance(final, dict) or final.get("status") != "PASS"
            or int(final.get("hard_fail_count", -1)) != 0
            or not isinstance(walk, dict)
            or int(walk.get("development_oos_n", 0)) < 1200
            or int(walk.get("untouched_holdout_n", 0)) < 120
            or int(walk.get("leakage_violations", -1)) != 0
            or not isinstance(policy, dict)
            or float(policy.get("alpha", 1.0)) > 0.01
            or not isinstance(gates, list) or not gates
            or any(not isinstance(row, dict) or row.get("status") != "PASS" for row in gates)
            or not isinstance(five_why, dict) or len(five_why) < 5
            or not isinstance(reverse, dict)
            or not all(reverse.get(key) is True for key in ("remove", "shuffle", "random_replace"))):
        raise ValueError("science evidence court did not satisfy the frozen validation contract")
    edge_state = court.get("edge_state")
    dan_state = court.get("dan_state")
    if edge_state == "NO_EDGE" and dan_state != "NULL_DAN":
        raise ValueError("NO_EDGE science result attempted to certify dan")
    if final.get("edge_proven") is False and edge_state != "NO_EDGE":
        raise ValueError("science edge state contradicts final validation")
    return {
        "court_hash": court_hash,
        "edge_state": edge_state,
        "dan_state": dan_state,
        "development_oos_n": walk.get("development_oos_n"),
        "untouched_holdout_n": walk.get("untouched_holdout_n"),
        "leakage_violations": walk.get("leakage_violations"),
        "independent_promotion": promotion,
    }


def _verify_counterexample_contract(
    science: dict[str, Any], random_worlds: list[dict[str, Any]]
) -> dict[str, Any]:
    court = science.get("result")
    null_world = court.get("null_world") if isinstance(court, dict) else None
    policy = court.get("pre_registered_policy") if isinstance(court, dict) else None
    if not isinstance(null_world, dict) or not isinstance(policy, dict):
        raise ValueError("science null-world evidence is missing")
    worlds = int(null_world.get("worlds", 0))
    fpr = float(null_world.get("false_positive_rate", 1.0))
    if (worlds < int(policy.get("null_worlds", 300))
            or fpr > float(policy.get("max_null_world_fpr", 0.05))
            or len(random_worlds) != 3):
        raise ValueError("counterexample/null-world firewall did not satisfy policy")
    for report in random_worlds:
        result = report.get("result")
        if not isinstance(result, dict) or result.get("status") not in {None, "PASS"}:
            raise ValueError("random-world evidence is malformed")
    return {"worlds": worlds, "false_positive_rate": fpr, "exact_random_world_checks": 3}


def _verify_reversal_contract(
    science: dict[str, Any], audit: dict[str, Any]
) -> dict[str, Any]:
    court = science.get("result")
    if not isinstance(court, dict):
        raise ValueError("science court is missing")
    science_court_hash = _rederive_court_hash(court)
    reverse = court.get("reverse_validation")
    ablation = court.get("ablation")
    audit_result = audit.get("result")
    audit_court = audit_result.get("court") if isinstance(audit_result, dict) else None
    if not isinstance(audit_court, dict):
        raise ValueError("audit court is missing")
    audit_court_hash = _rederive_court_hash(audit_court)
    audit_reverse = audit_court.get("reverse_validation")
    audit_ablation = audit_court.get("ablation") if isinstance(audit_court, dict) else None
    if (not isinstance(reverse, dict)
            or not all(reverse.get(key) is True for key in ("remove", "shuffle", "random_replace"))
            or not isinstance(ablation, dict) or ablation.get("executed") is not True
            or not isinstance(audit_result, dict)
            or audit_result.get("software_verdict") != "PASS"
            or not isinstance(audit_court, dict)
            or audit_court.get("software_verdict") != "PASS"
            or audit_court.get("edge_state") != "NO_EDGE"
            or audit_court.get("dan_state") != "NULL_DAN"
            or audit_court.get("pre_registered_policy") != court.get("pre_registered_policy")
            or audit_court.get("model_hash") != court.get("model_hash")
            or audit_court.get("selector_hash") != court.get("selector_hash")
            or audit_reverse != reverse
            or not isinstance(audit_ablation, dict)
            or audit_ablation.get("executed") is not True
            or not isinstance(audit_court.get("final_validation"), dict)
            or audit_court["final_validation"].get("status") != "PASS"):
        raise ValueError("reversal/ablation/audit evidence did not PASS")
    return {
        "remove": True,
        "shuffle": True,
        "random_replace": True,
        "ablation_executed": True,
        "audit_edge_state": audit_court.get("edge_state"),
        "science_court_hash": science_court_hash,
        "audit_court_hash": audit_court_hash,
    }


def _utc_recent(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    return now - timedelta(hours=24) <= stamp <= now + timedelta(minutes=5)


def _raw_status_allowed(http_status: Any, receipt_status: str) -> bool:
    # A failed source is allowed in an otherwise valid two-source fallback only
    # as a documented FAIL, never as a successful 200 receipt. The Store's
    # independent validator verifies the actual status range and raw bytes.
    return receipt_status == "FAIL" or (receipt_status == "PASS" and http_status == 200)


def _canonical_hash(draws: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(draws, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _parsed_draw(issue: Any, draw_day: Any, reds: Any, blue: Any) -> dict[str, Any]:
    """A gate-local SSQ schema check, independent of the producer's Draw object."""
    issue = str(issue or "").strip()
    if re.fullmatch(r"\d{5}", issue):
        issue = "20" + issue
    if not re.fullmatch(r"20\d{5}", issue):
        raise ValueError("raw page has an invalid SSQ issue")
    match = re.fullmatch(r"(20\d{2})[-/](\d{2})[-/](\d{2})(?:\s*\([^)]*\))?",
                         str(draw_day or "").strip())
    if match is None:
        raise ValueError("raw page has an invalid SSQ date")
    day = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    date.fromisoformat(day)
    if issue[:4] != day[:4]:
        raise ValueError("raw issue/date years disagree")

    def numbers(value: Any, count: int) -> list[int]:
        if isinstance(value, (list, tuple)):
            tokens = list(value)
        elif count == 6 and re.fullmatch(r"\d{12}", str(value or "").strip()):
            compact = str(value).strip()
            tokens = [compact[i:i + 2] for i in range(0, 12, 2)]
        else:
            tokens = re.split(r"[,，\s;|/-]+", str(value or "").strip())
        if (len(tokens) != count or any(isinstance(token, bool)
               or not re.fullmatch(r"\d{1,2}", str(token)) for token in tokens)):
            raise ValueError("raw page has invalid ball tokens")
        return [int(token) for token in tokens]

    front = sorted(numbers(reds, 6))
    back = numbers(blue, 1)
    if (len(set(front)) != 6 or not all(1 <= number <= 33 for number in front)
            or not 1 <= back[0] <= 16):
        raise ValueError("raw page has out-of-range or repeated balls")
    return {"issue": issue, "draw_date": day, "front": front, "back": back}


def _ordered_draws(draws: list[dict[str, Any]], source: str, *, require_fresh: bool = True) -> list[dict[str, Any]]:
    if not draws:
        raise ValueError(f"{source} raw history is empty")
    ordered = sorted(draws, key=lambda row: (row["draw_date"], row["issue"]))
    if any(ordered[i]["issue"] >= ordered[i + 1]["issue"]
           or ordered[i]["draw_date"] >= ordered[i + 1]["draw_date"]
           for i in range(len(ordered) - 1)):
        raise ValueError(f"{source} raw history has duplicate/conflicting/nonmonotonic rows")
    if require_fresh:
        newest = date.fromisoformat(ordered[-1]["draw_date"])
        today = datetime.now(_GATE_CHINA_TZ).date()
        expected = _expected_gate_latest_completed_draw_day(today)
        if newest > today or newest < expected:
            raise ValueError(
                f"{source} raw latest draw is stale/future under frozen draw calendar: "
                f"latest={newest.isoformat()} expected>={expected.isoformat()}"
            )
    return ordered


def _successful_raw(record: dict[str, Any], evidence_dir: Path, source: str,
                    content_types: set[str], parser_version: str) -> bytes:
    if (record.get("source") != source or record.get("http_status") != 200
            or record.get("parser_version") != parser_version
            or not isinstance(record.get("content_type"), str)
            or record["content_type"].split(";", 1)[0].strip().lower() not in content_types):
        raise ValueError(f"{source} successful raw response has invalid provenance/media type")
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError(f"{source} successful raw response has no NetClient attempt ledger")
    terminal = attempts[-1]
    if (not isinstance(terminal, dict) or terminal.get("outcome") != "HTTP_RESPONSE"
            or terminal.get("status_code") != 200 or terminal.get("url") != record.get("url")
            or isinstance(terminal.get("attempt"), bool)
            or not isinstance(terminal.get("attempt"), int)
            or not 1 <= terminal["attempt"] <= 3):
        raise ValueError(f"{source} successful raw response has no matching terminal request")
    for attempt in attempts:
        if (not isinstance(attempt, dict) or isinstance(attempt.get("attempt"), bool)
                or not isinstance(attempt.get("attempt"), int)
                or not 1 <= attempt["attempt"] <= terminal["attempt"]
                or not isinstance(attempt.get("url"), str)
                or urlsplit(attempt["url"]).scheme != "https"
                or urlsplit(attempt["url"]).hostname != urlsplit(record["requested_url"]).hostname
                or isinstance(attempt.get("retry_delay"), bool)
                or not isinstance(attempt.get("retry_delay"), (int, float))
                or not math.isfinite(attempt["retry_delay"])
                or not 0 <= attempt["retry_delay"] <= 30):
            raise ValueError(f"{source} NetClient attempt ledger is malformed")
    return (evidence_dir / "raw_responses" / f"{record['sha256']}.bin").read_bytes()


def _parse_national_page(raw: bytes) -> tuple[list[dict[str, Any]], int]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("CWL raw page is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("CWL raw page root is not an object")
    state = payload.get("state")
    if isinstance(state, bool) or str(state).upper() not in {"0", "OK", "PASS", "SUCCESS"}:
        raise ValueError("CWL raw page did not report success")
    rows = payload.get("result")
    if not isinstance(rows, list) or not rows:
        raise ValueError("CWL raw page has no result rows")
    page_num = payload.get("pageNum")
    if page_num is None:
        total = payload.get("total")
        if isinstance(total, bool) or not str(total or "").isdigit():
            raise ValueError("CWL raw page has no valid page count")
        page_num = (int(total) + 99) // 100
    if isinstance(page_num, bool) or not str(page_num).isdigit() or not 1 <= int(page_num) <= 10000:
        raise ValueError("CWL raw page count is invalid")
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CWL raw result row is not an object")
        parsed.append(_parsed_draw(row.get("code"), row.get("date"),
                                   row.get("red"), row.get("blue")))
    if len({row["issue"] for row in parsed}) != len(parsed):
        raise ValueError("CWL raw page repeats an issue")
    return parsed, int(page_num)


def _html_text(raw: bytes) -> tuple[str, str]:
    markup = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            markup = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if markup is None:
        raise ValueError("official HTML raw bytes cannot be decoded")
    without_active = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>",
                            " ", markup)
    text = html.unescape(re.sub(r"(?is)<[^>]+>", " ", without_active))
    return markup, re.sub(r"\s+", " ", text).strip()


def _parse_shanghai_raw(raw: bytes, *, require_fresh: bool = True) -> list[dict[str, Any]]:
    """Independent gate-local table parser; unknown row shapes fail closed."""
    _, text = _html_text(raw)
    anchors = list(re.finditer(
        r"(?<!\d)(20\d{5})\s+(20\d{2}-\d{2}-\d{2})(?:\([^)]*\))?",
        text,
    ))
    if not anchors:
        raise ValueError("Shanghai raw page contains no anchored SSQ draw rows")
    draws: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        end = anchors[index + 1].start() if index + 1 < len(anchors) else min(len(text), anchor.end() + 700)
        tail = text[anchor.end():end]
        compact = re.match(r"\s*(\d{12})\s+(\d{2})(?!\d)", tail)
        if compact:
            draw = _parsed_draw(anchor.group(1), anchor.group(2),
                                compact.group(1), compact.group(2))
        else:
            # The official table may render each ball in a separate cell.
            # Only the seven adjacent tokens immediately after the date may
            # contribute; prize figures later in the row are not accepted.
            tokens = re.findall(r"(?<!\d)\d{1,2}(?!\d)", tail[:260])
            if len(tokens) < 7:
                raise ValueError("Shanghai row has fewer than seven ball tokens")
            draw = _parsed_draw(anchor.group(1), anchor.group(2), tokens[:6], tokens[6])
        draws.append(draw)
    if len(draws) != len(anchors):
        raise ValueError("Shanghai raw rows were only partially parsed")
    return _ordered_draws(draws, "Shanghai", require_fresh=require_fresh)


def _parse_hebei_raw(home_raw: bytes, announce_raw: bytes) -> dict[str, Any]:
    """Independently require issue/balls from home and date/balls from announcement."""
    markup, _ = _html_text(home_raw)
    panels = re.findall(r'<li\b[^>]*class=["\'][^"\']*kj-info-item[^"\']*["\'][^>]*>(.*?)</li>',
                        markup, re.IGNORECASE | re.DOTALL)
    ssq_panels = [panel for panel in panels if "logo_ssq.png" in panel]
    if len(ssq_panels) != 1:
        raise ValueError("Hebei home has no unique SSQ draw panel")
    panel = ssq_panels[0]
    panel_text = html.unescape(re.sub(r"(?is)<[^>]+>", " ", panel))
    issue_match = re.search(r"第\s*(20\d{5})\s*期", panel_text)
    ball_block = re.search(
        r'<div\b[^>]*class=["\'][^"\']*cirle-number[^"\']*["\'][^>]*>(.*?)</div>',
        panel, re.IGNORECASE | re.DOTALL,
    )
    if issue_match is None or ball_block is None:
        raise ValueError("Hebei home issue or numbered-ball block is absent")
    spans = re.findall(r"<span\b([^>]*)>\s*(\d{1,2})\s*</span>",
                       ball_block.group(1), re.IGNORECASE | re.DOTALL)
    if (len(spans) != 7 or any("blue-num" in attrs for attrs, _ in spans[:6])
            or "blue-num" not in spans[-1][0]):
        raise ValueError("Hebei home has no valid six-red/one-blue structure")
    home_front = sorted(int(number) for _, number in spans[:6])
    home_back = int(spans[-1][1])

    _, announcement = _html_text(announce_raw)
    date_match = re.search(r"开奖日期\s*[:：]?\s*(20\d{2}-\d{2}-\d{2})", announcement)
    numbers_marker = re.search(r"开奖号码\s*[:：]?", announcement)
    if date_match is None or numbers_marker is None:
        raise ValueError("Hebei announcement lacks date or draw-number marker")
    tokens = re.findall(r"(?<!\d)\d{1,2}(?!\d)",
                        announcement[numbers_marker.end():numbers_marker.end() + 240])
    if len(tokens) < 7:
        raise ValueError("Hebei announcement has fewer than seven ball tokens")
    announced_front = sorted(int(number) for number in tokens[:6])
    announced_back = int(tokens[6])
    if home_front != announced_front or home_back != announced_back:
        raise ValueError("Hebei home and announcement ball sets conflict")
    return _parsed_draw(issue_match.group(1), date_match.group(1),
                        home_front, home_back)


def _reparse_manifest(manifest: dict[str, Any], evidence_dir: Path,
                      *, baseline: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rebuild source agreement from exported bytes, never the producer's result.

    Parsers, merge, quorum and crosscheck decisions are gate-local. This
    separate process never calls a fetch function or NetClient.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
    from glp.constants import (
        HEBEI_ANNOUNCE_URL, HEBEI_URL, NATIONAL_URL, SHANGHAI_HISTORY_URL,
        SHANGHAI_URL, SSQ_HISTORY_START_ISSUE,
    )
    from glp.sources import PARSER_VERSION
    from glp.storage import Store

    if (manifest.get("parser_version") != PARSER_VERSION
            or manifest.get("game") != "SSQ" or not _utc_recent(manifest.get("fetched_at"))):
        raise ValueError("source manifest parser/game/fetch timestamp is not current")
    Store.validate_raw_evidence(manifest, evidence_dir)
    records = manifest["raw_responses"]
    receipts = {row["source"]: row for row in manifest["source_receipts"]}
    by_source: dict[str, list[dict[str, Any]]] = {name: [] for name in receipts}
    for record in records:
        by_source[record["source"]].append(record)
    for source, receipt in receipts.items():
        if not _utc_recent(receipt.get("fetched_at")):
            raise ValueError(f"{source} receipt lacks a current UTC timestamp")
        if receipt.get("status") == "FAIL" and not str(receipt.get("detail") or ""):
            raise ValueError(f"{source} failed receipt has no failure reason")

    parsed: dict[str, list[dict[str, Any]]] = {}
    national = receipts["official_cwl_L0"]
    if national["status"] == "PASS":
        pages = manifest.get("national_raw_manifest")
        if not isinstance(pages, list):
            raise ValueError("CWL page manifest is missing")
        by_page = {str(record.get("request_params", {}).get("pageNo")): record
                   for record in by_source["official_cwl_L0"]}
        all_draws: list[dict[str, Any]] = []
        for page in sorted(pages, key=lambda row: row["page"]):
            page_number = page["page"]
            record = by_page.get(str(page_number))
            if record is None or record.get("requested_url") != NATIONAL_URL:
                raise ValueError("CWL page is not linked to an official raw response")
            expected_params = {
                "name": "ssq", "issueCount": "", "issueStart": "", "issueEnd": "",
                "dayStart": "", "dayEnd": "", "pageNo": str(page_number),
                "pageSize": "100", "week": "", "systemType": "PC",
            }
            if record.get("request_params") != expected_params:
                raise ValueError("CWL raw page request parameters are not the production contract")
            actual_query = dict(parse_qsl(urlsplit(record["url"]).query,
                                          keep_blank_values=True))
            if actual_query != expected_params:
                raise ValueError("CWL response URL does not match its requested page")
            raw = _successful_raw(record, evidence_dir, "official_cwl_L0",
                                  {"application/json", "text/json"}, PARSER_VERSION)
            if page.get("sha256") != record["sha256"] or page.get("bytes") != len(raw):
                raise ValueError("CWL page receipt differs from preserved bytes")
            page_draws, reported_pages = _parse_national_page(raw)
            if reported_pages != len(pages):
                raise ValueError("CWL page count changed during capture")
            all_draws.extend(page_draws)
        if len({draw["issue"] for draw in all_draws}) != len(all_draws):
            raise ValueError("CWL pages repeat an issue")
        parsed["official_cwl_L0"] = _ordered_draws(all_draws, "CWL")

    shanghai = receipts["official_shanghai_L1"]
    if shanghai["status"] == "PASS":
        source_records = by_source["official_shanghai_L1"]
        shanghai_manifest = manifest.get("shanghai_raw_manifest")
        if isinstance(shanghai_manifest, list) and shanghai_manifest:
            ordered_chunks = sorted(shanghai_manifest, key=lambda row: row["sequence"])
            if [row.get("sequence") for row in ordered_chunks] != list(range(1, len(ordered_chunks) + 1)):
                raise ValueError("Shanghai chunk manifest sequence is incomplete")
            by_range = {
                (
                    str(record.get("request_params", {}).get("start_issue")),
                    str(record.get("request_params", {}).get("end_issue")),
                ): record
                for record in source_records
                if record.get("requested_url") == SHANGHAI_HISTORY_URL
            }
            all_draws: list[dict[str, Any]] = []
            for chunk in ordered_chunks:
                key = (str(chunk.get("start_issue")), str(chunk.get("end_issue")))
                record = by_range.get(key)
                expected_params = {
                    "view": "previous", "limit": "100",
                    "start_issue": key[0], "end_issue": key[1],
                }
                if record is None or record.get("request_params") != expected_params:
                    raise ValueError("Shanghai chunk is not linked to its official HTTPS request")
                actual_query = dict(parse_qsl(urlsplit(record["url"]).query, keep_blank_values=True))
                if actual_query != expected_params:
                    raise ValueError("Shanghai chunk response URL differs from requested range")
                raw = _successful_raw(
                    record, evidence_dir, "official_shanghai_L1",
                    {"text/html", "application/xhtml+xml"}, PARSER_VERSION,
                )
                if chunk.get("sha256") != record["sha256"] or chunk.get("bytes") != len(raw):
                    raise ValueError("Shanghai chunk manifest differs from preserved bytes")
                declared_count = chunk.get("draw_count")
                if declared_count == 0:
                    _, html_text = _html_text(raw)
                    if re.search(r"(?<!\d)20\d{5}\s+20\d{2}-\d{2}-\d{2}", html_text):
                        raise ValueError("Shanghai chunk declared empty but contains draw rows")
                    chunk_draws = []
                else:
                    chunk_draws = _parse_shanghai_raw(raw, require_fresh=False)
                    if len(chunk_draws) != declared_count:
                        raise ValueError("Shanghai chunk draw count differs from manifest")
                    if (chunk.get("first_issue") != chunk_draws[0]["issue"]
                            or chunk.get("last_issue") != chunk_draws[-1]["issue"]):
                        raise ValueError("Shanghai chunk first/last issue differs from raw reparse")
                    if any(not key[0] <= draw["issue"] <= key[1] for draw in chunk_draws):
                        raise ValueError("Shanghai raw row falls outside requested issue range")
                all_draws.extend(chunk_draws)
            if len({draw["issue"] for draw in all_draws}) != len(all_draws):
                raise ValueError("Shanghai full-history chunks repeat an issue")
            shanghai_full = _ordered_draws(all_draws, "Shanghai full history")
            if not shanghai_full or shanghai_full[0]["issue"] != SSQ_HISTORY_START_ISSUE:
                raise ValueError("Shanghai full-history raw set has the wrong frozen start issue")
            by_year: dict[str, list[int]] = {}
            for draw in shanghai_full:
                by_year.setdefault(draw["issue"][:4], []).append(int(draw["issue"][-3:]))
            for year, suffixes in by_year.items():
                first = int(SSQ_HISTORY_START_ISSUE[-3:]) if year == SSQ_HISTORY_START_ISSUE[:4] else 1
                if suffixes != list(range(first, max(suffixes) + 1)):
                    raise ValueError(f"Shanghai full-history raw set has issue gaps in {year}")
            parsed["official_shanghai_L1"] = shanghai_full
        else:
            if len(source_records) != 1 or source_records[0].get("requested_url") != SHANGHAI_URL:
                raise ValueError("Shanghai successful receipt has no unique official raw page")
            raw = _successful_raw(source_records[0], evidence_dir, "official_shanghai_L1",
                                  {"text/html", "application/xhtml+xml"}, PARSER_VERSION)
            parsed["official_shanghai_L1"] = _parse_shanghai_raw(raw)

    hebei = receipts["official_hebei_L2"]
    if hebei["status"] == "PASS":
        source_records = {row["requested_url"]: row for row in by_source["official_hebei_L2"]}
        if set(source_records) != {HEBEI_URL, HEBEI_ANNOUNCE_URL}:
            raise ValueError("Hebei successful receipt lacks its two official pages")
        home = _successful_raw(source_records[HEBEI_URL], evidence_dir, "official_hebei_L2",
                               {"text/html", "application/xhtml+xml"}, PARSER_VERSION)
        announce = _successful_raw(source_records[HEBEI_ANNOUNCE_URL], evidence_dir,
                                   "official_hebei_L2",
                                   {"text/html", "application/xhtml+xml"}, PARSER_VERSION)
        parsed["official_hebei_L2"] = _ordered_draws(
            [_parse_hebei_raw(home, announce)], "Hebei")

    for source, draws in parsed.items():
        receipt = receipts[source]
        if receipt.get("draw_count") != len(draws) or receipt.get("latest_issue") != draws[-1]["issue"]:
            raise ValueError(f"{source} receipt does not match reparsed draw history")
    if len(parsed) < 2:
        raise ValueError("fewer than two official sources could be reparsed")

    crosscheck = 0
    verification = manifest.get("verification")
    if national["status"] == "PASS":
        canonical = parsed["official_cwl_L0"]
        by_issue = {draw["issue"]: draw for draw in canonical}
        validators = 0
        sh_draws = parsed.get("official_shanghai_L1")
        if sh_draws is not None:
            overlap = [draw for draw in sh_draws if draw["issue"] in by_issue]
            if not overlap or any(by_issue[draw["issue"]] != draw for draw in overlap):
                raise ValueError("CWL/Shanghai raw histories have no consistent overlap")
            if canonical[-1] != sh_draws[-1]:
                raise ValueError("CWL/Shanghai latest draw conflicts")
            crosscheck += len(overlap)
            validators += 1
        hb_draws = parsed.get("official_hebei_L2")
        if hb_draws is not None:
            if canonical[-1] != hb_draws[-1]:
                raise ValueError("CWL/Hebei latest draw conflicts")
            crosscheck += 1
            validators += 1
        if (validators < 1 or verification != f"CWL_L0_PLUS_{validators}_PROVINCIAL_VALIDATOR"
                or manifest.get("baseline_lineage") is not None):
            raise ValueError("CWL source-quorum mode or baseline lineage is inconsistent")
        # A prior baseline must also be reconstructed, but only from its own
        # current preserved pages. It is never allowed to contain a second lineage.
        if baseline and manifest.get("baseline_lineage") is not None:
            raise ValueError("nested baseline lineage is not allowed")
    else:
        sh_draws = parsed.get("official_shanghai_L1")
        hb_draws = parsed.get("official_hebei_L2")
        if sh_draws is None or hb_draws is None:
            raise ValueError("CWL failure lacks two current provincial sources")
        if sh_draws[-1] != hb_draws[-1]:
            raise ValueError("Shanghai/Hebei latest draw conflicts")
        if verification == "TRUSTED_BASELINE_PLUS_SHANGHAI_HEBEI_CONSENSUS":
            if baseline:
                raise ValueError("nested provincial fallback lineage is not allowed")
            lineage = manifest.get("baseline_lineage")
            if not isinstance(lineage, dict):
                raise ValueError("provincial fallback lacks prior raw baseline lineage")
            baseline_draws, _ = _reparse_manifest(lineage, evidence_dir, baseline=True)
            if (_canonical_hash(baseline_draws) != manifest.get("baseline_canonical_hash")
                    or len(baseline_draws) != manifest.get("baseline_draw_count")):
                raise ValueError("baseline raw reparse differs from declared lineage")
            by_issue = {draw["issue"]: draw for draw in sh_draws}
            overlap = [draw for draw in baseline_draws if draw["issue"] in by_issue]
            if (not overlap or baseline_draws[-1]["issue"] not in by_issue
                    or any(by_issue[draw["issue"]] != draw for draw in overlap)):
                raise ValueError("baseline/Shanghai raw histories lack consistent overlap")
            canonical = list(baseline_draws)
            seen = {draw["issue"] for draw in canonical}
            last_date = canonical[-1]["draw_date"]
            for draw in sh_draws:
                if draw["issue"] in seen:
                    continue
                if draw["draw_date"] <= last_date:
                    raise ValueError("provincial fallback would regress canonical dates")
                canonical.append(draw)
                seen.add(draw["issue"])
                last_date = draw["draw_date"]
            crosscheck = len(overlap) + 1
        elif verification == "SHANGHAI_FULL_L1_PLUS_HEBEI_CURRENT":
            if baseline or manifest.get("baseline_lineage") is not None:
                raise ValueError("Shanghai full-history mode must not inherit raw baseline lineage")
            count = manifest.get("baseline_draw_count")
            overlap_count = manifest.get("baseline_overlap_count")
            baseline_hash = manifest.get("baseline_canonical_hash")
            if (isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= len(sh_draws)
                    or overlap_count != count
                    or not isinstance(baseline_hash, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", baseline_hash)
                    or _canonical_hash(sh_draws[:count]) != baseline_hash):
                raise ValueError("Shanghai full-history mode does not reverify the declared baseline prefix")
            canonical = list(sh_draws)
            crosscheck = 1
        else:
            raise ValueError("CWL failure lacks an allowed fail-closed verification mode")

    canonical = _ordered_draws(canonical, "canonical")
    if (manifest.get("crosscheck_count") != crosscheck
            or manifest.get("canonical_hash") != _canonical_hash(canonical)
            or manifest.get("canonical_payload_sha256") != _canonical_hash(canonical)
            or manifest.get("draw_count") != len(canonical)
            or manifest.get("latest") != canonical[-1]):
        raise ValueError("raw-derived canonical/crosscheck does not match source manifest")
    return canonical, {"sources": sorted(parsed), "crosscheck_count": crosscheck,
                       "draw_count": len(canonical), "canonical_hash": _canonical_hash(canonical),
                       "verification": verification}


def _verify_gui_update_source(data_dir: Path, observed: dict[str, Any]) -> dict[str, Any]:
    """Reparse the bytes produced by this GUI click, not a separate CLI run."""
    source_path = data_dir / "source_evidence.json"
    canonical_path = data_dir / "canonical_history.json"
    manifest = _read(source_path)
    canonical = _read(canonical_path)
    if not manifest or not canonical:
        raise ValueError("GUI update source manifest/canonical history is missing")
    # Includes the Store's provenance/hash/freshness checks for every raw byte
    # record, then independently reconstructs parsing and source agreement.
    reparsed, reparse_proof = _reparse_manifest(manifest, data_dir)
    digest = _canonical_hash(reparsed)
    if (canonical.get("game") != "SSQ"
            or canonical.get("schema") != 4
            or canonical.get("draws") != reparsed
            or canonical.get("canonical_hash") != digest
            or manifest.get("canonical_hash") != digest
            or observed.get("display_token") != digest):
        raise ValueError("GUI update raw/canonical/displayed ledger token mismatch")
    # Bind the same click's source receipts and data to its exact ledger event.
    # Merely presenting a different valid manifest next to a PASS ledger fails.
    event_id = observed.get("experiment_id")
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        raise ValueError("GUI update has no exact ledger event ID")
    db_path = (data_dir / "ledger.sqlite3").resolve()
    db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        row = db.execute(
            "SELECT kind,status,payload_json FROM experiments WHERE id=?", (event_id,),
        ).fetchone()
    finally:
        db.close()
    if row is None or row[0] != "official_update" or row[1] != "PASS":
        raise ValueError("GUI update ledger event is not an official update PASS")
    payload = json.loads(row[2])
    if (not isinstance(payload, dict)
            or payload.get("canonical_hash") != digest
            or payload.get("source_receipts") != manifest.get("source_receipts")
            or payload.get("draw_count") != len(reparsed)
            or payload.get("latest") != reparsed[-1]
            or payload.get("latest_issue") != reparsed[-1]["issue"]
            or payload.get("crosscheck_status") != "PASS"
            or payload.get("crosscheck_count") != manifest.get("crosscheck_count")
            or payload.get("verification") != manifest.get("verification")):
        raise ValueError("GUI update ledger/source evidence binding mismatch")
    return {
        "manifest_sha256": _hash(source_path),
        "canonical_sha256": _hash(canonical_path),
        "canonical_hash": digest,
        "raw_response_count": len(manifest["raw_responses"]),
        "canonical_reparse": "PASS",
        "reparse": reparse_proof,
    }


def _verify_gui_evidence(physical: dict[str, Any], evidence_dir: Path, exe: Path,
                         acceptance_ok: bool) -> dict[str, Any]:
    if (not acceptance_ok or not exe.is_file()
            or physical.get("schema") != "physical-gui-click-smoke-v2"
            or physical.get("status") != "PASS"
            or physical.get("coordinate_fallback") is not False
            or physical.get("visual_hash_as_proof") is not False
            or physical.get("exe") != exe.name
            or physical.get("exe_sha256") != _hash(exe)
            or physical.get("github_sha") != os.environ.get("GITHUB_SHA")
            or physical.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or not _utc_recent(physical.get("tested_at"))):
        raise ValueError("physical GUI report is not bound to the exact current-run EXE")
    buttons = physical.get("buttons")
    expected = ((101, "predict"), (102, "update"), (103, "repair"), (104, "audit"))
    if not isinstance(buttons, list) or len(buttons) != len(expected):
        raise ValueError("four exact child controls were not exercised")
    from verify_gui_effect import EVENT_KINDS, inspect_effect
    seen_dirs: set[str] = set()
    ledgers: list[dict[str, Any]] = []
    for index, (row, (control_id, operation)) in enumerate(zip(buttons, expected), 1):
        if not isinstance(row, dict):
            raise ValueError("physical GUI button row is malformed")
        before = row.get("before_output_sha256")
        after = row.get("after_output_sha256")
        leaf = row.get("data_dir")
        effect = row.get("backend_effect")
        if (row.get("button_index") != index or row.get("control_id") != control_id
                or row.get("operation") != operation or row.get("status") != "PASS"
                or str(row.get("control_class") or "").upper() != "BUTTON"
                or not isinstance(row.get("control_name"), str) or not row["control_name"]
                or not isinstance(row.get("process_id"), int) or row["process_id"] <= 0
                or any(row.get(flag) is not True for flag in (
                    "control_verified", "physical_click_verified", "output_verified",
                    "backend_effect_verified"))
                or not isinstance(before, str) or not re.fullmatch(r"[0-9a-f]{64}", before)
                or not isinstance(after, str) or not re.fullmatch(r"[0-9a-f]{64}", after)
                or before == after or not isinstance(leaf, str)
                or not re.fullmatch(r"physical-gui-run-[0-9a-f]{32}", leaf)
                or leaf in seen_dirs or not isinstance(effect, dict)):
            raise ValueError(f"physical GUI row {index} lacks exact control/output proof")
        seen_dirs.add(leaf)
        data_dir = evidence_dir / leaf
        before_path = data_dir / "gui_before.txt"
        after_path = data_dir / "gui_after.txt"
        if (row.get("before_output_artifact") != f"{leaf}/gui_before.txt"
                or row.get("after_output_artifact") != f"{leaf}/gui_after.txt"
                or not before_path.is_file() or not after_path.is_file()
                or row.get("before_output_artifact_sha256") != _hash(before_path)
                or row.get("after_output_artifact_sha256") != _hash(after_path)
                or before != _hash(before_path) or after != _hash(after_path)):
            raise ValueError(f"physical GUI row {index} lacks exact raw output artifacts")
        after_text = after_path.read_text(encoding="utf-8")
        markers = row.get("output_markers")
        if (not isinstance(markers, list) or len(markers) != 2
                or not all(isinstance(marker, str) and marker and marker in after_text
                           for marker in markers)
                or not isinstance(row.get("after_status"), str)
                or "FAIL" in row["after_status"].upper()):
            raise ValueError(f"physical GUI row {index} has no inspectable operation output")
        experiment_id = effect.get("experiment_id")
        if not isinstance(experiment_id, int) or experiment_id <= 0:
            raise ValueError(f"physical GUI row {index} has no exact ledger event ID")
        observed = inspect_effect(
            data_dir, operation, 0, experiment_id=experiment_id,
            parent_pid=int(row["process_id"]),
        )
        fields = ("status", "operation", "after_id", "experiment_id", "kind",
                  "event_status", "payload_sha256", "display_token")
        if (observed.get("status") != "PASS"
                or observed.get("kind") not in EVENT_KINDS[operation]
                or not isinstance(observed.get("display_token"), str)
                or not observed["display_token"]
                or row.get("displayed_backend_token") != observed["display_token"]
                or observed["display_token"] not in after_text
                or not all(effect.get(field) == observed.get(field) for field in fields)):
            raise ValueError(f"physical GUI row {index} is not backed by a matching ledger event")
        if operation == "update":
            source_proof = _verify_gui_update_source(data_dir, observed)
        ledger_path = data_dir / "ledger.sqlite3"
        ledger_proof = {"operation": operation, "experiment_id": observed["experiment_id"],
                        "ledger_sha256": _hash(ledger_path)}
        if operation == "update":
            ledger_proof["source_evidence"] = source_proof
        ledgers.append(ledger_proof)
    return {"ledgers": ledgers}


def _verify_gui_failure_evidence(
    report: dict[str, Any], evidence_dir: Path, exe: Path, acceptance_ok: bool,
    expected_operation: str = "update",
) -> dict[str, Any]:
    if expected_operation not in {"update", "repair"}:
        raise ValueError("unsupported physical GUI failure operation")
    control_id = {"update": 102, "repair": 103}[expected_operation]
    operation_label = {"update": "\u4e00\u952e\u66f4\u65b0", "repair": "\u4e00\u952e\u4fee\u590d"}[expected_operation]
    updater_exe = exe.parent / "Geometry_Lotto_Pro_SSQ_Updater.exe"
    if (not acceptance_ok or not exe.is_file() or not updater_exe.is_file()
            or report.get("schema") != "physical-gui-failure-smoke-v2"
            or report.get("operation") != expected_operation
            or type(report.get("control_id")) is not int or report["control_id"] != control_id
            or type(report.get("process_id")) is not int or report["process_id"] <= 0
            or any(type(report.get(key)) is not int or report[key] < 0 for key in ("click_x", "click_y"))
            or report.get("status") != "PASS"
            or report.get("scenario") != "controlled Windows outbound block"
            or report.get("exe") != exe.name
            or report.get("exe_sha256") != _hash(exe)
            or report.get("updater_exe") != updater_exe.name
            or report.get("updater_sha256") != _hash(updater_exe)
            or report.get("github_sha") != os.environ.get("GITHUB_SHA")
            or report.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or report.get("firewall_rules_created") is not True
            or report.get("ui_fail_closed") is not True
            or not isinstance(report.get("ui_status"), str)
            or report["ui_status"] != operation_label + "\uff1aFAIL"
            or not _utc_recent(report.get("tested_at"))):
        raise ValueError("physical GUI failure report is not bound to the exact current-run EXEs")

    leaf = report.get("data_dir")
    source_leaf = report.get("source_success_data_dir")
    if (not isinstance(leaf, str)
            or not re.fullmatch(r"physical-gui-failure-[0-9a-f]{32}", leaf)
            or not isinstance(source_leaf, str)
            or not re.fullmatch(r"physical-gui-run-[0-9a-f]{32}", source_leaf)):
        raise ValueError("physical GUI failure data lineage is malformed")

    run_dir = evidence_dir / leaf
    source_dir = evidence_dir / source_leaf
    updater_hash = _hash(updater_exe)
    expected_materialized = (
        run_dir / "updater" / updater_hash / updater_exe.name
    ).resolve()
    materialized_value = report.get("materialized_updater")
    materialized_hash = report.get("materialized_updater_sha256")
    firewall_programs = report.get("firewall_programs")
    try:
        materialized_path = Path(str(materialized_value)).resolve()
        firewall_paths = {
            Path(str(value)).resolve()
            for value in firewall_programs
        } if isinstance(firewall_programs, list) else set()
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise ValueError("physical GUI failure firewall path evidence is malformed") from exc
    required_firewall_paths = {
        exe.resolve(), updater_exe.resolve(), expected_materialized,
    }
    if (materialized_path != expected_materialized
            or not expected_materialized.is_file()
            or materialized_hash != updater_hash
            or _hash(expected_materialized) != updater_hash
            or not required_firewall_paths.issubset(firewall_paths)):
        raise ValueError(
            "physical GUI failure did not bind firewall rules to the exact materialized updater"
        )

    history = run_dir / "canonical_history.json"
    source_evidence = run_dir / "source_evidence.json"
    source_history = source_dir / "canonical_history.json"
    source_source_evidence = source_dir / "source_evidence.json"
    ledger = run_dir / "ledger.sqlite3"
    ui_output = run_dir / "gui_failure_output.txt"
    for required in (history, source_evidence, source_history, source_source_evidence, ledger, ui_output):
        if not required.is_file():
            raise ValueError(f"physical GUI failure evidence file missing: {required.name}")

    history_hash = _hash(history)
    evidence_hash = _hash(source_evidence)
    ui_text = ui_output.read_text(encoding="utf-8-sig")
    if (report.get("ui_output_sha256") != _hash(ui_output)
            or operation_label + " FAIL" not in ui_text or "Fail-Closed" not in ui_text):
        raise ValueError("physical GUI failure text is missing, tampered or for the wrong operation")
    if report.get("original_canonical_sha256") != _hash(source_history):
        raise ValueError("physical GUI failure original dataset hash mismatch")
    if expected_operation == "repair":
        if (report.get("corruption_injected") is not True
                or history.read_bytes() != b"SSQ_CONTROLLED_CORRUPT_HISTORY_V1\n"
                or history_hash == _hash(source_history)):
            raise ValueError("repair failure must exercise the specified corrupt dataset, not a healthy no-op")
    elif report.get("corruption_injected") is not False or _hash(source_history) != history_hash:
        raise ValueError("update failure must retain its accepted dataset")
    if (report.get("before_canonical_sha256") != history_hash
            or report.get("after_canonical_sha256") != history_hash
            or report.get("before_evidence_sha256") != evidence_hash
            or report.get("after_evidence_sha256") != evidence_hash
            or report.get("canonical_unchanged") is not True
            or report.get("evidence_unchanged") is not True
            or _hash(source_source_evidence) != evidence_hash):
        raise ValueError("controlled GUI network failure mutated the last accepted canonical/source evidence")

    manifests = sorted((run_dir / "failed").glob("*/failure_evidence.json"))
    declared_count = report.get("failure_manifest_count")
    if (type(declared_count) is not int or declared_count < 1
            or len(manifests) != declared_count):
        raise ValueError("physical GUI failure evidence manifest count is invalid")
    manifest_proofs: list[dict[str, Any]] = []
    for manifest_path in manifests:
        failure = _read(manifest_path)
        if (not isinstance(failure, dict)
                or failure.get("status") != "FAIL"
                or failure.get("crosscheck_status") != "FAIL"
                or failure.get("raw_response_status") not in {"FAIL", "UNAVAILABLE"}):
            raise ValueError("physical GUI failure manifest attempted to claim success")
        manifest_proofs.append({
            "relative_path": str(manifest_path.relative_to(evidence_dir)).replace("\\", "/"),
            "sha256": _hash(manifest_path),
            "raw_response_status": failure.get("raw_response_status"),
        })

    db = sqlite3.connect(str(ledger))
    repair_proof: dict[str, Any] = {}
    try:
        row = db.execute(
            "SELECT COUNT(*) FROM experiments WHERE kind='official_update' AND status='PASS'"
        ).fetchone()
        if expected_operation == "repair":
            repair_rows = db.execute("SELECT status,payload_json FROM experiments WHERE kind='repair'").fetchall()
            failures = [json.loads(payload) for status, payload in repair_rows if status == "FAIL"]
            if (not failures or any(status != "FAIL" for status, _ in repair_rows)
                    or type(report.get("repair_fail_count")) is not int
                    or report["repair_fail_count"] != len(failures)
                    or type(report.get("repair_pass_count")) is not int or report["repair_pass_count"] != 0):
                raise ValueError("controlled repair failure lacks its own FAIL ledger or emitted PASS")
            for payload in failures:
                if not isinstance(payload, dict):
                    raise ValueError("repair ledger payload must be an object")
                attempts = payload.get("repair_attempts")
                if (payload.get("status") != "FAIL" or payload.get("repaired") is not False
                        or not isinstance(payload.get("before"), dict) or payload["before"].get("ok") is not False
                        or not isinstance(attempts, list) or not attempts
                        or any(not isinstance(a, dict) or a.get("status") != "FAIL" for a in attempts)):
                    raise ValueError("repair ledger does not prove corrupt-data rebuild failure")
            repair_proof = {"repair_fail_count": len(failures), "repair_pass_count": 0, "ledger_sha256": _hash(ledger)}
    finally:
        db.close()
    pass_count = int(row[0]) if row else -1
    if (pass_count != 0 or type(report.get("official_update_pass_count")) is not int
            or report["official_update_pass_count"] != 0):
        raise ValueError("controlled GUI network failure produced an official_update PASS")

    return {
        "report_schema": report.get("schema"),
        "operation": expected_operation,
        "control_id": control_id,
        "ui_output_sha256": _hash(ui_output),
        **repair_proof,
        "exe_sha256": report.get("exe_sha256"),
        "updater_sha256": report.get("updater_sha256"),
        "materialized_updater": str(expected_materialized),
        "materialized_updater_sha256": updater_hash,
        "firewall_programs": sorted(str(path) for path in required_firewall_paths),
        "data_dir": leaf,
        "source_success_data_dir": source_leaf,
        "canonical_sha256": history_hash,
        "source_evidence_sha256": evidence_hash,
        "failure_manifests": manifest_proofs,
        "official_update_pass_count": pass_count,
        "ui_status": report.get("ui_status"),
    }


def _corrupt_repair_is_fault_injection(evidence_dir: Path, exe_hash: str) -> bool:
    report = _read(evidence_dir / "corrupt-repair.json")
    if not isinstance(report, dict):
        return False
    result = report.get("result")
    return bool(
        report.get("status") == "PASS" and report.get("scope") == "corrupt-repair"
        and report.get("game") == "SSQ" and report.get("platform") == "win32"
        and report.get("github_sha") == os.environ.get("GITHUB_SHA")
        and report.get("github_run_id") == os.environ.get("GITHUB_RUN_ID")
        and report.get("exe_sha256") == exe_hash
        and report.get("final_release_gate") == "PENDING"
        and report.get("test_data_classification") == "TEST_ONLY_SYNTHETIC"
        and report.get("real_network_status") == "PENDING"
        and report.get("real_network_tested") is False
        and report.get("production_repair_status") == "PENDING"
        and isinstance(result, dict) and result.get("status") == "PASS"
        and result.get("validation_scope") == "FAULT_INJECTION_ONLY"
        and result.get("test_data_classification") == "TEST_ONLY_SYNTHETIC"
        and result.get("real_network_status") == "PENDING"
        and result.get("real_network_tested") is False
        and result.get("production_repair_status") == "PENDING"
        and result.get("synthetic_artifacts_exported") is False
        and isinstance(result.get("checks"), dict) and result["checks"]
        and all(value is True for value in result["checks"].values())
    )


def _verify_live_evidence(evidence_dir: Path, exe_hash: str) -> dict[str, Any]:
    update_path = evidence_dir / "update.json"
    update = _read(update_path)
    if update is None or not update:
        raise ValueError("exact-EXE update result is missing or malformed")
    result = update.get("result")
    if (update.get("status") != "PASS" or update.get("game") != "SSQ"
            or update.get("scope") != "update" or update.get("platform") != "win32"
            or update.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or update.get("github_sha") != os.environ.get("GITHUB_SHA")
            or update.get("exe_sha256") != exe_hash or not isinstance(result, dict)
            or result.get("crosscheck_status") != "PASS"
            or not isinstance(result.get("persisted_integrity"), dict)
            or result["persisted_integrity"].get("ok") is not True):
        raise ValueError("exact-EXE live update or strict persistence integrity did not PASS")
    preservation = result.get("preserved_live_evidence")
    manifest_path = evidence_dir / "update-source-evidence.json"
    canonical_path = evidence_dir / "update-canonical-history.json"
    if (not isinstance(preservation, dict) or preservation.get("status") != "PASS"
            or preservation.get("manifest") != manifest_path.name
            or preservation.get("manifest_sha256") != _hash(manifest_path)):
        raise ValueError("live response preservation proof is missing or hash-mismatched")
    if (preservation.get("canonical") != canonical_path.name
            or preservation.get("canonical_sha256") != _hash(canonical_path)):
        raise ValueError("canonical history preservation proof is missing or hash-mismatched")
    manifest = _read(manifest_path)
    if (manifest is None or manifest.get("schema") != "official-source-evidence-v8.5"
            or manifest.get("raw_response_status") != "PASS"
            or manifest.get("crosscheck_status") != "PASS"
            or manifest.get("canonical_hash") != result.get("canonical_hash")
            or manifest.get("source_receipts") != result.get("source_receipts")):
        raise ValueError("live source manifest is not bound to the exact-EXE result")
    canonical = _read(canonical_path)
    draws = canonical.get("draws") if canonical is not None else None
    if (not isinstance(draws, list) or not draws
            or canonical.get("game") != "SSQ"
            or canonical.get("canonical_hash") != result.get("canonical_hash")
            or len(draws) != result.get("draw_count")
            or draws[-1] != manifest.get("latest")
            or draws[-1].get("issue") != result.get("latest_issue")
            or hashlib.sha256(json.dumps(draws, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()
               != canonical.get("canonical_hash")):
        raise ValueError("preserved canonical history is not bound to live evidence")
    freshness = manifest.get("freshness")
    china_today = datetime.now(_GATE_CHINA_TZ).date()
    expected_latest = _expected_gate_latest_completed_draw_day(china_today)
    latest_day = date.fromisoformat(str(draws[-1].get("draw_date"))) if isinstance(draws, list) and draws else None
    expected_policy_sources = {
        "rule": _GATE_FRESHNESS_POLICY_SOURCES["rule"],
        "closure": _GATE_FRESHNESS_POLICY_SOURCES[str(china_today.year)],
    }
    if (not isinstance(freshness, dict)
            or freshness.get("schema") != "ssq-freshness-calendar-v1"
            or freshness.get("latest_date") != draws[-1].get("draw_date")
            or freshness.get("china_local_date") != china_today.isoformat()
            or freshness.get("expected_latest_completed_draw_date") != expected_latest.isoformat()
            or freshness.get("policy_year") != china_today.year
            or freshness.get("policy_sources") != expected_policy_sources
            or latest_day is None or latest_day > china_today or latest_day < expected_latest):
        raise ValueError("live canonical freshness is not independently justified by frozen official calendar")

    records = manifest.get("raw_responses")
    if (not isinstance(records, list) or not records
            or preservation.get("raw_response_count") != len(records)):
        raise ValueError("raw response set is incomplete")
    # Re-run the Store's full receipt/page/quorum validator against the copied
    # acceptance artifacts, not the temporary data directory the EXE used.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "SSQ"))
    from glp.storage import Store
    verified_count = Store.validate_raw_evidence(manifest, evidence_dir)
    if verified_count != len(records):
        raise ValueError("validated raw response count differs from manifest")
    lineage = manifest.get("baseline_lineage")
    baseline_records = lineage.get("raw_responses", []) if isinstance(lineage, dict) else []
    if preservation.get("baseline_raw_response_count") != len(baseline_records):
        raise ValueError("preserved fallback lineage artifact count differs from manifest")
    Store._check_baseline_prefix(manifest, draws)
    receipts = manifest.get("source_receipts")
    if (not isinstance(receipts, list) or len(receipts) != 3
            or sum(isinstance(item, dict) and item.get("status") == "PASS" for item in receipts) < 2):
        raise ValueError("official source quorum is unproven")
    receipt_status = {item["source"]: item["status"] for item in receipts}
    if (len(receipt_status) != 3
            or any(status not in {"PASS", "FAIL"} for status in receipt_status.values())):
        raise ValueError("official source receipt state is incomplete")
    official_hosts = {
        "official_cwl_L0": "www.cwl.gov.cn",
        "official_shanghai_L1": "www.swlc.net.cn",
        "official_hebei_L2": "www.yzfcw.com",
    }
    from urllib.parse import urlsplit
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("raw response record is malformed")
        digest = record.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("raw response hash is invalid")
        url = urlsplit(str(record.get("url", "")))
        source = record.get("source")
        if (source not in official_hosts
                or url.scheme != "https" or url.hostname != official_hosts[source]
                or not _raw_status_allowed(record.get("http_status"), receipt_status[source])
                or not _utc_recent(record.get("fetched_at"))
                or record.get("artifact") != f"raw_responses/{digest}.bin"):
            raise ValueError("raw response source, freshness or provenance is invalid")
        artifact = evidence_dir / "raw_responses" / f"{digest}.bin"
        if (not artifact.is_file() or artifact.stat().st_size != record.get("bytes")
                or _hash(artifact) != digest):
            raise ValueError("raw response bytes are missing or hash-mismatched")
    reparsed, reparse_proof = _reparse_manifest(manifest, evidence_dir)
    if draws != reparsed:
        raise ValueError("preserved canonical rows differ from independent raw reparse")
    return {
        "result": str(update_path), "result_sha256": _hash(update_path),
        "manifest": str(manifest_path), "manifest_sha256": _hash(manifest_path),
        "canonical": str(canonical_path), "canonical_sha256": _hash(canonical_path),
        "raw_response_count": len(records),
        "canonical_hash": result["canonical_hash"],
        "canonical_reparse": "PASS",
        "freshness": {
            "status": "PASS",
            "china_local_date": china_today.isoformat(),
            "expected_latest_completed_draw_date": expected_latest.isoformat(),
            "latest_date": latest_day.isoformat(),
            "policy_sources": expected_policy_sources,
        },
        "reparse": reparse_proof,
        # This proof was reconstructed from the exact current-run raw bytes,
        # independently of the producer parser, including current Shanghai and
        # Hebei live captures and source/quorum/hash binding.
        "official_html_parser_contract": "PASS",
    }


def _trusted_ssq_release_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None:
        return False
    if parsed.hostname != "github.com" or parsed.port not in (None, 443):
        return False
    prefix = f"/{EXPECTED_INDEPENDENT_REPOSITORY}/releases/download/"
    return parsed.path.startswith(prefix)


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _software_version_precedence(version: Any) -> tuple[Any, ...]:
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.-]+))?(?:\+([A-Za-z0-9.-]+))?",
        str(version).strip(),
    )
    if not match:
        raise ValueError(f"invalid software version: {version!r}")
    core = tuple(int(match.group(i)) for i in (1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        return (*core, 1, ())
    identifiers: list[tuple[int, Any]] = []
    for token in prerelease.split("."):
        if not token:
            raise ValueError("empty prerelease identifier")
        identifiers.append((0, int(token)) if token.isdigit() else (1, token))
    return (*core, 0, tuple(identifiers))


def _verify_updater_release_network(evidence: Path, updater_hash: str, main_exe_hash: str) -> dict[str, Any]:
    report = _require_current_report(
        evidence, "updater-software-release-network.json", "ssq-independent-updater-v2"
    )
    if (report.get("mode") != "software-update"
            or report.get("updater_exe_sha256") != updater_hash
            or report.get("parent_pid_match") is not True):
        raise ValueError("software-update report is not bound to the exact updater process")
    service = report.get("service_result")
    if (not isinstance(service, dict)
            or service.get("schema") != "ssq-software-update-result-v1"
            or service.get("status") != "PASS"
            or report.get("service_result_sha256") != _sha256_json(service)):
        raise ValueError("software-update service result is malformed or hash-unbound")
    manifest = service.get("manifest")
    manifest_receipt = service.get("manifest_receipt")
    artifact_receipt = service.get("artifact_receipt")
    replacement = service.get("replacement")
    wait = service.get("wait_for_main")
    if not all(isinstance(x, dict) for x in (manifest, manifest_receipt, artifact_receipt, replacement, wait)):
        raise ValueError("software-update evidence sections are incomplete")
    manifest_url = manifest_receipt.get("requested_url")
    artifact_url = artifact_receipt.get("requested_url")
    digest = manifest.get("artifact_sha256")
    size = manifest.get("artifact_bytes")
    version = manifest.get("version")
    if (manifest.get("schema") != "ssq-software-update-manifest-v1"
            or manifest.get("app") != "Geometry Lotto Pro SSQ"
            or not isinstance(version, str) or not version
            or not _trusted_ssq_release_url(manifest_url)
            or not _trusted_ssq_release_url(artifact_url)
            or manifest.get("artifact_url") != artifact_url
            or not isinstance(digest, str) or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
            or digest != main_exe_hash
            or type(size) is not int or size <= 0):
        raise ValueError("software-update manifest is not a trusted independent-repo release")
    for label, receipt in (("manifest", manifest_receipt), ("artifact", artifact_receipt)):
        final_url = receipt.get("final_url")
        parsed_final = urlsplit(final_url) if isinstance(final_url, str) else None
        if (receipt.get("status") != "PASS"
                or receipt.get("http_status") != 200
                or type(receipt.get("bytes")) is not int or receipt["bytes"] <= 0
                or not isinstance(receipt.get("sha256"), str) or len(receipt["sha256"]) != 64
                or parsed_final is None or parsed_final.scheme != "https"
                or parsed_final.hostname not in {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}):
            raise ValueError(f"{label} release receipt is incomplete or untrusted")
    if (service.get("manifest_raw_sha256") != manifest_receipt.get("sha256")
            or artifact_receipt.get("sha256") != digest
            or artifact_receipt.get("bytes") != size):
        raise ValueError("software-update release receipt hash/size binding mismatch")
    post = replacement.get("post_replace_validation")
    wait_elapsed = wait.get("elapsed")
    wait_elapsed_ok = (
        isinstance(wait_elapsed, (int, float))
        and not isinstance(wait_elapsed, bool)
        and wait_elapsed > 0
    )
    if (replacement.get("status") != "PASS"
            or replacement.get("expected_sha256") != digest
            or replacement.get("staged_sha256") != digest
            or replacement.get("installed_sha256") != digest
            or replacement.get("previous_preserved") is not True
            or not isinstance(post, dict)
            or post.get("status") != "PASS"
            or post.get("expected_version") != version
            or post.get("reported_version") != version
            or post.get("target_sha256") != digest
            or wait.get("status") != "PASS"
            or wait.get("waited") is not True
            or type(wait.get("pid")) is not int
            or wait.get("pid") <= 0
            or not wait_elapsed_ok):
        raise ValueError("software-update installed artifact/self-test/wait evidence is incomplete")

    summary = _require_current_report(
        evidence, "UPDATER_REAL_RELEASE_ACCEPTANCE.json",
        "ssq-updater-real-release-acceptance-v1",
    )
    wait_target = summary.get("wait_target")
    base_manifest_receipt = summary.get("base_manifest_receipt")
    base_artifact_receipt = summary.get("base_artifact_receipt")
    summary_wait = summary.get("wait_for_main")
    base_version = summary.get("base_version")
    base_manifest_url = summary.get("base_manifest_url")
    base_artifact_url = (
        base_artifact_receipt.get("requested_url")
        if isinstance(base_artifact_receipt, dict) else None
    )
    try:
        version_forward = (
            _software_version_precedence(version)
            > _software_version_precedence(base_version)
        )
    except ValueError as exc:
        raise ValueError(f"real-release version evidence is invalid: {exc}") from exc
    if (summary.get("repository") != EXPECTED_INDEPENDENT_REPOSITORY
            or summary.get("updater_exe_sha256") != updater_hash
            or summary.get("candidate_exe_sha256") != main_exe_hash
            or summary.get("installed_sha256") != main_exe_hash
            or summary.get("candidate_version") != version
            or summary.get("exact_updater_report") != "updater-software-release-network.json"
            or summary.get("exact_updater_report_sha256") != _hash(
                evidence / "updater-software-release-network.json"
            )
            or not isinstance(wait_target, dict)
            or wait_target.get("kind") != "exact_base_main_exe"
            or type(wait_target.get("pid")) is not int
            or wait_target.get("pid") != wait.get("pid")
            or wait_target.get("pid") <= 0
            or wait_target.get("sha256") != summary.get("base_artifact_sha256")
            or wait_target.get("version") != base_version
            or service.get("from_version") != base_version
            or service.get("to_version") != version
            or not version_forward
            or not _trusted_ssq_release_url(base_manifest_url)
            or not _trusted_ssq_release_url(base_artifact_url)
            or not isinstance(base_manifest_receipt, dict)
            or base_manifest_receipt.get("requested_url") != base_manifest_url
            or base_manifest_receipt.get("status") != "PASS"
            or base_manifest_receipt.get("http_status") != 200
            or type(base_manifest_receipt.get("bytes")) is not int
            or base_manifest_receipt.get("bytes") <= 0
            or base_manifest_receipt.get("sha256") != summary.get("base_manifest_raw_sha256")
            or not isinstance(base_artifact_receipt, dict)
            or base_artifact_receipt.get("status") != "PASS"
            or base_artifact_receipt.get("http_status") != 200
            or base_artifact_receipt.get("sha256") != wait_target.get("sha256")
            or base_artifact_receipt.get("sha256") != summary.get("base_artifact_sha256")
            or base_artifact_receipt.get("bytes") != summary.get("base_artifact_bytes")
            or summary_wait != wait):
        raise ValueError("real-release summary is not bound to trusted prior release and exact main handoff")
    for label, receipt in (
        ("base_manifest", base_manifest_receipt),
        ("base_artifact", base_artifact_receipt),
    ):
        final_url = receipt.get("final_url")
        parsed_final = urlsplit(final_url) if isinstance(final_url, str) else None
        if (parsed_final is None
                or parsed_final.scheme != "https"
                or parsed_final.hostname not in {
                    "github.com", "objects.githubusercontent.com",
                    "release-assets.githubusercontent.com",
                }):
            raise ValueError(f"{label} final URL is not a trusted HTTPS release target")
    return {
        "report": str(evidence / "updater-software-release-network.json"),
        "report_sha256": _hash(evidence / "updater-software-release-network.json"),
        "manifest_url": manifest_url,
        "artifact_url": artifact_url,
        "version": version,
        "artifact_sha256": digest,
        "artifact_bytes": size,
        "manifest_raw_sha256": service.get("manifest_raw_sha256"),
        "installed_sha256": replacement.get("installed_sha256"),
        "post_replace_self_test": "PASS",
        "waited_for_main": True,
        "wait_pid": wait.get("pid"),
        "wait_elapsed": wait_elapsed,
        "wait_target_sha256": wait_target.get("sha256"),
        "wait_target_version": wait_target.get("version"),
        "base_manifest_url": base_manifest_url,
        "base_artifact_url": base_artifact_url,
        "base_version": base_version,
        "version_forward": True,
        "summary_report": str(evidence / "UPDATER_REAL_RELEASE_ACCEPTANCE.json"),
        "summary_sha256": _hash(evidence / "UPDATER_REAL_RELEASE_ACCEPTANCE.json"),
    }

def _verify_checkout_identity(evidence: Path) -> dict[str, Any]:
    report = _require_current_report(
        evidence, "CHECKOUT_IDENTITY_GATE.json", "ssq-checkout-identity-v1"
    )
    event = report.get("event")
    actual = report.get("actual_checkout_sha")
    expected_head = report.get("event_head_sha")
    parents = report.get("parent_shas")
    sha_re = re.compile(r"[0-9a-f]{40}")
    if not isinstance(actual, str) or sha_re.fullmatch(actual) is None:
        raise ValueError("checkout identity has no valid actual SHA")
    if not isinstance(parents, list) or any(
        not isinstance(value, str) or sha_re.fullmatch(value) is None for value in parents
    ):
        raise ValueError("checkout identity parent list is malformed")
    if event == "pull_request":
        if (not isinstance(expected_head, str)
                or sha_re.fullmatch(expected_head) is None
                or not (actual == expected_head or expected_head in parents)):
            raise ValueError("pull-request checkout does not contain the current event HEAD")
    elif event in {"push", "workflow_dispatch"}:
        if actual != os.environ.get("GITHUB_SHA"):
            raise ValueError("push/dispatch checkout does not equal GITHUB_SHA")
    else:
        raise ValueError(f"unsupported checkout identity event: {event}")
    return {
        "report": str(evidence / "CHECKOUT_IDENTITY_GATE.json"),
        "report_sha256": _hash(evidence / "CHECKOUT_IDENTITY_GATE.json"),
        "event": event,
        "actual_checkout_sha": actual,
        "event_head_sha": expected_head,
        "parent_shas": parents,
    }

def _verify_standard_user_evidence(
    evidence: Path, exe: Path, acceptance_ok: bool,
) -> dict[str, Any]:
    report_path = evidence / "STANDARD_USER_ACCEPTANCE.json"
    report = _read(report_path)
    exe_hash = _hash(exe) if exe.is_file() else None
    if (not acceptance_ok or not exe_hash or not isinstance(report, dict)
            or report.get("schema") != "ssq-standard-user-acceptance-v1"
            or report.get("status") != "PASS"
            or report.get("github_sha") != os.environ.get("GITHUB_SHA")
            or report.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or report.get("exe") != exe.name
            or report.get("exe_sha256") != exe_hash
            or report.get("administrators_member") is not False
            or report.get("medium_integrity") is not True
            or report.get("self_status") != "PASS"
            or report.get("gui_default_launch") != "PASS"
            or report.get("localappdata_ledger_created") is not True
            or not _utc_recent(report.get("tested_at"))):
        raise ValueError("standard-user report is not a current-run/hash-bound PASS")

    username = report.get("disposable_user")
    sid = report.get("user_sid")
    if (not isinstance(username, str) or not re.fullmatch(r"glpssq[0-9a-f]{8}", username)
            or not isinstance(sid, str) or not re.fullmatch(r"S-1-5-21(?:-\d+){4}", sid)):
        raise ValueError("standard-user identity is malformed")

    filenames = {
        "self": (report.get("self_result"), report.get("self_result_sha256")),
        "whoami": (report.get("whoami_evidence"), report.get("whoami_evidence_sha256")),
        "groups": (report.get("groups_evidence"), report.get("groups_evidence_sha256")),
    }
    resolved: dict[str, Path] = {}
    for label, (filename, expected_hash) in filenames.items():
        if (not isinstance(filename, str)
                or filename != Path(filename).name
                or not isinstance(expected_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)):
            raise ValueError(f"standard-user {label} evidence path/hash is malformed")
        evidence_path = evidence / filename
        if not evidence_path.is_file() or _hash(evidence_path) != expected_hash:
            raise ValueError(f"standard-user {label} evidence bytes do not match report")
        resolved[label] = evidence_path

    self_report = _read(resolved["self"])
    if (not isinstance(self_report, dict)
            or self_report.get("status") != "PASS"
            or self_report.get("scope") != "self"
            or self_report.get("platform") != "win32"
            or self_report.get("game") != "SSQ"
            or self_report.get("github_sha") != os.environ.get("GITHUB_SHA")
            or self_report.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or self_report.get("exe_sha256") != exe_hash
            or self_report.get("final_release_gate") != "PENDING"):
        raise ValueError("standard-user exact-EXE self evidence is not current/hash bound")

    whoami = resolved["whoami"].read_text(encoding="utf-8-sig", errors="strict").strip().lower()
    expected_identity = f"{str(os.environ.get('COMPUTERNAME') or '').lower()}\\{username.lower()}"
    if not expected_identity.strip("\\") or whoami != expected_identity:
        raise ValueError("standard-user whoami evidence does not match disposable identity")
    if str(report.get("whoami") or "").strip().lower() != whoami:
        raise ValueError("standard-user whoami report contradicts raw evidence")

    groups = resolved["groups"].read_text(encoding="utf-8-sig", errors="strict")
    if "S-1-5-32-544" in groups:
        raise ValueError("standard-user token contains local Administrators SID")
    if "S-1-16-8192" not in groups or "S-1-16-12288" in groups:
        raise ValueError("standard-user raw token is not Medium integrity")

    appdata = str(report.get("default_appdata_root") or "").replace("\\", "/").lower()
    expected_fragment = f"/users/{username.lower()}/appdata/local/geometrylottopro/ssq"
    if expected_fragment not in appdata:
        raise ValueError("standard-user default AppData path is not user-local")

    return {
        "status": "PASS",
        "report": str(report_path),
        "report_sha256": _hash(report_path),
        "exe_sha256": exe_hash,
        "user_sid": sid,
        "whoami": whoami,
        "self_result_sha256": _hash(resolved["self"]),
        "whoami_sha256": _hash(resolved["whoami"]),
        "groups_sha256": _hash(resolved["groups"]),
        "medium_integrity": True,
        "administrators_member": False,
        "gui_default_launch": "PASS",
        "default_appdata_root": report.get("default_appdata_root"),
        "localappdata_ledger_created": True,
    }


NO_SHELL_ENTRY_OPERATIONS = ("predict", "update", "repair", "audit")
NO_SHELL_PREREQUISITE_GATES = (
    "integration_test",
    "real_network",
    "business_validation",
    "counterexample_validation",
    "reversal_validation",
    "physical_gui_click",
    "physical_gui_failure",
    "physical_gui_repair_failure",
    "updater_process",
    "updater_exact_exe",
    "updater_atomic_rollback",
    "updater_same_hash",
)


def _derive_no_shell_gate(
    gates: dict[str, str], proofs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Prove the declared four-entry desktop product is not a UI/static shell.

    This gate intentionally does *not* claim full business completion.  It only
    binds the currently declared entry inventory to current-run physical GUI,
    backend ledger, updater, network and scientific evidence.
    """
    missing = {
        name: gates.get(name, "PENDING")
        for name in NO_SHELL_PREREQUISITE_GATES
        if gates.get(name) != "PASS"
    }
    if missing:
        return "PENDING", {
            "status": "UNVERIFIED",
            "scope": "declared-four-entry-runtime-binding",
            "required_operations": list(NO_SHELL_ENTRY_OPERATIONS),
            "missing_prerequisites": missing,
            "release_authorized": False,
        }

    physical = proofs.get("physical_gui_click")
    ledgers = physical.get("ledgers") if isinstance(physical, dict) else None
    if not isinstance(ledgers, list) or len(ledgers) != len(NO_SHELL_ENTRY_OPERATIONS):
        return "FAIL", {
            "status": "FAIL",
            "reason": "physical GUI proof does not contain exactly one ledger for every declared entry",
            "release_authorized": False,
        }
    operations = []
    ledger_hashes: dict[str, str] = {}
    update_source: dict[str, Any] | None = None
    for row in ledgers:
        if not isinstance(row, dict):
            return "FAIL", {
                "status": "FAIL", "reason": "GUI ledger proof row is not an object",
                "release_authorized": False,
            }
        operation = row.get("operation")
        experiment_id = row.get("experiment_id")
        ledger_sha = row.get("ledger_sha256")
        if (operation not in NO_SHELL_ENTRY_OPERATIONS
                or type(experiment_id) is not int or experiment_id <= 0
                or not isinstance(ledger_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", ledger_sha)):
            return "FAIL", {
                "status": "FAIL", "reason": "GUI ledger proof is incomplete or malformed",
                "release_authorized": False,
            }
        operations.append(operation)
        ledger_hashes[operation] = ledger_sha
        if operation == "update":
            update_source = row.get("source_evidence")

    if (set(operations) != set(NO_SHELL_ENTRY_OPERATIONS)
            or len(set(operations)) != len(NO_SHELL_ENTRY_OPERATIONS)):
        return "FAIL", {
            "status": "FAIL",
            "reason": "declared GUI entry inventory is missing, duplicated or substituted",
            "observed_operations": operations,
            "release_authorized": False,
        }

    if (not isinstance(update_source, dict)
            or update_source.get("canonical_reparse") != "PASS"
            or type(update_source.get("raw_response_count")) is not int
            or update_source["raw_response_count"] <= 0
            or not isinstance(update_source.get("canonical_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", update_source["canonical_hash"])):
        return "FAIL", {
            "status": "FAIL",
            "reason": "GUI update entry is not bound to current official-source evidence",
            "release_authorized": False,
        }

    update_failure = proofs.get("physical_gui_failure")
    repair_failure = proofs.get("physical_gui_repair_failure")
    if (not isinstance(update_failure, dict) or update_failure.get("operation") != "update"
            or not isinstance(repair_failure, dict) or repair_failure.get("operation") != "repair"
            or type(repair_failure.get("repair_fail_count")) is not int
            or repair_failure["repair_fail_count"] < 1
            or repair_failure.get("repair_pass_count") != 0):
        return "FAIL", {
            "status": "FAIL",
            "reason": "GUI fail-closed evidence is missing or not operation-specific",
            "release_authorized": False,
        }

    updater = proofs.get("updater")
    if (not isinstance(updater, dict)
            or updater.get("process_boundary") != "PASS"
            or updater.get("atomic_rollback") != "PASS"
            or updater.get("same_hash") != "PASS"
            or not isinstance(updater.get("artifact_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", updater["artifact_sha256"])):
        return "FAIL", {
            "status": "FAIL",
            "reason": "independent updater runtime identity/rollback/hash evidence is incomplete",
            "release_authorized": False,
        }

    network = proofs.get("real_network")
    if (not isinstance(network, dict)
            or network.get("canonical_reparse") != "PASS"
            or type(network.get("raw_response_count")) is not int
            or network["raw_response_count"] <= 0
            or not isinstance(network.get("canonical_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", network["canonical_hash"])):
        return "FAIL", {
            "status": "FAIL",
            "reason": "current real-network evidence is incomplete",
            "release_authorized": False,
        }

    science = proofs.get("business_validation")
    if (not isinstance(science, dict)
            or not isinstance(science.get("court_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", science["court_hash"])
            or type(science.get("development_oos_n")) is not int
            or science["development_oos_n"] < 1200
            or type(science.get("untouched_holdout_n")) is not int
            or science["untouched_holdout_n"] < 240
            or science.get("leakage_violations") != 0):
        return "FAIL", {
            "status": "FAIL",
            "reason": "advanced-analysis entry is not bound to the current scientific evidence court",
            "release_authorized": False,
        }

    return "PASS", {
        "status": "PASS",
        "scope": "declared-four-entry-runtime-binding",
        "declared_entries": [
            {"control_id": 101, "label": "预测下一期", "operation": "predict"},
            {"control_id": 102, "label": "一键更新", "operation": "update"},
            {"control_id": 103, "label": "一键修复", "operation": "repair"},
            {"control_id": 104, "label": "高级分析", "operation": "audit"},
        ],
        "observed_operations": operations,
        "ledger_sha256": ledger_hashes,
        "update_canonical_hash": update_source["canonical_hash"],
        "real_network_canonical_hash": network["canonical_hash"],
        "science_court_hash": science["court_hash"],
        "updater_sha256": updater["artifact_sha256"],
        "negative_paths": {
            "update_fail_closed": "PASS",
            "repair_corrupt_offline_fail_closed": "PASS",
        },
        "full_business_completion_claimed": False,
        "release_authorized": True,
    }


BUSINESS_SCOPE_IDS = ("B01", "B02", "B03", "B04", "B05", "B06", "B07")


def _business_scope_approval(evidence: Path) -> dict[str, Any]:
    """Require a separate explicit user approval of the complete SSQ denominator."""
    path = evidence / "BUSINESS_SCOPE_APPROVAL.json"
    raw = _read(path)
    if raw is None:
        return {
            "status": "PENDING",
            "required_artifact": str(path),
            "reason": "complete SSQ business/entry denominator has not been explicitly approved by the user",
            "release_authorized": False,
        }
    expected_entries = ["predict", "update", "repair", "audit"]
    checks = {
        "schema": raw.get("schema") == "ssq-business-scope-approval-v1",
        "project": raw.get("project") == "SSQ",
        "approval_status": raw.get("status") == "APPROVED",
        "approved_by_user": raw.get("approved_by") == "user",
        "scope_ids_exact": raw.get("scope_ids") == list(BUSINESS_SCOPE_IDS),
        "entry_inventory_exact": raw.get("entry_inventory") == expected_entries,
        "approval_reference_present": (
            isinstance(raw.get("approval_reference"), str)
            and bool(raw["approval_reference"].strip())
        ),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "status": status,
        "report": str(path),
        "report_sha256": _hash(path),
        "checks": checks,
        "scope_ids": raw.get("scope_ids"),
        "entry_inventory": raw.get("entry_inventory"),
        "approval_reference": raw.get("approval_reference"),
        "release_authorized": status == "PASS",
    }


def _business_row(
    status: str, purpose: str, *, evidence_refs: list[str] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if status not in {"PASS", "FAIL", "PENDING"}:
        raise ValueError("invalid business task status")
    return {
        "status": status,
        "purpose": purpose,
        "evidence": evidence_refs or [],
        "reason": reason,
    }


def _business_gate_state(gates: dict[str, str], names: tuple[str, ...]) -> str:
    states = [gates.get(name, "PENDING") for name in names]
    if all(state == "PASS" for state in states):
        return "PASS"
    if any(state == "FAIL" for state in states):
        return "FAIL"
    return "PENDING"


def _derive_business_content_gate(
    gates: dict[str, str],
    proofs: dict[str, Any],
    exact_results: dict[str, dict[str, Any]],
    static_business_proof: dict[str, Any] | None,
    scope_approval: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Freeze and execute the SSQ B01-B07 business denominator.

    These seven tasks apply to SSQ only. They do not define completion for any
    other portfolio project. Static BUSINESS_GATE evidence is structural input,
    never sufficient by itself.
    """
    tasks: dict[str, dict[str, Any]] = {}

    physical_runtime = proofs.get("physical_gui_click")
    physical_ledgers = (
        physical_runtime.get("ledgers")
        if isinstance(physical_runtime, dict) else None
    )
    network_runtime = proofs.get("real_network")
    runtime_evidence_started = bool(
        exact_results
        or (isinstance(physical_ledgers, list) and bool(physical_ledgers))
        or (
            isinstance(network_runtime, dict)
            and isinstance(network_runtime.get("canonical_hash"), str)
        )
    )
    structural_ok = bool(
        isinstance(static_business_proof, dict)
        and static_business_proof.get("static_contract_status") == "PASS"
    )
    if not runtime_evidence_started:
        if not structural_ok:
            return "FAIL", {
                "status": "FAIL",
                "scope": "SSQ-B01-B07-v1",
                "scope_frozen_for": "SSQ only",
                "does_not_apply_to_other_projects": True,
                "structural_business_gate": static_business_proof,
                "tasks": {},
                "passed": 0,
                "pending": 0,
                "failed": 1,
                "total": len(BUSINESS_SCOPE_IDS),
                "reason": "static business contract is absent or invalid",
                "release_authorized": False,
            }
        pending_tasks = {
            key: _business_row(
                "PENDING",
                purpose,
                reason="current-run dynamic business evidence has not executed yet",
            )
            for key, purpose in {
                "B01": "更新历史并审计官方来源、最新期、冲突与网络失败",
                "B02": "生成可追溯研究结果并禁止未合格模型冒充生产优势",
                "B03": "独立科学与事后审计",
                "B04": "损坏检测与修复",
                "B05": "独立 Updater 真实版本 N→N+1",
                "B06": "所有 GUI 入口实体点击到真实后端",
                "B07": "长期维护与普通账户/中文路径",
            }.items()
        }
        return "PENDING", {
            "status": "PENDING",
            "scope": "SSQ-B01-B07-v1",
            "scope_frozen_for": "SSQ only",
            "does_not_apply_to_other_projects": True,
            "structural_business_gate": static_business_proof,
            "tasks": pending_tasks,
            "passed": 0,
            "pending": len(BUSINESS_SCOPE_IDS),
            "failed": 0,
            "total": len(BUSINESS_SCOPE_IDS),
            "release_authorized": False,
        }

    b01_required = (
        "contract_test", "fault_injection", "real_network",
        "physical_gui_click", "physical_gui_failure",
    )
    b01_status = _business_gate_state(gates, b01_required)
    tasks["B01"] = _business_row(
        b01_status,
        "更新历史并审计官方来源、最新期、冲突与网络失败",
        evidence_refs=["real_network", "fault_injection", "physical_gui_click", "physical_gui_failure"],
        reason=None if b01_status == "PASS" else "real-network/update positive+negative evidence is incomplete",
    )

    predict = exact_results.get("predict")
    predict_result = predict.get("result") if isinstance(predict, dict) else None
    contract = (
        predict_result.get("acceptance_autonomous_contract")
        if isinstance(predict_result, dict) else None
    )
    prediction = predict_result.get("prediction") if isinstance(predict_result, dict) else None
    lineage_fields = ("prediction_id", "freeze_hash", "score_hash", "model_hash", "selector_hash")
    b02_dynamic_present = isinstance(predict_result, dict)
    b02_ok = bool(
        isinstance(contract, dict) and contract
        and all(value is True for value in contract.values())
        and isinstance(prediction, dict)
        and all(isinstance(prediction.get(key), str) and prediction.get(key) for key in lineage_fields)
        and gates.get("business_validation") == "PASS"
    )
    if b02_ok:
        b02_status = "PASS"
    elif gates.get("business_validation") == "FAIL" or b02_dynamic_present:
        b02_status = "FAIL"
    else:
        b02_status = "PENDING"
    tasks["B02"] = _business_row(
        b02_status,
        "生成可追溯研究结果并禁止未合格模型冒充生产优势",
        evidence_refs=["exact_exe:predict", "business_validation"],
        reason=None if b02_status == "PASS" else "prediction lineage/model qualification evidence is incomplete",
    )

    b03_required = (
        "business_validation", "counterexample_validation", "reversal_validation",
    )
    b03_gate_status = _business_gate_state(gates, b03_required)
    if b03_gate_status == "PASS":
        b03_status = "PASS" if "audit" in exact_results else "FAIL"
    else:
        b03_status = b03_gate_status
    tasks["B03"] = _business_row(
        b03_status,
        "独立科学与事后审计：OOS/holdout/ablation/多重比较/反例/无泄漏",
        evidence_refs=["business_validation", "counterexample_validation", "reversal_validation", "exact_exe:audit"],
        reason=None if b03_status == "PASS" else "scientific/audit evidence is incomplete",
    )

    physical = proofs.get("physical_gui_click")
    ledgers_raw = physical.get("ledgers") if isinstance(physical, dict) else None
    ledgers = ledgers_raw if isinstance(ledgers_raw, list) else []
    repair_success = any(
        isinstance(row, dict) and row.get("operation") == "repair"
        and type(row.get("experiment_id")) is int and row["experiment_id"] > 0
        for row in ledgers
    )
    b04_required = (
        "fault_injection", "physical_gui_repair_failure", "updater_atomic_rollback",
    )
    b04_gate_status = _business_gate_state(gates, b04_required)
    if b04_gate_status == "PASS":
        b04_status = "PASS" if repair_success else "FAIL"
    else:
        b04_status = b04_gate_status
    tasks["B04"] = _business_row(
        b04_status,
        "损坏检测与修复：真实成功路径、失败证据、原子性与回滚",
        evidence_refs=["physical_gui_click:repair", "physical_gui_repair_failure", "fault_injection", "updater_atomic_rollback"],
        reason=None if b04_status == "PASS" else "repair success/failure/rollback evidence is incomplete",
    )

    b05_required = (
        "updater_process", "updater_exact_exe", "updater_atomic_rollback",
        "updater_same_hash", "updater_real_network",
        "repository_independence", "release_context",
    )
    b05_states = {name: gates.get(name, "PENDING") for name in b05_required}
    b05_ok = all(value == "PASS" for value in b05_states.values())
    b05_status = "PASS" if b05_ok else "PENDING"
    tasks["B05"] = _business_row(
        b05_status,
        "独立 Updater 真实版本 N→N+1：release、hash、进程身份、健康检查与失败回滚",
        evidence_refs=list(b05_required),
        reason=None if b05_ok else f"independent release/update prerequisites not closed: {b05_states}",
    )

    b06_required = (
        "no_shell", "physical_gui_click", "physical_gui_failure",
        "physical_gui_repair_failure",
    )
    b06_status = _business_gate_state(gates, b06_required)
    tasks["B06"] = _business_row(
        b06_status,
        "所有 GUI 入口实体点击到真实后端、显示和 ledger；失败不得显示 PASS",
        evidence_refs=["no_shell", "physical_gui_click", "physical_gui_failure", "physical_gui_repair_failure"],
        reason=None if b06_status == "PASS" else "GUI runtime/no-shell evidence is incomplete",
    )

    maintenance = exact_results.get("maintenance")
    maintenance_result = maintenance.get("result") if isinstance(maintenance, dict) else None
    maintenance_checks = (
        maintenance_result.get("checks") if isinstance(maintenance_result, dict) else None
    )
    standard = proofs.get("standard_user")
    b07_ok = bool(
        isinstance(maintenance_result, dict)
        and maintenance_result.get("status") == "PASS"
        and maintenance_result.get("real_network_status") == "PASS"
        and isinstance(maintenance_checks, dict) and maintenance_checks
        and all(value is True for value in maintenance_checks.values())
        and isinstance(standard, dict) and standard.get("status") == "PASS"
        and gates.get("exact_exe") == "PASS"
    )
    if b07_ok:
        b07_status = "PASS"
    elif gates.get("exact_exe") == "PASS":
        b07_status = "FAIL"
    elif gates.get("exact_exe") == "FAIL":
        b07_status = "FAIL"
    else:
        b07_status = "PENDING"
    tasks["B07"] = _business_row(
        b07_status,
        "长期维护：备份恢复、数据迁移、Evidence 导出、来源失败告警、普通账户与中文路径",
        evidence_refs=["exact_exe:maintenance", "standard_user", "unicode-path-no-python-path"],
        reason=None if b07_ok else "maintenance/standard-user/Unicode evidence is incomplete",
    )

    statuses = [tasks[key]["status"] for key in BUSINESS_SCOPE_IDS]
    approval_state = (
        scope_approval.get("status")
        if isinstance(scope_approval, dict) else "PENDING"
    )
    if not structural_ok:
        overall = "FAIL"
    elif any(status == "FAIL" for status in statuses):
        overall = "FAIL"
    elif any(status == "PENDING" for status in statuses):
        overall = "PENDING"
    elif approval_state == "FAIL":
        overall = "FAIL"
    elif approval_state != "PASS":
        overall = "PENDING"
    else:
        overall = "PASS"

    return overall, {
        "status": overall,
        "scope": "SSQ-B01-B07-v1",
        "scope_frozen_for": "SSQ only",
        "does_not_apply_to_other_projects": True,
        "structural_business_gate": static_business_proof,
        "scope_approval": scope_approval,
        "tasks": tasks,
        "passed": sum(status == "PASS" for status in statuses),
        "pending": sum(status == "PENDING" for status in statuses),
        "failed": sum(status == "FAIL" for status in statuses),
        "total": len(BUSINESS_SCOPE_IDS),
        "reason": (
            None if overall == "PASS"
            else "dynamic B01-B07 evidence does not replace explicit user approval of the complete business/entry denominator"
        ),
        "release_authorized": overall == "PASS",
    }


def derive(evidence: Path, exe: Path) -> dict[str, Any]:
    gates = {name: "PENDING" for name in HARD_GATES}
    proofs: dict[str, Any] = {}
    repository_status, repository_proof = _repository_independence_proof()
    gates["repository_independence"] = repository_status
    proofs["repository_independence"] = repository_proof
    release_context_status, release_context_proof = _release_context_proof()
    gates["release_context"] = release_context_status
    proofs["release_context"] = release_context_proof
    checkout_identity_ok = False
    try:
        proofs["checkout_identity"] = _verify_checkout_identity(evidence)
        checkout_identity_ok = True
    except Exception as exc:
        proofs["checkout_identity"] = {"error": f"{type(exc).__name__}: {exc}"}

    architecture_names = (
        "purpose_model", "five_why", "risk_boundary", "domain_model", "architecture",
        "function_contract", "interface_contract", "data_source", "netclient",
        "storage", "engine", "evidence", "service", "ui",
    )
    try:
        architecture = _require_current_report(
            evidence, "ARCHITECTURE_GATE.json", "ssq-architecture-gate-v2"
        )
        arch_gates = architecture.get("gates")
        if not isinstance(arch_gates, dict):
            raise ValueError("architecture report has no gate map")
        for name in architecture_names:
            gates[name] = "PASS" if arch_gates.get(name) == "PASS" else "FAIL"
        proofs["architecture"] = {
            "report": str(evidence / "ARCHITECTURE_GATE.json"),
            "report_sha256": _hash(evidence / "ARCHITECTURE_GATE.json"),
        }
    except Exception as exc:
        for name in architecture_names:
            gates[name] = "FAIL"
        proofs["architecture"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        unit = _require_current_report(evidence, "UNIT_GATE.json", "ssq-unit-gate-v1")
        if unit.get("exit_code") != 0:
            raise ValueError("unit gate exit code is nonzero")
        gates["unit_test"] = "PASS"
        proofs["unit_test"] = {
            "report": str(evidence / "UNIT_GATE.json"),
            "report_sha256": _hash(evidence / "UNIT_GATE.json"),
        }
    except Exception as exc:
        gates["unit_test"] = "FAIL"
        proofs["unit_test"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        contract = _require_current_report(
            evidence, "NETCLIENT_CONTRACT_GATE.json", "ssq-netclient-contract-gate-v2"
        )
        hard_fail_count = contract.get("hard_fail_count")
        if type(hard_fail_count) is not int or hard_fail_count != 0:
            raise ValueError("NetClient contract hard failures are nonzero")
        checks = contract.get("checks")
        if (not isinstance(checks, dict) or not REQUIRED_NETCLIENT_CHECKS.issubset(checks)
                or any(
            not isinstance(row, dict) or row.get("status") != "PASS"
            for row in checks.values()
        )):
            raise ValueError("NetClient contract check set is incomplete")
        gates["contract_test"] = "PASS"
        gates["netclient"] = "PASS" if gates["netclient"] == "PASS" else "FAIL"
        proofs["contract_test"] = {
            "report": str(evidence / "NETCLIENT_CONTRACT_GATE.json"),
            "report_sha256": _hash(evidence / "NETCLIENT_CONTRACT_GATE.json"),
        }
    except Exception as exc:
        gates["contract_test"] = "FAIL"
        gates["netclient"] = "FAIL"
        proofs["contract_test"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        business = _require_current_report(
            evidence, "BUSINESS_GATE.json", "ssq-business-gate-v1"
        )
        checks = business.get("checks")
        if (not isinstance(checks, dict) or not REQUIRED_BUSINESS_CHECKS.issubset(checks)
                or any(value is not True for value in checks.values())):
            raise ValueError("business content checks are incomplete")
        # This producer reads constants and searches source text. It does not
        # execute an approved, complete business/entry-point inventory. A
        # structural PASS must never open the product-completion release gate.
        gates["business_content"] = "PENDING"
        proofs["business_content"] = {
            "report": str(evidence / "BUSINESS_GATE.json"),
            "report_sha256": _hash(evidence / "BUSINESS_GATE.json"),
            "static_contract_status": "PASS",
            "full_business_completion": "UNVERIFIED",
            "reason": "approved complete business baseline and current entry-specific evidence are absent",
        }
    except Exception as exc:
        gates["business_content"] = "FAIL"
        proofs["business_content"] = {"error": f"{type(exc).__name__}: {exc}"}

    # Missing acceptance functionality is an explicit blocking gate, not a
    # placeholder product feature and not an invitation to provide PASS strings.
    # No full user-approved entry inventory currently exists in this candidate.
    gates["no_shell"] = "PENDING"
    proofs["no_shell"] = {
        "status": "UNVERIFIED",
        "reason": "complete approved button/module/model/updater/network/analysis inventory has not been bound to execution evidence",
        "release_authorized": False,
    }

    source_self_ok = False
    source_fault_ok = False
    try:
        _require_source_result(evidence, "source-self.json", "self")
        source_self_ok = True
    except Exception as exc:
        proofs["source_self"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        for filename, scope in (
            ("source-integrity-tamper.json", "integrity-tamper"),
            ("source-offline-failclosed.json", "offline-failclosed"),
            ("source-corrupt-repair.json", "corrupt-repair"),
        ):
            _require_source_result(evidence, filename, scope)
        source_fault_ok = True
        proofs["source_fault_injection"] = {
            "reports": [
                "source-integrity-tamper.json",
                "source-offline-failclosed.json",
                "source-corrupt-repair.json",
            ],
        }
    except Exception as exc:
        proofs["source_fault_injection"] = {"error": f"{type(exc).__name__}: {exc}"}

    acceptance_path = evidence / "WINDOWS_EXACT_EXE_ACCEPTANCE.json"
    acceptance = _read(acceptance_path)
    acceptance_ok = False
    if acceptance is not None:
        checks = acceptance.get("checks")
        if not isinstance(checks, dict):
            checks = {}
        declared_hash = acceptance.get("sha256")
        actual_hash = _hash(exe) if exe.is_file() else None
        current_sha = os.environ.get("GITHUB_SHA")
        current_run = os.environ.get("GITHUB_RUN_ID")
        acceptance_ok = (
            checkout_identity_ok
            and acceptance.get("runner_os") == "Windows"
            and isinstance(current_sha, str) and bool(re.fullmatch(r"[0-9a-f]{40}", current_sha))
            and isinstance(current_run, str) and bool(re.fullmatch(r"\d+", current_run))
            and acceptance.get("github_sha") == current_sha
            and acceptance.get("github_run_id") == current_run
            and acceptance.get("artifact") == exe.name
            and bool(actual_hash)
            and actual_hash == declared_hash
            and acceptance.get("windows_exact_exe_acceptance") == "PASS"
            and acceptance.get("final_release_gate") == "PENDING"
            and acceptance.get("hard_fail_count") == 0
            and REQUIRED_EXE_CHECKS.issubset(checks)
            and _corrupt_repair_is_fault_injection(evidence, actual_hash)
            and all(
                isinstance(check, dict)
                and check.get("status") == "PASS"
                and check.get("exit_code") == 0
                and check.get("exe_hash_matches") is True
                for check in checks.values()
            )
        )
        gates["windows_build"] = "PASS" if acceptance_ok else "FAIL"
        gates["exact_exe"] = "PASS" if acceptance_ok else "FAIL"
        reproducible_check = checks.get("reproducible-build")
        reproducible_ok = bool(
            acceptance_ok
            and isinstance(reproducible_check, dict)
            and reproducible_check.get("status") == "PASS"
            and reproducible_check.get("exit_code") == 0
            and reproducible_check.get("exe_hash_matches") is True
            and reproducible_check.get("primary_sha256") == actual_hash
            and reproducible_check.get("rebuild_sha256") == actual_hash
            and isinstance(reproducible_check.get("updater_primary_sha256"), str)
            and reproducible_check.get("updater_primary_sha256")
                == reproducible_check.get("updater_rebuild_sha256")
            and _repro_workspace_isolated(reproducible_check)
        )
        gates["reproducible_build"] = "PASS" if reproducible_ok else "FAIL"
        proofs["reproducible_build"] = {
            "report": str(evidence / "REPRODUCIBLE_BUILD.json"),
            "report_sha256": (
                _hash(evidence / "REPRODUCIBLE_BUILD.json")
                if (evidence / "REPRODUCIBLE_BUILD.json").is_file() else None
            ),
            "main_primary_sha256": (
                reproducible_check.get("primary_sha256")
                if isinstance(reproducible_check, dict) else None
            ),
            "main_rebuild_sha256": (
                reproducible_check.get("rebuild_sha256")
                if isinstance(reproducible_check, dict) else None
            ),
            "updater_primary_sha256": (
                reproducible_check.get("updater_primary_sha256")
                if isinstance(reproducible_check, dict) else None
            ),
            "updater_rebuild_sha256": (
                reproducible_check.get("updater_rebuild_sha256")
                if isinstance(reproducible_check, dict) else None
            ),
            "workspace_isolated": (
                _repro_workspace_isolated(reproducible_check)
                if isinstance(reproducible_check, dict) else False
            ),
            "workspace_paths": (
                reproducible_check.get("workspace_paths")
                if isinstance(reproducible_check, dict) else None
            ),
        }
        # Build/CLI checks prove only a narrow exact-EXE hash. The cross-stage
        # Same Hash gate also needs the physical GUI and live-network evidence.
        gates["same_hash"] = "PENDING" if acceptance_ok else "FAIL"
        proofs["exact_exe"] = {
            "report": str(acceptance_path),
            "report_sha256": _hash(acceptance_path),
            "actual_sha256": actual_hash,
            "declared_sha256": declared_hash,
        }
        self_check = checks.get("self")
        gates["self_test"] = (
            "PASS" if acceptance_ok and isinstance(self_check, dict)
            and self_check.get("status") == "PASS"
            and self_check.get("exe_hash_matches") is True else "FAIL"
        )

        exact_results: dict[str, dict[str, Any]] = {}
        if acceptance_ok and actual_hash:
            for name in (
                "self", "integrity-tamper", "offline-failclosed", "corrupt-repair",
                "update", "science", "random-world-101", "random-world-202",
                "random-world-303", "predict", "audit", "gui", "maintenance",
            ):
                try:
                    exact_results[name] = _require_exact_result(evidence, name, actual_hash)
                except Exception as exc:
                    proofs.setdefault("exact_result_errors", {})[name] = (
                        f"{type(exc).__name__}: {exc}"
                    )

        exact_self = exact_results.get("self")
        exact_version = exact_self.get("version") if isinstance(exact_self, dict) else None
        stable_version = bool(
            isinstance(exact_version, str)
            and re.fullmatch(
                r"\d+\.\d+\.\d+(?:\+[A-Za-z0-9.-]+)?",
                exact_version,
            )
        )
        gates["release_version"] = "PASS" if stable_version else "FAIL"
        proofs["release_version"] = {
            "version": exact_version,
            "stable_semver": stable_version,
            "rule": "Portfolio FINAL requires stable SemVer; prerelease labels such as -verification are forbidden",
        }

        gates["fault_injection"] = (
            "PASS"
            if source_fault_ok and all(
                name in exact_results
                for name in ("integrity-tamper", "offline-failclosed", "corrupt-repair")
            )
            else "FAIL"
        )
        if gates["fault_injection"] == "PASS":
            proofs["fault_injection"] = {
                "source_level": "PASS",
                "exact_exe_scopes": [
                    "integrity-tamper", "offline-failclosed", "corrupt-repair"
                ],
            }

        try:
            science = exact_results["science"]
            science_proof = _verify_science_contract(science)
            gates["business_validation"] = "PASS"
            if gates["five_why"] == "PASS":
                gates["five_why"] = "PASS"
            proofs["business_validation"] = science_proof

            random_worlds = [
                exact_results["random-world-101"],
                exact_results["random-world-202"],
                exact_results["random-world-303"],
            ]
            proofs["counterexample_validation"] = _verify_counterexample_contract(
                science, random_worlds
            )
            gates["counterexample_validation"] = "PASS"

            audit = exact_results["audit"]
            proofs["reversal_validation"] = _verify_reversal_contract(science, audit)
            gates["reversal_validation"] = "PASS"
        except Exception as exc:
            gates["business_validation"] = "FAIL"
            gates["counterexample_validation"] = "FAIL"
            gates["reversal_validation"] = "FAIL"
            proofs["scientific_dynamic"] = {"error": f"{type(exc).__name__}: {exc}"}

        live_check = checks.get("update")
        if not acceptance_ok or not isinstance(live_check, dict) or live_check.get("status") != "PASS":
            gates["real_network"] = "FAIL"
        else:
            # The EXE result alone is insufficient: independently read and hash
            # every preserved raw response from this exact candidate run.
            try:
                live_proof = _verify_live_evidence(evidence, actual_hash)
                if (live_proof.get("canonical_reparse") != "PASS"
                        or live_proof.get("official_html_parser_contract") != "PASS"):
                    raise ValueError("independent live raw reparse/parser contract did not PASS")
                proofs["real_network"] = live_proof
                gates["real_network"] = "PASS"
            except Exception as exc:
                gates["real_network"] = "FAIL"
                proofs["real_network"] = {"error": f"{type(exc).__name__}: {exc}"}
    # Independent updater proof is a first-class hard-gate family. The exact
    # updater EXE must be current-run/hash-bound, execute as a separate process,
    # prove atomic replacement + rollback from its own bytes, and preserve the
    # same updater hash that was embedded in the accepted main EXE. A real
    # software release-host transaction is deliberately separate and remains
    # non-PASS until an independent repository publishes a verifiable manifest
    # and exact main-EXE artifact.
    updater_path = evidence / "UPDATER_EXACT_EXE_ACCEPTANCE.json"
    updater = _read(updater_path)
    updater_actual_hash = None
    updater_exe = None
    try:
        if not isinstance(updater, dict) or not updater:
            raise ValueError("updater exact-EXE acceptance report missing")
        if updater.get("schema") != "ssq-updater-exact-exe-acceptance-v2":
            raise ValueError("updater acceptance schema mismatch")
        updater_exe = exe.parent / str(updater.get("artifact") or "")
        if not updater_exe.is_file():
            raise ValueError("exact updater EXE missing beside main EXE")
        updater_actual_hash = _hash(updater_exe)
        if (
            updater.get("runner_os") != "Windows"
            or updater.get("github_sha") != os.environ.get("GITHUB_SHA")
            or updater.get("github_run_id") != os.environ.get("GITHUB_RUN_ID")
            or updater.get("sha256") != updater_actual_hash
            or updater.get("updater_exact_exe") != "PASS"
            or type(updater.get("hard_fail_count")) is not int
            or updater.get("hard_fail_count") != 0
        ):
            raise ValueError("updater acceptance is not current-run/hash bound")

        updater_checks = updater.get("checks")
        required_updater_checks = {
            "self-test", "software-self-test", "offline-failclosed", "update", "repair",
            "software-local-install-acceptance", "software-local-rollback-acceptance",
        }
        if not isinstance(updater_checks, dict) or not required_updater_checks.issubset(updater_checks):
            raise ValueError("updater exact-EXE check set incomplete")
        updater_repro = updater_checks.get("reproducible-build")
        if (not isinstance(updater_repro, dict)
                or updater_repro.get("status") != "PASS"
                or updater_repro.get("exit_code") != 0
                or updater_repro.get("hash_matches") is not True
                or updater_repro.get("primary_sha256") != updater_actual_hash
                or updater_repro.get("rebuild_sha256") != updater_actual_hash
                or not _repro_workspace_isolated(updater_repro)):
            raise ValueError("updater reproducible-build evidence incomplete")
        process_ok = all(
            isinstance(updater_checks[name], dict)
            and updater_checks[name].get("status") == "PASS"
            and updater_checks[name].get("exit_code") == 0
            and updater_checks[name].get("hash_matches") is True
            and updater_checks[name].get("separate_process") is True
            and updater_checks[name].get("parent_pid_match") is True
            for name in required_updater_checks
        )
        if not process_ok:
            raise ValueError("updater process-boundary evidence incomplete")
        gates["updater_process"] = "PASS"
        gates["updater_exact_exe"] = "PASS"

        software_self = _read(evidence / "updater-software-self-test.json")
        software_result = software_self.get("service_result") if isinstance(software_self, dict) else None
        software_checks = software_result.get("checks") if isinstance(software_result, dict) else None
        rollback_ok = (
            isinstance(software_self, dict)
            and software_self.get("schema") == "ssq-independent-updater-v2"
            and software_self.get("mode") == "software-self-test"
            and software_self.get("status") == "PASS"
            and software_self.get("github_sha") == os.environ.get("GITHUB_SHA")
            and software_self.get("github_run_id") == os.environ.get("GITHUB_RUN_ID")
            and software_self.get("updater_exe_sha256") == updater_actual_hash
            and software_self.get("parent_pid_match") is True
            and isinstance(software_checks, dict)
            and software_checks
            and all(value is True for value in software_checks.values())
        )
        real_main_install = _read(evidence / "updater-local-main-install.json")
        real_main_rollback = _read(evidence / "updater-local-main-rollback.json")
        install_result = real_main_install.get("service_result") if isinstance(real_main_install, dict) else None
        rollback_result = real_main_rollback.get("service_result") if isinstance(real_main_rollback, dict) else None
        real_main_ok = (
            isinstance(real_main_install, dict)
            and real_main_install.get("schema") == "ssq-independent-updater-v2"
            and real_main_install.get("mode") == "software-local-install-acceptance"
            and real_main_install.get("status") == "PASS"
            and real_main_install.get("updater_exe_sha256") == updater_actual_hash
            and isinstance(install_result, dict)
            and install_result.get("status") == "PASS"
            and install_result.get("release_network_status") == "PENDING"
            and isinstance(install_result.get("transaction"), dict)
            and install_result["transaction"].get("status") == "PASS"
            and isinstance(real_main_rollback, dict)
            and real_main_rollback.get("schema") == "ssq-independent-updater-v2"
            and real_main_rollback.get("mode") == "software-local-rollback-acceptance"
            and real_main_rollback.get("status") == "PASS"
            and real_main_rollback.get("updater_exe_sha256") == updater_actual_hash
            and isinstance(rollback_result, dict)
            and rollback_result.get("status") == "PASS"
            and rollback_result.get("release_network_status") == "PENDING"
            and rollback_result.get("expect_rollback") is True
            and isinstance(rollback_result.get("transaction"), dict)
            and rollback_result["transaction"].get("status") == "FAIL"
            and rollback_result["transaction"].get("rolled_back") is True
        )
        gates["updater_atomic_rollback"] = "PASS" if rollback_ok and real_main_ok else "FAIL"

        embedded = acceptance.get("updater") if isinstance(acceptance, dict) else None
        main_self = (
            acceptance.get("checks", {}).get("self")
            if isinstance(acceptance, dict) and isinstance(acceptance.get("checks"), dict)
            else None
        )
        updater_same_hash_ok = (
            isinstance(embedded, dict)
            and embedded.get("sha256") == updater_actual_hash
            and isinstance(embedded.get("manifest"), dict)
            and embedded["manifest"].get("sha256") == updater_actual_hash
            and isinstance(main_self, dict)
            and main_self.get("updater_bundle_integrity") is True
            and main_self.get("embedded_updater_sha256") == updater_actual_hash
        )
        gates["updater_same_hash"] = "PASS" if updater_same_hash_ok else "FAIL"

        release_state = str(updater.get("software_release_network") or "PENDING")
        release_gate = str(updater.get("updater_release_gate") or "PENDING")
        release_proof: dict[str, Any] | None = None
        if release_state == "PASS" and release_gate == "PASS":
            release_proof = _verify_updater_release_network(evidence, updater_actual_hash, actual_hash)
            gates["updater_real_network"] = "PASS"
        elif release_state in {"PENDING", "WARNING", "UNAVAILABLE", "SKIPPED", "UNKNOWN"}:
            gates["updater_real_network"] = "PENDING"
        else:
            gates["updater_real_network"] = "FAIL"

        proofs["updater"] = {
            "acceptance_report": str(updater_path),
            "acceptance_sha256": _hash(updater_path),
            "artifact": str(updater_exe),
            "artifact_sha256": updater_actual_hash,
            "process_boundary": gates["updater_process"],
            "atomic_rollback": gates["updater_atomic_rollback"],
            "real_main_install_report": str(evidence / "updater-local-main-install.json"),
            "real_main_rollback_report": str(evidence / "updater-local-main-rollback.json"),
            "same_hash": gates["updater_same_hash"],
            "software_release_network": gates["updater_real_network"],
            "software_release_reason": updater.get("software_release_reason"),
            "software_release_proof": release_proof,
        }
    except Exception as exc:
        for name in (
            "updater_process", "updater_exact_exe", "updater_atomic_rollback",
            "updater_real_network", "updater_same_hash",
        ):
            gates[name] = "FAIL"
        proofs["updater"] = {"error": f"{type(exc).__name__}: {exc}"}

    physical_path = evidence / "physical_gui_click.json"
    physical = _read(physical_path)
    if physical is not None:
        try:
            gui_proof = _verify_gui_evidence(physical, evidence, exe, acceptance_ok)
            gates["gui_smoke"] = "PASS"
            gates["physical_gui_click"] = "PASS"
            physical_proof = {
                "report": str(physical_path),
                "report_sha256": _hash(physical_path),
                **gui_proof,
            }
            proofs["gui_smoke"] = dict(physical_proof)
            proofs["physical_gui_click"] = dict(physical_proof)
        except (OSError, TypeError, ValueError, KeyError, sqlite3.Error) as exc:
            gates["gui_smoke"] = "FAIL"
            gates["physical_gui_click"] = "FAIL"
            error = {"error": f"{type(exc).__name__}: {exc}"}
            proofs["gui_smoke"] = dict(error)
            proofs["physical_gui_click"] = dict(error)
            gates["same_hash"] = "FAIL"
    for operation, gate_name, filename in (
        ("update", "physical_gui_failure", "physical_gui_failure.json"),
        ("repair", "physical_gui_repair_failure", "physical_gui_repair_failure.json"),
    ):
        failure_path = evidence / filename
        physical_failure = _read(failure_path)
        if physical_failure is None:
            continue
        try:
            failure_proof = _verify_gui_failure_evidence(
                physical_failure, evidence, exe, acceptance_ok, expected_operation=operation,
            )
            gates[gate_name] = "PASS"
            proofs[gate_name] = {
                "report": str(failure_path),
                "report_sha256": _hash(failure_path),
                **failure_proof,
            }
        except (OSError, TypeError, ValueError, KeyError, sqlite3.Error) as exc:
            gates[gate_name] = "FAIL"
            proofs[gate_name] = {
                "error": f"{type(exc).__name__}: {exc}"
            }
            gates["same_hash"] = "FAIL"

    if (acceptance_ok and gates["physical_gui_click"] == "PASS"
            and gates["physical_gui_failure"] == "PASS"
            and gates["physical_gui_repair_failure"] == "PASS"
            and gates["real_network"] == "PASS"):
        gates["same_hash"] = "PASS"
    gates["integration_test"] = (
        "PASS"
        if source_self_ok and acceptance_ok
        and gates["real_network"] == "PASS"
        and gates["physical_gui_click"] == "PASS"
        and gates["physical_gui_failure"] == "PASS"
        and gates["physical_gui_repair_failure"] == "PASS"
        and "update" in locals().get("exact_results", {})
        else "FAIL"
    )
    if gates["integration_test"] == "PASS":
        proofs["integration_test"] = {
            "source_self": "PASS",
            "exact_exe_update": "PASS",
            "real_network": "PASS",
            "physical_gui": "PASS",
            "physical_gui_failure": "PASS",
            "physical_gui_repair_failure": "PASS",
        }

    # Re-derive no-shell only after all runtime evidence has been independently
    # verified above. Static source strings can never make this gate PASS.
    gates["no_shell"], proofs["no_shell"] = _derive_no_shell_gate(gates, proofs)

    try:
        proofs["standard_user"] = _verify_standard_user_evidence(
            evidence, exe, acceptance_ok
        )
    except Exception as exc:
        proofs["standard_user"] = {
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }

    static_business_proof = proofs.get("business_content")
    scope_approval = _business_scope_approval(evidence)
    proofs["business_scope_approval"] = scope_approval
    gates["business_content"], proofs["business_content"] = _derive_business_content_gate(
        gates,
        proofs,
        locals().get("exact_results", {}),
        static_business_proof if isinstance(static_business_proof, dict) else None,
        scope_approval,
    )
    return {
        "schema": "ssq-current-run-gate-evidence-v1",
        "commit_sha": os.environ.get("GITHUB_SHA"),
        "gates": gates,
        "proofs": proofs,
        "rule": "Every PASS is re-derived from current-run machine evidence; missing, stale, unbound or contradictory evidence is FAIL/PENDING",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = derive(args.evidence_dir, args.exe)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
