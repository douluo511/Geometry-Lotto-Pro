
from __future__ import annotations
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import re
import threading
import time
import pandas as pd
import numpy as np
import requests

from .config import ROOT, load_config
from .netclient import AkShareProxy, NetClientError, RetryableHTTPError
from .utils import write_json, now_iso

def _ak():
    try:
        import akshare as ak
        return AkShareProxy(
            ak,
            (load_config().get("network", {}) or {}),
            ROOT / "evidence" / "netclient_raw.jsonl",
        )
    except Exception as e:
        raise RuntimeError(
            "AkShare 未安装或导入失败。请运行 FIRST_TIME_SETUP.bat 或 REPAIR_ENV.bat。"
        ) from e

def _clean_code(s: str) -> str:
    text = str(s).strip()
    m = re.search(r"(\d{6})$", text)
    if m:
        return m.group(1)
    digits = re.sub(r"\D", "", text)
    return digits[-6:].zfill(6)

def _is_a_share_code(code: str, include_bj=False) -> bool:
    c = _clean_code(code)
    if c.startswith(("000","001","002","003","300","301","600","601","603","605","688")):
        return True
    if include_bj and c.startswith(("4","8")):
        return True
    return False

def _filter_universe(df: pd.DataFrame, cfg: dict, allow_st=False) -> pd.DataFrame:
    x = df.copy()
    x["code"] = x["code"].map(_clean_code)
    include_bj = bool(cfg["universe"].get("include_bj", False))
    x = x[x["code"].map(lambda c: _is_a_share_code(c, include_bj))]
    if cfg["universe"].get("exclude_st", True) and "name" in x and not allow_st:
        x = x[~x["name"].astype(str).str.upper().str.contains("ST", na=False)]
    return x.drop_duplicates("code").reset_index(drop=True)

def _parse_delist(df, code_candidates, name_candidates, list_candidates, delist_candidates):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["code","name","list_date","delist_date"])
    cols = list(df.columns)
    def pick(cands, default=None):
        for c in cands:
            if c in cols:
                return c
        return default
    cc = pick(code_candidates, cols[0])
    nc = pick(name_candidates, cols[1] if len(cols) > 1 else cols[0])
    lc = pick(list_candidates)
    dc = pick(delist_candidates)
    out = pd.DataFrame({"code": df[cc].astype(str), "name": df[nc].astype(str)})
    out["list_date"] = pd.to_datetime(df[lc], errors="coerce") if lc else pd.NaT
    out["delist_date"] = pd.to_datetime(df[dc], errors="coerce") if dc else pd.NaT
    return out

def fetch_delisted_universe(cfg: dict, logger=None) -> pd.DataFrame:
    if not cfg["universe"].get("include_delisted_research", True):
        return pd.DataFrame(columns=["code","name","list_date","delist_date","status"])
    ak = _ak()
    parts = []
    try:
        sz = ak.stock_info_sz_delist(symbol="终止上市公司")
        parts.append(_parse_delist(
            sz, ["证券代码","代码"], ["证券简称","名称"], ["上市日期"], ["终止上市日期"]
        ))
    except Exception as e:
        if logger:
            logger.warning("深市退市清单获取失败: %s", e)
    try:
        sh = ak.stock_info_sh_delist(symbol="全部")
        parts.append(_parse_delist(
            sh, ["公司代码","证券代码","代码"], ["公司简称","证券简称","名称"],
            ["上市日期"], ["暂停上市日期","终止上市日期"]
        ))
    except Exception as e:
        if logger:
            logger.warning("沪市退市清单获取失败: %s", e)

    if not parts:
        cached = ROOT / "cache" / "delisted_master.csv"
        if cached.exists():
            return pd.read_csv(
                cached, dtype={"code": str}, parse_dates=["list_date","delist_date"]
            )
        return pd.DataFrame(columns=["code","name","list_date","delist_date","status"])

    out = pd.concat(parts, ignore_index=True)
    out = _filter_universe(out, cfg, allow_st=True)
    start = pd.to_datetime(
        str(cfg["universe"].get("history_start","20180101")),
        format="%Y%m%d", errors="coerce"
    )
    if pd.notna(start):
        out = out[out["delist_date"].isna() | (out["delist_date"] >= start)]
    out["status"] = "delisted"
    out["retrieved_at"] = now_iso()
    out.to_csv(ROOT / "cache" / "delisted_master.csv", index=False, encoding="utf-8-sig")
    return out.reset_index(drop=True)

def _current_universe_from_spot(ak, cfg: dict, logger=None) -> pd.DataFrame:
    errors = []
    providers = [
        ("eastmoney_spot", ak.stock_zh_a_spot_em),
        ("sina_spot", ak.stock_zh_a_spot),
    ]
    for provider, getter in providers:
        try:
            df = getter()
            cols = list(df.columns)
            code_col = next(
                (x for x in cols if str(x).lower() in {"code","证券代码","股票代码","代码"}),
                None,
            )
            name_col = next(
                (x for x in cols if str(x).lower() in {"name","证券简称","股票简称","名称"}),
                None,
            )
            if code_col is None or name_col is None:
                raise RuntimeError(f"{provider} 缺少 code/name 字段")
            current = df[[code_col, name_col]].rename(
                columns={code_col:"code", name_col:"name"}
            )
            current["code"] = current["code"].map(_clean_code)
            current = _filter_universe(current, cfg, allow_st=True)
            if current.empty:
                raise RuntimeError(f"{provider} 当前股票清单为空")
            current["list_date"] = pd.NaT
            current["delist_date"] = pd.NaT
            current["status"] = "current"
            current["universe_provider"] = provider
            return current.reset_index(drop=True)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            if logger:
                logger.warning("当前股票清单备用源 %s 失败: %s", provider, exc)
    raise RuntimeError("实时股票清单主备源均失败: " + " | ".join(errors))


def fetch_full_universe(cfg: dict, logger=None) -> pd.DataFrame:
    ak = _ak()
    primary_error = None
    try:
        df = ak.stock_info_a_code_name()
        cols = list(df.columns)
        code_col = next(
            (c for c in cols if str(c).lower() in {"code","证券代码","股票代码","代码"}),
            cols[0]
        )
        name_col = next(
            (c for c in cols if str(c).lower() in {"name","证券简称","股票简称","名称"}),
            cols[1] if len(cols) > 1 else cols[0]
        )
        current = df[[code_col,name_col]].rename(
            columns={code_col:"code", name_col:"name"}
        )
        # 研究主表保留当前 ST；实时选股池仍按配置排除
        current = _filter_universe(current, cfg, allow_st=True)
        current["list_date"] = pd.NaT
        current["delist_date"] = pd.NaT
        current["status"] = "current"
        current["universe_provider"] = "exchange_list_aggregate"
    except Exception as e:
        primary_error = e
        if logger:
            logger.warning("交易所股票清单聚合失败，尝试实时全量行情源: %s", e)
        try:
            current = _current_universe_from_spot(ak, cfg, logger)
        except Exception as fallback_error:
            cached = ROOT / "cache" / "universe_master.csv"
            if cached.exists():
                if logger:
                    logger.warning(
                        "当前股票清单实时主备源均失败，使用已验证缓存: primary=%s fallback=%s",
                        primary_error,
                        fallback_error,
                    )
                return pd.read_csv(
                    cached, dtype={"code":str}, parse_dates=["list_date","delist_date"]
                )
            raise RuntimeError(
                f"无法取得A股股票清单: primary={primary_error} | fallback={fallback_error}"
            ) from fallback_error

    delisted = fetch_delisted_universe(cfg, logger)
    out = pd.concat([current, delisted], ignore_index=True, sort=False)
    out["priority"] = out["status"].map({"current":0,"delisted":1}).fillna(2)
    out = (
        out.sort_values(["code","priority"])
           .drop_duplicates("code", keep="first")
           .drop(columns=["priority"])
    )
    out["retrieved_at"] = now_iso()
    out.to_csv(ROOT / "cache" / "universe_master.csv", index=False, encoding="utf-8-sig")
    return out.reset_index(drop=True)

def _normalize_spot(df: pd.DataFrame, cfg: dict, provider: str) -> pd.DataFrame:
    rename = {
        "代码":"code","名称":"name","最新价":"price","涨跌幅":"pct_chg",
        "成交量":"volume","成交额":"amount","换手率":"turnover_rate",
        "市盈率-动态":"pe_dynamic","市净率":"pb","总市值":"market_cap",
        "流通市值":"float_market_cap","60日涨跌幅":"ret60_snapshot",
        "年初至今涨跌幅":"ytd"
    }
    x = df.rename(columns=rename).copy()
    if "code" not in x or "name" not in x:
        raise RuntimeError(f"{provider} 实时行情缺少 code/name")
    x["code"] = x["code"].map(_clean_code)

    for c in ["price","pct_chg","volume","amount","turnover_rate","pe_dynamic","pb",
              "market_cap","float_market_cap","ret60_snapshot","ytd"]:
        if c in x:
            x[c] = pd.to_numeric(x[c], errors="coerce")

    # 统一成交量为“股”。东财接口单位为“手”，新浪为“股”。
    if provider == "eastmoney" and "volume" in x:
        x["volume"] = x["volume"] * 100.0

    x = _filter_universe(x, cfg)
    x["spot_provider"] = provider
    return x

def fetch_market_snapshot(cfg: dict, logger=None) -> pd.DataFrame:
    ak = _ak()
    errors = []
    x = None

    try:
        x = _normalize_spot(ak.stock_zh_a_spot_em(), cfg, "eastmoney")
    except Exception as e:
        errors.append(f"eastmoney: {e}")
        if logger:
            logger.warning("东财实时行情失败，尝试新浪备用源: %s", e)

    if x is None or x.empty:
        try:
            x = _normalize_spot(ak.stock_zh_a_spot(), cfg, "sina")
            # 新浪批量行情不含 PE/PB/市值，保留为空；这些字段仅展示，不进历史模型。
            for c in ["turnover_rate","pe_dynamic","pb","market_cap","float_market_cap",
                      "ret60_snapshot","ytd"]:
                if c not in x:
                    x[c] = np.nan
        except Exception as e:
            errors.append(f"sina: {e}")
            raise RuntimeError("实时行情主备源均失败: " + " | ".join(errors)) from e

    min_amount = float(cfg["universe"].get("min_turnover_cny", 0))
    if "amount" not in x:
        raise RuntimeError("实时行情缺少成交额 amount，拒绝生成股票池")
    x = x[x["amount"].fillna(0) >= min_amount].sort_values("amount", ascending=False)
    top_n = int(cfg["universe"].get("live_top_n", 300))
    if top_n > 0:
        x = x.head(top_n)
    return x.reset_index(drop=True)

def _normalize_hist(df: pd.DataFrame, code: str, adjust_mode: str, provider: str) -> pd.DataFrame:
    """
    Canonical history schema:
      volume         = shares
      amount         = CNY
      turnover_rate  = fraction (0.01 = 1%)
    """
    if provider == "eastmoney":
        rename = {
            "日期":"date","股票代码":"code","开盘":"open","收盘":"close",
            "最高":"high","最低":"low","成交量":"volume","成交额":"amount",
            "振幅":"amplitude","涨跌幅":"pct_chg","涨跌额":"chg",
            "换手率":"turnover_rate"
        }
        x = df.rename(columns=rename).copy()
        # 东财成交量=手，换手率=百分数
        if "volume" in x:
            x["volume"] = pd.to_numeric(x["volume"], errors="coerce") * 100.0
        if "turnover_rate" in x:
            x["turnover_rate"] = pd.to_numeric(x["turnover_rate"], errors="coerce") / 100.0
    elif provider == "tencent":
        # 腾讯: volume=股, amount=元, turnover=小数换手率
        x = df.copy()
        if "turnover" in x and "turnover_rate" not in x:
            x = x.rename(columns={"turnover":"turnover_rate"})
    else:
        raise ValueError(f"unknown provider: {provider}")

    basic = {
        "date":"date","open":"open","close":"close","high":"high","low":"low",
        "volume":"volume","amount":"amount","turnover_rate":"turnover_rate"
    }
    x = x.rename(columns={k:v for k,v in basic.items() if k in x.columns}).copy()

    if "date" not in x or "close" not in x:
        raise RuntimeError(f"{code} 历史行情字段异常 ({provider})")

    x["date"] = pd.to_datetime(x["date"], errors="coerce")
    x["code"] = code
    x["adjust_mode"] = adjust_mode or "none"
    x["provider"] = provider
    x["schema_version"] = 3

    for c in ["open","close","high","low","volume","amount","amplitude",
              "pct_chg","chg","turnover_rate"]:
        if c in x:
            x[c] = pd.to_numeric(x[c], errors="coerce")

    keep = [c for c in [
        "date","code","open","close","high","low","volume","amount",
        "amplitude","pct_chg","chg","turnover_rate","adjust_mode",
        "provider","schema_version"
    ] if c in x]
    x = (
        x[keep]
        .dropna(subset=["date","close"])
        .drop_duplicates("date")
        .sort_values("date")
    )
    if x.empty:
        raise RuntimeError(f"{code} 历史行情为空")
    if (x["close"] <= 0).any():
        raise RuntimeError(f"{code} 历史价格出现非正值")
    if "amount" in x and (x["amount"].dropna() < 0).any():
        raise RuntimeError(f"{code} 历史成交额出现负值")
    return x

def _market_prefix(code: str) -> str:
    return ("sh" if str(code).startswith(("6","9")) else
            "bj" if str(code).startswith(("4","8")) else "sz")

def _fetch_history_primary(ak, code, start, end, adjust, timeout=15):
    raw = ak.stock_zh_a_hist(
        symbol=code, period="daily", start_date=start, end_date=end,
        adjust=adjust, timeout=timeout
    )
    return _normalize_hist(raw, code, adjust, "eastmoney")

def _fetch_history_fallback(ak, code, start, end, adjust, timeout=15):
    raw = ak.stock_zh_a_hist_tx(
        symbol=_market_prefix(code) + code,
        start_date=start, end_date=end, adjust=adjust, timeout=timeout
    )
    return _normalize_hist(raw, code, adjust, "tencent")

def _upgrade_legacy_history(old: pd.DataFrame) -> pd.DataFrame:
    """
    Upgrade v2.x cache to canonical v3 units:
      volume=shares, amount=CNY, turnover_rate=fraction.
    v2.x successful historical files were normally Eastmoney:
      volume was hands and turnover_rate was percent.
    """
    x = old.copy()
    legacy = "schema_version" not in x or pd.to_numeric(
        x.get("schema_version", pd.Series([2])), errors="coerce"
    ).fillna(2).max() < 3

    if "amount" not in x and "turnover" in x:
        x = x.rename(columns={"turnover":"amount"})

    if legacy:
        provider = (
            x["provider"].astype(str).str.lower()
            if "provider" in x else pd.Series(["eastmoney"] * len(x), index=x.index)
        )
        em = provider.eq("eastmoney")
        if "volume" in x:
            vol = pd.to_numeric(x["volume"], errors="coerce")
            vol.loc[em] = vol.loc[em] * 100.0
            x["volume"] = vol
        if "turnover_rate" in x:
            tr = pd.to_numeric(x["turnover_rate"], errors="coerce")
            tr.loc[em] = tr.loc[em] / 100.0
            x["turnover_rate"] = tr
        x["schema_version"] = 3
    return x

def _transient_transport_failure(exc: Exception) -> bool:
    """True only when a provider failure is rooted in a retryable transport error."""
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (requests.Timeout, requests.ConnectionError, RetryableHTTPError)):
            return True
        current = current.__cause__ or current.__context__
    return False


class _HistorySourceHealth:
    """Batch-local primary-source circuit breaker.

    A repeatedly unavailable primary must not consume the full retry budget for
    every symbol. The fallback still runs for every skipped symbol, and the
    primary is periodically probed so recovery is detected during the same batch.
    Non-transport data/schema failures never open this breaker.
    """

    def __init__(self, failures: int = 4, probe_every: int = 24):
        self.failures = max(2, int(failures))
        self.probe_every = max(4, int(probe_every))
        self._lock = threading.Lock()
        self._consecutive_transient = 0
        self._open = False
        self._skipped_since_probe = 0
        self._skipped_total = 0
        self._probe_total = 0
        self._opened_total = 0
        self._primary_successes = 0
        self._primary_transient_failures = 0
        self._primary_nontransient_failures = 0

    def allow_primary(self) -> bool:
        with self._lock:
            if not self._open:
                return True
            self._skipped_since_probe += 1
            if self._skipped_since_probe >= self.probe_every:
                self._skipped_since_probe = 0
                self._probe_total += 1
                return True
            self._skipped_total += 1
            return False

    def record_primary_success(self) -> None:
        with self._lock:
            self._primary_successes += 1
            self._consecutive_transient = 0
            self._open = False
            self._skipped_since_probe = 0

    def record_primary_failure(self, exc: Exception) -> None:
        transient = _transient_transport_failure(exc)
        with self._lock:
            if transient:
                self._primary_transient_failures += 1
                self._consecutive_transient += 1
                if self._consecutive_transient >= self.failures and not self._open:
                    self._open = True
                    self._opened_total += 1
                    self._skipped_since_probe = 0
            else:
                self._primary_nontransient_failures += 1
                # The endpoint was reachable enough to return/parse a response;
                # do not suppress future symbols because their data can differ.
                self._consecutive_transient = 0
                self._open = False
                self._skipped_since_probe = 0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "primary_circuit_open": self._open,
                "primary_consecutive_transient_failures": self._consecutive_transient,
                "primary_skipped_total": self._skipped_total,
                "primary_probe_total": self._probe_total,
                "primary_opened_total": self._opened_total,
                "primary_successes": self._primary_successes,
                "primary_transient_failures": self._primary_transient_failures,
                "primary_nontransient_failures": self._primary_nontransient_failures,
                "failure_threshold": self.failures,
                "probe_every": self.probe_every,
            }


def update_symbol_history(code: str, cfg: dict, logger=None, provider=None, source_health=None) -> pd.DataFrame:
    ak = provider if provider is not None else _ak()
    out = ROOT / "data" / "history" / f"{code}.csv"
    adjust = str(cfg["universe"].get("history_adjust","hfq"))
    start = str(cfg["universe"].get("history_start","20180101"))
    old = pd.DataFrame()

    if out.exists():
        try:
            old = pd.read_csv(out, parse_dates=["date"], dtype={"code":str})
            old = _upgrade_legacy_history(old)
            if not old.empty:
                old_mode = str(old.get("adjust_mode", pd.Series([adjust])).iloc[-1])
                if old_mode != (adjust or "none"):
                    old = pd.DataFrame()
                else:
                    start = (old["date"].max() - pd.Timedelta(days=14)).strftime("%Y%m%d")
        except Exception:
            old = pd.DataFrame()

    end = datetime.now().strftime("%Y%m%d")
    new = None
    errs = []
    nc = cfg.get("network", {}) or {}
    timeout = float(nc.get("timeout_seconds",15))

    primary_allowed = source_health is None or source_health.allow_primary()
    if primary_allowed:
        try:
            new = _fetch_history_primary(ak, code, start, end, adjust, timeout=timeout)
            if source_health is not None:
                source_health.record_primary_success()
        except Exception as e:
            if source_health is not None:
                source_health.record_primary_failure(e)
            errs.append(f"_fetch_history_primary: {e}")
    else:
        errs.append("_fetch_history_primary: batch circuit open after repeated transient transport failures")

    if new is None:
        # Fallback is never suppressed by the primary breaker. AkShareProxy still
        # owns its normal bounded retry/timeout policy.
        try:
            new = _fetch_history_fallback(ak, code, start, end, adjust, timeout=timeout)
        except Exception as e:
            errs.append(f"_fetch_history_fallback: {e}")

    if new is None:
        if out.exists() and not old.empty:
            if logger:
                logger.warning("%s 两个历史源均失败，保留缓存但本次更新计为失败: %s", code, " | ".join(errs))
            # Preserving user data is separate from a successful live refresh.
            # Counting old cache as ok could conceal a complete provider outage.
        raise RuntimeError(" | ".join(errs))

    if not old.empty:
        # Overlap dates from current fetch replace legacy/current cache.
        new = pd.concat([old, new], ignore_index=True)
        new["date"] = pd.to_datetime(new["date"])
        new = new.drop_duplicates("date", keep="last").sort_values("date")

    # Canonical file is always schema v3 from this write forward.
    new["schema_version"] = 3
    tmp = out.with_suffix(".csv.tmp")
    new.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(out)
    return new

def fetch_expected_trade_date(logger=None):
    """
    Latest completed A-share trading date from Shanghai Composite index.
    Main source: Eastmoney; fallback: Tencent.
    Returns date string or None if both benchmark sources fail.
    """
    ak = _ak()
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - pd.Timedelta(days=45)).strftime("%Y%m%d")
    errors = []
    try:
        idx = ak.stock_zh_index_daily_em(
            symbol="sh000001", start_date=start, end_date=end
        )
        if idx is not None and not idx.empty:
            col = "date" if "date" in idx.columns else idx.columns[0]
            return pd.to_datetime(idx[col], errors="coerce").dropna().max().strftime("%Y-%m-%d")
    except Exception as e:
        errors.append(f"eastmoney_index: {e}")
        if logger:
            logger.warning("交易日基准东财失败，尝试腾讯: %s", e)

    try:
        idx = ak.stock_zh_index_daily_tx(
            symbol="sh000001", start_date=start, end_date=end
        )
        if idx is not None and not idx.empty:
            col = "date" if "date" in idx.columns else idx.columns[0]
            return pd.to_datetime(idx[col], errors="coerce").dropna().max().strftime("%Y-%m-%d")
    except Exception as e:
        errors.append(f"tencent_index: {e}")

    if logger:
        logger.warning("交易日基准主备源均失败，跳过新鲜度硬门禁: %s", " | ".join(errors))
    return None

def _run_history_batch(codes, cfg: dict, phase: str, logger=None):
    # Keep the production universe and historical date range intact. A small
    # worker bound overlaps provider I/O rather than reducing the workload.
    codes = list(dict.fromkeys(map(str, codes)))
    nc = cfg.get("network", {}) or {}
    if str(phase).startswith("qualification_history"):
        workers = min(12, max(1, int(nc.get("qualification_history_workers", 12))))
    else:
        workers = min(4, max(1, int(nc.get("history_workers", 4))))
    ak = _ak()
    source_health = _HistorySourceHealth(
        failures=int(nc.get("history_primary_circuit_failures", 4)),
        probe_every=int(nc.get("history_primary_probe_every", 24)),
    )
    completed, failed = 0, []
    checkpoint = ROOT / "state" / f"{phase}_progress.json"
    started = time.monotonic()

    def record(status, code=None):
        write_json(checkpoint, {
            "status": status, "phase": phase, "total": len(codes),
            "completed": completed, "failed_count": len(failed),
            "failed": failed, "last_code": code, "workers": workers,
            "source_health": source_health.snapshot(),
            "elapsed_seconds": time.monotonic() - started, "updated_at": now_iso(),
        })

    def fetch(code):
        try:
            return update_symbol_history(code, cfg, logger, provider=ak, source_health=source_health)
        finally:
            time.sleep(float((cfg.get("network", {}) or {}).get("request_delay_seconds", 0.12)))

    record("RUNNING")
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stock-history") as pool:
        futures = {pool.submit(fetch, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                value, error = future.result(), None
            except Exception as exc:
                value, error = None, str(exc)
                failed.append({"code": code, "error": error})
            completed += 1
            record("COMPLETE" if completed == len(codes) else "RUNNING", code)
            if logger:
                logger.info("历史更新进度 %s: %s/%s，失败=%s，当前=%s", phase, completed, len(codes), len(failed), code)
            yield code, value, error
    if not codes:
        record("COMPLETE")


def update_live_histories(snapshot: pd.DataFrame, cfg: dict, logger=None) -> dict:
    ok, failed, latest_dates = 0, [], []
    provider_counts = {}
    codes = list(dict.fromkeys(snapshot["code"].astype(str)))
    for code, x, error in _run_history_batch(codes, cfg, "live_history", logger):
        if error is None:
            ok += 1
            if not x.empty:
                latest_dates.append(pd.to_datetime(x["date"]).max())
                if "provider" in x:
                    provider = str(x["provider"].iloc[-1])
                    provider_counts[provider] = provider_counts.get(provider, 0) + 1
        else:
            failed.append({"code":code,"error":error})
            if logger:
                logger.error("更新 %s 失败: %s", code, error)

    latest = max(latest_dates).strftime("%Y-%m-%d") if latest_dates else None
    return {
        "ok":ok,"failed":failed,"total":len(codes),"latest_date":latest,
        "provider_counts":provider_counts
    }

def bootstrap_research_pool(master: pd.DataFrame, cfg: dict, live_codes=None, logger=None) -> dict:
    if not cfg["universe"].get("bootstrap_full_universe", True):
        return {"enabled":False,"downloaded":0,"coverage":None}

    folder = ROOT / "data" / "history"
    existing = {p.stem for p in folder.glob("*.csv")}
    m = master.copy()
    m["code"] = m["code"].astype(str)

    max_symbols = int(cfg["universe"].get("bootstrap_max_symbols", 0))
    if max_symbols > 0:
        m = m.head(max_symbols)

    live = set(map(str, live_codes or []))
    missing = m[~m["code"].isin(existing | live)].copy()
    batch = int(cfg["universe"].get("bootstrap_batch",60))
    frac = float(cfg["universe"].get("delisted_bootstrap_fraction",0.25))
    dcount = max(1, int(batch * frac))

    delist = missing[missing.get("status","current") == "delisted"]["code"].tolist()
    current = missing[missing.get("status","current") != "delisted"]["code"].tolist()
    queue = delist[:dcount] + current[:max(0, batch - min(dcount, len(delist)))]
    if len(queue) < batch:
        used = set(queue)
        leftovers = [c for c in missing["code"].tolist() if c not in used]
        queue += leftovers[:batch-len(queue)]

    downloaded, failed = 0, []
    for code, _, error in _run_history_batch(queue, cfg, "bootstrap_history", logger):
        if error is None:
            downloaded += 1
        else:
            failed.append({"code":code,"error":error})

    existing_after = {p.stem for p in folder.glob("*.csv")}
    all_codes = set(m["code"])
    current_codes = set(m.loc[m["status"]=="current","code"]) if "status" in m else all_codes
    delisted_codes = set(m.loc[m["status"]=="delisted","code"]) if "status" in m else set()
    covered = len(all_codes & existing_after)

    status = {
        "enabled":True,"downloaded":downloaded,"failed":failed,
        "covered_symbols":covered,"target_symbols":len(all_codes),
        "coverage":covered/max(1,len(all_codes)),
        "remaining":max(0,len(all_codes)-covered),
        "current_coverage":len(current_codes & existing_after)/max(1,len(current_codes)),
        "delisted_coverage":(
            len(delisted_codes & existing_after)/max(1,len(delisted_codes))
            if delisted_codes else 1.0
        ),
        "current_target":len(current_codes),"delisted_target":len(delisted_codes),
        "updated_at":now_iso()
    }
    write_json(ROOT / "cache" / "bootstrap_status.json", status)
    return status


def _research_coverage_snapshot(master: pd.DataFrame) -> dict:
    """Measure persisted real-history coverage against the frozen research master."""
    m = master.copy()
    m["code"] = m["code"].astype(str)
    existing = {p.stem for p in (ROOT / "data" / "history").glob("*.csv")}
    all_codes = set(m["code"])
    if "status" in m:
        current_codes = set(m.loc[m["status"] == "current", "code"])
        delisted_codes = set(m.loc[m["status"] == "delisted", "code"])
    else:
        current_codes, delisted_codes = all_codes, set()
    covered = len(all_codes & existing)
    return {
        "covered_symbols": covered,
        "target_symbols": len(all_codes),
        "coverage": covered / max(1, len(all_codes)),
        "remaining": max(0, len(all_codes) - covered),
        "current_coverage": len(current_codes & existing) / max(1, len(current_codes)),
        "delisted_coverage": (
            len(delisted_codes & existing) / max(1, len(delisted_codes))
            if delisted_codes else 1.0
        ),
        "current_target": len(current_codes),
        "delisted_target": len(delisted_codes),
        "_existing": existing,
        "_current_codes": current_codes,
        "_delisted_codes": delisted_codes,
    }


def qualify_research_pool_coverage(master: pd.DataFrame, cfg: dict, logger=None) -> dict:
    """Build a mature research corpus without weakening the >=90% audit gate.

    Daily bootstrap remains intentionally incremental. Advanced qualification may
    spend a larger, explicitly bounded real-network budget to mature the same
    persisted corpus. Failed symbols never count as covered and are not retried
    forever during one invocation.
    """
    if not cfg["universe"].get("bootstrap_full_universe", True):
        raise RuntimeError("full-universe research bootstrap is disabled")

    m = master.copy()
    m["code"] = m["code"].astype(str)
    max_symbols = int(cfg["universe"].get("bootstrap_max_symbols", 0))
    if max_symbols > 0:
        m = m.head(max_symbols)

    target = max(0.90, float(cfg["universe"].get("qualification_coverage_target", 0.90)))
    delisted_target = max(
        0.90, float(cfg["universe"].get("qualification_delisted_target", 0.90))
    )
    if target > 1.0 or delisted_target > 1.0:
        raise ValueError("qualification coverage targets must be <= 1.0")
    chunk = max(1, min(512, int(cfg["universe"].get("qualification_bootstrap_chunk", 384))))
    max_seconds = max(
        60.0, float(cfg["universe"].get("qualification_bootstrap_max_seconds", 7200))
    )
    started = time.monotonic()
    failed_once: set[str] = set()
    failures: list[dict] = []
    downloaded = 0

    def persist(snapshot: dict, status: str) -> dict:
        clean = {k: v for k, v in snapshot.items() if not k.startswith("_")}
        clean.update({
            "enabled": True,
            "downloaded": downloaded,
            "failed": failures,
            "qualification_status": status,
            "qualification_target": target,
            "qualification_delisted_target": delisted_target,
            "qualification_failed_once_count": len(failed_once),
            "qualification_elapsed_seconds": time.monotonic() - started,
            "updated_at": now_iso(),
        })
        write_json(ROOT / "cache" / "bootstrap_status.json", clean)
        return clean

    while True:
        snap = _research_coverage_snapshot(m)
        if snap["coverage"] >= target and snap["delisted_coverage"] >= delisted_target:
            return persist(snap, "PASS")
        if time.monotonic() - started >= max_seconds:
            return persist(snap, "NOT VERIFIED")

        existing = snap["_existing"]
        current_codes = snap["_current_codes"]
        delisted_codes = snap["_delisted_codes"]
        need_current = max(
            0, math.ceil(target * len(current_codes)) - len(current_codes & existing)
        )
        need_delisted = max(
            0,
            math.ceil(delisted_target * len(delisted_codes))
            - len(delisted_codes & existing),
        )
        missing_delisted = sorted(delisted_codes - existing - failed_once)
        missing_current = sorted(current_codes - existing - failed_once)

        # Preserve both denominators: each chunk allocates capacity to delisted
        # and current deficits instead of filling only the much larger current set.
        selected: list[str] = []
        if need_delisted and missing_delisted:
            take = min(len(missing_delisted), max(1, min(need_delisted, chunk // 4)))
            selected.extend(missing_delisted[:take])
        remaining_slots = chunk - len(selected)
        if remaining_slots > 0 and need_current and missing_current:
            selected.extend(missing_current[:min(need_current, remaining_slots)])
        remaining_slots = chunk - len(selected)
        if remaining_slots > 0 and need_delisted:
            used = set(selected)
            more = [x for x in missing_delisted if x not in used]
            selected.extend(more[:remaining_slots])

        if not selected:
            return persist(snap, "NOT VERIFIED")

        before = snap["covered_symbols"]
        for code, _, error in _run_history_batch(
            selected, cfg, "qualification_history", logger
        ):
            if error is None:
                downloaded += 1
            else:
                failed_once.add(code)
                failures.append({"code": code, "error": error})
        after = _research_coverage_snapshot(m)
        persist(after, "RUNNING")
        if after["covered_symbols"] <= before and all(code in failed_once for code in selected):
            # No-progress batches remain explicit NOT VERIFIED; never spin/retry
            # a permanently unavailable population until the CI timeout.
            continue


def load_histories(codes=None) -> dict[str,pd.DataFrame]:
    folder = ROOT / "data" / "history"
    wanted = set(map(str,codes)) if codes is not None else None
    out = {}
    for p in sorted(folder.glob("*.csv")):
        if wanted is not None and p.stem not in wanted:
            continue
        try:
            df = pd.read_csv(p, parse_dates=["date"], dtype={"code":str})
            df = _upgrade_legacy_history(df)
            if len(df) >= 30 and (pd.to_numeric(df["close"], errors="coerce") > 0).all():
                out[p.stem] = df.sort_values("date")
        except Exception:
            continue
    return out

def select_training_histories(
    all_histories: dict[str,pd.DataFrame],
    live_codes,
    master: pd.DataFrame,
    cfg: dict
) -> dict[str,pd.DataFrame]:
    """
    Current candidates determine only what gets scored.
    Historical training additionally draws a deterministic research sample,
    including delisted securities when available.
    """
    live = set(map(str, live_codes))
    selected = {c:all_histories[c] for c in live if c in all_histories}

    extra_n = int(cfg["model"].get("research_training_extra_symbols",500))
    if extra_n <= 0:
        return selected

    status_map = {}
    if master is not None and not master.empty and "status" in master:
        status_map = dict(zip(master["code"].astype(str), master["status"].astype(str)))

    candidates = [c for c in all_histories if c not in live]
    # Stable pseudo-random order by SHA-256 code: no return-based cherry-picking.
    def key(c):
        import hashlib
        return hashlib.sha256(c.encode("utf-8")).hexdigest()

    delisted = sorted(
        [c for c in candidates if status_map.get(c) == "delisted"], key=key
    )
    others = sorted(
        [c for c in candidates if status_map.get(c) != "delisted"], key=key
    )

    delist_quota = min(len(delisted), max(1, extra_n // 4))
    chosen = delisted[:delist_quota]
    remaining = extra_n - len(chosen)
    chosen += others[:remaining]

    if len(chosen) < extra_n:
        used = set(chosen)
        chosen += [c for c in delisted[delist_quota:] if c not in used][:extra_n-len(chosen)]

    for c in chosen:
        selected[c] = all_histories[c]
    return selected

def load_industry_cache() -> dict:
    p = ROOT / "cache" / "industry_cache.csv"
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p, dtype={"code":str})
        return {str(r["code"]):str(r["industry"]) for _,r in df.iterrows()}
    except Exception:
        return {}

def enrich_industries(codes, logger=None) -> dict:
    # Preserve the exact requested denominator and provider/retry policy while
    # overlapping independent read-only calls with a bounded worker pool.
    requested = list(dict.fromkeys(map(str, codes)))
    cache = load_industry_cache()
    pending = [c for c in requested if c not in cache or cache[c] in {"","nan","未知"}]
    network = (load_config().get("network", {}) or {})
    workers = min(4, max(1, int(network.get("industry_workers", 4))))
    ak = _ak()
    progress = ROOT / "state" / "industry_progress.json"
    started = time.monotonic()
    completed = 0
    failed = []

    def record(status, code=None):
        write_json(progress, {
            "status": status, "phase": "industry_enrichment",
            "total": len(requested), "pending": len(pending),
            "completed": completed, "failed_count": len(failed),
            "failed": failed, "last_code": code, "workers": workers,
            "elapsed_seconds": time.monotonic() - started, "updated_at": now_iso(),
        })

    def fetch(code):
        try:
            df = ak.stock_individual_info_em(symbol=code)
            ic = "item" if "item" in df.columns else df.columns[0]
            vc = "value" if "value" in df.columns else df.columns[1]
            m = df[df[ic].astype(str).str.contains("行业", na=False)]
            return str(m.iloc[0][vc]) if not m.empty else "未知", None
        except Exception as exc:
            return "未知", str(exc)
        finally:
            time.sleep(0.01)

    record("RUNNING")
    changed = False
    if pending:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stock-industry") as pool:
            futures = {pool.submit(fetch, code): code for code in pending}
            for future in as_completed(futures):
                code = futures[future]
                industry, error = future.result()
                cache[code] = industry
                changed = True
                completed += 1
                if error is not None:
                    failed.append({"code": code, "error": error})
                    if logger:
                        logger.warning("行业信息 %s 获取失败: %s", code, error)
                record("COMPLETE" if completed == len(pending) else "RUNNING", code)
    else:
        record("COMPLETE")

    if changed:
        pd.DataFrame(
            [{"code": k, "industry": v} for k, v in cache.items()]
        ).to_csv(ROOT/"cache"/"industry_cache.csv", index=False, encoding="utf-8-sig")
    return {c: cache.get(c, "未知") for c in requested}
