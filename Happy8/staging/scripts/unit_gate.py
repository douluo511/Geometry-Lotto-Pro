from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.domain import Draw
from happy8.net_client import NetClient
from happy8.storage import canonical_json, sha256_json
from happy8.updater import _trusted_https, _version_tuple


def expect_raises(exc_type, fn) -> bool:
    try:
        fn()
    except exc_type:
        return True
    return False


def main() -> int:
    checks = {}

    draw = Draw.from_values(
        "2026261",
        "2026-09-28",
        [2,7,16,19,21,25,30,31,33,35,42,45,50,52,53,55,56,60,63,72],
    )
    checks["domain_valid_draw"] = {"status": "PASS" if len(draw.numbers) == 20 else "FAIL"}
    checks["domain_bad_issue"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "bad", "2026-09-28", range(1, 21)
        )) else "FAIL"
    }
    checks["domain_duplicate"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "2026261", "2026-09-28", [1] * 20
        )) else "FAIL"
    }
    checks["domain_out_of_range"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "2026261", "2026-09-28", list(range(1, 20)) + [81]
        )) else "FAIL"
    }
    checks["domain_future_date"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: Draw.from_values(
            "2026261", "2099-01-01", range(1, 21)
        )) else "FAIL"
    }

    checks["version_numeric"] = {
        "status": "PASS" if _version_tuple("1.2.30") == (1, 2, 30) else "FAIL"
    }
    checks["version_invalid_fail_closed"] = {
        "status": "PASS" if expect_raises(ValueError, lambda: _version_tuple("1.2-beta")) else "FAIL"
    }
    checks["trusted_https"] = {
        "status": "PASS"
        if _trusted_https("https://updates.example/a", {"updates.example"})
        and not _trusted_https("http://updates.example/a", {"updates.example"})
        and not _trusted_https("https://evil.example/a", {"updates.example"})
        else "FAIL"
    }

    value = {"b": 2, "a": [3, 1]}
    stable = canonical_json(value)
    checks["canonical_json_deterministic"] = {
        "status": "PASS"
        if stable == canonical_json(value) and sha256_json(value) == sha256_json({"a": [3, 1], "b": 2})
        else "FAIL"
    }

    client = NetClient(connect_timeout=1, read_timeout=2, max_attempts=99, backoff_base=0)
    checks["netclient_bounded_attempts"] = {
        "status": "PASS" if client.max_attempts == 4 else "FAIL"
    }
    checks["netclient_invalid_timeout"] = {
        "status": "PASS"
        if expect_raises(ValueError, lambda: NetClient(connect_timeout=0, read_timeout=1))
        else "FAIL"
    }

    status = "PASS" if checks and all(x["status"] == "PASS" for x in checks.values()) else "FAIL"
    report = {"schema": "happy8-unit-gate-v1", "status": status, "checks": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
