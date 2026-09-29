from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.storage import Store, sha256_bytes, sha256_json


def sample():
    draws = [{
        "issue": "2026261",
        "draw_date": "2026-09-28",
        "numbers": [2,7,16,19,21,25,30,31,33,35,42,45,50,52,53,55,56,60,63,72],
    }]
    raw = {
        "shanghai_welfare_lottery.html": b"<html>shanghai fixture</html>" * 100,
        "jiangsu_welfare_lottery.html": b"<html>jiangsu fixture</html>" * 100,
    }
    receipts = [
        {"source":"shanghai_welfare_lottery","raw_sha256":sha256_bytes(raw["shanghai_welfare_lottery.html"])},
        {"source":"jiangsu_welfare_lottery","raw_sha256":sha256_bytes(raw["jiangsu_welfare_lottery.html"])},
    ]
    report = {
        "schema":"happy8-staging-official-network-v2",
        "status":"PASS",
        "latest":draws[-1],
        "history_count":len(draws),
        "draws":draws,
        "canonical_hash":sha256_json(draws),
        "crosscheck_count":1,
        "crosscheck_status":"PASS",
        "source_receipts":receipts,
    }
    return report, raw


def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory(prefix="happy8-storage-gate-") as td:
        root = Path(td)
        store = Store(root)
        report, raw = sample()
        committed = store.commit_official_snapshot(report, raw)
        checks["commit"] = {"status":"PASS" if committed["status"] == "PASS" else "FAIL"}
        checks["integrity"] = {"status":store.integrity_check()["status"]}

        pointer = json.loads(store.current.read_text(encoding="utf-8"))
        generation = store.generations / pointer["generation_id"]
        target = generation / "RAW" / "shanghai_welfare_lottery.html"
        original = target.read_bytes()
        target.write_bytes(original + b"tamper")
        tampered = store.integrity_check()
        checks["raw_tamper_detection"] = {"status":"PASS" if tampered["status"] == "FAIL" else "FAIL"}
        target.write_bytes(original)

        bad_report = copy.deepcopy(report)
        bad_report["canonical_hash"] = "0" * 64
        before = store.current.read_bytes()
        try:
            store.commit_official_snapshot(bad_report, raw)
            checks["bad_hash_fail_closed"] = {"status":"FAIL"}
        except ValueError:
            checks["bad_hash_fail_closed"] = {"status":"PASS"}
        checks["failed_commit_preserves_current"] = {
            "status":"PASS" if store.current.read_bytes() == before else "FAIL"
        }

    status = "PASS" if all(x["status"] == "PASS" for x in checks.values()) else "FAIL"
    value = {"schema":"happy8-storage-gate-v1","status":status,"checks":checks}
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
