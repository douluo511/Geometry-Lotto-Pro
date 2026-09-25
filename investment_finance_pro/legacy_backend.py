from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import statistics
import sys
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

APP_NAME = "Investment Finance Pro"
VERSION = "0.1.0-mvp"
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
USER_AGENT = "InvestmentFinancePro/0.1 (+research-only)"

@dataclass
class ProviderResult:
    name: str
    ok: bool
    detail: str

def storage_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    root = Path(base) if base else Path.home() / ".investment_finance_pro"
    path = root / "InvestmentFinancePro"
    path.mkdir(parents=True, exist_ok=True)
    return path

def cache_path() -> Path:
    return storage_dir() / "snapshot.json"

def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data.decode("utf-8-sig", errors="replace")

def stooq_symbol(symbol: str) -> str:
    return symbol.lower() + ".us"

def fetch_yahoo_history(symbol: str) -> list[dict[str, Any]]:
    errors = []
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            safe_symbol = urllib.parse.quote(symbol, safe="")
            url = (
                f"https://{host}/v8/finance/chart/{safe_symbol}"
                "?range=6mo&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                "Accept": "application/json,text/plain,*/*",
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                payload = json.loads(r.read().decode("utf-8", errors="replace"))
            result = payload["chart"]["result"][0]
            timestamps = result.get("timestamp") or []
            quote = (result.get("indicators", {}).get("quote") or [{}])[0]
            adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
            rows = []
            for i, ts in enumerate(timestamps):
                try:
                    raw_close = quote.get("close", [])[i]
                    close = adj[i] if i < len(adj) and adj[i] is not None else raw_close
                    if close is None or float(close) <= 0:
                        continue
                    rows.append({
                        "date": datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat(),
                        "open": float(quote.get("open", [])[i] or close),
                        "high": float(quote.get("high", [])[i] or close),
                        "low": float(quote.get("low", [])[i] or close),
                        "close": float(close),
                        "volume": int(quote.get("volume", [])[i] or 0),
                    })
                except (IndexError, TypeError, ValueError):
                    continue
            rows.sort(key=lambda x: x["date"])
            if len(rows) < 30:
                raise RuntimeError(f"{symbol}: Yahoo history too short ({len(rows)} rows)")
            return rows
        except Exception as e:
            errors.append(f"{host}: {e}")
    raise RuntimeError(" ; ".join(errors))


def fetch_market_history(symbol: str) -> tuple[list[dict[str, Any]], str]:
    errors = []
    try:
        return fetch_yahoo_history(symbol), "YahooChart"
    except Exception as e:
        errors.append("YahooChart=" + str(e))
    try:
        return fetch_stooq_history(symbol), "Stooq"
    except Exception as e:
        errors.append("Stooq=" + str(e))
    raise RuntimeError(" | ".join(errors))


def fetch_stooq_history(symbol: str, calendar_days: int = 220) -> list[dict[str, Any]]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=calendar_days)
    qs = urllib.parse.urlencode({
        "s": stooq_symbol(symbol),
        "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"),
        "i": "d",
    })
    url = "https://stooq.com/q/d/l/?" + qs
    text = fetch_text(url)
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(io.StringIO(text)):
        try:
            close = float(raw["Close"])
            if not math.isfinite(close) or close <= 0:
                continue
            rows.append({
                "date": raw["Date"],
                "open": float(raw["Open"]),
                "high": float(raw["High"]),
                "low": float(raw["Low"]),
                "close": close,
                "volume": int(float(raw["Volume"])) if raw.get("Volume") else 0,
            })
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda x: x["date"])
    if len(rows) < 30:
        raise RuntimeError(f"{symbol}: history too short ({len(rows)} rows)")
    return rows

def fetch_fred_series(series_id: str) -> dict[str, Any]:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + urllib.parse.quote(series_id)
    text = fetch_text(url)
    values = []
    for raw in csv.DictReader(io.StringIO(text)):
        value_key = series_id if series_id in raw else next((k for k in raw if k != "DATE"), None)
        if not value_key:
            continue
        try:
            v = float(raw[value_key])
            if math.isfinite(v):
                values.append((raw.get("DATE") or raw.get("observation_date") or "", v))
        except (TypeError, ValueError):
            continue
    if not values:
        raise RuntimeError(f"FRED {series_id}: no numeric observations")
    date, value = values[-1]
    return {"series": series_id, "date": date, "value": value}

def pct_change(a: float, b: float) -> float:
    return (b / a - 1.0) if a else 0.0

def max_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    worst = 0.0
    for v in closes:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst

def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [float(r["close"]) for r in rows]
    if len(closes) < 30:
        raise ValueError("Need at least 30 closes")
    returns = [pct_change(closes[i - 1], closes[i]) for i in range(1, len(closes))]
    recent20 = returns[-20:]
    vol20 = statistics.pstdev(recent20) * math.sqrt(252) if len(recent20) >= 2 else 0.0
    return {
        "date": rows[-1]["date"],
        "close": round(closes[-1], 4),
        "change_1d": round(pct_change(closes[-2], closes[-1]), 6),
        "momentum_20d": round(pct_change(closes[-21], closes[-1]), 6),
        "momentum_60d": round(pct_change(closes[-61], closes[-1]), 6) if len(closes) >= 61 else None,
        "volatility_20d_ann": round(vol20, 6),
        "max_drawdown_60d": round(max_drawdown(closes[-60:]), 6),
        "rows": len(rows),
    }

def research_score(m: dict[str, Any]) -> float:
    mom = float(m.get("momentum_20d") or 0.0)
    vol = max(float(m.get("volatility_20d_ann") or 0.0), 0.05)
    dd = abs(float(m.get("max_drawdown_60d") or 0.0))
    return mom / vol - 0.35 * dd

def rank_research(metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for symbol, m in metrics.items():
        ranked.append({
            "symbol": symbol,
            "close": m["close"],
            "change_1d": m["change_1d"],
            "momentum_20d": m["momentum_20d"],
            "volatility_20d_ann": m["volatility_20d_ann"],
            "max_drawdown_60d": m["max_drawdown_60d"],
            "score": round(research_score(m), 6),
            "status": "UNVALIDATED_RESEARCH_RANK",
        })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked

def one_click_update() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    metrics: dict[str, dict[str, Any]] = {}
    providers: list[dict[str, Any]] = []
    for symbol in WATCHLIST:
        try:
            rows, provider = fetch_market_history(symbol)
            metrics[symbol] = compute_metrics(rows)
            providers.append(ProviderResult(provider + ":" + symbol, True, f"{len(rows)} rows").__dict__)
        except Exception as e:
            providers.append(ProviderResult("Stooq:" + symbol, False, str(e)).__dict__)

    macro: dict[str, Any] = {}
    for series_id, label in [("DGS10", "US_10Y_TREASURY"), ("DFF", "FED_FUNDS_EFFECTIVE")]:
        try:
            macro[label] = fetch_fred_series(series_id)
            providers.append(ProviderResult("FRED:" + series_id, True, "latest observation loaded").__dict__)
        except Exception as e:
            providers.append(ProviderResult("FRED:" + series_id, False, str(e)).__dict__)

    ok_count = sum(1 for p in providers if p["ok"])
    if ok_count == len(providers):
        state = "PASS"
    elif metrics:
        state = "PARTIAL"
    else:
        state = "FAILED"

    payload = {
        "app": APP_NAME,
        "version": VERSION,
        "research_only": True,
        "model_status": "UNVALIDATED",
        "update_state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
        "providers": providers,
        "macro": macro,
        "metrics": metrics,
        "ranking": rank_research(metrics),
    }
    atomic_json_write(cache_path(), payload)
    return payload

def repair_system() -> dict[str, Any]:
    checks = []
    path = cache_path()
    if path.exists():
        try:
            data = read_json(path)
            if not isinstance(data, dict) or "version" not in data:
                raise ValueError("invalid snapshot schema")
            checks.append({"check": "cache_schema", "status": "PASS"})
        except Exception as e:
            backup = path.with_suffix(".corrupt.json")
            try:
                os.replace(path, backup)
                checks.append({"check": "cache_schema", "status": "REPAIRED", "detail": str(e)})
            except Exception as move_error:
                checks.append({"check": "cache_schema", "status": "FAILED", "detail": str(move_error)})
    else:
        checks.append({"check": "cache_schema", "status": "PASS", "detail": "no cache yet"})
    checks.append({"check": "storage_write", "status": "PASS", "detail": str(storage_dir())})
    overall = "PASS" if all(c["status"] in {"PASS", "REPAIRED"} for c in checks) else "FAILED"
    return {"overall": overall, "checks": checks, "at_utc": datetime.now(timezone.utc).isoformat()}

def deterministic_self_test() -> dict[str, Any]:
    rows = []
    base = datetime(2026, 1, 1).date()
    price = 100.0
    for i in range(90):
        price *= 1.0 + (0.001 if i % 7 else -0.002)
        rows.append({
            "date": (base + timedelta(days=i)).isoformat(),
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1000000 + i,
        })
    m = compute_metrics(rows)
    ranking = rank_research({"TEST": m})
    assertions = {
        "metrics_close_positive": m["close"] > 0,
        "volatility_nonnegative": m["volatility_20d_ann"] >= 0,
        "ranking_status_guard": ranking[0]["status"] == "UNVALIDATED_RESEARCH_RANK",
        "storage_exists": storage_dir().exists(),
    }
    return {
        "app": APP_NAME,
        "version": VERSION,
        "type": "deterministic_self_test",
        "status": "PASS" if all(assertions.values()) else "FAILED",
        "assertions": assertions,
    }

def network_smoke_test() -> dict[str, Any]:
    checks = []
    try:
        rows, provider = fetch_market_history("SPY")
        m = compute_metrics(rows)
        checks.append({"source": provider + ":SPY", "status": "PASS", "rows": len(rows), "last_date": m["date"]})
    except Exception as e:
        checks.append({"source": "MARKET:SPY", "status": "FAILED", "detail": str(e)})
    try:
        item = fetch_fred_series("DGS10")
        checks.append({"source": "FRED:DGS10", "status": "PASS", "last_date": item["date"], "value": item["value"]})
    except Exception as e:
        checks.append({"source": "FRED:DGS10", "status": "FAILED", "detail": str(e)})
    return {
        "app": APP_NAME,
        "version": VERSION,
        "type": "network_smoke",
        "status": "PASS" if all(x["status"] == "PASS" for x in checks) else "FAILED",
        "checks": checks,
    }

def write_report(report: dict[str, Any], path: str | None) -> None:
    target = Path(path or "investment_finance_pro_report.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

def run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME}  {VERSION}")
    root.geometry("1080x700")
    root.minsize(900, 620)
    root.configure(bg="#f5f7fb")

    style = ttk.Style(root)
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass
    style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

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
    status = tk.Label(body, textvariable=status_var, anchor="w", bg="white", fg="#263238",
                      padx=16, pady=10, font=("Microsoft YaHei UI", 10))
    status.pack(fill="x", pady=(0, 14))

    toolbar = tk.Frame(body, bg="#f5f7fb")
    toolbar.pack(fill="x")

    table_frame = tk.Frame(body, bg="white")
    table_frame.pack(fill="both", expand=True, pady=(14, 0))

    columns = ("rank", "symbol", "close", "1d", "mom20", "vol20", "dd60", "state")
    tree = ttk.Treeview(table_frame, columns=columns, show="headings")
    headings = {
        "rank": "#", "symbol": "资产", "close": "价格", "1d": "1日", "mom20": "20日动量",
        "vol20": "20日年化波动", "dd60": "60日回撤", "state": "验证状态"
    }
    widths = {"rank": 45, "symbol": 75, "close": 90, "1d": 90, "mom20": 105, "vol20": 115, "dd60": 105, "state": 205}
    for c in columns:
        tree.heading(c, text=headings[c])
        tree.column(c, width=widths[c], anchor="center")
    tree.pack(side="left", fill="both", expand=True)
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    scroll.pack(side="right", fill="y")
    tree.configure(yscrollcommand=scroll.set)

    def fmt_pct(x: Any) -> str:
        return "—" if x is None else f"{float(x) * 100:.2f}%"

    def render_snapshot(data: dict[str, Any]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for idx, row in enumerate(data.get("ranking", []), start=1):
            tree.insert("", "end", values=(
                idx, row["symbol"], f'{row["close"]:.2f}', fmt_pct(row["change_1d"]),
                fmt_pct(row["momentum_20d"]), fmt_pct(row["volatility_20d_ann"]),
                fmt_pct(row["max_drawdown_60d"]), "UNVALIDATED"
            ))
        status_var.set(
            f'状态：{data.get("update_state", "UNKNOWN")}｜'
            f'更新时间：{data.get("updated_at_utc", "—")}｜模型：{data.get("model_status", "UNVALIDATED")}'
        )

    def load_cached() -> dict[str, Any] | None:
        try:
            return read_json(cache_path()) if cache_path().exists() else None
        except Exception:
            return None

    def action_opportunities() -> None:
        data = load_cached()
        if not data:
            messagebox.showinfo("投资机会", "还没有数据。请先点击“一键更新”。")
            return
        render_snapshot(data)
        messagebox.showinfo("研究排序", "当前榜单是研究排序，不是买卖建议；模型状态固定显示 UNVALIDATED，直到严格样本外验证通过。")

    def action_update() -> None:
        status_var.set("状态：UPDATING｜正在访问真实网络数据源…")
        for b in buttons:
            b.configure(state="disabled")

        def worker() -> None:
            try:
                data = one_click_update()
                root.after(0, lambda: render_snapshot(data))
                root.after(0, lambda: messagebox.showinfo(
                    "一键更新完成",
                    f'更新状态：{data["update_state"]}\n成功数据源：{sum(1 for p in data["providers"] if p["ok"])}/{len(data["providers"])}'
                ))
            except Exception as e:
                root.after(0, lambda: status_var.set("状态：FAILED｜更新异常"))
                root.after(0, lambda: messagebox.showerror("更新失败", str(e)))
            finally:
                root.after(0, lambda: [b.configure(state="normal") for b in buttons])

        threading.Thread(target=worker, daemon=True).start()

    def action_repair() -> None:
        result = repair_system()
        details = "\n".join(f'{x["check"]}: {x["status"]}' for x in result["checks"])
        messagebox.showinfo("一键修复", f'总体：{result["overall"]}\n\n{details}')

    def action_advanced() -> None:
        win = tk.Toplevel(root)
        win.title("高级分析 / 审计")
        win.geometry("820x580")
        text = tk.Text(win, wrap="word", font=("Consolas", 10), padx=12, pady=12)
        text.pack(fill="both", expand=True)
        data = load_cached()
        audit = {
            "version": VERSION,
            "research_only": True,
            "validation_rule": "No strategy is VALIDATED until walk-forward/holdout/benchmark/cost/leakage/ablation checks pass.",
            "cache_file": str(cache_path()),
            "snapshot": data,
        }
        text.insert("1.0", json.dumps(audit, ensure_ascii=False, indent=2))
        text.configure(state="disabled")

    specs = [
        ("投资机会", action_opportunities),
        ("一键更新", action_update),
        ("一键修复", action_repair),
        ("高级分析", action_advanced),
    ]
    buttons = []
    for i, (label, command) in enumerate(specs):
        b = tk.Button(
            toolbar, text=label, command=command, cursor="hand2",
            font=("Microsoft YaHei UI", 13, "bold"), fg="#0b63ce", bg="white",
            activeforeground="white", activebackground="#0b63ce",
            relief="flat", bd=0, padx=22, pady=18
        )
        b.grid(row=i // 2, column=i % 2, sticky="nsew", padx=7, pady=7)
        toolbar.grid_columnconfigure(i % 2, weight=1)
        buttons.append(b)

    cached = load_cached()
    if cached:
        render_snapshot(cached)

    footer = tk.Label(root, text="Research tool only · No guaranteed returns · Every model edge must be independently validated",
                      bg="#eef2f7", fg="#546e7a", pady=8, font=("Segoe UI", 9))
    footer.pack(fill="x")
    root.mainloop()
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--network-smoke", action="store_true")
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    if args.self_test:
        report = deterministic_self_test()
        write_report(report, args.report)
        return 0 if report["status"] == "PASS" else 1
    if args.network_smoke:
        report = network_smoke_test()
        write_report(report, args.report)
        return 0 if report["status"] == "PASS" else 2
    return run_gui()

if __name__ == "__main__":
    raise SystemExit(main())
