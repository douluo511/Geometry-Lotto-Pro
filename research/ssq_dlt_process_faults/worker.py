"""Real child-process entry point, confined to one marked synthetic case.

The append observer only waits before or after the original append.  The
parent owns process termination; this worker never simulates a crash.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ADDRESS = "synthetic@example.invalid"
PASSWORD_ENV = "GLP_SYNTHETIC_SMTP_PASSWORD"
PHASE_KINDS = {
    "cycle_committed": "cycle",
    "outbox_committed": "outbox",
    "send_started_committed": "send_started",
    "sent_before_commit": "sent",
}


def emit(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False), flush=True)


def read_json(path):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("DUPLICATE_JSON_KEY")
            value[key] = item
        return value

    def reject_constant(_):
        raise ValueError("NONFINITE_JSON")

    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=reject_constant)


def confined(root, value, *, absolute=True):
    path = Path(value)
    if absolute and not path.is_absolute():
        raise ValueError("ABSOLUTE_SYNTHETIC_PATH_REQUIRED")
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("PATH_OUTSIDE_SYNTHETIC_CASE")
    return resolved


def validate_case(root_argument):
    if not root_argument.is_absolute():
        raise ValueError("ABSOLUTE_CASE_ROOT_REQUIRED")
    root = root_argument.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("SYNTHETIC_CASE_DIRECTORY_REQUIRED")
    marker_path = confined(root, root / "_CASE.json")
    marker = read_json(marker_path)
    if (type(marker) is not dict
            or set(marker) != {"schema", "scope", "case"}
            or marker["schema"] != "v45-process-fault-case-v1"
            or marker["scope"] != "SYNTHETIC_ONLY"
            or type(marker["case"]) is not str
            or not re.fullmatch(r"R[0-9]{2}", marker["case"])):
        raise ValueError("INVALID_SYNTHETIC_CASE_MARKER")
    config = read_json(confined(root, root / "config.json"))
    if type(config) is not dict:
        raise ValueError("SYNTHETIC_CONFIG_OBJECT_REQUIRED")
    # Caller booleans cannot establish authority, even when set to false.
    forbidden = {"target", "targets", "official_target", "formal", "authorized",
                 "tsa", "tsa_verified", "formal_A"}
    if forbidden.intersection(config):
        raise ValueError("TARGET_OR_AUTHORIZATION_FIELDS_FORBIDDEN")
    state = confined(root, config.get("state_dir", ""))
    if state != root / "state":
        raise ValueError("EXACT_SYNTHETIC_STATE_DIRECTORY_REQUIRED")
    if config.get("live_sources") is not False:
        raise ValueError("LIVE_SOURCES_FORBIDDEN")
    if config.get("recipient") != ADDRESS:
        raise ValueError("SYNTHETIC_RECIPIENT_REQUIRED")
    history = config.get("history")
    if type(history) is not dict or set(history) != {"SSQ", "DLT"}:
        raise ValueError("BOTH_SYNTHETIC_HISTORIES_REQUIRED")
    for game, spec in history.items():
        if type(spec) is not dict or set(spec) != {"path", "sha256"}:
            raise ValueError("INVALID_SYNTHETIC_HISTORY_SPEC")
        path = confined(root, spec["path"])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise ValueError("SYNTHETIC_HISTORY_SHA_MISMATCH")
        document = read_json(path)
        if (type(document) is not dict or document.get("game") != game
                or document.get("fixture_scope") != "INVENTED_SYNTHETIC_HISTORY_NOT_OFFICIAL"):
            raise ValueError("EXPLICIT_SYNTHETIC_HISTORY_MARKER_REQUIRED")
    overlay = confined(root, root / "smtp-overlay.json")
    if overlay.exists():
        config = {**config, "smtp": read_json(overlay)}
    smtp = config.get("smtp")
    if smtp is not None:
        expected = dict(host="127.0.0.1", port=587, sender=ADDRESS,
                        username="synthetic", password_env=PASSWORD_ENV)
        if type(smtp) is not dict or smtp != expected or type(smtp["port"]) is not int:
            raise ValueError("EXACT_LOOPBACK_SYNTHETIC_SMTP_REQUIRED")
        credential = os.environ.get(PASSWORD_ENV)
        if credential is not None and credential != "SYNTHETIC_ONLY":
            raise ValueError("ONLY_SYNTHETIC_SMTP_CREDENTIAL_ALLOWED")
        trust = os.environ.get("SSL_CERT_FILE")
        if trust:
            confined(root, trust)
    for name in ("research.sqlite3", "workflow.sqlite3"):
        candidate = confined(root, state / name)
        if candidate.parent != state:
            raise ValueError("SYNTHETIC_DATABASE_PATH_REQUIRED")
    return root, marker, config


def install_guards(root):
    """Refuse unmarked databases or external sockets in imported real code."""
    allowed = {root / "state" / name for name in ("research.sqlite3", "workflow.sqlite3")}

    def audit(event, arguments):
        if event == "sqlite3.connect":
            raw = os.fsdecode(arguments[0])
            if raw.startswith("file:"):
                parsed = urlsplit(raw)
                if parsed.netloc not in ("", "localhost"):
                    raise ValueError("EXTERNAL_SQLITE_FORBIDDEN")
                raw = unquote(parsed.path)
                if os.name == "nt" and re.match(r"^/[A-Za-z]:/", raw):
                    raw = raw[1:]
            if Path(raw).resolve() not in allowed:
                raise ValueError("ONLY_CASE_SYNTHETIC_SQLITE_ALLOWED")
        elif event == "socket.connect":
            endpoint = arguments[1]
            if (not isinstance(endpoint, tuple) or len(endpoint) != 2
                    or endpoint != ("127.0.0.1", 587)):
                raise ValueError("ONLY_SYNTHETIC_LOOPBACK_SMTP_ALLOWED")

    sys.addaudithook(audit)


def worker_info(now):
    modules = {}
    for name, module in sorted(sys.modules.copy().items()):
        if not name.startswith(("research.ssq_dlt_v45", "research.ssq_dlt_d2_v44",
                                "research.ssq_dlt_process_faults")):
            continue
        filename = getattr(module, "__file__", None)
        if filename:
            path = Path(filename).resolve()
            if path.is_file():
                modules[name] = dict(file=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    path = Path(__file__).resolve()
    modules["research.ssq_dlt_process_faults.worker"] = dict(
        file=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return dict(python_version=sys.version, python_executable=sys.executable,
                modules=modules, clock_scope="SYNTHETIC_EXPLICIT_CLOCK_NOT_LIVE",
                synthetic_clock=True, now=now.isoformat() if now else None)


def observe_appends(Store, phase, marker, now):
    original = Store.append
    fired = False

    def ready(kind, key, returned):
        nonlocal fired
        fired = True
        emit(dict(event="READY", phase=phase, pid=os.getpid(), case=marker["case"],
                  kind=kind, key=key, append_return=returned, worker_info=worker_info(now)))
        # EOF is not an instruction to continue. A parent must write a line or
        # terminate this live child; process faults are never synthesized here.
        line = sys.stdin.readline()
        if not line:
            from threading import Event
            Event().wait()

    def observed(self, kind, key, payload):
        matches = not fired and PHASE_KINDS.get(phase) == kind
        if matches and phase == "sent_before_commit":
            ready(kind, key, None)
        returned = original(self, kind, key, payload)
        if matches and phase != "sent_before_commit":
            ready(kind, key, returned)
        return returned

    Store.append = observed


def snapshot_d2(report):
    return {
        game: {name: model["primary_d2"] for name, model in
               data.get("preview", {}).get("models", {}).items()}
        for game, data in report.get("games", {}).items()
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--operation", required=True,
                        choices=("runtime", "workflow-old", "workflow-new", "prepare", "flush"))
    parser.add_argument("--now")
    parser.add_argument("--pause", default="none", choices=("none", *PHASE_KINDS))
    args = parser.parse_args(argv)
    marker = {}
    try:
        root, marker, config = validate_case(args.root)
        now = datetime.fromisoformat(args.now) if args.now else None
        if now is not None and now.tzinfo is None:
            raise ValueError("AWARE_SYNTHETIC_CLOCK_REQUIRED")
        if args.operation in ("runtime", "workflow-old", "workflow-new") and now is None:
            raise ValueError("EXPLICIT_SYNTHETIC_CLOCK_REQUIRED")
        install_guards(root)
        from research.ssq_dlt_v45 import delivery, runtime
        from research.ssq_dlt_v45.store import Store, digest
        observe_appends(Store, args.pause, marker, now)
        value = dict(event="RESULT", case=marker["case"], operation=args.operation)
        if args.operation == "runtime":
            result = runtime.run(config, now=now)
            report = {key: item for key, item in result.items() if key != "run_receipt"}
            value.update(receipt=result["run_receipt"], report_sha256=digest(report),
                         primary_d2=snapshot_d2(report))
        elif args.operation.startswith("workflow-"):
            module = ("research.ssq_dlt_v45.workflow" if args.operation == "workflow-old"
                      else "research.ssq_dlt_process_faults.workflow_recovery")
            workflow = importlib.import_module(module)
            # Never invoke discovery: the parent must seed the explicit offline
            # prerequisite in this case's own workflow ledger.
            store = Store(root / "state" / "workflow.sqlite3")
            prerequisite = store.read("workflow_stage", workflow.active_slot(now).isoformat() + "/discover")
            if (not prerequisite or prerequisite.get("stage") != "discover"
                    or "SYNTHETIC" not in str(prerequisite.get("result", {}).get("scope", ""))):
                raise ValueError("SYNTHETIC_OFFLINE_DISCOVERY_PREREQUISITE_REQUIRED")
            value["receipt"] = workflow.tick(config, now=now)
        elif args.operation == "prepare":
            report = read_json(confined(root, root / "input-report.json"))
            if type(report) is not dict or report.get("scope") != "SYNTHETIC_ONLY":
                raise ValueError("SYNTHETIC_INPUT_REPORT_REQUIRED")
            store = Store(root / "state" / "research.sqlite3")
            value["id"] = delivery.prepare(store, root / "state" / "outbox", ADDRESS,
                                            report, runtime.render(report))
        else:
            store = Store(root / "state" / "research.sqlite3")
            value["mail"] = delivery.flush(store, config.get("smtp"))
        value["worker_info"] = worker_info(now)
        emit(value)
        return 0
    except Exception as exc:
        emit(dict(event="ERROR", operation=args.operation, case=marker.get("case"),
                  error=type(exc).__name__, reason=str(exc), pid=os.getpid()))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
