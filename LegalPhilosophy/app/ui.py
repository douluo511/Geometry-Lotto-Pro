from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
import traceback

from .service import LegalPhilosophyService


class LegalPhilosophyUI:
    def __init__(self, service: LegalPhilosophyService):
        self.service = service
        self.root = tk.Tk()
        self.root.title("法哲学原理 · Evidence-First Study System")
        self.root.geometry("920x650")
        self.status_var = tk.StringVar(value="READY")

        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="研习问题").pack(side="left")
        self.question = ttk.Entry(top, width=72)
        self.question.insert(0, "国家与自由之间有什么关系？")
        self.question.pack(side="left", padx=8, fill="x", expand=True)

        buttons = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")
        self.buttons = {}
        for text, action in (
            ("核心研习", self.on_study),
            ("一键更新", self.on_update),
            ("一键修复", self.on_repair),
            ("高级分析", self.on_advanced),
        ):
            button = ttk.Button(buttons, text=text, command=action)
            button.pack(side="left", padx=4)
            self.buttons[text] = button

        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 0)).pack(fill="x")
        self.output = tk.Text(self.root, wrap="word", height=30)
        self.output.pack(fill="both", expand=True, padx=10, pady=10)
        self.output.insert("1.0", "所有输出区分来源、解释与模型推断；本系统不提供个案法律意见。\n")
        self.output.configure(state="disabled")
        self.root.after(500, self._write_layout)

    def _write_layout(self) -> None:
        self.root.update_idletasks()
        layout = {
            "status": "PASS",
            "pid": os.getpid(),
            "window_title": self.root.title(),
            "window": {
                "x": self.root.winfo_rootx(),
                "y": self.root.winfo_rooty(),
                "width": self.root.winfo_width(),
                "height": self.root.winfo_height(),
            },
            "buttons": {},
        }
        for text, button in self.buttons.items():
            layout["buttons"][text] = {
                "center_x": button.winfo_rootx() + button.winfo_width() // 2,
                "center_y": button.winfo_rooty() + button.winfo_height() // 2,
                "width": button.winfo_width(),
                "height": button.winfo_height(),
            }
        self.service.storage.atomic_json(self.service.storage.evidence / "ui_layout.json", layout)

    def _audit(self, action: str, status: str, payload: object) -> None:
        path = self.service.storage.evidence / "gui_actions.jsonl"
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "status": status,
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _render(self, payload: object) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        self.output.configure(state="disabled")

    def _run(self, action: str, fn) -> None:
        self.status_var.set(f"{action}: RUNNING")
        self.root.update_idletasks()
        try:
            result = fn()
            status = str(result.get("status", "PASS")) if isinstance(result, dict) else "PASS"
            self._render(result)
            self._audit(action, status, result)
            self.status_var.set(f"{action}: {status}")
        except Exception as exc:
            payload = {"status": "FAIL", "error": repr(exc), "trace": traceback.format_exc(limit=6)}
            self._render(payload)
            self._audit(action, "FAIL", payload)
            self.status_var.set(f"{action}: FAIL")

    def on_study(self) -> None:
        self._run("核心研习", lambda: self.service.study(self.question.get(), refresh_if_missing=True))

    def _software_update(self) -> dict:
        if getattr(sys, "frozen", False):
            updater = Path(sys.executable).with_name("LegalPhilosophyUpdater.exe")
            cmd = [str(updater), "--root", str(self.service.root)]
        else:
            updater = Path(__file__).resolve().parents[1] / "updater_main.py"
            cmd = [sys.executable, str(updater), "--root", str(self.service.root)]
        if not updater.is_file():
            return {"status": "FAIL", "reason": "independent updater executable/script is missing"}
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        result_path = self.service.root / "updater_result.json"
        if not result_path.is_file():
            return {
                "status": "FAIL",
                "reason": "independent updater produced no evidence",
                "returncode": proc.returncode,
            }
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["independent_process_returncode"] = proc.returncode
        result["independent_updater_path"] = str(updater)
        if result.get("status") == "BLOCKED" and proc.returncode != 3:
            raise RuntimeError("BLOCKED updater must return rc=3")
        return result

    def on_update(self) -> None:
        self._run("一键更新", self._software_update)

    def on_repair(self) -> None:
        self._run("一键修复", self.service.repair)

    def on_advanced(self) -> None:
        self._run("高级分析", self.service.advanced)

    def run(self) -> None:
        self.root.mainloop()
