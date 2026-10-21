"""Read-only receipt verification; no SQLite opens, replay or process execution."""
from pathlib import Path
import hashlib

from research.ssq_dlt_v45.store import digest, parse


def verify(output):
    output=Path(output).resolve()
    index=parse((output/"SHA256.json").read_bytes())
    files=index["files"]
    # Only the top-level inventory is excluded. A nested same-name file is data.
    actual={p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file() and p!=output/"SHA256.json"}
    if actual!=set(files): raise ValueError("ARTIFACT_LAYOUT_CHANGED")
    for name, entry in files.items():
        path=output/name
        if Path(name).is_absolute() or ".." in Path(name).parts or not path.resolve().is_relative_to(output):
            raise ValueError("UNSAFE_ARTIFACT_PATH")
        if path.stat().st_size!=entry["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=entry["sha256"]:
            raise ValueError("ARTIFACT_HASH_CHANGED")
    receipt=parse((output/"RECEIPT.json").read_bytes())
    start=parse((output/"STARTED.json").read_bytes())
    if (type(receipt.get("formal_A")) is not int or receipt["formal_A"]!=0 or receipt.get("decision")!="NO_EDGE"
            or type(receipt.get("qualified_prospective_samples")) is not int or receipt["qualified_prospective_samples"]!=0
            or receipt.get("full_physical_p0")!="NOT_RUN" or receipt.get("actual_scheduler")!="NOT_RUN"
            or receipt.get("real_inbox_delivery")!="NOT_RUN"):
        raise ValueError("SCOPE_OR_ADMISSION_CHANGED")
    if receipt["selected_cases"]!=start["selected_cases"] or [x["case"] for x in receipt["cases"]]!=start["selected_cases"]:
        raise ValueError("CASE_RECTANGLE_CHANGED")
    for case in receipt["cases"]:
        identity=case["case"]
        if case.get("expectations_executed"):
            saved=parse((output/"cases"/identity/"RESULT.json").read_bytes())
            if saved!=case or any(x["status"]!="PASS" or x["actual"]!=x["expected"] for x in case["checks"]):
                raise ValueError("CASE_ASSERTIONS_CHANGED")
            if identity in ("R01","R02","R03","R04","R05","R06"):
                process=output/"cases"/identity/"processes/killed"
                checkpoint=parse((process/"checkpoint.json").read_bytes())
                command=parse((process/"command.json").read_bytes())
                if (command["pid"]!=checkpoint["pid"] or command["exit_code"]==0
                        or command.get("termination",{}).get("method")!="Popen.terminate"
                        or command["termination"]["child_pid"]!=command["pid"]
                        or command["termination"]["poll_before"] is not None):
                    raise ValueError("LIVE_PROCESS_TERMINATION_NOT_ESTABLISHED")
            for view_name in ("before-kill.json","before-retry.json","after-restart.json","after-retry.json","after-disconnect.json"):
                path=output/"cases"/identity/view_name
                if path.exists():
                    rows=parse(path.read_bytes())["events"]
                    if len({(x["kind"],x["key"]) for x in rows})!=len(rows) or any(digest(x["payload"])!=x["sha256"] for x in rows):
                        raise ValueError("SAVED_LEDGER_ROW_INVALID")
        if identity in ("R03","R04") and case.get("expectations_executed"):
            after=parse((output/"cases"/identity/"after-restart.json").read_bytes())
            publications=[x["payload"] for x in after["events"] if x["kind"]=="workflow_publish"]
            if len(publications)!=1: raise ValueError("PUBLICATION_COUNT_CHANGED")
            pub=publications[0]
            outbox=next(x["payload"] for x in after["events"] if x["kind"]=="outbox" and x["key"]==pub["outbox_id"])
            equality=digest(pub["report"])==outbox["report_sha256"]
            if equality!=(identity=="R04"):
                raise ValueError("BASELINE_FAILURE_OR_REPAIR_CONSISTENCY_CHANGED")
            if identity=="R03" and case["status"]!="FAIL_BASELINE_MAPPING":
                raise ValueError("BASELINE_FAILURE_HIDDEN")
    return dict(status="VERIFIED_LOCAL_ARTIFACTS_AND_SAVED_CONSISTENCY",files=len(files),selected_cases=receipt["selected_cases"],
                execution_status=receipt["status"],source_reexecuted=False,sqlite_opened=False,
                external_timestamp_custody=False,formal_A=0,decision="NO_EDGE",qualified_prospective_samples=0)
