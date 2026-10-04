from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Iterable


@dataclass(frozen=True)
class ActionResult:
    action: str
    status: str
    returncode: int
    started_at: float
    finished_at: float
    stdout: str
    stderr: str
    invocation_id: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "PASS" and self.returncode == 0


class StockAIService:
    """Application/service boundary for the native Windows desktop shell.

    The UI calls only these methods. Business work remains in the recovered
    Stock AI modules/scripts; no business logic is embedded in Tkinter.
    """

    def __init__(self, package_root: Path | None = None, timeout_seconds: int = 3300):
        self.package_root = (package_root or self._detect_package_root()).resolve()
        self.timeout_seconds = min(3300, int(timeout_seconds))
        if self.timeout_seconds <= 0:
            raise ValueError("positive bounded action timeout required")
        self.current = self._read_current()
        self.active_version = str(self.current["active_version"])
        self.version_root = self.package_root / "versions" / self.active_version
        self._validate_layout()
        executable = Path(sys.executable).resolve()
        with executable.open("rb") as stream:
            executable_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        self.identity = {
            "pid": os.getpid(),
            "executable": str(executable),
            "exe_sha256": executable_hash,
            "frozen": bool(getattr(sys, "frozen", False)),
            "source_commit": os.environ.get("STOCK_SOURCE_SHA"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "active_version": self.active_version,
        }

    def data_root(self) -> Path:
        explicit = os.environ.get("STOCK_AI_DATA_ROOT")
        if explicit:
            return Path(explicit).expanduser().resolve()
        if os.name == "nt" and os.environ.get("APPDATA"):
            return Path(os.environ["APPDATA"]) / "StockAIPro"
        return Path.cwd() / "userdata"

    def write_evidence(self, name: str, payload: dict) -> Path:
        target = self.data_root() / "evidence" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps({**payload, **self.identity,
                                        "recorded_at": time.time()},
                                       ensure_ascii=True, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return target

    @staticmethod
    def _detect_package_root() -> Path:
        explicit = os.environ.get("STOCK_AI_PACKAGE_ROOT")
        if explicit:
            return Path(explicit)
        here = Path(__file__).resolve()
        # Source tree: StockAIPro/desktop_native/service.py
        source_candidate = here.parents[1] / "staging" / "Stock_AI_Pro"
        if source_candidate.exists():
            return source_candidate
        # Frozen PyInstaller candidate: data files live under sys._MEIPASS.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            frozen_candidate = Path(meipass) / "Stock_AI_Pro"
            if frozen_candidate.exists():
                return frozen_candidate
        # Alternate onedir layout: data files may sit beside the executable.
        exe_candidate = Path(sys.executable).resolve().parent / "Stock_AI_Pro"
        if exe_candidate.exists():
            return exe_candidate
        raise FileNotFoundError(
            "Stock AI package root not found; set STOCK_AI_PACKAGE_ROOT or ship Stock_AI_Pro beside the executable."
        )

    def _read_current(self) -> dict:
        path = self.package_root / "current.json"
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or not obj.get("active_version"):
            raise ValueError("current.json missing active_version")
        return obj

    def _validate_layout(self) -> None:
        required = [
            self.package_root / "launcher.py",
            self.package_root / "updater_runtime" / "updater.py",
            self.version_root / "run_daily.py",
            self.version_root / "run_backtest.py",
            self.version_root / "run_audit.py",
            self.version_root / "doctor.py",
            self.version_root / "stock_ai",
        ]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            raise FileNotFoundError("missing required Stock AI runtime files: " + "; ".join(missing))

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["STOCK_AI_PACKAGE_ROOT"] = str(self.package_root)
        return env

    def _run(self, action: str, argv: Iterable[str], cwd: Path) -> ActionResult:
        started = time.time()
        invocation_id = uuid.uuid4().hex
        command = list(argv)
        env = self._env()
        env["STOCK_GUI_INVOCATION_ID"] = invocation_id
        action_limit = {"update": 180, "repair": 420}.get(action, 3300)
        timeout = min(self.timeout_seconds, action_limit)
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                shell=False,
            )
            status = "PASS" if proc.returncode == 0 else "FAIL"
            # Return code 3 is BLOCKED only when the actual updater emitted a
            # matching structured result. It is never a generic success code.
            if action == "update" and proc.returncode == 3:
                for line in reversed(proc.stdout.splitlines()):
                    try:
                        payload = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(payload, dict) and payload.get("status") == "BLOCKED" and payload.get("reason"):
                        status = "BLOCKED"
                    break
            result = ActionResult(
                action=action,
                status=status,
                returncode=int(proc.returncode),
                started_at=started,
                finished_at=time.time(),
                stdout=proc.stdout[-30000:],
                stderr=proc.stderr[-30000:],
                invocation_id=invocation_id,
            )
        except subprocess.TimeoutExpired as exc:
            result = ActionResult(
                action=action,
                status="FAIL",
                returncode=124,
                started_at=started,
                finished_at=time.time(),
                stdout=(exc.stdout or "")[-30000:] if isinstance(exc.stdout, str) else "",
                stderr="timeout",
                invocation_id=invocation_id,
            )
        except Exception as exc:
            result = ActionResult(
                action=action,
                status="FAIL",
                returncode=125,
                started_at=started,
                finished_at=time.time(),
                stdout="",
                stderr=repr(exc),
                invocation_id=invocation_id,
            )
        self.write_evidence("service_" + action + ".json", {
            "schema": "stock-ai-service-invocation-v1",
            "action": result.action,
            "status": result.status,
            "returncode": result.returncode,
            "invocation_id": invocation_id,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "argv": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timeout_seconds": timeout,
        })
        return result

    def _worker_argv(self, action: str) -> list[str]:
        if getattr(sys, "frozen", False):
            return [
                sys.executable,
                "--worker",
                action,
                "--package-root",
                str(self.package_root),
            ]
        return [
            sys.executable,
            str(Path(__file__).resolve().parent / "worker.py"),
            "--worker",
            action,
            "--package-root",
            str(self.package_root),
        ]

    def core_function(self) -> ActionResult:
        """Real source -> pipeline -> frozen prediction path."""
        return self._run("core_function", self._worker_argv("core"), self.package_root)

    def repair(self) -> ActionResult:
        return self._run("repair", self._worker_argv("repair"), self.package_root)

    def advanced_analysis(self) -> ActionResult:
        return self._run(
            "advanced_analysis",
            self._worker_argv("advanced"),
            self.package_root,
        )

    def update(self) -> ActionResult:
        """Launch the updater as a separate process.

        In a packaged Windows build the UI must use StockAIUpdater.exe beside
        the main executable. Source mode uses updater_entry.py only for
        development/CI and is not release evidence.
        """
        exe = Path(sys.executable).resolve().parent / "StockAIUpdater.exe"
        if getattr(sys, "frozen", False):
            if not exe.exists():
                started = time.time()
                invocation_id = uuid.uuid4().hex
                result = ActionResult(
                    action="update",
                    status="FAIL",
                    returncode=127,
                    started_at=started,
                    finished_at=time.time(),
                    stdout="",
                    stderr=f"independent updater executable missing: {exe}",
                    invocation_id=invocation_id,
                )
                self.write_evidence("service_update.json", {
                    "schema": "stock-ai-service-invocation-v1",
                    "action": "update", "status": "FAIL", "returncode": 127,
                    "invocation_id": invocation_id, "started_at": started,
                    "finished_at": result.finished_at,
                    "argv": [str(exe), "--package-root", str(self.package_root)],
                    "process_invoked": False, "stdout": "", "stderr": result.stderr,
                })
                return result
            argv = [str(exe), "--package-root", str(self.package_root)]
        else:
            argv = [
                sys.executable,
                str(Path(__file__).resolve().parent / "updater_entry.py"),
                "--package-root",
                str(self.package_root),
            ]
        return self._run("update", argv, self.package_root)
