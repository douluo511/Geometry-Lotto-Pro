"""Execute real process faults against new synthetic state, never production data."""
from __future__ import annotations
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time

from research.ssq_dlt_v45.store import canonical, digest, parse, Store
from research.ssq_dlt_v45 import workflow as old_workflow

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]
NOW = datetime(2000, 2, 7, 7, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=30)
ADDRESS = "synthetic@example.invalid"


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources_manifest():
    frozen = parse((PACKAGE / "frozen-source-sha256.json").read_bytes())
    files = {}
    for name, expected in frozen.items():
        actual = file_sha(REPO / name)
        if actual != expected:
            raise ValueError("FROZEN_SOURCE_CHANGED:" + name)
        files[name] = actual
    for path in PACKAGE.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            files[path.relative_to(REPO).as_posix()] = file_sha(path)
    workflow = REPO / ".github/workflows/ssq-dlt-process-recovery.yml"
    if workflow.is_file():
        files[workflow.relative_to(REPO).as_posix()] = file_sha(workflow)
    # Filesystem traversal order varies between checkout and ZIP extraction.
    # Keep the recorded bytes reproducible across the independent executions.
    return dict(sorted(files.items()))


def setup_case(directory, identity, *, workflow=False):
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "_CASE.json", dict(schema="v45-process-fault-case-v1", scope="SYNTHETIC_ONLY", case=identity))
    config = dict(state_dir=str(directory / "state"), live_sources=False, preview=True,
                  recipient=ADDRESS, smtp=None, history={})
    for game in ("SSQ", "DLT"):
        rows = []
        for i in range(6):
            front_count, upper = (6, 33) if game == "SSQ" else (5, 35)
            front = sorted(1 + (i * 3 + j * 5) % upper for j in range(front_count))
            back = [1+i] if game == "SSQ" else [1+i, 7+i]
            rows.append(dict(issue=("2000" if game == "SSQ" else "00") + f"{i+1:03d}",
                             draw_date=(date(2000, 1, 1) + timedelta(days=i)).isoformat(), front=front, back=back))
        path = directory / (game + ".json")
        write(path, dict(game=game, draws=rows, fixture_scope="INVENTED_SYNTHETIC_HISTORY_NOT_OFFICIAL"))
        config["history"][game] = dict(path=str(path), sha256=file_sha(path))
    write(directory / "config.json", config)
    report = dict(schema="GLP_V45_RESEARCH_REPORT_1", due_slot=old_workflow.active_slot(NOW).isoformat(),
                  created_at=NOW.isoformat(), scope="SYNTHETIC_ONLY", games={}, blockers=["SYNTHETIC_NOT_OFFICIAL"],
                  formal_A=0, decision="NO_EDGE")
    write(directory / "input-report.json", report)
    if workflow:
        # Explicitly injected prerequisite; the discovery adapter is not exercised.
        slot = old_workflow.active_slot(NOW).isoformat()
        store = Store(directory / "state/workflow.sqlite3")
        store.append("workflow_stage", slot + "/discover", dict(due_slot=slot, stage="discover",
                     scheduled_at=NOW.isoformat(), observed_at=NOW.isoformat(), backdated=False,
                     result=dict(status="DEGRADED", scope="SYNTHETIC_OFFLINE_DISCOVERY_STUB_NOT_LIVE")))
    return config


def snapshot(database):
    if not database.exists():
        return dict(exists=False, events=[], integrity="NOT_RUN_NO_DATABASE")
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        events = []
        for kind, key, payload, checksum in db.execute("SELECT kind,key,payload,sha256 FROM events ORDER BY kind,key"):
            value = Store.checked((payload, checksum))
            events.append(dict(kind=kind, key=key, sha256=checksum, payload=value))
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    return dict(exists=True, events=events, integrity=integrity)


def kind(view, name):
    return [row for row in view["events"] if row["kind"] == name]


class Child:
    """Capture a worker, require its real checkpoint, terminate only this child."""
    def __init__(self, root, operation, label, *, pause="none", now=NOW, env=None):
        self.root, self.operation, self.pause = root, operation, pause
        self.folder = root / "processes" / label
        self.folder.mkdir(parents=True, exist_ok=False)
        # On Windows the venv redirector can spawn a distinct worker PID. Use the
        # actual base interpreter for stdlib-only workers so Popen owns that PID.
        executable=getattr(sys,"_base_executable",sys.executable)
        self.argv = [executable, "-m", "research.ssq_dlt_process_faults.worker", "--root", str(root),
                     "--operation", operation, "--now", now.isoformat(), "--pause", pause]
        child_env = os.environ.copy()
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        child_env.update(env or {})
        self.stdout = (self.folder / "stdout.log").open("xb")
        self.stderr = (self.folder / "stderr.log").open("xb")
        self.started = datetime.now(timezone.utc).isoformat()
        self.process = subprocess.Popen(self.argv, cwd=REPO, env=child_env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.stderr)
        self.messages = queue.Queue()
        self.lines = []
        self.termination = None
        self.closed = False
        def pump():
            try:
                for line in iter(self.process.stdout.readline, b""):
                    self.stdout.write(line); self.stdout.flush()
                    self.lines.append(line)
                    self.messages.put(line)
            finally:
                self.messages.put(None)
        self.reader = threading.Thread(target=pump, daemon=True)
        self.reader.start()

    def ready(self, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self.messages.get(timeout=max(.001, deadline-time.monotonic()))
            except queue.Empty:
                raise TimeoutError("WORKER_CHECKPOINT_NOT_REACHED")
            if line is None:
                raise RuntimeError("WORKER_EXITED_BEFORE_CHECKPOINT")
            value = parse(line)
            if value.get("event") == "ERROR":
                raise RuntimeError("WORKER_ERROR:" + str(value))
            if value.get("event") == "READY":
                if value["phase"] != self.pause or value["pid"] != self.process.pid or self.process.poll() is not None:
                    raise ValueError("CHECKPOINT_IDENTITY_OR_LIVENESS_MISMATCH")
                write(self.folder / "checkpoint.json", value)
                return value

    def terminate_at_checkpoint(self):
        if self.process.poll() is not None:
            raise RuntimeError("CHILD_ALREADY_TERMINAL_NOT_A_FAULT_INJECTION")
        self.termination = dict(method="Popen.terminate", child_pid=self.process.pid,
                                poll_before=None, requested_at_local=datetime.now(timezone.utc).isoformat())
        self.process.terminate()
        return self.finish(expected_kill=True)

    def finish(self, expected_kill=False):
        if self.closed:
            raise RuntimeError("CHILD_RECEIPT_ALREADY_FINAL")
        try:
            code = self.process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            self.process.kill(); code = self.process.wait(timeout=5)
            self.termination = dict(method="TIMEOUT_FORCED_KILL_NOT_SUCCESSFUL_SCENARIO", child_pid=self.process.pid)
        self.reader.join(timeout=5)
        self.process.stdin.close(); self.process.stdout.close()
        self.stdout.close(); self.stderr.close(); self.closed=True
        receipt = dict(argv=self.argv, pid=self.process.pid, started_at_local=self.started,
                       finished_at_local=datetime.now(timezone.utc).isoformat(), exit_code=code,
                       termination=self.termination, checkpoint_requested=self.pause,
                       stdout_sha256=file_sha(self.folder / "stdout.log"), stderr_sha256=file_sha(self.folder / "stderr.log"))
        write(self.folder / "command.json", receipt)
        if expected_kill:
            if code == 0 or self.termination["method"] != "Popen.terminate":
                raise RuntimeError("FAULT_DID_NOT_TERMINATE_LIVE_CHILD")
            return receipt
        if code != 0 or self.termination is not None:
            raise RuntimeError("CHILD_DID_NOT_COMPLETE:" + str(self.folder))
        results = [parse(x) for x in self.lines if parse(x).get("event") == "RESULT"]
        if len(results) != 1:
            raise RuntimeError("ONE_WORKER_RESULT_REQUIRED")
        return results[0]

    def abort(self):
        if not self.closed:
            if self.process.poll() is None:
                self.process.terminate()
            try: self.finish(expected_kill=True)
            except Exception: pass


def completed(root, operation, label, **kwargs):
    child = Child(root, operation, label, **kwargs)
    try: return child.finish()
    finally: child.abort()


def check(items, name, actual, expected):
    result = actual == expected
    items.append(dict(name=name, actual=actual, expected=expected, status="PASS" if result else "FAIL"))
    if not result:
        raise AssertionError(name)


class Assertions(list):
    def __init__(self, path):
        super().__init__()
        self.path=path
        with path.open("x",encoding="utf-8"): pass

    def append(self, value):
        super().append(value)
        with self.path.open("a",encoding="utf-8",newline="\n") as stream:
            stream.write(json.dumps(value,ensure_ascii=False,default=str)+"\n")
            stream.flush();os.fsync(stream.fileno())


def save_view(root, name, database):
    value = snapshot(database)
    write(root / (name + ".json"), value)
    return value


def run_case(root, identity):
    config = setup_case(root, identity, workflow=identity in ("R03", "R04"))
    checks = Assertions(root/"assertions.jsonl")
    db = root / "state/research.sqlite3"
    info = {}
    if identity == "R00":
        first = completed(root, "runtime", "first")
        before = save_view(root, "before-retry", db)
        second = completed(root, "runtime", "retry", now=LATER)
        after = save_view(root, "after-retry", db)
        check(checks, "one-cycle", len(kind(after,"cycle")), 1)
        check(checks, "cycle-immutable", kind(before,"cycle"), kind(after,"cycle"))
        check(checks, "restart-reused", second["receipt"]["reused"], True)
        check(checks, "report-hash-stable", first["report_sha256"], second["report_sha256"])
    elif identity == "R01":
        child = Child(root, "runtime", "killed", pause="cycle_committed")
        try:
            child.ready()
            before = save_view(root,"before-kill",db)
            check(checks,"cycle-committed-before-kill",len(kind(before,"cycle")),1)
            check(checks,"report-not-yet-materialized",(root/"state/reports").exists(),False)
            child.terminate_at_checkpoint()
        finally: child.abort()
        second = completed(root,"runtime","restart",now=LATER)
        after = save_view(root,"after-restart",db)
        check(checks,"cycle-bytes-logically-unchanged",kind(before,"cycle"),kind(after,"cycle"))
        check(checks,"restart-reused",second["receipt"]["reused"],True)
        check(checks,"materialized-original-report",file_sha(Path(second["receipt"]["report_directory"])/"report.json"),
              hashlib.sha256(canonical(kind(before,"cycle")[0]["payload"]).encode()).hexdigest())
    elif identity == "R02":
        child = Child(root,"prepare","killed",pause="outbox_committed")
        try:
            child.ready(); before=save_view(root,"before-kill",db)
            check(checks,"one-committed-outbox",len(kind(before,"outbox")),1)
            check(checks,"eml-not-yet-created",list((root/"state").glob("outbox/*.eml")),[])
            child.terminate_at_checkpoint()
        finally: child.abort()
        completed(root,"prepare","restart")
        after=save_view(root,"after-restart",db)
        check(checks,"outbox-unchanged",kind(before,"outbox"),kind(after,"outbox"))
        check(checks,"one-eml-materialized",len(list((root/"state").glob("outbox/*.eml"))),1)
    elif identity in ("R03","R04"):
        db=root/"state/workflow.sqlite3"
        op="workflow-old" if identity=="R03" else "workflow-new"
        child=Child(root,op,"killed",pause="outbox_committed")
        try:
            child.ready(); before=save_view(root,"before-kill",db)
            check(checks,"outbox-before-publication",len(kind(before,"outbox")),1)
            check(checks,"no-publication-before-kill",len(kind(before,"workflow_publish")),0)
            check(checks,"durable-intent-count",len(kind(before,"workflow_publish_intent")),int(identity=="R04"))
            child.terminate_at_checkpoint()
        finally: child.abort()
        completed(root,op,"restart",now=LATER)
        after=save_view(root,"after-restart",db)
        check(checks,"one-publication-after-restart",len(kind(after,"workflow_publish")),1)
        publication=kind(after,"workflow_publish")[0]["payload"]
        outbox=next(x["payload"] for x in kind(after,"outbox") if x["key"]==publication["outbox_id"])
        mapping=outbox["report_sha256"]==digest(publication["report"])
        check(checks,"hash-mapping-predicted-repair-comparison",mapping,identity=="R04")
        info.update(publication_report_sha256=digest(publication["report"]),outbox_report_sha256=outbox["report_sha256"],
                    publication_mapping_status="PASS" if mapping else "FAIL_MAPPING_INCONSISTENCY_OBSERVED")
        check(checks,"publication-artifact-matches-publish-record",
              file_sha(Path(publication["report_directory"])/"report.json"),digest(publication["report"]))
        check(checks,"first-outbox-immutable",kind(before,"outbox"),kind(after,"outbox"))
    else:
        from .smtp_fixture import LoopbackSMTP
        completed(root,"prepare","prepare")
        mode="disconnect_after_data" if identity=="R07" else "accept"
        with LoopbackSMTP(root/"loopback-smtp",mode) as server:
            # Worker reads this dedicated SMTP overlay; the canonical config stays immutable.
            write(root/"smtp-overlay.json",server.smtp_config)
            if identity in ("R05","R06"):
                phase="send_started_committed" if identity=="R05" else "sent_before_commit"
                child=Child(root,"flush","killed",pause=phase,env=server.child_env)
                try:
                    child.ready()
                    if identity=="R06": server.wait_for_ack()
                    before=save_view(root,"before-kill",db)
                    check(checks,"send-started-committed",len(kind(before,"send_started")),1)
                    check(checks,"no-sent-record-before-kill",len(kind(before,"sent")),0)
                    child.terminate_at_checkpoint()
                finally: child.abort()
            else:
                first=completed(root,"flush","disconnected",env=server.child_env)
                server.wait_for_data()
                check(checks,"disconnect-yields-unknown",[x["status"] for x in first["mail"]],["UNKNOWN_REQUIRES_RECONCILIATION"])
                before=save_view(root,"after-disconnect",db)
            baseline_stats=server.stats
            retry=completed(root,"flush","restart",env=server.child_env)
            after=save_view(root,"after-restart",db)
            check(checks,"restart-remains-unknown",[x["status"] for x in retry["mail"]],["UNKNOWN_REQUIRES_RECONCILIATION"])
            check(checks,"retry-does-not-open-connection",server.stats["connections"],baseline_stats["connections"])
            check(checks,"one-initial-connection",server.stats["connections"],1)
            check(checks,"expected-receiver-data-count",server.stats["data_transactions"],0 if identity=="R05" else 1)
            check(checks,"expected-250-count",server.stats["acknowledgements"],int(identity=="R06"))
            check(checks,"still-no-sent-receipt",len(kind(after,"sent")),0)
            check(checks,"outbox-unchanged",kind(before,"outbox"),kind(after,"outbox"))
            if identity!="R05":
                data=(root/"loopback-smtp/received-0001.eml").read_bytes()
                check(checks,"receiver-bytes-match-receiver-receipt",hashlib.sha256(data).hexdigest(),server.receipts[0].data_sha256)
                message=BytesParser(policy=policy.default).parsebytes(data)
                item=kind(after,"outbox")[0]["payload"]
                check(checks,"receiver-message-id-bound-to-outbox",str(message["Message-ID"]).strip(),f"<{item['id']}@glp.local>")
                check(checks,"receiver-recipient-is-synthetic",str(message["To"]),ADDRESS)
                check(checks,"receiver-subject-bound-to-outbox",str(message["Subject"]),item["subject"])
                body=message.get_body(preferencelist=("html",)).get_content()
                check(checks,"receiver-html-bound-to-first-outbox",body.rstrip("\r\n"),item["html"].rstrip("\r\n"))
            info.update(smtp_stats=server.stats,delivery_status="UNKNOWN_REQUIRES_RECONCILIATION",
                        inbox_delivery="NOT_VERIFIED",external_smtp_used=False,
                        possible_unsent_message_held=identity=="R05")
        write(root/"receiver-summary.json",dict(stats=server.stats,receipts=[asdict(x) for x in server.receipts],
                                               listener_stopped=not server.is_running))
    final=snapshot(db)
    check(checks,"sqlite-integrity-check",final["integrity"],"ok")
    status="FAIL_BASELINE_MAPPING" if identity=="R03" else "PASS_NARROW_FAULT_CONTRACT"
    result=dict(case=identity,status=status,expectations_executed=True,checks=checks,scope="SYNTHETIC_PROCESS_FAULT_ONLY",
                formal_A=0,decision="NO_EDGE",qualified_prospective_samples=0,**info)
    write(root/"RESULT.json",result)
    return result


def execute(output, cases=None):
    output=Path(output)
    if not output.is_absolute(): raise ValueError("ABSOLUTE_NEW_OUTPUT_REQUIRED")
    output=output.resolve()
    if output.is_relative_to(REPO) or REPO.is_relative_to(output): raise ValueError("OUTPUT_MUST_BE_SEPARATE_FROM_SOURCE")
    protocol=parse((PACKAGE/"protocol.json").read_bytes())
    allowed=[x["id"] for x in protocol["cases"]]
    selected=allowed if cases is None else cases
    if not selected or len(set(selected))!=len(selected) or any(x not in allowed for x in selected):
        raise ValueError("INVALID_CASE_SELECTION")
    before=sources_manifest()
    output.mkdir(parents=True,exist_ok=False)
    write(output/"STARTED.json",dict(schema="v45-process-recovery-run-v1",started_at_local=datetime.now(timezone.utc).isoformat(),
          protocol_sha256=file_sha(PACKAGE/"protocol.json"),source_manifest=before,selected_cases=selected,
          physical_power_test=False,external_network=False,formal_A=0,decision="NO_EDGE",qualified_prospective_samples=0))
    results=[]
    for identity in selected:
        root=output/"cases"/identity
        try: results.append(run_case(root,identity))
        except Exception as error:
            from .smtp_fixture import FixtureBlocked
            status="BLOCKED" if isinstance(error,FixtureBlocked) else "FAIL_HARNESS_OR_EXPECTATION"
            failure=dict(case=identity,status=status,error_type=type(error).__name__,error=str(error),formal_A=0,decision="NO_EDGE")
            if not root.exists(): root.mkdir(parents=True)
            write(root/"FAILURE.json",failure);results.append(failure)
    unchanged=before==sources_manifest()
    all_executed=all(x.get("expectations_executed") for x in results)
    baseline_failed=any(x["case"]=="R03" and x["status"]=="FAIL_BASELINE_MAPPING" for x in results)
    complete_status="DIAGNOSTIC_COMPLETE_WITH_BASELINE_FAIL" if baseline_failed else "DIAGNOSTIC_COMPLETE_PARTIAL_SCOPE"
    receipt=dict(schema="v45-process-recovery-run-v1",
                 status=complete_status if all_executed and unchanged else "INCOMPLETE_OR_FAILED",
                 cases=results,selected_cases=selected,all_registered_cases_run=selected==allowed,
                 source_unchanged=unchanged,baseline_failure_preserved=baseline_failed,formal_A=0,decision="NO_EDGE",qualified_prospective_samples=0,
                 full_physical_p0="NOT_RUN",actual_scheduler="NOT_RUN",real_inbox_delivery="NOT_RUN",
                 note="Expected baseline defect remains a FAIL; diagnostic completion is not production success")
    write(output/"RECEIPT.json",receipt)
    manifest={p.relative_to(output).as_posix():dict(bytes=p.stat().st_size,sha256=file_sha(p))
              for p in output.rglob("*") if p.is_file()}
    write(output/"SHA256.json",dict(files=manifest,self_excluded=True))
    return receipt
