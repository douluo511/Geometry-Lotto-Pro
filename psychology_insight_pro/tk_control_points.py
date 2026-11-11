"""Measure visible Tk control positions; this is layout input, never click proof."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

def button_points(root, labels):
    import tkinter as tk
    from tkinter import ttk
    root.update_idletasks()
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)
    found = {}
    for widget in walk(root):
        if not isinstance(widget, (tk.Button, ttk.Button)):
            continue
        label = str(widget.cget("text"))
        if label in labels:
            if label in found:
                raise RuntimeError("ambiguous button label")
            found[label] = [(widget.winfo_rootx() + widget.winfo_width()/2 - root.winfo_rootx()) / root.winfo_width(),
                            (widget.winfo_rooty() + widget.winfo_height()/2 - root.winfo_rooty()) / root.winfo_height()]
    if set(found) != set(labels):
        raise RuntimeError("visible button missing")
    return [found[label] for label in labels]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from app import PsychologyApp
    app = PsychologyApp()
    try:
        labels = ["心理分析", "一键更新", "一键修复", "高级分析"]
        home = button_points(app, labels)
        app._show_analysis()  # Build the view; no Engine or button invocation.
        analysis = button_points(app, ["开始分析"])[0]
        Path(args.output).write_text(json.dumps({"home": home, "analysis_start": analysis}), encoding="utf-8")
    finally:
        app.destroy()

if __name__ == "__main__":
    main()
