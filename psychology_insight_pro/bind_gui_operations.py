from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

def validate_operations(records, buttons, source_sha, run_id, attempt, mode="BlockedRelease"):
    expected = ["analysis", "update", "repair", "advanced"]
    matched = {}
    for i, operation in enumerate(expected):
        valid = [x for x in records if x.get("operation") == operation
                 and x.get("source_sha") == source_sha and x.get("github_run_id") == run_id
                 and x.get("github_run_attempt") == attempt and x.get("process_id") == buttons[i].get("gui_process_id")]
        if len(valid) != 1:
            raise ValueError(f"missing or ambiguous current physical process operation: {operation}")
        matched[operation] = valid[0]
    analysis = matched["analysis"]
    if analysis.get("status") != "PASS" or analysis.get("result", {}).get("hypothesis_count", 0) < 2 or "不是心理诊断" not in analysis.get("result", {}).get("disclaimer", ""):
        raise ValueError("actual analysis result or risk boundary missing")
    update = matched["update"]
    if mode == "BlockedRelease":
        if update.get("status") != "BLOCKED" or update.get("result", {}).get("action") != "RELEASE_DEPENDENCY_UNAVAILABLE":
            raise ValueError("absent release must keep software update BLOCKED")
    elif mode == "ConfiguredRelease":
        result = update.get("result", {})
        if update.get("status") != "PASS" or result.get("action") != "UPDATER_HANDOFF" or result.get("requires_parent_exit") is not True:
            raise ValueError("configured release requires successful physical GUI Updater handoff")
    else:
        raise ValueError("unknown release acceptance mode")
    repair = matched["repair"]
    if repair.get("status") != "PASS" or repair.get("result", {}).get("repair_action") != "RESTORED_VALIDATED_BUNDLE" or repair.get("result", {}).get("post_repair_self_test", {}).get("status") != "PASS":
        raise ValueError("corrupt-state repair and post repair self-test missing")
    advanced = matched["advanced"]
    if advanced.get("status") != "PASS" or any(advanced.get("result", {}).get(k) != "PASS" for k in ("core", "reverse_validation", "confidence_calibration")):
        raise ValueError("advanced health evidence incomplete")
    return matched

def main():
    p = argparse.ArgumentParser()
    for name in ("exe", "evidence", "audit", "data-root"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    physical = json.loads(Path(a.evidence).read_text(encoding="utf-8-sig"))
    buttons = physical.get("buttons", [])
    if physical.get("status") != "PASS" or len(buttons) != 4 or not all(x.get("status") == "PASS" and x.get("visual_changed") is True for x in buttons):
        raise ValueError("actual mouse and visible response missing")
    records = [json.loads(x) for x in Path(a.audit).read_text(encoding="utf-8").splitlines() if x]
    mode = physical.get("acceptance_mode", "BlockedRelease")
    operations = validate_operations(records, buttons, os.environ["PSYCHOLOGY_SOURCE_SHA"], os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"], mode)
    digest = hashlib.sha256(Path(a.exe).read_bytes()).hexdigest()
    software_state = "BLOCKED"
    if mode == "ConfiguredRelease":
        handoff = operations["update"]["result"]
        transaction_path = Path(handoff["evidence_file"]).resolve()
        transaction_path.relative_to(Path(a.data_root).resolve())
        transaction = json.loads(transaction_path.read_text(encoding="utf-8-sig"))
        config = json.loads(Path(handoff["release_config"]).read_text(encoding="utf-8-sig"))
        updater_hash = hashlib.sha256(Path(handoff["updater_exe"]).read_bytes()).hexdigest()
        receipt = transaction.get("manifest_receipt", {})
        receipt_url = receipt.get("final_url", receipt.get("requested_url", ""))
        receipt_parsed = urlsplit(receipt_url)
        valid = (transaction.get("schema") == "psychology-updater-execution-v1" and transaction.get("status") == "PASS"
                 and transaction.get("operation") == "software_update" and transaction.get("action") == "UP_TO_DATE"
                 and transaction.get("current_version") == transaction.get("manifest_version") == "0.4.0"
                 and transaction.get("github_sha") == os.environ["PSYCHOLOGY_SOURCE_SHA"]
                 and transaction.get("github_run_id") == os.environ["GITHUB_RUN_ID"]
                 and transaction.get("github_run_attempt") == os.environ["GITHUB_RUN_ATTEMPT"]
                 and transaction.get("main_sha256_before") == transaction.get("main_sha256_after") == digest
                 and transaction.get("updater_exe_sha256") == updater_hash
                 and isinstance(transaction.get("process_id"), int) and transaction["process_id"] > 0
                 and transaction["process_id"] != operations["update"]["process_id"]
                 and receipt.get("requested_url") == config.get("manifest_url")
                 and receipt_parsed.scheme == "https" and receipt_parsed.hostname in config.get("trusted_hosts", [])
                 and receipt.get("http_status") == 200 and int(receipt.get("byte_count", 0)) > 0
                 and bool(re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256", "")))))
        if not valid:
            raise ValueError("configured physical update lacks current independent transaction and production manifest receipt")
        physical["configured_update_transaction"] = transaction
        software_state = "PASS"
    repair = operations["repair"]["result"]
    backup = Path(repair["backups"]["knowledge.json"])
    data_root = Path(a.data_root).resolve()
    backup.resolve().relative_to(data_root)
    if backup.read_bytes() != b"CORRUPT_FOR_PHYSICAL_REPAIR":
        raise ValueError("exact damaged bytes were not preserved")
    restored = json.loads((data_root / "knowledge.json").read_text(encoding="utf-8"))
    from contracts import validate_knowledge
    validate_knowledge(restored)
    physical.update({"operation_binding": "PASS", "operations": operations,
                     "github_sha": os.environ["PSYCHOLOGY_SOURCE_SHA"], "github_run_id": os.environ["GITHUB_RUN_ID"],
                     "github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                     "exe_sha256": digest,
                     "schema": "psychology-physical-gui-bound-v3", "software_update_release": software_state})
    Path(a.evidence).write_text(json.dumps(physical, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "operation_binding": "PASS", "software_update_release": software_state}))

if __name__ == "__main__":
    main()
