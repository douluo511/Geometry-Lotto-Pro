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

# FIRST-PARTY BSE counterexample to the mistaken global May 2025 gate:
# https://www.bse.cn/important_news/200021617.html : new-issue 920 codes
# authorized 2024-04-22; https://www.bse.cn/issue_report_meeting/200021986.html
# confirms genuine 920002 (万达轴承) listed 2024-05-30.
# This is only a proved single-issuer boundary; not a complete BSE master.
check_valid_structure("2024-05-30", "920002")
# First 6 BSE 920-code pilots activated 2025-05-06; remaining 242 on
# 2025-10-09. These tests only impose an unambiguous earliest-day bound.
check_invalid("2024-04-08", "920931", "bse_920_before_first_activation")
check_invalid("2025-05-05", "920931", "bse_920_before_first_activation")
check_valid_structure("2025-10-09", "920931")
check_valid_structure("2026-09-30", "920001")

# BSE's official three-bulletin 920 switch completed for the remaining
# 242 stocks on 2025-10-09. An old 4/8 identity cannot be counted after it.
check_valid_structure("2025-10-08", "830001")  # boundary only; not issuer proof
check_invalid("2025-10-09", "830001", "bse_legacy_after_unified_switch")
check_invalid("2026-09-30", "430001", "bse_legacy_after_unified_switch")

assert len(cases) == 11, cases
print("STOCK BSE IMPOSSIBLE HISTORICAL DATE BUSINESS TESTS 11/11 PASS")
