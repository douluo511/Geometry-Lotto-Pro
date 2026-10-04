from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from core import (
    PRODUCT,
    advanced_analysis,
    create_project,
    ensure_root,
    network_probe,
    read_json,
    repair,
    self_test,
    sha256_file,
    write_json,
)

try:
    from build_info import SOURCE_SHA
except Exception:
    SOURCE_SHA = "UNBUILT"


def default_root() -> Path:
    explicit = os.environ.get("AI_MUSIC_DATA_ROOT")
    if explicit:
        return Path(explicit)
    base = os.environ.get("APPDATA") if os.name == "nt" else None
    return Path(base) / "AIMusicPro" if base else Path.cwd() / "AIMusicProData"


def executable_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def update_action_state(root: Path, label: str, payload: dict) -> None:
    path = ensure_root(root) / "state" / "gui_actions.json"
    state = read_json(path, {}) or {}
    state[label] = {
        "time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "action": label,
        "status": payload.get("status", "UNKNOWN"),
        "payload": payload,
    }
    write_json(path, state)


def run_updater_process(root: Path) -> dict:
    if getattr(sys, "frozen", False):
        updater = Path(sys.executable).resolve().with_name("AIMusicUpdater.exe")
        if not updater.is_file():
            return {"status": "BLOCKED", "reason": "independent updater executable missing"}
        proc = subprocess.run(
            [str(updater), "--root", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        status = read_json(ensure_root(root) / "state" / "update_status.json", {}) or {}
        status["independent_updater_path"] = str(updater)
        status["independent_process_returncode"] = proc.returncode
        return status

    updater_py = Path(__file__).resolve().with_name("updater.py")
    proc = subprocess.run([sys.executable, str(updater_py), "--root", str(root)], timeout=30)
    status = read_json(ensure_root(root) / "state" / "update_status.json", {}) or {}
    status["independent_process_returncode"] = proc.returncode
    return status


def launch_gui(root_path: Path) -> int:
    import tkinter as tk
    from tkinter import messagebox

    data_root = ensure_root(root_path)
    window = tk.Tk()
    window.title("AI Music Production System · Re-authored Candidate")
    window.geometry("760x420+120+110")
    window.minsize(760, 420)

    header = tk.Label(
        window,
        text="AI Music Production System",
        font=("Segoe UI", 19, "bold"),
    )
    header.pack(pady=(24, 4))
    subtitle = tk.Label(
        window,
        text="Idea → structure → chords → melody → arrangement → mix → master → evidence",
        font=("Segoe UI", 10),
    )
    subtitle.pack(pady=(0, 22))

    button_frame = tk.Frame(window)
    button_frame.pack(pady=8)

    status_var = tk.StringVar(value="Candidate-only: external AI provider / production updater remain blocked.")
    status = tk.Label(window, textvariable=status_var, wraplength=680, justify="left", font=("Segoe UI", 9))
    status.pack(pady=(18, 0))

    def do_core():
        try:
            result = create_project(data_root, "夜色里的希望 / hope in the night", 42, 8.0)
            payload = {
                "status": "PASS",
                "project_id": result["project"]["project_id"],
                "wav_sha256": result["project"]["audio"]["sha256"],
                "provider": result["project"]["provider"],
                "external_ai_provider": "NOT VERIFIED",
            }
            update_action_state(data_root, "AI创作", payload)
            status_var.set("AI创作 PASS：已生成真实 WAV + project/evidence；外部 AI provider 仍 NOT VERIFIED。")
        except Exception as exc:
            payload = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
            update_action_state(data_root, "AI创作", payload)
            status_var.set(payload["error"])

    def do_update():
        try:
            payload = run_updater_process(data_root)
        except Exception as exc:
            payload = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        update_action_state(data_root, "一键更新", payload)
        status_var.set(f"一键更新 {payload.get('status')}: {payload.get('reason', '')}")

    def do_repair():
        try:
            payload = repair(data_root)
        except Exception as exc:
            payload = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        update_action_state(data_root, "一键修复", payload)
        status_var.set(f"一键修复 {payload.get('status')}：不会自动删除用户作品。")

    def do_advanced():
        try:
            payload = advanced_analysis(data_root)
        except Exception as exc:
            payload = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        update_action_state(data_root, "高级制作", payload)
        status_var.set(
            f"高级制作 {payload.get('status')}：project_count={payload.get('project_count', 0)}；"
            "provider/license gaps 保持显式。"
        )

    buttons = {}
    for idx, (label, command) in enumerate(
        [("AI创作", do_core), ("一键更新", do_update), ("一键修复", do_repair), ("高级制作", do_advanced)]
    ):
        btn = tk.Button(button_frame, text=label, command=command, width=13, height=2, font=("Segoe UI", 10))
        btn.grid(row=0, column=idx, padx=7)
        buttons[label] = btn

    def publish_layout():
        window.update_idletasks()
        window.update()
        out = {
            "schema": "ai-music-gui-layout-v1",
            "status": "PASS",
            "pid": os.getpid(),
            "window_title": window.title(),
            "executable": str(Path(sys.executable).resolve()) if getattr(sys, "frozen", False) else str(Path(__file__).resolve()),
            "exe_sha256": sha256_file(Path(sys.executable).resolve()) if getattr(sys, "frozen", False) else "SOURCE_MODE",
            "window": {
                "x": window.winfo_rootx(),
                "y": window.winfo_rooty(),
                "width": window.winfo_width(),
                "height": window.winfo_height(),
            },
            "buttons": {},
        }
        for label, btn in buttons.items():
            out["buttons"][label] = {
                "x": btn.winfo_rootx(),
                "y": btn.winfo_rooty(),
                "width": btn.winfo_width(),
                "height": btn.winfo_height(),
                "center_x": btn.winfo_rootx() + btn.winfo_width() // 2,
                "center_y": btn.winfo_rooty() + btn.winfo_height() // 2,
            }
        target = os.environ.get("AI_MUSIC_GUI_LAYOUT")
        if target:
            write_json(Path(target), out)

    window.after(500, publish_layout)
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(default_root()))
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--health-report")
    parser.add_argument("--health-nonce", default="")
    parser.add_argument("--network-probe", action="store_true")
    parser.add_argument("--network-url", default="https://api.github.com/repos/douluo511/Geometry-Lotto-Pro/issues/20")
    parser.add_argument("--network-report")
    parser.add_argument("--create-sample", action="store_true")
    args = parser.parse_args()
    root = ensure_root(Path(args.root))

    if args.self_test:
        report = self_test(SOURCE_SHA, executable_path(), args.health_nonce)
        if args.health_report:
            write_json(Path(args.health_report), report)
        return 0 if report.get("status") == "PASS" else 2

    if args.network_probe:
        report = network_probe(args.network_url, Path(args.network_report) if args.network_report else None)
        return 0 if report.get("status") == "PASS" else 2

    if args.create_sample:
        create_project(root, "strict candidate sample", 42, 8.0)
        return 0

    return launch_gui(root)


if __name__ == "__main__":
    raise SystemExit(main())
