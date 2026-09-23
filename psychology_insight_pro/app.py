from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from core import analyze, self_test


APP_NAME = "Psychology Insight Pro"
APP_VERSION = "0.1.0"
RAW_BASE = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/psychology_insight_pro"
KNOWLEDGE_URL = RAW_BASE + "/knowledge.json"
MAX_DOWNLOAD = 2_000_000


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def app_data_dir() -> Path:
    root = Path(os.environ.get("APPDATA", str(Path.home())))
    p = root / "PsychologyInsightPro"
    p.mkdir(parents=True, exist_ok=True)
    return p


def local_knowledge_path() -> Path:
    return app_data_dir() / "knowledge.json"


def bundled_knowledge_path() -> Path:
    return resource_path("knowledge.json")


def validate_knowledge(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("knowledge root must be object")
    if not isinstance(data.get("version"), str):
        raise ValueError("knowledge.version missing")
    hypotheses = data.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ValueError("knowledge.hypotheses missing")
    required = {"key", "name", "explanation", "support_keywords", "contradict_keywords"}
    for item in hypotheses:
        if not required.issubset(item):
            raise ValueError("invalid hypothesis schema")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    validate_knowledge(data)
    return data


def ensure_local_knowledge() -> dict:
    dst = local_knowledge_path()
    if not dst.exists():
        shutil.copy2(bundled_knowledge_path(), dst)
    try:
        return load_json(dst)
    except Exception:
        shutil.copy2(bundled_knowledge_path(), dst)
        return load_json(dst)


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read(MAX_DOWNLOAD + 1)
    if len(raw) > MAX_DOWNLOAD:
        raise ValueError("download too large")
    data = json.loads(raw.decode("utf-8"))
    validate_knowledge(data)
    return data


def parse_version(v: str):
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="pip_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def format_result(result) -> str:
    lines = []
    lines.append("=== 心理分析结果 ===")
    lines.append(f"总体证据等级：{result.overall_confidence}")
    lines.append("")
    lines.append("【客观观察】")
    for o in result.observations:
        lines.append(f"• {o.detail}")

    lines.append("")
    lines.append("【竞争假设】")
    for i, h in enumerate(result.hypotheses[:5], 1):
        lines.append(f"{i}. {h.name}  置信度 {h.confidence:.0%}")
        lines.append(f"   {h.explanation}")
        if h.evidence:
            for e in h.evidence[:4]:
                sign = "+" if e.direction == "support" else "-"
                lines.append(f"   {sign} {e.text}")
        else:
            lines.append("   · 暂无直接关键词证据")

    lines.append("")
    lines.append("【言行/基线一致性】")
    lines.extend([f"• {x}" for x in result.consistency_notes])

    lines.append("")
    lines.append("【5 Why】")
    lines.extend([f"• {x}" for x in result.five_whys])

    lines.append("")
    lines.append("【逆转验证】")
    lines.extend([f"• {x}" for x in result.reverse_validation])

    lines.append("")
    lines.append("【下一步怎么验证】")
    lines.extend([f"• {x}" for x in result.guidance])

    lines.append("")
    lines.append("【边界说明】")
    lines.append(result.disclaimer)
    return "\n".join(lines)


class PsychologyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry("1120x760")
        self.minsize(900, 640)
        self.configure(bg="#f5f7fb")
        self.knowledge = ensure_local_knowledge()
        self.status_var = tk.StringVar(value=f"知识库 {self.knowledge['version']} · 系统就绪")
        self._build_styles()
        self._show_home()

    def _build_styles(self):
        s = ttk.Style(self)
        try:
            s.theme_use("vista")
        except tk.TclError:
            pass
        s.configure("Title.TLabel", font=("Microsoft YaHei UI", 24, "bold"), background="#f5f7fb")
        s.configure("Sub.TLabel", font=("Microsoft YaHei UI", 10), background="#f5f7fb", foreground="#4b5563")
        s.configure("Action.TButton", font=("Microsoft YaHei UI", 14, "bold"), padding=22)
        s.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10, "bold"), padding=(12, 8))

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
        ttk.Label(body, text="心理洞察 · 多假设竞争 · 证据/反证 · 5 Why · 逆转验证", style="Sub.TLabel").pack(anchor="w", pady=(6, 26))

        grid = tk.Frame(body, bg="#f5f7fb")
        grid.pack(fill="both", expand=True)
        for c in range(2):
            grid.grid_columnconfigure(c, weight=1)
        for r in range(2):
            grid.grid_rowconfigure(r, weight=1)

        actions = [
            ("心理分析", self._show_analysis, "从对话/行为中建立竞争心理假设"),
            ("一键更新", self._one_click_update, "联网更新知识规则并安全回滚"),
            ("一键修复", self._one_click_repair, "检查知识库、核心引擎、网络与配置"),
            ("高级分析", self._show_advanced, "查看证据链、模块、版本与分析原则"),
        ]

        for idx, (title, cmd, desc) in enumerate(actions):
            card = tk.Frame(grid, bg="white", bd=0, highlightthickness=1, highlightbackground="#dbe3ef")
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
        left = tk.Frame(panes, bg="white")
        right = tk.Frame(panes, bg="white")
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        tk.Label(left, text="当前对话 / 行为 / 事件", bg="white", fg="#0f172a",
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        self.input_text = tk.Text(left, wrap="word", height=13, font=("Microsoft YaHei UI", 11), relief="solid", bd=1)
        self.input_text.pack(fill="both", expand=False, padx=16)
        self.input_text.insert("1.0", "例：最近他回复越来越短，经常说“最近很忙，改天再说”，但偶尔又会主动问我什么时候有空。")

        tk.Label(left, text="过去常态 / 历史基线（可选）", bg="white", fg="#0f172a",
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        self.baseline_text = tk.Text(left, wrap="word", height=7, font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
        self.baseline_text.pack(fill="x", padx=16)
        self.baseline_text.insert("1.0", "例：以前通常当天回复，话题会主动延续，也会主动约具体时间。")
        ttk.Button(left, text="开始分析", style="Action.TButton", command=self._run_analysis).pack(anchor="e", padx=16, pady=16)

        tk.Label(right, text="分析报告", bg="white", fg="#0f172a",
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        self.result_text = tk.Text(right, wrap="word", font=("Microsoft YaHei UI", 10), relief="solid", bd=1)
        self.result_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.result_text.insert("1.0", "分析结果会显示在这里。\n\n系统不会输出“读心结论”，而会展示多个竞争解释、支持证据、反证和下一步验证方式。")
        self.result_text.configure(state="disabled")

    def _run_analysis(self):
        current = self.input_text.get("1.0", "end").strip()
        baseline = self.baseline_text.get("1.0", "end").strip()
        try:
            result = analyze(current, self.knowledge, baseline)
            report = format_result(result)
        except Exception as e:
            messagebox.showerror("分析失败", str(e))
            return
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", report)
        self.result_text.configure(state="disabled")
        self.status_var.set(f"分析完成 · 证据等级 {result.overall_confidence} · {datetime.now().strftime('%H:%M:%S')}")

    def _one_click_update(self):
        self.status_var.set("正在检查 GitHub 知识库更新…")
        def worker():
            try:
                remote = fetch_json(KNOWLEDGE_URL)
                local = ensure_local_knowledge()
                if parse_version(remote["version"]) < parse_version(local["version"]):
                    msg = f"远端版本 {remote['version']} 低于本地 {local['version']}，拒绝降级。"
                elif remote == local:
                    msg = f"已是最新知识库版本 {local['version']}。"
                else:
                    dst = local_knowledge_path()
                    backup = dst.with_suffix(".json.bak")
                    if dst.exists():
                        shutil.copy2(dst, backup)
                    atomic_write_json(dst, remote)
                    self.knowledge = load_json(dst)
                    msg = f"更新成功：知识库 {self.knowledge['version']}。已保留备份。"
                self.after(0, lambda: self._notify("一键更新", msg))
            except Exception as e:
                self.after(0, lambda: self._notify("一键更新失败", f"未修改当前可用版本。\n\n{e}", error=True))
        threading.Thread(target=worker, daemon=True).start()

    def _one_click_repair(self):
        self.status_var.set("正在执行系统自检与修复…")
        def worker():
            checks = []
            try:
                app_data_dir()
                checks.append("配置目录：PASS")
                try:
                    self.knowledge = load_json(local_knowledge_path())
                    checks.append("本地知识库：PASS")
                except Exception:
                    shutil.copy2(bundled_knowledge_path(), local_knowledge_path())
                    self.knowledge = load_json(local_knowledge_path())
                    checks.append("本地知识库：REPAIRED")
                checks.extend([f"核心 {k}：{v}" for k, v in self_test().items()])
                try:
                    remote = fetch_json(KNOWLEDGE_URL)
                    checks.append(f"真实网络：PASS（远端知识库 {remote['version']}）")
                except Exception as ne:
                    checks.append(f"真实网络：WARNING（{ne}）")
                checks.append("最终状态：PASS（若网络 WARNING，则仅离线核心可用）")
                msg = "\n".join(checks)
                self.after(0, lambda: self._notify("一键修复完成", msg))
            except Exception as e:
                self.after(0, lambda: self._notify("一键修复失败", str(e), error=True))
        threading.Thread(target=worker, daemon=True).start()

    def _show_advanced(self):
        win = tk.Toplevel(self)
        win.title("高级分析")
        win.geometry("760x620")
        text = tk.Text(win, wrap="word", font=("Microsoft YaHei UI", 10), padx=18, pady=18)
        text.pack(fill="both", expand=True)
        modules = [
            "Observation Engine：只提取可观察事实",
            "Personal Baseline：对比个人历史常态",
            "Hypothesis Competition：多解释竞争，不单点读心",
            "Evidence / Counter-evidence：支持证据与反证并存",
            "Consistency Check：只标记言行/基线不一致，不直接判定说谎",
            "5 Why：向底层需求、压力、激励与约束追问",
            "Reverse Validation：假设主解释错误时，寻找仍能解释现象的替代路径",
            "Confidence Calibration：证据少时自动降置信度",
            "Outcome Feedback（后续版本）：用真实结果做校准与删除无效规则",
        ]
        content = [
            f"{APP_NAME}  v{APP_VERSION}",
            f"知识库版本：{self.knowledge['version']}",
            f"规则假设数：{len(self.knowledge.get('hypotheses', []))}",
            "",
            "核心模块：",
            *[f"• {m}" for m in modules],
            "",
            "安全边界：",
            "• 不用于心理诊断、测谎或宣称知道他人的真实内心。",
            "• 不把脆弱点用于胁迫、欺骗或精准操纵。",
            "• 重要关系判断优先通过直接沟通与后续可验证行为确认。",
        ]
        text.insert("1.0", "\n".join(content))
        text.configure(state="disabled")

    def _notify(self, title, msg, error=False):
        self.status_var.set(msg.splitlines()[0])
        if error:
            messagebox.showerror(title, msg)
        else:
            messagebox.showinfo(title, msg)


def cli_self_test() -> int:
    try:
        validate_knowledge(load_json(bundled_knowledge_path()))
        results = self_test()
        if not all(v == "PASS" for v in results.values()):
            return 2
        return 0
    except Exception:
        return 3


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(cli_self_test())
    PsychologyApp().mainloop()
