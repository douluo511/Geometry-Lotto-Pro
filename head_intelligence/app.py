from __future__ import annotations

import argparse
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from head_intelligence.engine import InformationEngine


class HeadIntelligenceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.engine = InformationEngine()
        self.title("Head Intelligence System")
        self.geometry("1000x700")
        self.minsize(860, 600)
        self.configure(bg="#f4f7fb")
        self._build_ui()
        self._render_snapshot(self.engine.load_latest_snapshot())

    def _build_ui(self):
        header = tk.Frame(self, bg="#0b63ce", height=86)
        header.pack(fill="x")
        tk.Label(
            header,
            text="头部信息智能判断系统",
            bg="#0b63ce",
            fg="white",
            font=("Microsoft YaHei UI", 22, "bold"),
        ).pack(anchor="w", padx=24, pady=(16, 0))
        self.status_var = tk.StringVar(value="状态：就绪")
        tk.Label(
            header,
            textvariable=self.status_var,
            bg="#0b63ce",
            fg="#dbeafe",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=26, pady=(2, 12))

        button_area = tk.Frame(self, bg="#f4f7fb")
        button_area.pack(fill="x", padx=22, pady=16)
        for i in range(2):
            button_area.columnconfigure(i, weight=1)

        buttons = [
            ("信息判断", self.show_judgment),
            ("一键更新", self.one_click_update),
            ("一键修复", self.one_click_repair),
            ("高级分析", self.show_advanced),
        ]
        for idx, (label, command) in enumerate(buttons):
            btn = tk.Button(
                button_area,
                text=label,
                command=command,
                height=2,
                bg="white",
                fg="#0f172a",
                activebackground="#e8f1fd",
                font=("Microsoft YaHei UI", 13, "bold"),
                relief="solid",
                bd=1,
                cursor="hand2",
            )
            btn.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=7, pady=7)

        content = tk.Frame(self, bg="#f4f7fb")
        content.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.text = tk.Text(
            content,
            wrap="word",
            font=("Microsoft YaHei UI", 11),
            bg="white",
            fg="#182230",
            relief="flat",
            padx=18,
            pady=18,
        )
        scrollbar = ttk.Scrollbar(content, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def one_click_update(self):
        self.status_var.set("状态：正在执行真实网络更新、验证、去重、排序与快照冻结...")
        self._set_text("正在更新，请保持程序开启。\n\n旧快照会继续保留，只有新更新通过后才原子替换。")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        report = self.engine.one_click_update()
        self.after(0, lambda: self._finish_update(report.to_dict()))

    def _finish_update(self, report: dict):
        if report.get("status") == "PASS":
            self.status_var.set(
                f"状态：更新成功｜原始 {report.get('raw_count', 0)}｜去重后 {report.get('deduped_count', 0)}"
            )
            self._render_snapshot(report)
        else:
            self.status_var.set("状态：更新失败，已保留旧快照")
            self._render_health(report.get("source_health", []), report.get("errors", []))
            messagebox.showwarning("更新未通过", "本次网络更新没有形成有效快照，旧版本未被覆盖。")

    def one_click_repair(self):
        result = self.engine.health_check()
        lines = ["一键修复 / 自检", "", f"总体状态：{result['status']}", f"数据目录：{result['data_dir']}", ""]
        for key, value in result["checks"].items():
            lines.append(f"{key}: {'PASS' if value else 'FAIL'}")
        if result["status"] == "PASS":
            lines.append("\n当前没有发现需要自动修复的本地结构问题。")
        else:
            lines.append("\n检测到问题。建议先执行一键更新；系统不会用损坏快照覆盖有效数据。")
        self._set_text("\n".join(lines))

    def show_judgment(self):
        self._render_snapshot(self.engine.load_latest_snapshot())

    def show_advanced(self):
        snapshot = self.engine.load_latest_snapshot()
        health = self.engine.health_check()
        lines = [
            "高级分析",
            "",
            f"本地健康：{health['status']}",
            f"数据目录：{health['data_dir']}",
        ]
        if not snapshot:
            lines += ["", "尚无有效快照。请先执行“一键更新”。"]
        else:
            lines += [
                f"快照 ID：{snapshot.get('snapshot_id')}",
                f"生成时间：{snapshot.get('generated_at')}",
                f"原始条目：{snapshot.get('raw_count')}",
                f"去重条目：{snapshot.get('deduped_count')}",
                "",
                "来源健康：",
            ]
            for src in snapshot.get("source_health", []):
                lines.append(
                    f"- {src.get('name')}｜{src.get('status')}｜items={src.get('items')}｜"
                    f"hash={str(src.get('raw_hash', ''))[:16]}"
                )
            lines += [
                "",
                "当前版本已经具备：真实 RSS 拉取、原始 Hash、原始文件留存、去重、",
                "新鲜度/来源质量/决策相关度评分、原子快照、失败不覆盖、自检。",
                "",
                "下一阶段：事件聚类、来源依赖图、冲突证据、竞争假设、判断账本、5 Why 与逆转验证。",
            ]
        self._set_text("\n".join(lines))

    def _render_snapshot(self, snapshot: dict | None):
        if not snapshot:
            self._set_text(
                "欢迎使用 Head Intelligence System。\n\n"
                "当前还没有有效快照。点击“一键更新”，系统会从已配置的官方信息源获取真实信息，"
                "保存原始证据并重新计算排序。"
            )
            return
        items = snapshot.get("items", [])
        lines = [
            "当前头部信息判断",
            f"快照：{snapshot.get('snapshot_id', '-')}",
            f"更新时间：{snapshot.get('generated_at', '-')}",
            f"状态：{snapshot.get('status', '-')}",
            "",
        ]
        for idx, item in enumerate(items[:20], 1):
            lines.append(f"{idx}. [{item.get('score', 0):.2f}] {item.get('title', '')}")
            lines.append(f"   来源：{item.get('source_name', '')}")
            lines.append(f"   时间：{item.get('published_at', '')}")
            lines.append(
                f"   证据：{item.get('evidence_status', '')}｜新鲜度 {item.get('freshness', 0):.2f}｜"
                f"决策相关度 {item.get('decision_relevance', 0):.2f}"
            )
            if item.get("link"):
                lines.append(f"   链接：{item.get('link')}")
            lines.append("")
        self._set_text("\n".join(lines))

    def _render_health(self, source_health: list[dict], errors: list[str]):
        lines = ["更新未通过", "", "来源状态："]
        for src in source_health:
            lines.append(f"- {src.get('name')}｜{src.get('status')}｜{src.get('error', '')}")
        if errors:
            lines.append("\n错误：")
            lines.extend(f"- {e}" for e in errors)
        self._set_text("\n".join(lines))

    def _set_text(self, value: str):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--network-smoke-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        result = InformationEngine().self_test()
        return 0 if result["status"] == "PASS" else 1

    if args.network_smoke_test:
        report = InformationEngine().one_click_update(limit_per_source=5)
        return 0 if report.status == "PASS" and report.deduped_count > 0 else 2

    app = HeadIntelligenceApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
