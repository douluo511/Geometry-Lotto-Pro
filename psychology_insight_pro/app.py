from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from service import PsychologyService, create_service

APP_NAME = "Psychology Insight Pro"
APP_VERSION = "0.3.0"
RAW_BASE = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/psychology_insight_pro"
KNOWLEDGE_URL = RAW_BASE + "/knowledge.json"


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def app_data_dir() -> Path:
    root = Path(os.environ.get("APPDATA", str(Path.home())))
    p = root / "PsychologyInsightPro"
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_service() -> PsychologyService:
    return create_service(
        local_path=app_data_dir() / "knowledge.json",
        bundled_path=resource_path("knowledge.json"),
        knowledge_url=KNOWLEDGE_URL,
    )


def format_result(result) -> str:
    lines = ["=== 心理分析结果 ===", f"总体证据等级：{result.overall_confidence}", "", "【客观观察】"]
    lines += [f"• {o.detail}" for o in result.observations]
    lines += ["", "【竞争假设】"]
    for i, h in enumerate(result.hypotheses[:5], 1):
        lines.append(f"{i}. {h.name}  置信度 {h.confidence:.0%}")
        lines.append(f"   {h.explanation}")
        if h.evidence:
            for e in h.evidence[:4]:
                sign = "+" if e.direction == "support" else "-"
                lines.append(f"   {sign} {e.text}")
        else:
            lines.append("   · 暂无直接关键词证据")
    lines += ["", "【言行/基线一致性】"] + [f"• {x}" for x in result.consistency_notes]
    lines += ["", "【5 Why】"] + [f"• {x}" for x in result.five_whys]
    lines += ["", "【逆转验证】"] + [f"• {x}" for x in result.reverse_validation]
    lines += ["", "【下一步怎么验证】"] + [f"• {x}" for x in result.guidance]
    lines += ["", "【边界说明】", result.disclaimer]
    return "\n".join(lines)


class PsychologyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.service = make_service()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry("1120x760")
        self.minsize(900, 640)
        self.configure(bg="#f5f7fb")
        self.status_var = tk.StringVar(value=f"知识库 {self.service.knowledge['version']} · 系统就绪")
        self._styles()
        self._show_home()

    def _styles(self):
        s = ttk.Style(self)
        try:
            s.theme_use("vista")
        except tk.TclError:
            pass
        s.configure("Title.TLabel", font=("Microsoft YaHei UI", 24, "bold"), background="#f5f7fb")
        s.configure("Sub.TLabel", font=("Microsoft YaHei UI", 10), background="#f5f7fb", foreground="#4b5563")
        s.configure("Action.TButton", font=("Microsoft YaHei UI", 14, "bold"), padding=22)

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _footer(self):
        footer = tk.Frame(self, bg="#e9eef7", height=34)
        footer.pack(side="bottom", fill="x")
        tk.Label(footer, textvariable=self.status_var, bg="#e9eef7", fg="#334155",
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=14, pady=7)
        tk.Label(footer, text="观察事实 ≠ 心理解读 ≠ 内心事实", bg="#e9eef7", fg="#2563eb",
                 font=("Microsoft YaHei UI", 9, "bold")).pack(side="right", padx=14)

    def _show_home(self):
        self._clear()
        self._footer()
        body = tk.Frame(self, bg="#f5f7fb")
        body.pack(fill="both", expand=True, padx=48, pady=38)
        ttk.Label(body, text="Psychology Insight Pro", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="心理洞察 · 多假设竞争 · 证据/反证 · 5 Why · 逆转验证",
                  style="Sub.TLabel").pack(anchor="w", pady=(6, 26))
        grid = tk.Frame(body, bg="#f5f7fb")
        grid.pack(fill="both", expand=True)
        for c in range(2): grid.grid_columnconfigure(c, weight=1)
        for r in range(2): grid.grid_rowconfigure(r, weight=1)

        actions = [
            ("心理分析", self._show_analysis, "从对话/行为中建立竞争心理假设"),
            ("一键更新", self._one_click_update, "真实网络更新知识规则，校验并原子替换"),
            ("一键修复", self._one_click_repair, "检查存储、核心引擎、契约与知识库"),
            ("高级分析", self._show_advanced, "查看架构、证据链与风险边界"),
        ]
        for idx, (title, cmd, desc) in enumerate(actions):
            card = tk.Frame(grid, bg="white", highlightthickness=1, highlightbackground="#dbe3ef")
            card.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=10, pady=10)
            tk.Label(card, text=title, bg="white", fg="#0f172a",
                     font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", padx=22, pady=(25, 6))
            tk.Label(card, text=desc, bg="white", fg="#64748b",
                     font=("Microsoft YaHei UI", 10), wraplength=360, justify="left").pack(anchor="w", padx=22)
            ttk.Button(card, text="打开", style="Action.TButton", command=cmd).pack(anchor="e", padx=22, pady=24)

    def _show_analysis(self):
        self._clear()
        self._footer()
        top = tk.Frame(self, bg="#f5f7fb")
        top.pack(fill="x", padx=28, pady=(20, 8))
        ttk.Button(top, text="← 返回", command=self._show_home).pack(side="left")
        tk.Label(top, text="心理分析", bg="#f5f7fb", fg="#0f172a",
                 font=("Microsoft YaHei UI", 18, "bold")).pack(side="left", padx=14)

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=28, pady=(0, 18))
        left, right = tk.Frame(panes, bg="white"), tk.Frame(panes, bg="white")
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        tk.Label(left, text="当前对话 / 行为 / 事件", bg="white", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        self.input_text = tk.Text(left, wrap="word", height=13, font=("Microsoft YaHei UI", 11), relief="solid", bd=1)
        self.input_text.pack(fill="x", padx=16)
        self.input_text.insert("1.0", "例：最近他回复越来越短，经常说“最近很忙，改天再说”，但偶尔又会主动问我什么时候有空。")

        tk.Label(left, text="过去常态 / 历史基线（可选）", bg="white", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        self.baseline_text = tk.Text(left, wrap="word", height=7, font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
        self.baseline_text.pack(fill="x", padx=16)
        self.baseline_text.insert("1.0", "例：以前通常当天回复，话题会主动延续，也会主动约具体时间。")
        ttk.Button(left, text="开始分析", style="Action.TButton", command=self._run_analysis).pack(anchor="e", padx=16, pady=16)

        tk.Label(right, text="分析报告", bg="white", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        self.result_text = tk.Text(right, wrap="word", font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
        self.result_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.result_text.insert("1.0", "结果会显示多个竞争解释、证据/反证、5 Why、逆转验证与下一步验证。")
        self.result_text.configure(state="disabled")

    def _run_analysis(self):
        try:
            result = self.service.analyze_text(
                self.input_text.get("1.0", "end").strip(),
                self.baseline_text.get("1.0", "end").strip(),
            )
        except Exception as e:
            messagebox.showerror("分析失败", str(e)); return
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", format_result(result))
        self.result_text.configure(state="disabled")
        self.status_var.set(f"分析完成 · 证据等级 {result.overall_confidence} · {datetime.now().strftime('%H:%M:%S')}")

    def _one_click_update(self):
        self.status_var.set("正在通过真实网络检查知识库更新…")
        def worker():
            try:
                r = self.service.update_knowledge()
                proof = f"\nHTTP {r.source.http_status}\nSHA256 {r.source.sha256[:16]}…" if r.source else ""
                self.after(0, lambda: self._notify("一键更新", f"{r.message}\n版本：{r.version}{proof}"))
            except Exception as e:
                self.after(0, lambda: self._notify("一键更新失败", f"当前可用版本保持不变。\n\n{e}", True))
        threading.Thread(target=worker, daemon=True).start()

    def _one_click_repair(self):
        self.status_var.set("正在执行系统自检与修复…")
        def worker():
            try:
                checks = self.service.repair()
                self.after(0, lambda: self._notify("一键修复完成", "\n".join(f"{k}: {v}" for k, v in checks.items())))
            except Exception as e:
                self.after(0, lambda: self._notify("一键修复失败", str(e), True))
        threading.Thread(target=worker, daemon=True).start()

    def _show_advanced(self):
        win = tk.Toplevel(self)
        win.title("高级分析")
        win.geometry("780x640")
        text = tk.Text(win, wrap="word", font=("Microsoft YaHei UI", 10), padx=18, pady=18)
        text.pack(fill="both", expand=True)
        h = self.service.health()
        text.insert("1.0", "\n".join([
            f"{APP_NAME} v{APP_VERSION}",
            f"知识库版本：{h['knowledge_version']}",
            f"竞争假设数：{h['hypothesis_count']}",
            "",
            "运行架构：",
            "UI → Service → Engine / Evidence → Domain",
            "             ↘ Storage",
            "             ↘ NetClient → Real Network",
            "",
            "发布链：",
            "Self-Test → Contract Test → Fault Injection → Real Network → Windows Build → Exact EXE → GUI Smoke → Same Hash → Final Gate",
            "",
            "风险边界：",
            "• 不声称读心、测谎或心理诊断。",
            "• 证据少时必须降置信度。",
            "• 同一行为必须保留竞争解释。",
            "• 不把脆弱点用于胁迫、欺骗或精准操纵。",
        ]))
        text.configure(state="disabled")

    def _notify(self, title, msg, error=False):
        self.status_var.set(msg.splitlines()[0])
        (messagebox.showerror if error else messagebox.showinfo)(title, msg)


def cli_self_test() -> int:
    try:
        health = make_service().health()
        return 0 if all(health.get(k) == "PASS" for k in ("core", "reverse_validation", "confidence_calibration")) else 2
    except Exception:
        return 3


def cli_gui_smoke() -> int:
    try:
        app = PsychologyApp()
        app.update_idletasks()
        app.update()
        ok = APP_NAME in app.title() and len(app.winfo_children()) > 0
        app.destroy()
        return 0 if ok else 4
    except Exception:
        return 5


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(cli_self_test())
    if "--gui-smoke" in sys.argv:
        raise SystemExit(cli_gui_smoke())
    PsychologyApp().mainloop()
