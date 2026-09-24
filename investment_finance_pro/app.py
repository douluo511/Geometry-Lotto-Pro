from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from service import APP_NAME, VERSION, create_service

def write_report(report: dict, path: str | None) -> None:
    target = Path(path or "investment_finance_pro_report.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

def run_gui(smoke: bool = False) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    service = create_service()
    root = tk.Tk()
    root.title(f"{APP_NAME}  {VERSION}")
    root.geometry("1080x700")
    root.minsize(900, 620)
    root.configure(bg="#f5f7fb")

    header = tk.Frame(root, bg="#0b63ce", height=92)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text=APP_NAME, fg="white", bg="#0b63ce",
             font=("Microsoft YaHei UI", 22, "bold")).pack(anchor="w", padx=28, pady=(17, 0))
    tk.Label(header, text="真实数据 · 估值研究 · 风险控制 · 可验证闭环",
             fg="#dbeafe", bg="#0b63ce", font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=30)

    body = tk.Frame(root, bg="#f5f7fb")
    body.pack(fill="both", expand=True, padx=24, pady=20)
    status_var = tk.StringVar(value="状态：尚未更新｜模型：UNVALIDATED")
    tk.Label(body, textvariable=status_var, anchor="w", bg="white", fg="#263238",
             padx=16, pady=10, font=("Microsoft YaHei UI", 10)).pack(fill="x", pady=(0, 14))

    toolbar = tk.Frame(body, bg="#f5f7fb")
    toolbar.pack(fill="x")
    table_frame = tk.Frame(body, bg="white")
    table_frame.pack(fill="both", expand=True, pady=(14, 0))

    columns = ("rank", "symbol", "close", "1d", "mom20", "vol20", "dd60", "state")
    tree = ttk.Treeview(table_frame, columns=columns, show="headings")
    headings = {
        "rank": "#", "symbol": "资产", "close": "价格", "1d": "1日", "mom20": "20日动量",
        "vol20": "20日年化波动", "dd60": "60日回撤", "state": "验证状态",
    }
    widths = {"rank": 45, "symbol": 75, "close": 90, "1d": 90, "mom20": 105, "vol20": 115, "dd60": 105, "state": 205}
    for c in columns:
        tree.heading(c, text=headings[c])
        tree.column(c, width=widths[c], anchor="center")
    tree.pack(side="left", fill="both", expand=True)
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    scroll.pack(side="right", fill="y")
    tree.configure(yscrollcommand=scroll.set)

    def fmt_pct(x):
        return "—" if x is None else f"{float(x) * 100:.2f}%"

    def render(data):
        for item in tree.get_children():
            tree.delete(item)
        if not data:
            return
        for idx, row in enumerate(data.get("ranking", []), start=1):
            tree.insert("", "end", values=(
                idx, row["symbol"], f'{row["close"]:.2f}', fmt_pct(row["change_1d"]),
                fmt_pct(row["momentum_20d"]), fmt_pct(row["volatility_20d_ann"]),
                fmt_pct(row["max_drawdown_60d"]), row.get("status", "UNVALIDATED"),
            ))
        status_var.set(
            f'状态：{data.get("update_state", "UNKNOWN")}｜'
            f'更新时间：{data.get("updated_at_utc", "—")}｜'
            f'模型：{data.get("model_status", "UNVALIDATED")}'
        )

    def action_opportunities():
        data = service.opportunities()
        if not data:
            messagebox.showinfo("投资机会", "还没有数据。请先点击“一键更新”。")
            return
        render(data)
        messagebox.showinfo("研究排序", "当前榜单仅是 UNVALIDATED 研究排序，不是买卖建议。")

    def action_update():
        status_var.set("状态：UPDATING｜正在访问真实网络数据源…")
        def worker():
            try:
                data = service.update_all()
                root.after(0, lambda: render(data))
                root.after(0, lambda: messagebox.showinfo("一键更新", f'更新状态：{data["update_state"]}'))
            except Exception as exc:
                root.after(0, lambda: status_var.set("状态：FAILED｜更新异常"))
                root.after(0, lambda: messagebox.showerror("更新失败", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def action_repair():
        result = service.repair()
        messagebox.showinfo("一键修复", json.dumps(result, ensure_ascii=False, indent=2))

    def action_advanced():
        win = tk.Toplevel(root)
        win.title("高级分析 / 审计")
        win.geometry("820x580")
        text = tk.Text(win, wrap="word", font=("Consolas", 10), padx=12, pady=12)
        text.pack(fill="both", expand=True)
        text.insert("1.0", json.dumps(service.advanced_analysis(), ensure_ascii=False, indent=2))
        text.configure(state="disabled")

    specs = [
        ("投资机会", action_opportunities),
        ("一键更新", action_update),
        ("一键修复", action_repair),
        ("高级分析", action_advanced),
    ]
    for i, (label, command) in enumerate(specs):
        b = tk.Button(toolbar, text=label, command=command, cursor="hand2",
                      font=("Microsoft YaHei UI", 13, "bold"), fg="#0b63ce", bg="white",
                      relief="flat", bd=0, padx=22, pady=18)
        b.grid(row=i // 2, column=i % 2, sticky="nsew", padx=7, pady=7)
        toolbar.grid_columnconfigure(i % 2, weight=1)

    cached = service.opportunities()
    if cached:
        render(cached)

    if smoke:
        checks = {
            "opportunities": True,
            "update_all": service.update_all().get("update_state") in {"PASS", "PARTIAL"},
            "repair": service.repair().get("status") == "PASS",
            "advanced_analysis": bool(service.advanced_analysis()),
        }
        if not all(checks.values()):
            root.destroy()
            return 3
        root.after(1200, root.destroy)

    root.mainloop()
    return 0

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--network-smoke", action="store_true")
    p.add_argument("--gui-smoke", action="store_true")
    p.add_argument("--report", default=None)
    args = p.parse_args()
    service = create_service()
    if args.self_test:
        report = service.self_test()
        write_report(report, args.report)
        return 0 if report["status"] == "PASS" else 1
    if args.network_smoke:
        report = service.network_smoke()
        write_report(report, args.report)
        return 0 if report["status"] == "PASS" else 2
    return run_gui(smoke=args.gui_smoke)

if __name__ == "__main__":
    raise SystemExit(main())
