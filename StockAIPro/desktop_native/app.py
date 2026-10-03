from __future__ import annotations

from pathlib import Path
import json
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext

from service import ActionResult, StockAIService
from worker import main as worker_main


APP_TITLE = "Stock AI Pro · Windows Desktop Candidate"


class StockAIDesktop(tk.Tk):
    def __init__(self, service: StockAIService | None = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x680")
        self.minsize(820, 560)
        self.service = service or StockAIService()
        self._events: queue.Queue[ActionResult | tuple[str, str]] = queue.Queue()
        self._busy = False

        title = tk.Label(self, text="Stock AI Pro", font=("Segoe UI", 22, "bold"))
        title.pack(pady=(18, 4))
        subtitle = tk.Label(
            self,
            text="原生桌面候选 · 核心功能 / 一键更新 / 一键修复 / 高级分析",
            font=("Segoe UI", 10),
        )
        subtitle.pack(pady=(0, 16))

        buttons = tk.Frame(self)
        buttons.pack(fill="x", padx=24)
        self.btn_core = self._button(buttons, "核心功能", self.service.core_function, 0, 0)
        self.btn_update = self._button(buttons, "一键更新", self.service.update, 0, 1)
        self.btn_repair = self._button(buttons, "一键修复", self.service.repair, 1, 0)
        self.btn_analysis = self._button(buttons, "高级分析", self.service.advanced_analysis, 1, 1)

        self.status_var = tk.StringVar(value="READY")
        status = tk.Label(self, textvariable=self.status_var, anchor="w", font=("Consolas", 10))
        status.pack(fill="x", padx=24, pady=(16, 6))

        self.output = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=("Consolas", 9))
        self.output.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.output.insert(tk.END, self._startup_text())

        self.after(150, self._poll)

    def _startup_text(self) -> str:
        return (
            f"PACKAGE_ROOT={self.service.package_root}\n"
            f"ACTIVE_VERSION={self.service.active_version}\n"
            "This executable candidate does not claim Final Gate.\n"
            "Update remains BLOCKED until a real signed production release endpoint is configured.\n\n"
        )

    def _button(self, parent: tk.Widget, text: str, action, row: int, column: int) -> tk.Button:
        b = tk.Button(
            parent,
            text=text,
            command=lambda: self._start(text, action),
            font=("Segoe UI", 13, "bold"),
            height=2,
        )
        b.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        parent.grid_columnconfigure(column, weight=1)
        return b

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for b in (self.btn_core, self.btn_update, self.btn_repair, self.btn_analysis):
            b.configure(state=state)

    def _start(self, label: str, action) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.status_var.set(f"RUNNING: {label}")
        self.output.insert(tk.END, f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] START {label}\n")
        self.output.see(tk.END)

        def worker() -> None:
            try:
                result = action()
                self._events.put(result)
            except Exception as exc:
                self._events.put(("FAIL", repr(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                item = self._events.get_nowait()
                if isinstance(item, ActionResult):
                    self._render_result(item)
                else:
                    status, detail = item
                    self.status_var.set(status)
                    self.output.insert(tk.END, detail + "\n")
                    self._set_busy(False)
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _render_result(self, result: ActionResult) -> None:
        self.status_var.set(f"{result.status}: {result.action} rc={result.returncode}")
        payload = {
            "action": result.action,
            "status": result.status,
            "returncode": result.returncode,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
        }
        self.output.insert(tk.END, json.dumps(payload, ensure_ascii=False) + "\n")
        if result.stdout:
            self.output.insert(tk.END, result.stdout + "\n")
        if result.stderr:
            self.output.insert(tk.END, "STDERR:\n" + result.stderr + "\n")
        self.output.see(tk.END)
        self._set_busy(False)
        if not result.ok:
            messagebox.showerror("Stock AI Pro", f"{result.action} -> {result.status}\nrc={result.returncode}")

    def self_test(self) -> int:
        checks = {
            "package_root_exists": self.service.package_root.exists(),
            "version_root_exists": self.service.version_root.exists(),
            "four_buttons": all(
                hasattr(self, name)
                for name in ("btn_core", "btn_update", "btn_repair", "btn_analysis")
            ),
        }
        print(json.dumps(checks, ensure_ascii=False))
        return 0 if all(checks.values()) else 1


def main() -> int:
    if "--worker" in sys.argv:
        return worker_main(sys.argv[1:])
    if "--self-test" in sys.argv:
        service = StockAIService()
        checks = {
            "package_root_exists": service.package_root.exists(),
            "version_root_exists": service.version_root.exists(),
            "active_version": service.active_version,
            "four_entries": ["核心功能", "一键更新", "一键修复", "高级分析"],
        }
        print(json.dumps(checks, ensure_ascii=False))
        return 0 if checks["package_root_exists"] and checks["version_root_exists"] else 1
    service = StockAIService()
    app = StockAIDesktop(service)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
