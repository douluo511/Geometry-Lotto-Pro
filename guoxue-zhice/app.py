from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from gui_audit import record_gui_result

from service import APP_NAME, APP_VERSION, create_service, self_test

BG = "#f4f7fb"
CARD = "#ffffff"
BLUE = "#2563eb"
TEXT = "#172033"
MUTED = "#667085"
BORDER = "#dbe3ef"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1040x760")
        self.minsize(920, 680)
        self.configure(bg=BG)
        self.service = create_service()
        self._goal_nav_seq = 0
        self._last_goal_result = None
        self.status_var = tk.StringVar(value="系统就绪 · 原典/解释/边界分层已启用")
        self._configure_style()
        self._build_shell()
        self.show_goal()

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=9)

    def _build_shell(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=34, pady=(22, 8))
        tk.Label(header, text="国学智策系统", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 25, "bold")).pack(anchor="w")
        tk.Label(header, text="经典证据 × 目标推演 × 反例验证 × 行动复盘",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(3, 0))

        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=34, pady=(8, 12))
        items = [
            ("目标推演", self.show_goal),
            ("一键更新", self.run_update),
            ("一键修复", self.run_repair),
            ("高级分析", self.show_analysis),
        ]
        for i, (label, cmd) in enumerate(items):
            b = tk.Button(nav, text=label, command=lambda l=label, c=cmd: self._invoke_gui(l, c), bg=BLUE, fg="white",
                          activebackground="#1d4ed8", activeforeground="white",
                          relief="flat", bd=0, cursor="hand2", height=2,
                          font=("Microsoft YaHei UI", 11, "bold"))
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=6)
        nav.grid_columnconfigure(0, weight=1)
        nav.grid_columnconfigure(1, weight=1)

        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="both", expand=True, padx=34, pady=(0, 12))
        bottom = tk.Frame(self, bg="#eaf0f8")
        bottom.pack(fill="x", side="bottom")
        tk.Label(bottom, textvariable=self.status_var, bg="#eaf0f8", fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=18, pady=7)
        tk.Label(bottom, text=f"v{APP_VERSION}", bg="#eaf0f8", fg=MUTED).pack(side="right", padx=18)

    def _invoke_gui(self, label, callback):
        # Only a navigation callback records a GUI operation; startup is excluded.
        try:
            callback()
            if label == "目标推演":
                result = self._last_goal_result
                ok = isinstance(result, dict) and bool(result.get("methods")) and bool(result.get("five_whys")) and bool(result.get("reverse_validation"))
                record_gui_result(label, "PASS" if ok else "FAIL", {"action": "GOAL_ANALYSIS", "result": result})
            elif label == "高级分析":
                stats = self.service.stats()
                ok = all(isinstance(stats.get(k), int) and stats[k] >= 0 for k in ("classics", "analyses", "reviews", "disputed"))
                record_gui_result(label, "PASS" if ok else "FAIL", {"action": "ADVANCED_ANALYSIS", "stats": stats})
        except Exception as exc:
            record_gui_result(label, "FAIL", {"error": f"{type(exc).__name__}: {exc}"})
            raise

    def _finish_update(self, result=None, error=None):
        if error is not None:
            detail = f"{type(error).__name__}: {error}"
            missing = str(error).startswith("real software-update release config is unavailable;")
            self.status_var.set(f"一键更新 FAIL-CLOSED · {detail}")
            self.update_idletasks()
            record_gui_result("一键更新", "BLOCKED" if missing else "FAIL", {
                "action": "RELEASE_CONFIG_UNAVAILABLE" if missing else "UPDATE_FAILED", "error": detail})
            messagebox.showerror("一键更新失败", detail)
            return
        self.status_var.set(f"一键更新已交接独立 Updater · PID {result['updater_pid']} · 主程序即将关闭")
        self.update_idletasks()
        record_gui_result("一键更新", "PASS", result)
        self.after(700, self.destroy)

    def _finish_repair(self, result=None, error=None):
        if error is not None:
            detail = f"{type(error).__name__}: {error}"
            self.status_var.set(f"一键修复 FAIL · {detail}")
            self.update_idletasks()
            record_gui_result("一键修复", "FAIL", {"action": "REPAIR_FAILED", "error": detail})
            messagebox.showerror("一键修复失败", detail)
            return
        self.status_var.set("一键修复 PASS · 用户数据保留 · 复检通过")
        self.update_idletasks()
        record_gui_result("一键修复", "PASS", {"action": "REPAIR_COMPLETE", "result": result})
        summary = "；".join(f"{name}:{status}" for name, status, _ in result.get("checks", []))
        messagebox.showinfo("一键修复 PASS", summary or "自检通过")

    def clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    def card(self, parent=None):
        return tk.Frame(parent or self.content, bg=CARD, highlightthickness=1, highlightbackground=BORDER)

    def show_goal(self):
        self.clear()
        c = self.card()
        c.pack(fill="both", expand=True)
        tk.Label(c, text="把经典变成可验证的现实分析工具", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w", padx=26, pady=(24, 6))
        tk.Label(c, text="写下你的真实目标。系统会先拆事实、利益、约束与风险，再调用相关经典，并强制给出边界、5 Why 与逆转验证。",
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 10), wraplength=900, justify="left").pack(anchor="w", padx=26)

        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=26, pady=18)
        self.goal_entry = tk.Entry(row, font=("Microsoft YaHei UI", 13), relief="solid", bd=1)
        self.goal_entry.pack(side="left", fill="x", expand=True, ipady=9)
        self.goal_entry.insert(0, "我要和长期合作伙伴谈价格，怎样判断底线、筹码和风险？")
        tk.Button(row, text="开始推演", command=self.analyze_goal, bg=BLUE, fg="white",
                  relief="flat", padx=18, pady=8, font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", padx=(10, 0))

        self.result = tk.Text(c, wrap="word", bg="#fbfcff", fg=TEXT, relief="flat",
                              padx=16, pady=14, font=("Microsoft YaHei UI", 10))
        self.result.pack(fill="both", expand=True, padx=26, pady=(0, 24))
        self.analyze_goal()
        self._goal_nav_seq += 1
        self.title(f"{APP_NAME} v{APP_VERSION} · 目标推演 #{self._goal_nav_seq}")
        self.status_var.set(f"目标推演已打开 · 导航响应 #{self._goal_nav_seq}")
        self.update_idletasks()

    def analyze_goal(self):
        self._last_goal_result = None
        try:
            r = self.service.analyze_goal(self.goal_entry.get())
        except Exception as exc:
            messagebox.showerror("推演失败", str(exc))
            return
        self._last_goal_result = r
        lines = [
            f"目标：{r['goal']}",
            f"识别场景：{' / '.join(r['scenarios'])}",
            "",
            "① 先问事实，不先套经典",
        ]
        lines.extend([f"  • {x}" for x in r["questions"]])
        lines.append("")
        lines.append("② 多经典交叉推演")
        for i, m in enumerate(r["methods"], 1):
            lines.extend([
                f"  {i}. 《{m['title']}》｜{m['method']}",
                f"     用法：{m['prompt']}",
                f"     来源：{m['source_note']}",
                f"     边界：{m['boundary']}",
            ])
            if m.get("authorship_status") != "常规传世文本":
                lines.append(f"     文本提示：{m['authorship_status']}")
        lines.append("")
        lines.append("③ 5 Why")
        lines.extend([f"  • {x}" for x in r["five_whys"]])
        lines.append("")
        lines.append("④ 逆转验证")
        lines.extend([f"  • {x}" for x in r["reverse_validation"]])
        lines.extend(["", f"状态：{r['status']}", f"提示：{r['note']}"])
        self.result.delete("1.0", "end")
        self.result.insert("1.0", "\n".join(lines))
        self.status_var.set("推演完成 · 输出已标记为行动假设，不把经典当圣旨")

    def run_update(self):
        self.title(f"{APP_NAME} v{APP_VERSION} · 一键更新已触发")
        self.status_var.set("正在检查可信软件发布配置并交接独立 Updater…")
        self.update_idletasks()
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            r = self.service.one_click_update()
            if r.get("status") != "PASS" or r.get("action") != "UPDATER_HANDOFF":
                raise RuntimeError(f"Updater handoff did not PASS: {r!r}")
            self.after(0, lambda value=r: self._finish_update(result=value))
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_update(error=error))

    def run_repair(self):
        self.title(f"{APP_NAME} v{APP_VERSION} · 一键修复已触发")
        self.status_var.set("正在检查知识库、状态库与数据完整性…")
        self.update_idletasks()
        threading.Thread(target=self._repair_worker, daemon=True).start()

    def _repair_worker(self):
        try:
            r = self.service.one_click_repair()
            if r.get("status") != "PASS":
                raise RuntimeError(f"repair did not PASS: {r!r}")
            self.after(0, lambda value=r: self._finish_repair(result=value))
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_repair(error=error))

    def run_knowledge_refresh(self):
        self.status_var.set("正在刷新知识库 · 这不是软件更新…")
        self.update_idletasks()
        threading.Thread(target=self._knowledge_refresh_worker, daemon=True).start()

    def _knowledge_refresh_worker(self):
        try:
            r = self.service.refresh_knowledge()
            if r.get("status") != "PASS":
                raise RuntimeError(f"knowledge refresh did not PASS: {r!r}")
            version = r.get("version")
            digest = str(r.get("sha256") or "")
            self.after(0, lambda v=version, d=digest: messagebox.showinfo(
                "知识库刷新 PASS",
                f"知识库版本：{v}\nSHA256：{d[:20]}…"
            ))
            self.after(0, lambda: self.status_var.set("知识库刷新 PASS · 原子提交完成"))
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            self.after(0, lambda d=detail: messagebox.showerror("知识库刷新失败", d))
            self.after(0, lambda d=detail: self.status_var.set(f"知识库刷新 FAIL-CLOSED · {d}"))

    def show_review(self):
        self.clear()
        tk.Label(self.content, text="一键复盘", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(4, 10))
        tk.Label(self.content, text="把“当时怎么想”与“后来发生什么”放在一起，系统才会越来越有用。",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(0, 10))
        c = self.card()
        c.pack(fill="both", expand=True)
        labels = ["当时目标", "实际行动", "实际结果", "下次教训"]
        defaults = ["谈合作时守住利润并保持长期关系", "先问对方预算与替代方案，再报价", "", ""]
        self.review_boxes = []
        for i, label in enumerate(labels):
            tk.Label(c, text=label, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 10, "bold")).grid(row=i, column=0, sticky="nw", padx=18, pady=(16 if i == 0 else 8, 4))
            box = tk.Text(c, height=3 if i > 1 else 2, wrap="word", font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
            box.grid(row=i, column=1, sticky="ew", padx=(0, 18), pady=(12 if i == 0 else 5, 4))
            box.insert("1.0", defaults[i])
            self.review_boxes.append(box)
        c.grid_columnconfigure(1, weight=1)
        tk.Button(c, text="保存复盘", command=self.save_review, bg=BLUE, fg="white", relief="flat",
                  padx=18, pady=8, font=("Microsoft YaHei UI", 10, "bold")).grid(row=4, column=1, sticky="e", padx=18, pady=16)

    def save_review(self):
        try:
            values = [x.get("1.0", "end").strip() for x in self.review_boxes]
            item = self.service.save_review(*values)
            messagebox.showinfo("复盘已保存", f"保存时间：{item['timestamp']}\n以后可在高级分析中统计。")
            self.status_var.set("复盘已保存 · 决策与结果已进入本地审计记录")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def show_analysis(self):
        self.clear()
        s = self.service.stats()
        tk.Label(self.content, text="高级分析", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(4, 12))
        grid = tk.Frame(self.content, bg=BG)
        grid.pack(fill="x")
        items = [
            ("经典条目", s["classics"], "每条都要求来源说明与适用边界"),
            ("目标推演", s["analyses"], "已保存的现实问题分析次数"),
            ("行动复盘", s["reviews"], "把判断和真实结果连接起来"),
            ("争议提示", s["disputed"], "作者/文本归属存在争议的条目"),
        ]
        for i, (title, num, note) in enumerate(items):
            c = self.card(grid)
            c.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            tk.Label(c, text=title, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=18, pady=(14, 2))
            tk.Label(c, text=str(num), bg=CARD, fg=TEXT, font=("Segoe UI", 26, "bold")).pack(anchor="w", padx=18)
            tk.Label(c, text=note, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9), wraplength=390, justify="left").pack(anchor="w", padx=18, pady=(0, 14))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        c = self.card()
        c.pack(fill="x", pady=(12, 0))
        tk.Label(c, text="当前治理规则", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=18, pady=(14, 6))
        rules = "原典 ≠ 后世解释 ≠ 网络鸡汤；任何方法必须给出来源、适用边界与反例入口。涉及健康时，古代文本只作为历史思想材料，不替代现代医学。"
        tk.Label(c, text=rules, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 10), wraplength=880, justify="left").pack(anchor="w", padx=18, pady=(0, 8))

        tools = tk.Frame(c, bg=CARD)
        tools.pack(fill="x", padx=18, pady=(0, 14))
        tk.Button(
            tools, text="行动复盘", command=self.show_review, bg="#475467", fg="white",
            relief="flat", padx=16, pady=7, font=("Microsoft YaHei UI", 10, "bold")
        ).pack(side="left")
        tk.Button(
            tools, text="刷新知识库", command=self.run_knowledge_refresh, bg=BLUE, fg="white",
            relief="flat", padx=16, pady=7, font=("Microsoft YaHei UI", 10, "bold")
        ).pack(side="left", padx=(10, 0))
        self.status_var.set(f"高级分析 · 上次知识库刷新：{s['last_update']}")


def main() -> int:
    if "--self-test" in sys.argv:
        result = self_test()
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if "--result-file" in sys.argv:
            try:
                idx = sys.argv.index("--result-file")
                path = sys.argv[idx + 1]
            except (ValueError, IndexError):
                print(json.dumps({"status": "FAIL", "error": "--result-file requires a path"}, ensure_ascii=False))
                return 2
            from pathlib import Path
            output = Path(path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0 if result["status"] == "PASS" else 2
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
