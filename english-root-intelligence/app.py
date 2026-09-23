from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from core import APP_NAME, APP_VERSION, LearningEngine, MaintenanceEngine, Store, self_test


BG = "#f5f7fb"
CARD = "#ffffff"
BLUE = "#2563eb"
TEXT = "#172033"
MUTED = "#667085"
BORDER = "#dce3ef"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("980x720")
        self.minsize(900, 650)
        self.configure(bg=BG)
        self.store = Store()
        self.engine = LearningEngine(self.store)
        self.maintenance = MaintenanceEngine(self.store)
        self.status_var = tk.StringVar(value="系统就绪 · 数据库已验证")
        self._configure_style()
        self._build_shell()
        self.show_home()

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei UI", 11), padding=10)
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=10)

    def _build_shell(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=34, pady=(24, 10))
        tk.Label(header, text="English Root Intelligence", bg=BG, fg=TEXT,
                 font=("Segoe UI", 25, "bold")).pack(anchor="w")
        tk.Label(header, text="词根理解 × 词族扩展 × 真实口语 × 自适应训练",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(2, 0))

        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=34, pady=(8, 12))
        labels = [
            ("今日学习", self.show_today),
            ("一键更新", self.run_update),
            ("一键修复", self.run_repair),
            ("高级分析", self.show_analysis),
        ]
        for i, (txt, cmd) in enumerate(labels):
            b = tk.Button(nav, text=txt, command=cmd, bg=BLUE, fg="white",
                          activebackground="#1d4ed8", activeforeground="white",
                          relief="flat", bd=0, cursor="hand2",
                          font=("Microsoft YaHei UI", 11, "bold"), height=2)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=6)
        nav.grid_columnconfigure(0, weight=1)
        nav.grid_columnconfigure(1, weight=1)

        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True, padx=34, pady=(0, 12))
        bottom = tk.Frame(self, bg="#eef2f8", height=34)
        bottom.pack(fill="x", side="bottom")
        tk.Label(bottom, textvariable=self.status_var, bg="#eef2f8", fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=18, pady=7)
        tk.Label(bottom, text=f"v{APP_VERSION}", bg="#eef2f8", fg=MUTED).pack(side="right", padx=18)

    def clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    def card(self, parent=None):
        p = parent or self.content
        return tk.Frame(p, bg=CARD, highlightthickness=1, highlightbackground=BORDER)

    def show_home(self):
        self.clear()
        c = self.card()
        c.pack(fill="both", expand=True)
        tk.Label(c, text="从“背单词”升级为“理解英语的组合逻辑”",
                 bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", padx=28, pady=(28, 8))
        tk.Label(c, text="输入一个单词，系统尝试识别前缀 / 词根 / 后缀，并把它连接到词族和真实口语语块。",
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 11)).pack(anchor="w", padx=28)

        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=28, pady=22)
        self.word_entry = tk.Entry(row, font=("Segoe UI", 16), relief="solid", bd=1)
        self.word_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.word_entry.insert(0, "predict")
        tk.Button(row, text="智能拆词", command=self.analyze_from_entry, bg=BLUE, fg="white",
                  relief="flat", font=("Microsoft YaHei UI", 11, "bold"),
                  padx=20, pady=8).pack(side="left", padx=(10, 0))
        self.result = tk.Text(c, height=16, wrap="word", bg="#fbfcfe", fg=TEXT,
                              relief="flat", font=("Microsoft YaHei UI", 11), padx=16, pady=14)
        self.result.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        self.analyze_from_entry()

    def analyze_from_entry(self):
        try:
            value = self.engine.analyze(self.word_entry.get())
        except Exception as exc:
            messagebox.showerror("分析失败", str(exc))
            return
        root = value.get("root") or {}
        family = "
".join(f"  • {w[0]}  {w[1]}  |  {w[2]}" for w in value.get("family", [])) or "  暂无可靠词族"
        chunks = "
".join(f"  • {x}" for x in value.get("chunks", [])) or "  暂无高置信口语语块"
        prefix = value.get("prefix")
        suffix = value.get("suffix")
        lines = [
            f"WORD   {value['word']}",
            f"拆解   {value['segmentation']}",
            f"置信度 {int(value['confidence'] * 100)}%",
            f"词义   {value['meaning']}",
            "",
            f"词根   {root.get('morpheme', '—')} = {root.get('meaning', '—')}",
            f"来源   {root.get('origin', '—')}",
            f"意义桥 {value['semantic_bridge']}",
            f"前缀   {prefix[0] + ' = ' + prefix[1] if prefix else '—'}",
            f"后缀   {suffix[0] + ' = ' + suffix[1] if suffix else '—'}",
            "",
            "核心词族",
            family,
            "",
            "真实口语语块",
            chunks,
        ]
        self.result.delete("1.0", "end")
        self.result.insert("1.0", "
".join(lines))
        self.status_var.set(f"已分析 {value['word']} · 不可靠时不会强行拆词")

    def show_today(self):
        self.clear()
        tk.Label(self.content, text="今日学习", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(4, 12))
        for r in self.engine.today_roots(3):
            c = self.card()
            c.pack(fill="x", pady=6)
            top = tk.Frame(c, bg=CARD)
            top.pack(fill="x", padx=20, pady=(16, 4))
            tk.Label(top, text=r["morpheme"], bg=CARD, fg=BLUE,
                     font=("Segoe UI", 19, "bold")).pack(side="left")
            tk.Label(top, text=f'  {r["meaning"]}   ·   {r["origin"]}',
                     bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(side="left")
            tk.Label(c, text=f'意义桥：{r["bridge"]}', bg=CARD, fg=TEXT,
                     font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=20)
            words = "   |   ".join(f"{w[0]} {w[1]}" for w in r["words"])
            tk.Label(c, text=words, bg=CARD, fg=TEXT,
                     font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=20, pady=(5, 2))
            chunk = r["chunks"][0]
            actions = tk.Frame(c, bg=CARD)
            actions.pack(fill="x", padx=20, pady=(3, 14))
            tk.Label(actions, text=f"口语：{chunk}", bg=CARD, fg=MUTED,
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Button(actions, text="朗读", command=lambda x=chunk: self.speak(x),
                      relief="flat", bg="#e9efff", fg=BLUE).pack(side="right", padx=4)
            tk.Button(actions, text="完成一次", command=lambda x=r["morpheme"]: self.practice(x),
                      relief="flat", bg=BLUE, fg="white").pack(side="right", padx=4)

    def practice(self, morpheme):
        self.store.mark_practiced(morpheme)
        self.status_var.set(f"{morpheme} 已完成一次主动练习")

    def speak(self, text):
        if os.name != "nt":
            self.status_var.set("朗读功能在 Windows EXE 中启用")
            return
        safe = text.replace("'", "''")
        script = f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak('{safe}')"
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            messagebox.showwarning("朗读", str(exc))

    def run_update(self):
        self.status_var.set("正在联网检查并验证词根数据库更新…")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            r = self.maintenance.one_click_update()
            self.after(0, lambda: messagebox.showinfo(
                "一键更新 PASS",
                f'版本：{r["version"]}\n词根数：{r["roots"]}\nSHA256：{r["sha256"][:16]}…'
            ))
            self.after(0, lambda: self.status_var.set("一键更新 PASS · SHA256 与结构校验均通过"))
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("一键更新失败", str(exc)))
            self.after(0, lambda: self.status_var.set("一键更新 FAIL · 保留旧数据库"))

    def run_repair(self):
        try:
            r = self.maintenance.one_click_repair()
            text = "\n".join(f"{name}: {status} · {detail}" for name, status, detail in r["checks"])
            if r["status"] == "PASS":
                messagebox.showinfo("一键修复 PASS", text)
            else:
                messagebox.showerror("一键修复 FAIL", text)
            self.status_var.set(f'一键修复 {r["status"]}')
        except Exception as exc:
            messagebox.showerror("修复失败", str(exc))

    def show_analysis(self):
        self.clear()
        s = self.engine.stats()
        tk.Label(self.content, text="高级分析", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(4, 12))
        grid = tk.Frame(self.content, bg=BG)
        grid.pack(fill="x")
        items = [
            ("词根库", str(s["root_total"]), "当前已验证核心词根"),
            ("已触达", str(s["root_touched"]), f'覆盖率 {s["coverage_pct"]}%'),
            ("主动练习", str(s["practice_repetitions"]), "点击“完成一次”的累计次数"),
            ("拆词分析", str(s["word_analyses"]), "你主动查询分析过的次数"),
        ]
        for i, (title, number, note) in enumerate(items):
            c = self.card(grid)
            c.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            tk.Label(c, text=title, bg=CARD, fg=MUTED,
                     font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=18, pady=(15, 2))
            tk.Label(c, text=number, bg=CARD, fg=TEXT,
                     font=("Segoe UI", 26, "bold")).pack(anchor="w", padx=18)
            tk.Label(c, text=note, bg=CARD, fg=MUTED,
                     font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18, pady=(0, 15))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        c = self.card()
        c.pack(fill="x", pady=(12, 0))
        tk.Label(c, text="学习诊断", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", padx=20, pady=(16, 8))
        advice = "当前版本将“看见认识”和“主动表达”分开记录。后续将继续增加听力识别、Shadowing、主动回忆和假掌握检测。"
        tk.Label(c, text=advice, wraplength=820, justify="left", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=20, pady=(0, 16))


def main() -> int:
    if "--self-test" in sys.argv:
        r = self_test()
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["status"] == "PASS" else 2
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
