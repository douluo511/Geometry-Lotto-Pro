"""Local operator view of the existing V4.7 loop, never another forecaster.

Opening/refreshing reads only. The explicit action buttons retain process bytes
before interpreting them; native widgets are loaded only when requested.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
import locale
import math
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import uuid

from . import closed_loop
from .core import GateError

ROOT = Path(__file__).resolve().parents[2]
TASK_NAME = "SSQDLT-V47-CLOSED-LOOP-SHADOW"
TICK_ID = re.compile(r"V47T-[0-9a-f]{32}\Z")
SID = re.compile(r"S-1-\d+(?:-\d+){1,15}\Z", re.IGNORECASE)


def _gates():
    return {"formal_A": 0, "decision": "NO_EDGE",
            "formal_future_denominator": "NOT_VERIFIED",
            "formal_K": "NOT_VERIFIED", "formal_N": "NOT_VERIFIED",
            "formal_CI": "NOT_VERIFIED", "formal_tests": "NOT_VERIFIED",
            "controller_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "runner_source_sha256": hashlib.sha256(Path(closed_loop.__file__).read_bytes()).hexdigest()}


def _path(value, *, base=None):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise GateError("DESKTOP_REQUIRED_PATH_INVALID")
    raw = Path(value)
    # Check lexical custody BEFORE resolving; resolve would hide ../ and links.
    closed_loop._not_symlink(raw)
    joined = (base / raw if base is not None and not raw.is_absolute() else raw)
    closed_loop._not_symlink(joined)
    return joined.resolve()


def _write_bytes(path, raw):
    closed_loop._not_symlink(path)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_json(path, value):
    _write_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 indent=2, allow_nan=False) + "\n").encode("utf-8"))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _bytes(value):
    return value.encode("utf-8") if isinstance(value, str) else value or b""


def _validate_tick(value, expected_tick=None):
    if not isinstance(value, dict):
        raise GateError("DESKTOP_TICK_RESULT_NOT_OBJECT")
    tick = value.get("tick_id")
    games = value.get("games")
    if (value.get("schema") != "V47-OPERATIONAL-TICK-SHADOW-1"
            or not isinstance(tick, str) or not TICK_ID.fullmatch(tick)
            or expected_tick is not None and tick != expected_tick
            or type(value.get("formal_A")) is not int or value["formal_A"] != 0
            or value.get("decision") != "NO_EDGE"
            or not isinstance(games, dict) or set(games) != {"SSQ", "DLT"}):
        raise GateError("DESKTOP_TICK_SCHEMA_OR_IDENTITY_INVALID")
    for game, state in games.items():
        if (not isinstance(state, dict)
                or not isinstance(state.get("target_gate"), str)
                or not isinstance(state.get("source_status"), str)
                or not isinstance(state.get("scoring"), dict)
                or not isinstance(state["scoring"].get("status"), str)
                or any(key in state and state[key] != game for key in ("game", "lottery"))
                or "formal_A" in state and (type(state["formal_A"]) is not int
                                             or state["formal_A"] != 0)
                or "decision" in state and state["decision"] != "NO_EDGE"):
            raise GateError("DESKTOP_TICK_GAME_RESULT_INVALID:" + game)
    return value


class DesktopController:
    def __init__(self, config_file, reports=(), owner_sid=None):
        self.config_file = _path(config_file)
        cfg = closed_loop._read_json(self.config_file)
        if not isinstance(cfg, dict) or cfg.get("operational_tick") is not True:
            raise GateError("DESKTOP_REQUIRES_EXACT_OPERATIONAL_MODE")
        if any(key in cfg for key in ("snapshot_bundle", "research_history_bundle",
                                      "ssq_snapshot_bundle", "dlt_snapshot_bundle")):
            raise GateError("CLOSED_LOOP_OPERATIONAL_MODE_INPUTS_CONFLICT")
        self.repository = _path(cfg.get("repository_root"))
        if self.repository != ROOT or not (self.repository / "research" / "harness_v46"
                                           / "closed_loop.py").is_file():
            raise GateError("DESKTOP_REPOSITORY_ROOT_MISMATCH")
        self.python = _path(cfg.get("python_exe"), base=self.repository)
        self.workspace = _path(cfg.get("workspace"), base=self.repository)
        log = _path(cfg.get("log_path"), base=self.repository)
        if not self.python.is_file():
            raise GateError("DESKTOP_PYTHON_MISSING")
        if self.workspace.exists() and not self.workspace.is_dir():
            raise GateError("DESKTOP_WORKSPACE_NOT_DIRECTORY")
        if not log.parent.is_dir():
            raise GateError("CLOSED_LOOP_LOG_DIR_NOT_PRECREATED")
        seconds = cfg.get("intake_timeout_seconds", 45)
        if (type(seconds) not in (int, float) or not math.isfinite(seconds)
                or not 0 < seconds <= 120):
            raise GateError("CLOSED_LOOP_OPERATIONAL_TIMEOUT_INVALID")
        self.seconds = seconds
        self.snapshots = {}
        for game in ("SSQ", "DLT"):
            key = game.lower() + "_snapshot_path"
            if key in cfg:
                raw = cfg[key]
                if not isinstance(raw, str) or not raw.strip():
                    raise GateError("DESKTOP_EXPLICIT_SNAPSHOT_PATH_INVALID:" + game)
                if not _path(raw, base=self.repository).is_file():
                    raise GateError("DESKTOP_EXPLICIT_SNAPSHOT_FILE_MISSING:" + game)
                # The existing CLI resolves explicit relative paths in repo cwd.
                self.snapshots[game] = raw
        self.reports = tuple(reports)
        self.owner_sid = owner_sid
        self.config = cfg

    def read_status(self, progress=None):
        value = {**_gates(), "status": "MISSING", "latest_complete_tick": None,
                 "unfinished_tick_ids": [], "operational_attempt_count": 0}
        ledger = self.workspace / "ledger.sqlite3"
        try:
            closed_loop._not_symlink(ledger)
            if not ledger.exists():
                return value
            # SQLite's read-only WAL connections can still create -wal/-shm.
            # Refuse before opening SQLite; immutable would hide concurrent WAL
            # contents and could present an older tick as current.
            with ledger.open("rb") as stream:
                header = stream.read(20)
            if (header[18:20] == b"\x02\x02"
                    or Path(str(ledger) + "-wal").exists()
                    or Path(str(ledger) + "-shm").exists()):
                raise GateError("DESKTOP_READ_ONLY_WAL_UNSUPPORTED")
            conn = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                conn.execute("PRAGMA query_only=ON")
                conn.execute("BEGIN")
                unfinished, count = closed_loop._operational_check_journal(conn)
                row = conn.execute("SELECT tick_id,event_payload FROM operational_events "
                                   "WHERE event_type='FINISHED' ORDER BY event_id DESC LIMIT 1").fetchone()
                latest = None
                if row:
                    payload = json.loads(row[1])  # Strict canonical bytes checked above.
                    latest = _validate_tick(payload.get("result"), row[0])
                    states = conn.execute("SELECT lottery,event_payload FROM operational_events "
                                          "WHERE tick_id=? AND event_type='GAME_RESULT'",
                                          (row[0],)).fetchall()
                    for game, raw in states:
                        state = json.loads(raw).get("state")
                        if state is not None and state != latest["games"][game]:
                            raise GateError("DESKTOP_FINISHED_GAME_STATE_MISMATCH")
                value.update(status="READY", latest_complete_tick=latest,
                             unfinished_tick_ids=unfinished, operational_attempt_count=count)
            finally:
                conn.close()
        except (OSError, sqlite3.Error, GateError, ValueError, TypeError, KeyError) as exc:
            value.update(status="BLOCKED", latest_complete_tick=None,
                         error=f"{type(exc).__name__}: {exc}")
        return value

    def _new_receipt(self, kind, *, owner=False):
        parent = self.config_file.parent if owner else self.workspace / "operator_receipts"
        closed_loop._not_symlink(parent)
        parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        # Owner monitor discovery requires the dated capture name. Operator
        # folders keep UUID uniqueness without spending Windows path budget on
        # a second timestamp; exact start/end times are in their receipts.
        name = ("capture-" + stamp + "-" if owner else kind + "-") + uuid.uuid4().hex
        folder = parent / name
        folder.mkdir()
        return folder

    def _execute(self, command, folder, *, timeout):
        closed_loop._not_symlink(folder)
        folder.mkdir(parents=True, exist_ok=True)
        record = {"command": command, "cwd": str(self.repository),
                  "started_at": _now(), "returncode": None, "timed_out": False,
                  "receipt_dir": str(folder), **_gates()}
        stdout, stderr = b"", b""
        try:
            options = {"cwd": str(self.repository), "capture_output": True, "timeout": timeout}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.run(command, **options)
            stdout, stderr = _bytes(process.stdout), _bytes(process.stderr)
            record.update(returncode=process.returncode,
                          status="COMPLETED" if process.returncode == 0 else "FAILED")
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = _bytes(exc.stdout), _bytes(exc.stderr)
            record.update(status="TIMEOUT", timed_out=True, error=str(exc))
        except OSError as exc:
            record.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        record["finished_at"] = _now()
        # Retain original bytes and actual exit before any decoding or parsing.
        _write_bytes(folder / "stdout.bin", stdout)
        _write_bytes(folder / "stderr.bin", stderr)
        _write_json(folder / "receipt.json", record)
        return record

    def run_tick(self, progress=None):
        command = [str(self.python), "-m", "research.harness_v46.closed_loop",
                   "--workspace", str(self.workspace), "--operational-tick",
                   "--intake-timeout-seconds", format(self.seconds, "g")]
        for game, raw in self.snapshots.items():
            closed_loop._not_symlink(Path(raw))
            closed_loop._not_symlink(self.repository / raw)
            command += ["--" + game.lower() + "-snapshot-path", raw]
        folder = self._new_receipt("tick")
        if progress:
            progress("Running existing V4.7 loop; retaining process output.")
        record = self._execute(command, folder, timeout=580)
        if record["status"] == "COMPLETED":
            try:
                record["result"] = _validate_tick(closed_loop._read_json(folder / "stdout.bin"))
            except (GateError, OSError, ValueError, TypeError, KeyError) as exc:
                record.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        _write_json(folder / "result.json", record)
        return record

    def install_task(self, progress=None):
        diagnostic = self._new_receipt("install-identity")
        value = {**_gates(), "status": "REFUSED", "receipt_dir": str(diagnostic),
                 "host_acceptance": "NOT_VERIFIED", "task_query_status": "NOT_VERIFIED"}
        expected = self.owner_sid
        if not isinstance(expected, str) or not SID.fullmatch(expected):
            value["error"] = "DURABLE_OWNER_SID_REQUIRED"
        else:
            identity = self._execute(["whoami.exe" if os.name == "nt" else "whoami",
                                      "/user", "/fo", "csv", "/nh"],
                                     diagnostic / "identity", timeout=30)
            raw = (diagnostic / "identity" / "stdout.bin").read_bytes()
            rows = list(csv.reader(io.StringIO(raw.decode(locale.getpreferredencoding(False),
                                                          errors="replace"))))
            accounts = [(row[0], row[-1].strip()) for row in rows
                        if len(row) >= 2 and SID.fullmatch(row[-1].strip())]
            if (identity["status"] != "COMPLETED" or len(accounts) != 1
                    or accounts[0][1].upper() != expected.upper()
                    or "codexsandbox" in accounts[0][0].lower()):
                value.update(error="ACTUAL_TOKEN_IS_NOT_DURABLE_OWNER", identity=identity)
            else:
                capture = self._new_receipt("install", owner=True)
                shutil.copytree(diagnostic / "identity", capture / "identity")
                command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                           str(ROOT / "research" / "harness_v46" / "windows_closed_loop_tasks.ps1"),
                           "-ConfigFile", str(self.config_file), "-Install"]
                if progress:
                    progress("Invoking original task installer as matched durable owner.")
                installed = self._execute(command, capture / "install", timeout=120)
                queries = []
                scripts = {
                    "task-xml": f"Export-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction Stop",
                    "task-info": (f"Get-ScheduledTaskInfo -TaskName '{TASK_NAME}' -ErrorAction Stop "
                                  "| Select-Object * | ConvertTo-Json -Depth 8")}
                for name, script in scripts.items():
                    queries.append(self._execute(["powershell.exe", "-NoProfile", "-NonInteractive",
                                                  "-Command", script], capture / name, timeout=30))
                value.update(status=installed["status"], receipt_dir=str(capture),
                             installation=installed, identity=identity, queries=queries,
                             task_query_status="CAPTURED" if all(q["status"] == "COMPLETED"
                                                               for q in queries) else "NOT_VERIFIED")
                _write_json(capture / "result.json", value)
        _write_json(diagnostic / "result.json", value)
        return value

    def research_status(self, progress=None):
        reports = []
        for raw in self.reports:
            item = {"path": str(raw)}
            try:
                path = _path(raw, base=self.repository)
                if path.suffix.lower() == ".json":
                    item["evidence"] = closed_loop._read_json(path)
                else:
                    with path.open("rb") as stream:
                        data = stream.read(closed_loop.MAX_JSON_BYTES + 1)
                    if len(data) > closed_loop.MAX_JSON_BYTES:
                        raise GateError("DESKTOP_RESEARCH_REPORT_TOO_LARGE")
                    item["text"] = data.decode("utf-8")
                item["status"] = "READ"
            except (OSError, GateError, ValueError) as exc:
                item.update(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
            reports.append(item)
        return {**_gates(), "status": "READ_ONLY", "reports": reports,
                "evidence_note": "Existing evidence tiers retained; no new formal admission."}


class _InertAdapter:
    """Truthy constructor adapters prevent legacy service/updater creation."""
    def unavailable(self, *args, **kwargs):
        raise RuntimeError("Legacy DLT callback is disabled in the V4.7 operator window")
    predict = audit = update = repair = unavailable


def _native_widgets():
    if os.name != "nt":
        raise RuntimeError("Native Win32 GUI requires Windows")
    namespace = "_v47_desktop_widgets_" + uuid.uuid5(uuid.NAMESPACE_URL, str(ROOT)).hex
    if namespace + ".gui" not in sys.modules:
        package = types.ModuleType(namespace)
        package.__path__ = [str(ROOT / "DLT" / "src" / "glp")]
        sys.modules[namespace] = package
        # The widget module needs these names at definition time. Supplying inert
        # private modules avoids importing the legacy predictor/updater at all.
        for suffix, name in (("service", "LottoService"), ("delivery", "UpdaterClient")):
            module = types.ModuleType(namespace + "." + suffix)
            setattr(module, name, _InertAdapter)
            sys.modules[module.__name__] = module
        importlib.import_module(namespace + ".gui")
    return sys.modules[namespace + ".gui"]


def build_window(controller):
    widgets = _native_widgets()

    class OperatorWindow(widgets.NativeApp):
        @property
        def class_name(self):
            return self._operator_class_name

        @class_name.setter
        def class_name(self, ignored):
            # Each window owns its WNDPROC; never reuse the legacy registered class.
            self._operator_class_name = "SSQDLTV47Operator" + uuid.uuid4().hex

        def __init__(self):
            self.controller = controller
            self.close_requested = False
            self.worker = None
            super().__init__(service=_InertAdapter(), updater=_InertAdapter())
            self.renderers = {
                1001: ("�������бջ�", controller.run_tick, self._render),
                1002: ("ˢ��ֻ���˱�", controller.read_status, self._render),
                1003: ("��װԭ��ʱ���񲢱����ִ", controller.install_task, self._render),
                1004: ("�鿴�����о�֤��", controller.research_status, self._render)}
            try:
                self._set("output", self._render(controller.read_status()))
                self._set("status", "ֻ���˱������룻A=0 / NO_EDGE��δ�ɼ���װ����")
            except Exception as exc:
                self._show_failure(f"{type(exc).__name__}: {exc}")

        @staticmethod
        def _render(value):
            labels = {"MISSING": "���������˱�", "READY": "ֻ���˱��Ѷ�ȡ",
                      "COMPLETED": "������ɣ���鿴��Դ��Ŀ���Ž�", "FAILED": "����ʧ�ܣ��ѱ�����ִ",
                      "TIMEOUT": "������ʱ���ѱ����������", "REFUSED": "�����Ѿܾ�",
                      "BLOCKED": "������ϣ���鿴����", "READ_ONLY": "ֻ��֤����ͼ"}
            current = value.get("result") or value.get("latest_complete_tick") or {}
            attempts = value.get("operational_attempt_count", current.get("operational_attempt_count"))
            rows = ["SSQ + DLT V4.7������A=0 / NO_EDGE",
                    labels.get(value.get("status"), str(value.get("status", "״̬����ʵ"))),
                    "��ʽ D2 �����ʣ�NOT_VERIFIED��������ʽ K/N ֤�ݣ�",
                    "��ʽ K / N / �������� / ���飺NOT_VERIFIED",
                    "���س��Դ�����" + (str(attempts) if attempts is not None else "����ʵ") +
                    "�����Դ��������ڿ�����������ʽԤ���ĸ��"]
            games = current.get("games", {})
            if not games:
                rows.append("��������˫��Ϸ���н���������ƶ�δ���ںš���ֹʱ�����ա�")
            for game in ("SSQ", "DLT"):
                state = games.get(game)
                if state:
                    scoring = state.get("scoring", {})
                    rows += ["", ("˫ɫ�� SSQ" if game == "SSQ" else "����͸ DLT"),
                             "��Դ��" + str(state.get("source_status", "����ʵ")),
                             "Ŀ�꣺" + str(state.get("target_gate", "����ʵ")),
                             "���֣�" + str(scoring.get("status", "����ʵ")) +
                             (" / " + str(scoring["reason"]) if scoring.get("reason") else "")]
                    if state.get("source_errors"):
                        rows.append("��Դ��ϣ�" + json.dumps(state["source_errors"], ensure_ascii=False))
            if value.get("unfinished_tick_ids"):
                rows.append("δ��ɳ��ԣ�" + ", ".join(value["unfinished_tick_ids"]))
            if value.get("receipt_dir"):
                rows.append("��ִĿ¼��" + value["receipt_dir"])
            if value.get("error"):
                rows.append("ԭ��" + value["error"])
            rows += ["", "��Դ��ʵ����־��������գ�NOT_VERIFIED�����ݸ�ʽ��鲻������Դ��֤��"]
            for report in value.get("reports", []):
                rows += ["", "�о�֤�ݣ�" + report["path"]]
                if "text" in report:
                    rows.append(report["text"])
                elif "evidence" in report:
                    rows.append(json.dumps(report["evidence"], ensure_ascii=False, indent=2))
                else:
                    rows.append(report.get("error", "�޷���ȡ"))
            rows += ["", "���� ԭʼ����ֶ����ִ���� ����",
                     json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)]
            return "\n".join(rows)

        def _build_controls(self):
            self.user32.SetWindowTextW(self.hwnd, "SSQ + DLT V4.7 �� Local SHADOW")
            title = self._ctl("STATIC", "SSQ + DLT V4.7", 0, 28, 20, 680, 44)
            self.user32.SendMessageW(title, self.WM_SETFONT, self._font(26, 700), True)
            self.controls["badge"] = self._ctl("STATIC", "A=0 / NO_EDGE", 0, 850, 30, 220, 30)
            labels = ("�������бջ�", "ˢ���˱���ֻ����", "��װԭ��ʱ����", "�鿴�����о�֤��")
            for index, label in enumerate(labels):
                button = self._ctl("BUTTON", label, self.BS_PUSHBUTTON,
                                   28 + index % 2 * 264, 84 + index // 2 * 62,
                                   245, 52, 1001 + index)
                self.buttons.append(button)
                self.user32.SendMessageW(button, self.WM_SETFONT, self._font(16, 600), True)
            for name, text, x, y, width, height in (
                ("heading", "���� V4.7 ���� / ���ֱջ�", 560, 84, 500, 34),
                ("summary", "ȱ����ʽδ��Ŀ�����ʱ���������¶��ᡣ\n"
                 "��ʽ D2 ������ / K / N��NOT_VERIFIED", 560, 122, 510, 62),
                ("status", "����ֻ����ȡ�����˱���", 28, 640, 1040, 26),
                ("disclaimer", "SHADOW / ̽�����о������Դ�����������ʽԤ���ĸ��"
                 "�־��������գ�NOT_VERIFIED��", 28, 678, 1040, 24)):
                self.controls[name] = self._ctl("STATIC", text, 0, x, y, width, height)
            self.controls["output"] = self._ctl("EDIT", "", self.WS_VSCROLL |
                self.ES_MULTILINE | self.ES_AUTOVSCROLL | self.ES_READONLY, 28, 220, 1040, 405)
            self.user32.SendMessageW(self.controls["output"], self.WM_SETFONT,
                                     self._font(15, 400, "Consolas"), True)

        def _write_acceptance_result(self, *args, **kwargs):
            # This surface never writes the old DLT physical acceptance files.
            return None

        def _start(self, cid):
            if self.busy or self.close_requested or cid not in self.renderers:
                return
            title, action, renderer = self.renderers[cid]
            self.busy, self.active_cid = True, cid
            self._enable(False)
            self._set("heading", title)
            self._set("status", "����ִ�У��ȱ���ԭʼ������ִ���ٽ��ͽ����")

            def work():
                try:
                    result = action(lambda message: self.events.put(("progress", message)))
                    self.events.put(("done", (result, renderer)))
                except Exception as exc:
                    self.events.put(("error", f"{type(exc).__name__}: {exc}"))
            self.worker = threading.Thread(target=work, daemon=False, name="V47-operator-action")
            self.worker.start()

        def _drain(self):
            while True:
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "progress":
                    self._set("status", payload)
                else:
                    try:
                        if kind == "done":
                            result, renderer = payload
                            self._set("output", renderer(result))
                            self._set("status", str(result.get("status", "�Ѽ�¼")) +
                                      " �� A=0 / NO_EDGE����鿴�ѱ������Ž����顣")
                        else:
                            # A worker exception may mean receipt persistence
                            # failed. A previously queued close cannot acknowledge
                            # an error the operator has not yet seen.
                            self.close_requested = False
                            self._show_failure(payload)
                    except Exception as exc:
                        self.close_requested = False
                        self._show_failure(f"{type(exc).__name__}: {exc}")
                    finally:
                        self.busy, self.active_cid = False, None
                        self._enable(True)
            if self.close_requested and not self.busy and self.user32.IsWindow(self.hwnd):
                self.user32.DestroyWindow(self.hwnd)

        def _wndproc(self, hwnd, message, wparam, lparam):
            if message == getattr(self, "WM_CLOSE", 0x0010) and self.busy:
                self.close_requested = True
                self._set("status", "���ڵȴ���ǰ�������ִ������ɣ����رա�")
                return 0
            return super()._wndproc(hwnd, message, wparam, lparam)

    return OperatorWindow()


def _gui_self_test():
    calls = []

    class SyntheticController:
        def read_status(self, progress=None):
            calls.append("read")
            return {**_gates(), "status": "MISSING", "scope": "TEST_ONLY_SYNTHETIC"}

        def run_tick(self, progress=None):
            calls.append("run")
            return {**_gates(), "status": "BLOCKED", "scope": "TEST_ONLY_SYNTHETIC"}

        def install_task(self, progress=None):
            calls.append("install-inert")
            return {**_gates(), "status": "REFUSED", "scope": "TEST_ONLY_SYNTHETIC"}

        def research_status(self, progress=None):
            calls.append("research")
            return {**_gates(), "status": "READ_ONLY", "scope": "TEST_ONLY_SYNTHETIC"}

    app = build_window(SyntheticController())
    checks = {"native_window": bool(app.user32.IsWindow(app.hwnd)),
              "four_native_buttons": len(app.buttons) == 4 and
                  all(app.user32.IsWindow(handle) for handle in app.buttons)}

    def pump():
        message = app.wintypes.MSG()
        while app.user32.PeekMessageW(app.ctypes.byref(message), None, 0, 0, 1):
            app.user32.TranslateMessage(app.ctypes.byref(message))
            app.user32.DispatchMessageW(app.ctypes.byref(message))

    try:
        for cid, expected in ((1001, "run"), (1002, "read"), (1003, "install-inert"),
                              (1004, "research")):
            previous = len(calls)
            app.user32.PostMessageW(app.hwnd, app.WM_COMMAND, cid, 0)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                pump()
                if len(calls) > previous and not app.busy:
                    break
                time.sleep(.01)
            checks["callback_" + expected] = len(calls) == previous + 1 and calls[-1] == expected
    finally:
        app.user32.PostMessageW(app.hwnd, app.WM_CLOSE, 0, 0)
        deadline = time.monotonic() + 3
        while app.user32.IsWindow(app.hwnd) and time.monotonic() < deadline:
            pump()
            time.sleep(.01)
        checks["window_closed"] = not bool(app.user32.IsWindow(app.hwnd))
    return {**_gates(), "status": "COMPLETED" if all(checks.values()) else "FAILED",
            "scope": "TEST_ONLY_SYNTHETIC", "host_acceptance": "NOT_VERIFIED",
            "checks": checks, "callbacks": calls,
            "limitation": "Native widget routing with inert callbacks; no collector or task installation."}


class _DesktopArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise GateError("DESKTOP_ARGUMENT_ERROR: " + message)


def _report_startup_failure(exc, args):
    # Do not require readable source/config files to report their own failure.
    error = f"{type(exc).__name__}: {exc}"
    record = {"schema": "V47-DESKTOP-STARTUP-DIAGNOSTIC-1", "status": "BLOCKED",
              "occurred_at": _now(), "error": error[:8192],
              "config_file": str(args.config)[:2048] if args.config else None,
              "error_truncated": len(error) > 8192, "formal_A": 0, "decision": "NO_EDGE",
              "formal_future_denominator": "NOT_VERIFIED", "host_acceptance": "NOT_VERIFIED"}
    detail = "BLOCKED: " + record["error"]
    if record["config_file"]:
        detail += "\nConfiguration: " + record["config_file"]
    try:
        if args.result_file:
            receipt = _path(args.result_file)
        else:
            try:
                parent = _path(args.config).parent
                if not parent.is_dir():
                    raise GateError("DESKTOP_DIAGNOSTIC_PARENT_MISSING")
            except (OSError, GateError, ValueError, TypeError):
                parent = _path(tempfile.gettempdir())
            folder = parent / "desktop_startup_receipts"
            closed_loop._not_symlink(folder)
            folder.mkdir(exist_ok=True)
            receipt = folder / ("startup-" + uuid.uuid4().hex + ".json")
        _write_json(receipt, record)
        detail += "\n\nStartup diagnostic: " + str(receipt)
    except Exception as diagnostic_error:
        detail += ("\n\nStartup diagnostic could not be saved: "
                   + f"{type(diagnostic_error).__name__}: {diagnostic_error}"[:8192])
    stream = sys.stderr
    if stream is not None:
        try:
            stream.write(detail + "\n")
            stream.flush()
        except (OSError, ValueError):
            stream = None
    if (os.name == "nt" and not getattr(args, "status_json", False)
            and not getattr(args, "gui_self_test", False)):
        try:
            import ctypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                          ctypes.c_wchar_p, ctypes.c_uint]
            user32.MessageBoxW(None, detail, "SSQ + DLT V4.7 �� Startup blocked", 0x10)
        except Exception:
            # Retain the original error/receipt; diagnostic display is best effort.
            pass


def main(argv=None):
    parser = _DesktopArgumentParser(description="SSQ + DLT V4.7 local SHADOW operator")
    parser.add_argument("--config")
    parser.add_argument("--owner-sid")
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--status-json", action="store_true")
    parser.add_argument("--gui-self-test", action="store_true")
    parser.add_argument("--result-file")
    args = argparse.Namespace(config=None, result_file=None)
    try:
        args = parser.parse_args(argv, namespace=args)
        if args.gui_self_test:
            result = _gui_self_test()
        else:
            if not args.config:
                raise GateError("--config is required outside the synthetic GUI self-test")
            controller = DesktopController(args.config, args.report, args.owner_sid)
            if not args.status_json:
                build_window(controller).run()
                return 0
            result = controller.read_status()
        if args.result_file:
            _write_json(_path(args.result_file), result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 1 if result["status"] in ("FAILED", "BLOCKED") else 0
    except (OSError, GateError, ValueError, RuntimeError, sqlite3.Error) as exc:
        _report_startup_failure(exc, args)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
