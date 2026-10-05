from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd
import akshare as ak


def pick(cols, *names):
    for name in names:
        if name in cols:
            return name
    return None


def norm_code(value):
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def main():
    df = ak.stock_info_sz_change_name(symbol="简称变更")
    if df is None or df.empty:
        raise RuntimeError("SZSE short-name change feed returned empty")
    cols = list(df.columns)
    code_col = pick(cols, "证券代码", "代码")
    date_col = pick(cols, "变更日期", "变更时间", "日期")
    old_col = pick(cols, "变更前证券简称", "变更前简称", "原证券简称", "原简称")
    new_col = pick(cols, "变更后证券简称", "变更后简称", "证券简称", "新证券简称", "新简称")
    if not code_col or not date_col:
        raise RuntimeError(f"required code/date columns missing: {cols}")

    work = df.copy()
    work["code"] = work[code_col].map(norm_code)
    work["change_date"] = pd.to_datetime(work[date_col], errors="coerce")
    work = work[work["code"].str.fullmatch(r"\d{6}") & work["change_date"].notna()].copy()
    if work.empty:
        raise RuntimeError("no valid dated SZSE name-change rows")

    def is_st(value):
        text = str(value or "").upper().replace(" ", "")
        return "ST" in text

    if old_col:
        work["old_name"] = work[old_col].astype(str)
    else:
        work["old_name"] = ""
    if new_col:
        work["new_name"] = work[new_col].astype(str)
    else:
        work["new_name"] = ""

    work["old_is_st"] = work["old_name"].map(is_st)
    work["new_is_st"] = work["new_name"].map(is_st)
    st = work[work["old_is_st"] | work["new_is_st"]].copy()

    payload = work.sort_values(["code", "change_date"]).to_json(
        orient="records", date_format="iso", force_ascii=False
    ).encode("utf-8")
    st_payload = st.sort_values(["code", "change_date"]).to_json(
        orient="records", date_format="iso", force_ascii=False
    ).encode("utf-8")

    report = {
        "schema": "stock-ai-historical-st-pit-diagnostic-v1",
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "SZSE via AkShare stock_info_sz_change_name",
            "scope": "Shenzhen-listed securities only",
            "official_exchange_source": True,
            "dated_change_records": True,
        },
        "columns": cols,
        "column_binding": {
            "code": code_col,
            "change_date": date_col,
            "old_name": old_col,
            "new_name": new_col,
        },
        "valid_rows": int(len(work)),
        "unique_codes": int(work["code"].nunique()),
        "date_min": work["change_date"].min().date().isoformat(),
        "date_max": work["change_date"].max().date().isoformat(),
        "st_related_rows": int(len(st)),
        "st_related_codes": int(st["code"].nunique()) if len(st) else 0,
        "dated_name_change_sha256": hashlib.sha256(payload).hexdigest(),
        "dated_st_change_sha256": hashlib.sha256(st_payload).hexdigest(),
        "historical_st_reconstruction": {
            "shenzhen": "SUPPORTED",
            "shanghai": "NOT VERIFIED",
            "beijing": "NOT VERIFIED",
            "full_a_share_gate": "NOT VERIFIED",
        },
        "historical_suspension_daily_state": "NOT VERIFIED",
        "product_bytes_changed": False,
        "final_gate": "FAIL",
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    with open("stock_historical_st_pit_diagnostic.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    if report["st_related_rows"] <= 0:
        raise RuntimeError("dated source had no ST-related transitions; cannot support reconstruction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
