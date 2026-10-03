from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess
import sys
import time
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

    @property
    def ok(self) -> bool:
        return self.status == "PASS" and self.returncode == 0


class StockAIService:
    """Application/service boundary for the native Windows desktop shell.

    The UI calls only these methods. Business work remains in the recovered
    Stock AI modules/scripts; no business logic is embedded in Tkinter.
    """

    def __init__(self, package_root: Path | None = None, timeout_seconds: int = 1800):
        self.package_root = (package_root or self._detect_package_root()).resolve()
        self.timeout_seconds = int(timeout_seconds)
        self.current = self._read_current()
        self.active_version = str(self.current["active_version"])
        self.version_root = self.package_root / "versions" / self.active_version
        self._validate_layout()

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
        env["STOCK_AI_PACKAGE_ROOT"] = str(self.package_root)
        return env

    def _run(self, action: str, argv: Iterable[str], cwd: Path) -> ActionResult:
        started = time.time()
        try:
            proc = subprocess.run(
                list(argv),
                cwd=str(cwd),
                env=self._env(),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
            status = "PASS" if proc.returncode == 0 else "FAIL"
            return ActionResult(
                action=action,
                status=status,
                returncode=int(proc.returncode),
                started_at=started,
                finished_at=time.time(),
                stdout=proc.stdout[-30000:],
                stderr=proc.stderr[-30000:],
            )
        except subprocess.TimeoutExpired as exc:
            return ActionResult(
                action=action,
                status="FAIL",
                returncode=124,
                started_at=started,
                finished_at=time.time(),
                stdout=(exc.stdout or "")[-30000:] if isinstance(exc.stdout, str) else "",
                stderr="timeout",
            )
        except Exception as exc:
            return ActionResult(
                action=action,
                status="FAIL",
                returncode=125,
                started_at=started,
                finished_at=time.time(),
                stdout="",
                stderr=repr(exc),
            )

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
                return ActionResult(
                    action="update",
                    status="FAIL",
                    returncode=127,
                    started_at=time.time(),
                    finished_at=time.time(),
                    stdout="",
                    stderr=f"independent updater executable missing: {exe}",
                )
            argv = [str(exe), "--package-root", str(self.package_root)]
        else:
            argv = [
                sys.executable,
                str(Path(__file__).resolve().parent / "updater_entry.py"),
                "--package-root",
                str(self.package_root),
            ]
        return self._run("update", argv, self.package_root)
