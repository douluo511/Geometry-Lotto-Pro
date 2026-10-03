from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

OPERATIONS = ("information_judgment", "software_update", "repair", "advanced_analysis")
REPAIR_CHECKS = {"database", "index", "missing_files", "cache", "configuration", "network_configuration", "version", "data_integrity"}

def sha256(path: Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def bind(value: dict, operations: dict, exe_hash: str) -> dict:
    buttons = value.get("buttons")
    run_id = value.get("gui_run_id")
    attempt = value.get("workflow_attempt")
    if not (value.get("schema") == "head-intelligence-physical-gui-v2" and value.get("status") == "PASS"
            and run_id and attempt and isinstance(buttons, list) and len(buttons) == 4
            and {button.get("operation") for button in buttons} == set(OPERATIONS)
            and all(button.get("status") == "PASS" and button.get("visual_changed") is True for button in buttons)):
        raise ValueError("physical clicks and visual changes are incomplete")
    by_name = operations.get("operations", {})
    if not (operations.get("schema") == "head-intelligence-gui-operations-v1"
            and operations.get("main_exe_sha256") == exe_hash and operations.get("gui_run_id") == run_id and operations.get("workflow_attempt") == attempt):
        raise ValueError("backend operations are not bound to the tested EXE/run")
    for button in buttons:
        operation = by_name.get(button["operation"], {})
        if not (operation.get("gui_run_id") == run_id and operation.get("workflow_attempt") == attempt and operation.get("process_id") == button.get("process_id")
                and operation.get("completed_at") and operation.get("status") == button.get("operation_status")):
            raise ValueError("a physical click has stale or unrelated backend evidence")
    judgment = by_name.get("information_judgment", {})
    advanced = by_name.get("advanced_analysis", {})
    repair = by_name.get("repair", {})
    checks = repair.get("checks", {})
    if not (judgment.get("status") == "PASS" and isinstance(judgment.get("snapshot"), dict)
            and judgment["snapshot"].get("status") == "PASS" and judgment["snapshot"].get("items")
            and advanced.get("status") == "PASS" and advanced.get("snapshot")
            and len(advanced.get("business_dimensions", [])) == 6
            and repair.get("local_integrity_status") == "PASS" and set(checks) == REPAIR_CHECKS
            and all(item.get("status") == "PASS" for key, item in checks.items() if key != "network_configuration")
            and "RESTORED_VERIFIED_SNAPSHOT" in repair.get("actions", [])):
        raise ValueError("judgment/advanced analysis/repair did not finish successfully")
    update = by_name.get("software_update", {})
    if update.get("status") == "BLOCKED" and repair.get("status") == "BLOCKED" and checks["network_configuration"].get("status") == "BLOCKED":
        release_mode = "BlockedRelease"
    elif (update.get("status") == "PASS" and update.get("action") == "UPDATER_HANDOFF"
          and update.get("requires_parent_exit") is True and repair.get("status") == "PASS"
          and checks["network_configuration"].get("status") == "PASS"):
        release_mode = "ConfiguredRelease"
    else:
        raise ValueError("software handoff and repair release state are inconsistent")
    return {**value, "operation_binding": "PASS", "release_mode": release_mode,
            "exe_sha256": exe_hash, "button_count": 4, "repair_local_integrity": "PASS"}

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--exe",required=True)
    p.add_argument("--evidence",required=True)
    p.add_argument("--marker",required=True)
    p.add_argument("--operation-evidence",required=True)
    a=p.parse_args()
    exe=Path(a.exe); evidence=Path(a.evidence); marker=Path(a.marker)
    marker.unlink(missing_ok=True)
    try:
        value=json.loads(evidence.read_text(encoding="utf-8-sig"))
        operations=json.loads(Path(a.operation_evidence).read_text(encoding="utf-8-sig"))
        value=bind(value, operations, sha256(exe))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status":"FAIL", "error":str(exc)}, ensure_ascii=True))
        return 4
    evidence.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    marker.parent.mkdir(parents=True,exist_ok=True)
    marker.write_text(value["exe_sha256"],encoding="ascii")
    print(json.dumps({"status":"PASS","exe_sha256":value["exe_sha256"],"release_mode":value["release_mode"]}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
