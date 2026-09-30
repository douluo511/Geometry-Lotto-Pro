from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from service import APP_VERSION, create_service, format_report


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def self_test() -> int:
    result = create_service(bundled_path=resource_path("knowledge_base.json")).self_test()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


def run_gui(smoke: bool = False) -> None:
    import tkinter as tk
    from tkinter import messagebox
    from tkinter.scrolledtext import ScrolledText

    BLUE = "#1769E0"
    BG = "#F5F7FB"
    CARD = "#FFFFFF"
    TEXT = "#172033"

    root = tk.Tk()
    root.title(f"Human Nature Pro 人性决策系统 v{APP_VERSION}")
    root.geometry("1060x760")
    root.minsize(900, 680)
    root.configure(bg=BG)

    service = create_service(bundled_path=resource_path("knowledge_base.json"))
    current_result = {"data": None}

    header = tk.Frame(root, bg=BLUE, height=78)
    header.pack(fill="x")
    tk.Label(header, text="Human Nature Pro  人性决策系统", font=("Microsoft YaHei UI", 20, "bold"), fg="white", bg=BLUE).pack(anchor="w", padx=28, pady=(15, 0))
    tk.Label(header, text="事实 → 多假设 → 信息增益 → 策略 → 逆转验证 → Replay", font=("Microsoft YaHei UI", 10), fg="#DCE9FF", bg=BLUE).pack(anchor="w", padx=30, pady=(2, 10))

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=22, pady=16)

    left = tk.Frame(body, bg=CARD, bd=0, highlightthickness=1, highlightbackground="#DCE3EF")
    left.pack(side="left", fill="y", padx=(0, 14))
    right = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground="#DCE3EF")
    right.pack(side="right", fill="both", expand=True)

    tk.Label(left, text="当前局面", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
    situation = ScrolledText(left, width=43, height=14, font=("Microsoft YaHei UI", 10), wrap="word", relief="solid", bd=1)
    situation.pack(padx=16)
    situation.insert("1.0", "例如：客户说价格太高，一直拖延付款。我不知道他是真没预算，还是在试探底价。")

    tk.Label(left, text="你的目标", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(14, 6))
    goal = tk.Entry(left, width=45, font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
    goal.pack(padx=16)
    goal.insert(0, "保证自身利益，同时尽量保留长期合作")

    status = tk.StringVar(value="就绪｜先把事实和推测分开")
    tk.Label(left, textvariable=status, bg=CARD, fg="#5C667A", font=("Microsoft YaHei UI", 9), wraplength=340, justify="left").pack(anchor="w", padx=16, pady=(10, 8))

    result_box = ScrolledText(right, font=("Microsoft YaHei UI", 10), wrap="word", bg="#FBFCFE", fg=TEXT, relief="flat")
    result_box.pack(fill="both", expand=True, padx=16, pady=16)
    result_box.insert("1.0", "输入一个真实局面，然后点击“分析当前局面”。\n\n系统不会直接替别人读心，而会保留多个竞争解释，并告诉你还缺什么证据。")

    def show(text: str):
        result_box.configure(state="normal")
        result_box.delete("1.0", "end")
        result_box.insert("1.0", text)
        result_box.configure(state="disabled")

    def do_analyze():
        try:
            r = service.analyze(situation.get("1.0", "end").strip(), goal.get().strip())
            current_result["data"] = r
            show(format_report(r))
            status.set("分析完成｜已生成竞争假设、策略与逆转验证")
        except Exception as exc:
            messagebox.showerror("分析失败", str(exc))

    def do_update():
        status.set("一键更新中｜正在从 GitHub 获取知识库…")
        def worker():
            try:
                r = service.update_all()
                root.after(0, lambda: status.set(f"更新完成｜知识库 {r['knowledge_version']}"))
                root.after(0, lambda: messagebox.showinfo("一键更新", f"知识库更新成功\n版本：{r['knowledge_version']}"))
            except Exception as exc:
                root.after(0, lambda: status.set("更新失败｜保留本地知识库，不影响分析"))
                root.after(0, lambda: messagebox.showwarning("一键更新", f"联网更新失败：{exc}\n已保留本地知识库。"))
        threading.Thread(target=worker, daemon=True).start()

    def do_repair():
        try:
            r = service.repair()
            status.set(f"修复完成｜{r['action']}")
            messagebox.showinfo("一键修复", "配置与知识库检查完成。若本地知识库损坏，已自动恢复。")
        except Exception as exc:
            messagebox.showerror("修复失败", str(exc))

    def do_advanced():
        if not current_result["data"]:
            do_analyze()
        if not current_result["data"]:
            return
        win = tk.Toplevel(root)
        win.title("高级分析｜Human State / Hypothesis / Validation")
        win.geometry("880x650")
        box = ScrolledText(win, font=("Consolas", 10), wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("1.0", json.dumps(service.advanced_analysis(current_result["data"]), ensure_ascii=False, indent=2))
        box.configure(state="disabled")

    btns = tk.Frame(left, bg=CARD)
    btns.pack(fill="x", padx=16, pady=(6, 16))
    for idx, (label, cmd) in enumerate([
        ("分析当前局面", do_analyze), ("一键更新", do_update),
        ("一键修复", do_repair), ("高级分析", do_advanced),
    ]):
        b = tk.Button(btns, text=label, command=cmd, font=("Microsoft YaHei UI", 10, "bold"), bg=BLUE if idx == 0 else "#EAF1FF", fg="white" if idx == 0 else BLUE, activebackground="#0F57C5", activeforeground="white", relief="flat", padx=10, pady=10, cursor="hand2")
        b.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=4, pady=4)
    btns.grid_columnconfigure(0, weight=1)
    btns.grid_columnconfigure(1, weight=1)

    if smoke:
        service.smoke_actions()
        root.after(1200, root.destroy)
    root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-smoke", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    run_gui(smoke=args.gui_smoke)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
