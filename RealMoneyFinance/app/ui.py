from __future__ import annotations

from pathlib import Path
import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from .service import FinanceService


class FinanceDesktop(tk.Tk):
    def __init__(self, root_dir: Path):
        super().__init__()
        self.title("Real-Money Finance System · Reauthored Candidate")
        self.geometry("960x680")
        self.minsize(820, 560)
        self.service = FinanceService(root_dir)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        tk.Label(self, text="Real-Money Finance System", font=("Segoe UI", 22, "bold")).pack(pady=(18, 3))
        tk.Label(
            self,
            text="新实现候选 · 公共 L1 只描述可观察活动，不宣称真实主力资金身份",
            font=("Segoe UI", 10),
        ).pack(pady=(0, 12))

        symbol_row = tk.Frame(self)
        symbol_row.pack(fill="x", padx=24)
        tk.Label(symbol_row, text="证券代码", font=("Segoe UI", 10)).pack(side="left")
        self.symbol = tk.StringVar(value="600000")
        tk.Entry(symbol_row, textvariable=self.symbol, width=16).pack(side="left", padx=8)

        grid = tk.Frame(self)
        grid.pack(fill="x", padx=24, pady=10)
        self.buttons = [
            self._button(grid, "资金变化", self._core, 0, 0),
            self._button(grid, "一键更新", self.service.software_update, 0, 1),
            self._button(grid, "一键修复", self.service.repair, 1, 0),
            self._button(grid, "高级分析", self._advanced, 1, 1),
        ]

        self.status = tk.StringVar(value="READY")
        tk.Label(self, textvariable=self.status, anchor="w", font=("Consolas", 10)).pack(fill="x", padx=24)
        self.output = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=("Consolas", 9))
        self.output.pack(fill="both", expand=True, padx=24, pady=(8, 20))
        self.output.insert(tk.END, "Final Gate = FAIL until all current acceptance gates pass.\n")
        self.after(150, self._poll)

    def _button(self, parent, label, fn, row, column):
        b = tk.Button(parent, text=label, font=("Segoe UI", 13, "bold"), height=2,
                      command=lambda: self._start(label, fn))
        b.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        parent.grid_columnconfigure(column, weight=1)
        return b

    def _core(self):
        symbol = self._validated_symbol()
        refreshed = self.service.refresh_real_data(symbol)
        current = self.service.capital_change(symbol)
        return {"refresh": refreshed, "capital_change": current}

    def _advanced(self):
        return self.service.advanced_analysis(self._validated_symbol())

    def _validated_symbol(self) -> str:
        symbol = "".join(c for c in self.symbol.get() if c.isdigit())
        if len(symbol) != 6:
            raise ValueError("证券代码必须为6位数字")
        return symbol

    def _set_busy(self, value: bool):
        self.busy = value
        state = tk.DISABLED if value else tk.NORMAL
        for b in self.buttons:
            b.configure(state=state)

    def _start(self, label, fn):
        if self.busy:
            return
        self._set_busy(True)
        self.status.set("RUNNING: " + label)

        def worker():
            try:
                self.events.put(("RESULT", {"label": label, "payload": fn()}))
            except Exception as exc:
                self.events.put(("ERROR", {"label": label, "error": repr(exc)}))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self.output.insert(tk.END, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
                self.output.see(tk.END)
                if kind == "ERROR":
                    self.status.set("FAIL: " + payload["label"])
                    messagebox.showerror("Real-Money Finance", payload["error"])
                else:
                    status = payload["payload"].get("status") if isinstance(payload["payload"], dict) else None
                    if status == "BLOCKED":
                        self.status.set("BLOCKED: " + payload["label"])
                        messagebox.showwarning("Real-Money Finance", str(payload["payload"].get("reason")))
                    else:
                        self.status.set("PASS: " + payload["label"])
                self._set_busy(False)
        except queue.Empty:
            pass
        self.after(150, self._poll)
