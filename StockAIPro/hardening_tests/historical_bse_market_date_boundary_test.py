"""Business falsification: impossible BSE stock-date claims cannot qualify PIT.

All fixture bytes here are synthetic. PASS means rejection of impossible dated
claims only, not actual SSE/SZSE/BSE historical data or any Final Gate.
"""
from __future__ import annotations
import hashlib
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"))
from stock_ai import historical_pit as pit

cases = []


def canonical_fixture(root: Path, when: str, bse_code: str):
    p = root / "canonical.jsonl"
    records = [
        {"date": when, "market": "SSE", "code": "600000", "st": False, "suspended": False},
        {"date": when, "market": "SZSE", "code": "000001", "st": False, "suspended": False},
        {"date": when, "market": "BSE", "code": bse_code, "st": False, "suspended": False},
    ]
    p.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records), encoding="utf-8")
    d = date.fromisoformat(when)
    return pit._validate_canonical_semantics(p, d, d, d)


def lifecycle_fixture(root: Path, when: str, code: str):
    p = root / "bse_lifecycle.jsonl"
    p.write_text(json.dumps({"market": "BSE", "code": code,
                             "listing_date": when, "delisting_date": None}) + "\n",
                 encoding="utf-8")
    return pit._read_lifecycle(p, "BSE")


def native_fixture(root: Path, when: str, code: str):
    raw = root / "bse_raw.json"
    raw.write_text(json.dumps({
        "schema": "stock-ai-security-lifecycle-source-v1",
        "market": "BSE", "point_in_time_only": True,
        "securities": [{"code": code, "listing_date": when, "delisting_date": None}],
    }) + "\n", encoding="utf-8")
    sh = hashlib.sha256(raw.read_bytes()).hexdigest()
    manifest = root / "provenance.json"
    manifest.write_text(json.dumps({
        "market": "BSE", "point_in_time_only": True,
        "raw_files": [{"path": raw.name, "sha256": sh}],
    }) + "\n", encoding="utf-8")
    return pit._validate_raw_provenance(root, manifest, "BSE")


def check_invalid(when: str, code: str, reason_fragment: str):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        results = {
            "canonical": canonical_fixture(root, when, code),
            "lifecycle": lifecycle_fixture(root, when, code),
            "raw": native_fixture(root, when, code),
        }
        for name, (accepted, reason, _) in results.items():
            assert not accepted, "FALSE PASS " + name + " " + when + "/" + code
            assert reason_fragment in reason, (name, when, code, reason)
        cases.append("reject:" + when + ":" + code)


def check_valid_structure(when: str, code: str):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, output in {
            "canonical": canonical_fixture(root, when, code),
            "lifecycle": lifecycle_fixture(root, when, code),
            "raw": native_fixture(root, when, code),
        }.items():
            assert output[0], (name, output)
        cases.append("allow-structural-only:" + when + ":" + code)


# BSE opened 2021-11-15. A selected-tier listing in 2020 is not a BSE day.
check_invalid("2020-12-23", "830001", "bse_before_market_open")
check_invalid("2021-11-14", "830001", "bse_before_market_open")
check_valid_structure("2021-11-15", "830001")

# First 6 BSE 920-code pilots activated 2025-05-06; remaining 242 on
# 2025-10-09. These tests only impose an unambiguous earliest-day bound.
# CRITICAL: official BSE 2024-04-19 bulletin authorizes NEW 920 IPOs from
# 2024-04-22, distinct from the 2025 switch of 248 EXISTING issuers.
# Official first-party BSE 2024-12-05 920098 IPO must not be rejected.
check_valid_structure("2024-12-05", "920098")
check_valid_structure("2025-05-05", "920098")
check_invalid("2024-04-08", "920098", "bse_920_before_new_ipo_activation")
check_valid_structure("2025-10-09", "920931")
check_valid_structure("2026-09-30", "920001")

# BSE's official three-bulletin 920 switch completed for the remaining
# 242 stocks on 2025-10-09. An old 4/8 identity cannot be counted after it.
check_valid_structure("2025-10-08", "830001")  # boundary only; not issuer proof
check_invalid("2025-10-09", "830001", "bse_legacy_after_unified_switch")
check_invalid("2026-09-30", "430001", "bse_legacy_after_unified_switch")

# BSE native 920 new-security IDs have a THREE-digit 920 prefix, not
# generic 92xxxx.  A 921/929 prefix must not silently enter an official BSE
# issuer/ST PIT under the six-digit code-shape helper.
for invalid in ("921001", "929999"):
    assert pit._market_for_code(invalid) is None, (
        "FALSE PASS: non-920 native BSE equity code classified as listed BSE: "+invalid)
    cases.append("reject-non-920-prefix:"+invalid)
assert pit._market_for_code("920002")=="BSE"
cases.append("allow-920-prefix-structural-only")
# Native exchange equity identifiers consist of ASCII digits exclusively.
# Python regex \d wrongly permits fullwidth and Arabic-Indic digits.
for invalid in ("920１２３", "600١٢٣", "300１２３"):
    assert pit._market_for_code(invalid) is None, (
        "FALSE BUSINESS PASS: forged non-ASCII security identity: " + repr(invalid))
    cases.append("non-ascii-identity-rejected:" + repr(invalid))
assert len(cases) == 17, cases
print("STOCK BSE IMPOSSIBLE HISTORICAL DATE BUSINESS TESTS 17/17 PASS")

# Source-native historical effective dates must be canonical YYYY-MM-DD.
# CPython date.fromisoformat also silently accepts YYYYMMDD and ISO-week
# notation. Neither is the declared calendar/PIT JSON wire format.
for noncanonical in ("20260930", "2026-W40-3", "2026W403"):
    assert pit._parse_day(noncanonical) is None, (
        "FALSE BUSINESS PASS: noncanonical PIT effective date accepted: " + noncanonical)
assert pit._parse_day("2026-09-30").isoformat() == "2026-09-30"
print("STOCK PIT CANONICAL DATE WIRE FORMAT 4/4 PASS")

# A successful process and frozen prediction are NOT successful stock business
# qualification when maintenance backtest fails due to missing official PIT.
# Read the real deployed pipeline source without importing pandas/AkShare.
import ast

_pipeline_path = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0" / "stock_ai" / "pipeline.py"
_pipeline_source = _pipeline_path.read_text(encoding="utf-8")
assert '"status":"PASS","asof":asof' not in _pipeline_source, (
    "FALSE BUSINESS PASS: daily pipeline publishes last_run.status=PASS even "
    "when automatic historical PIT backtest reports FAIL")
_tree = ast.parse(_pipeline_source)
_helpers = [n for n in _tree.body if isinstance(n, ast.FunctionDef)
            and n.name == "_maintenance_business_status"]
assert len(_helpers) == 1, "missing real production maintenance/business-status guard"
_ns = {}
exec(compile(ast.Module(body=_helpers, type_ignores=[]), str(_pipeline_path), "exec"), _ns)
_status = _ns["_maintenance_business_status"]
for maintenance, wanted in (
    ({"due": True, "backtest": "FAIL: historical_st_pit.json missing", "audit": "LOW"}, "BLOCKED"),
    ({"due": True, "backtest": "PASS", "audit": "MEDIUM"}, "PASS"),
    ({"due": True, "backtest": "PASS", "audit": "FAIL: no valid source"}, "BLOCKED"),
    ({"due": False, "backtest": None, "audit": None}, "NOT_VERIFIED"),
    (None, "NOT_VERIFIED"),
):
    observed = _status(maintenance)
    assert observed == wanted, (maintenance, wanted, observed)
assert '"business_status":business_status' in _pipeline_source, (
    "FALSE PASS: business qualification not explicitly emitted in last_run JSON")
print("STOCK DAILY BACKTEST VS BUSINESS STATUS FAIL-CLOSED CONTRACT 5/5 PASS")


# Research-only ranks MUST NOT produce TRADE/WATCH when the official historical
# SSE/SZSE/BSE ST and suspension source gate is WARN/missing, even if the
# recorded maintenance process itself completed. Validate the actual extracted
# production guard as a pure function; never fabricate original PIT acceptance.
_guards = [n for n in _tree.body if isinstance(n, ast.FunctionDef)
           and n.name == "_enforce_pit_trade_gate"]
assert len(_guards) == 1, "P0: missing pre-Freeze PIT trade decision guard"
_ns = {}
exec(compile(ast.Module(body=_guards, type_ignores=[]),
             str(_pipeline_path), "exec"), _ns)
_gate = _ns["_enforce_pit_trade_gate"]
for label, proposed, status, expected in (
    ("strong_signal", {"decision":"TRADE","model_trust":"HIGH","reasons":[]}, "WARN", "NO_TRADE"),
    ("watch_signal", {"decision":"WATCH","model_trust":"MEDIUM","reasons":[]}, "WARN", "NO_TRADE"),
    ("missing_gate", {"decision":"TRADE","model_trust":"HIGH","reasons":[]}, "UNKNOWN", "NO_TRADE"),
    ("qualified", {"decision":"TRADE","model_trust":"HIGH","reasons":[]}, "PASS", "TRADE"),
    ("existing_no_trade", {"decision":"NO_TRADE","model_trust":"LOW","reasons":[]}, "WARN", "NO_TRADE"),
):
    immutable = dict(proposed)
    guarded = _gate(proposed, status, "official historical PIT missing")
    assert proposed == immutable, ("mutated original decision",label)
    assert guarded["decision"] == expected, ("FALSE TRADE: unqualified PIT",label,guarded)
    assert guarded["historical_pit_status"] == status, (label,guarded)
    if status != "PASS":
        assert guarded["model_trust"] == "LOW", (label,guarded)
        assert guarded["reasons"], (label,guarded)
assert 'evaluate_historical_st_pit(ROOT,expected_trade_date=asof)' in _pipeline_source, (
    "FALSE BUSINESS PASS: full official historical PIT never evaluated before forecast freeze")
assert 'decision=_enforce_pit_trade_gate(decision,pit_status,pit_reason)' in _pipeline_source, (
    "FALSE TRADE: evaluated PIT does not control published decision")
assert _pipeline_source.index('decision=_enforce_pit_trade_gate(decision,pit_status,pit_reason)') < _pipeline_source.index('freeze_prediction(asof,'), (
    "FALSE BUSINESS PASS: a tradable Freeze was committed before PIT safety")
print("STOCK HISTORICAL PIT PRE-FREEZE TRADE AUTHORITY 5/5 PASS")


# OLD immutable Freeze may have contained TRADE before the new pipeline PIT
# barrier. The dashboard must render a safely qualified effective decision,
# rather than relabel old decision.json as executable without current evidence.
_app_path = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0" / "app.py"
_app_source = _app_path.read_text(encoding="utf-8")
_app_tree = ast.parse(_app_source)
_display_helpers = [n for n in _app_tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "_effective_display_decision"]
assert len(_display_helpers) == 1, (
    "FALSE BUSINESS PASS: dashboard has no historical frozen TRADE display gate")
_display_ns = {}
exec(compile(ast.Module(body=_display_helpers, type_ignores=[]),
             str(_app_path), "exec"), _display_ns)
_display_gate = _display_ns["_effective_display_decision"]
_old = {"decision":"TRADE","model_trust":"HIGH","reasons":[]}
_valid_last = {"status":"PASS","business_status":"PASS","execution_status":"PASS","asof":"2026-10-08"}
for label, last, pit, frozen, expected in (
    ("blocked_run", {"status":"BLOCKED","business_status":"BLOCKED","execution_status":"PASS","asof":"2026-10-08"}, "WARN", _old, "NO_TRADE"),
    ("legacy_false_pass", {"status":"PASS","asof":"2026-10-08"}, "PASS", _old, "NO_TRADE"),
    ("current_pit_missing", _valid_last, "WARN", _old, "NO_TRADE"),
    ("wrong_freeze_day", _valid_last, "PASS", _old, "NO_TRADE"),
    ("fully_verified", _valid_last, "PASS", {**_old,"historical_pit_status":"PASS"}, "TRADE"),
    ("existing_no_trade", _valid_last, "WARN", {"decision":"NO_TRADE","model_trust":"LOW","reasons":[]}, "NO_TRADE"),
):
    day = "2026-10-07" if label == "wrong_freeze_day" else "2026-10-08"
    previous = dict(frozen)
    actual = _display_gate(frozen,last,day,pit,"official PIT status "+pit)
    assert frozen == previous, ("old immutable Freeze was mutated",label)
    assert actual["decision"] == expected, ("FALSE TRADE displayed",label,actual)
    if expected == "NO_TRADE":
        assert actual["model_trust"] == "LOW" and actual["reasons"], (label,actual)
assert "evaluate_historical_st_pit(ROOT,expected_trade_date=summary.get('asof'))" in _app_source, (
    "FALSE BUSINESS PASS: dashboard never independently evaluates actual official PIT")
assert "decision=_effective_display_decision(" in _app_source, (
    "FALSE BUSINESS PASS: dashboard displays raw legacy frozen decision")
assert _app_source.index("decision=_effective_display_decision(") < _app_source.index("cols=st.columns(8)"), (
    "FALSE TRADE: dashboard displays metrics before source-date safety")
print("STOCK LEGACY FREEZE DASHBOARD PIT TRADE REFUSAL 6/6 PASS")
