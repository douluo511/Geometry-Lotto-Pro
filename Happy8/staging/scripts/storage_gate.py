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
    sh_name = "shanghai_2026200_2026297.html"
    raw = {
        sh_name: b"<html>shanghai fixture</html>" * 100,
        "jiangsu_welfare_lottery.html": b"<html>jiangsu fixture</html>" * 100,
    }
    manifest = [{
        "sequence": 1,
        "start_issue": "2026200",
        "end_issue": "2026297",
        "filename": sh_name,
        "http_status": 200,
        "sha256": sha256_bytes(raw[sh_name]),
        "bytes": len(raw[sh_name]),
        "draw_count": 1,
        "first_issue": "2026261",
        "last_issue": "2026261",
        "url": "https://www.swlc.net.cn/lottery/kl8.html?view=previous&limit=100&start_issue=2026200&end_issue=2026297",
    }]
    receipts = [
        {
            "source":"shanghai_welfare_lottery",
            "raw_sha256":sha256_json(manifest),
            "bytes":len(raw[sh_name]),
            "status":"PASS",
        },
        {
            "source":"jiangsu_welfare_lottery",
            "raw_sha256":sha256_bytes(raw["jiangsu_welfare_lottery.html"]),
            "bytes":len(raw["jiangsu_welfare_lottery.html"]),
            "status":"PASS",
        },
    ]
    report = {
        "schema":"happy8-staging-official-network-v3",
        "status":"PASS",
        "latest":draws[-1],
        "history_count":len(draws),
        "draws":draws,
        "canonical_hash":sha256_json(draws),
        "crosscheck_count":1,
        "crosscheck_status":"PASS",
        "verification":"SHANGHAI_FULL_HISTORY_PLUS_JIANGSU_CURRENT",
        "history_source":"shanghai_welfare_lottery",
        "history_raw_manifest":manifest,
        "source_receipts":receipts,
        "shanghai_raw_manifest":manifest,
    }
    return report, raw, sh_name



def national_bootstrap_sample():
    draws = [{
        "issue": "2026261",
        "draw_date": "2026-09-28",
        "numbers": [2,7,16,19,21,25,30,31,33,35,42,45,50,52,53,55,56,60,63,72],
    }]
    bootstrap_name = "national_session_bootstrap.html"
    page_name = "national_page_0001.json"
    raw = {
        bootstrap_name: b"<html>CWL bootstrap fixture</html>" * 100,
        page_name: b'{"state":0,"result":[]}' * 100,
        "jiangsu_welfare_lottery.html": b"<html>jiangsu current fixture</html>" * 100,
    }
    bootstrap = {
        "url": "https://www.cwl.gov.cn/ygkj/wqkjgg/kl8/",
        "http_status": 200,
        "sha256": sha256_bytes(raw[bootstrap_name]),
        "bytes": len(raw[bootstrap_name]),
        "attempts": [],
        "cookie_names": ["example"],
    }
    manifest = [{
        "sequence": 1,
        "session_bootstrap": bootstrap,
        "page": 1,
        "filename": page_name,
        "http_status": 200,
        "sha256": sha256_bytes(raw[page_name]),
        "bytes": len(raw[page_name]),
        "draw_count": 1,
        "first_issue": "2026261",
        "last_issue": "2026261",
        "url": "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?pageNo=1",
    }]
    report = {
        "schema": "happy8-staging-official-network-v4",
        "status": "PASS",
        "latest": draws[-1],
        "history_count": len(draws),
        "draws": draws,
        "canonical_hash": sha256_json(draws),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
        "verification": "CWL_FULL_HISTORY_PLUS_JIANGSU_CURRENT",
        "history_source": "national_welfare_lottery",
        "history_raw_manifest": manifest,
        "source_receipts": [
            {
                "source": "national_welfare_lottery",
                "raw_sha256": sha256_json({"session_bootstrap": bootstrap, "pages": manifest}),
                "bytes": len(raw[bootstrap_name]) + len(raw[page_name]),
                "status": "PASS",
            },
            {
                "source": "jiangsu_welfare_lottery",
                "raw_sha256": sha256_bytes(raw["jiangsu_welfare_lottery.html"]),
                "bytes": len(raw["jiangsu_welfare_lottery.html"]),
                "status": "PASS",
            },
        ],
    }
    return report, raw


def composite_sample():
    draws = [{
        "issue": "2026261",
        "draw_date": "2026-09-28",
        "numbers": [2,7,16,19,21,25,30,31,33,35,42,45,50,52,53,55,56,60,63,72],
    }]
    source_id = "jiangxi_fuzhou_numbers_plus_mof_calendar_plus_jiangsu_issue_provenance"
    fuzhou_name = "fuzhou_page_001.html"
    mof_name = "mof_market_calendar_contract.json"
    jiangsu_history_name = "jiangsu_history_page_001.html"
    raw = {
        fuzhou_name: b"<html>fuzhou official fixture</html>" * 100,
        mof_name: b'{"2026":"official-mof-calendar-fixture"}',
        jiangsu_history_name: b"<html>jiangsu history fixture</html>" * 100,
        "jiangsu_welfare_lottery.html": b"<html>jiangsu current fixture</html>" * 100,
    }
    manifest = [
        {
            "source": "jiangxi_fuzhou_welfare_lottery",
            "page": 1,
            "filename": fuzhou_name,
            "url": "https://www.jxfzfc.cn/lottery.php?play=kl8&sid=new&page=1",
            "http_status": 200,
            "sha256": sha256_bytes(raw[fuzhou_name]),
            "bytes": len(raw[fuzhou_name]),
            "row_count": 1,
            "first_issue": "2026261",
            "last_issue": "2026261",
        },
        {
            "source": "ministry_of_finance_lottery_market_calendar",
            "filename": mof_name,
            "url": "https://zhs.mof.gov.cn/zhengcefabu/",
            "http_status": 200,
            "sha256": sha256_bytes(raw[mof_name]),
            "bytes": len(raw[mof_name]),
            "row_count": 1,
            "first_issue": "2026261",
            "last_issue": "2026261",
        },
        {
            "source": "jiangsu_welfare_lottery",
            "page": 1,
            "filename": jiangsu_history_name,
            "url": "https://www.jslottery.com/winning_history_a?locale=zh-CN&lottery_type_id=17&page=1&periods=",
            "http_status": 200,
            "sha256": sha256_bytes(raw[jiangsu_history_name]),
            "bytes": len(raw[jiangsu_history_name]),
            "row_count": 1,
            "first_issue": "2026261",
            "last_issue": "2026261",
        },
        {
            "source": "jiangsu_welfare_lottery_issue_provenance_crosscheck",
            "filename": "derived_from_jiangsu_history_pages",
            "url": "https://www.jslottery.com/winning_history_a",
            "http_status": 200,
            "sha256": sha256_json({"publication_evidence": {"2026261": "fixture"}, "missing_index_issues": []}),
            "bytes": 0,
            "row_count": 1,
            "first_issue": "2026261",
            "last_issue": "2026261",
            "missing_index_count": 0,
            "missing_index_issues": [],
        },
    ]
    report = {
        "schema": "happy8-staging-official-network-v4",
        "status": "PASS",
        "latest": draws[-1],
        "history_count": len(draws),
        "draws": draws,
        "canonical_hash": sha256_json(draws),
        "crosscheck_count": 1,
        "crosscheck_status": "PASS",
        "verification": "FUZHOU_NUMBERS_PLUS_MOF_MARKET_CALENDAR_CROSSCHECKED_JIANGSU_AND_CURRENT_NUMBERS",
        "history_source": source_id,
        "history_raw_manifest": manifest,
        "source_receipts": [
            {
                "source": source_id,
                "raw_sha256": sha256_json(manifest),
                "bytes": sum(len(raw[name]) for name in (fuzhou_name, mof_name, jiangsu_history_name)),
                "status": "PASS",
            },
            {
                "source": "jiangsu_welfare_lottery",
                "raw_sha256": sha256_bytes(raw["jiangsu_welfare_lottery.html"]),
                "bytes": len(raw["jiangsu_welfare_lottery.html"]),
                "status": "PASS",
            },
        ],
    }
    return report, raw

def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory(prefix="happy8-storage-gate-") as td:
        root = Path(td)
        store = Store(root)
        report, raw, sh_name = sample()
        committed = store.commit_official_snapshot(report, raw)
        checks["commit"] = {"status":"PASS" if committed["status"] == "PASS" else "FAIL"}
        checks["integrity"] = {"status":store.integrity_check()["status"]}

        pointer = json.loads(store.current.read_text(encoding="utf-8"))
        generation = store.generations / pointer["generation_id"]
        target = generation / "RAW" / sh_name
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

        bad_manifest = copy.deepcopy(report)
        bad_manifest["history_raw_manifest"][0]["sha256"] = "0" * 64
        try:
            store.commit_official_snapshot(bad_manifest, raw)
            checks["manifest_tamper_fail_closed"] = {"status":"FAIL"}
        except ValueError:
            checks["manifest_tamper_fail_closed"] = {"status":"PASS"}

    with tempfile.TemporaryDirectory(prefix="happy8-storage-repair-") as td:
        store = Store(Path(td))
        report, raw, _ = sample()
        store.commit_official_snapshot(report, raw)
        store.current.write_text("{corrupt", encoding="utf-8")
        repaired = store.repair_current_pointer()
        checks["repair_corrupt_current_pointer"] = {
            "status": "PASS"
            if repaired.get("status") == "PASS" and store.integrity_check().get("status") == "PASS"
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-storage-repair-fail-") as td:
        store = Store(Path(td))
        report, raw, sh_name = sample()
        store.commit_official_snapshot(report, raw)
        pointer = json.loads(store.current.read_text(encoding="utf-8"))
        generation = store.generations / pointer["generation_id"]
        target = generation / "RAW" / sh_name
        target.write_bytes(target.read_bytes() + b"corrupt-all-generations")
        store.current.write_text("{still-corrupt", encoding="utf-8")
        before = store.current.read_bytes()
        repaired = store.repair_current_pointer()
        checks["repair_no_valid_generation_fail_closed"] = {
            "status": "PASS"
            if repaired.get("status") == "FAIL" and store.current.read_bytes() == before
            else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-storage-national-") as td:
        report, raw = national_bootstrap_sample()
        result = Store(Path(td)).commit_official_snapshot(report, raw)
        checks["national_bootstrap_raw_binding"] = {
            "status": "PASS" if result.get("status") == "PASS" else "FAIL"
        }

    with tempfile.TemporaryDirectory(prefix="happy8-storage-composite-") as td:
        report, raw = composite_sample()
        store = Store(Path(td))
        result = store.commit_official_snapshot(report, raw)
        checks["provincial_composite_raw_binding"] = {
            "status": "PASS" if result.get("status") == "PASS" else "FAIL"
        }
        tampered = copy.deepcopy(report)
        tampered["history_raw_manifest"][0]["source"] = "untrusted_source"
        try:
            store.commit_official_snapshot(tampered, raw)
            checks["composite_source_identity_fail_closed"] = {"status": "FAIL"}
        except ValueError:
            checks["composite_source_identity_fail_closed"] = {"status": "PASS"}

        derived_tamper = copy.deepcopy(report)
        derived_tamper["history_raw_manifest"][-1]["missing_index_count"] = 1
        derived_tamper["source_receipts"][0]["raw_sha256"] = sha256_json(
            derived_tamper["history_raw_manifest"]
        )
        try:
            store.commit_official_snapshot(derived_tamper, raw)
            checks["composite_derived_metadata_fail_closed"] = {"status": "FAIL"}
        except ValueError:
            checks["composite_derived_metadata_fail_closed"] = {"status": "PASS"}

    status = "PASS" if all(x["status"] == "PASS" for x in checks.values()) else "FAIL"
    value = {"schema":"happy8-storage-gate-v2","status":status,"checks":checks}
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
