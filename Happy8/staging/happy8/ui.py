from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .services import Happy8Service


UI_SERVICE_BINDINGS = {
    "predict": ("预测下一期", "predict_next"),
    "update": ("一键更新", "update_data"),
    "repair": ("一键修复", "repair"),
    "advanced": ("高级分析", "advanced_analysis"),
}


def source_ui_contract() -> dict[str, Any]:
    checks = {}
    for key, (label, service_method) in UI_SERVICE_BINDINGS.items():
        checks[key] = {
            "label": label,
            "service_method": service_method,
            "service_callable": callable(getattr(Happy8Service, service_method, None)),
        }
    return {
        "status": "PASS" if all(item["service_callable"] for item in checks.values()) else "FAIL",
        "bindings": checks,
    }


class Happy8Window(tk.Tk):
    def __init__(self, service: Happy8Service):
        super().__init__()
        self.service = service
        self.title("Geometry Lotto Pro · 快乐8")
        self.geometry("920x640")
        self.minsize(760, 520)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=(18, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Geometry Lotto Pro · 快乐8",
            font=("Microsoft YaHei UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.state_var = tk.StringVar(value="STORE: NOT VERIFIED")
        ttk.Label(header, textvariable=self.state_var).grid(row=0, column=1, sticky="e")

        actions = ttk.Frame(self, padding=(18, 0, 18, 12))
        actions.grid(row=1, column=0, sticky="ew")
        for col in range(4):
            actions.columnconfigure(col, weight=1)

        self.buttons: dict[str, ttk.Button] = {}
        specs = [
            ("predict", UI_SERVICE_BINDINGS["predict"][0], self._predict),
            ("update", UI_SERVICE_BINDINGS["update"][0], self._update),
            ("repair", UI_SERVICE_BINDINGS["repair"][0], self._repair),
            ("advanced", UI_SERVICE_BINDINGS["advanced"][0], self._advanced),
        ]
        for col, (key, label, command) in enumerate(specs):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=0, column=col, padx=5, sticky="ew", ipady=12)
            self.buttons[key] = button

        body = ttk.Frame(self, padding=(18, 0, 18, 18))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        self.operation_var = tk.StringVar(value="READY")
        ttk.Label(body, textvariable=self.operation_var).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.output = tk.Text(body, wrap="word", font=("Consolas", 10))
        self.output.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, command=self.output.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)
        self.after(100, self.refresh_status)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self.buttons.values():
            button.configure(state=state)

    def _render(self, value: Any) -> None:
        self.output.delete("1.0", "end")
        self.output.insert("end", json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))

    def _run(self, label: str, operation: Callable[[], dict[str, Any]]) -> None:
        self._set_busy(True)
        self.operation_var.set(f"{label}: RUNNING")

        def worker() -> None:
            try:
                result = operation()
                status = str(result.get("status") or "UNKNOWN")
                self.after(0, lambda: self._complete(label, status, result, None))
            except Exception as exc:
                failure = {
                    "status": "FAIL",
                    "operation": label,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                self.after(0, lambda: self._complete(label, "FAIL", failure, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _complete(self, label: str, status: str, result: dict[str, Any], exc: Exception | None) -> None:
        self._set_busy(False)
        self.operation_var.set(f"{label}: {status}")
        self._render(result)
        self.refresh_status()
        if exc is not None:
            messagebox.showerror("操作失败", result["error"])

    def refresh_status(self) -> None:
        try:
            status = self.service.status()
            if status.get("status") == "PASS":
                self.state_var.set(
                    f"STORE: PASS · {status.get('latest_issue')} · "
                    f"{str(status.get('canonical_hash') or '')[:12]}"
                )
            else:
                self.state_var.set("STORE: FAIL / NOT READY")
        except Exception as exc:
            self.state_var.set(f"STORE: FAIL · {type(exc).__name__}")

    def _predict(self) -> None:
        self._run("预测下一期", self.service.predict_next)

    def _update(self) -> None:
        self._run("一键更新", self.service.update_data)

    def _repair(self) -> None:
        self._run("一键修复", self.service.repair)

    def _advanced(self) -> None:
        self._run("高级分析", self.service.advanced_analysis)


def ui_contract(window: Happy8Window) -> dict[str, Any]:
    expected = {
        "predict": "预测下一期",
        "update": "一键更新",
        "repair": "一键修复",
        "advanced": "高级分析",
    }
    actual = {key: button.cget("text") for key, button in window.buttons.items()}
    commands_bound = all(bool(str(button.cget("command"))) for button in window.buttons.values())
    return {
        "status": "PASS" if actual == expected and commands_bound else "FAIL",
        "buttons": actual,
        "commands_bound": commands_bound,
        "title": window.title(),
    }
