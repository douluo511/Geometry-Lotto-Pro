from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SRC = Path("stock_bse_risk_warning_effective_dates.json")
OUT = Path("stock_bse_transition_taxonomy.json")

def classify(title: str) -> str:
    t = "".join((title or "").split())
    if "继续实施退市风险警示" in t:
        return "continuation_notice"
    if "叠加实施退市风险警示" in t:
        return "overlay_notice"
    if "可能被实施退市风险警示" in t or "可能被实施" in t:
        return "prospective_notice"
    if "将被实施退市风险警示" in t:
        return "initial_implementation_candidate"
    if "被实施退市风险警示" in t:
        return "initial_implementation_candidate"
    return "other_or_ambiguous"

def main() -> int:
    if not SRC.exists():
        raise SystemExit("missing effective-date diagnostic output")
    src = json.loads(SRC.read_text(encoding="utf-8"))
    rows = []
    for item in src.get("results") or []:
        title = str(item.get("title") or "")
        klass = classify(title)
        eff = item.get("effective_date")
        order = item.get("publish_date_order_check")
        rows.append({
            "canonical_company_code": item.get("canonical_company_code"),
            "publishDate": item.get("publishDate"),
            "title": title,
            "class": klass,
            "effective_date": eff,
            "publish_date_order_check": order,
            "source_status": item.get("status"),
            "candidate_date_count": len(item.get("candidate_dates") or []),
            "candidate_dates": item.get("candidate_dates") or [],
            "pdf_text_sha256": item.get("pdf_text_sha256"),
        })

    counts = Counter(x["class"] for x in rows)
    initial = [x for x in rows if x["class"] == "initial_implementation_candidate"]
    continuation = [x for x in rows if x["class"] in {"continuation_notice","overlay_notice"}]
    other = [x for x in rows if x["class"] not in {
        "initial_implementation_candidate","continuation_notice","overlay_notice"
    }]
    initial_pass = [x for x in initial if x["source_status"] == "PASS"]
    initial_nonpass = [x for x in initial if x["source_status"] != "PASS"]
    continuation_prior = [
        x for x in continuation
        if x.get("effective_date")
        and str(x.get("effective_date")) < str(x.get("publishDate") or "")[:10]
    ]

    all_accounted = len(rows) == sum(counts.values()) and bool(rows)
    report = {
        "schema":"stock-bse-transition-taxonomy-v1",
        "source_schema":src.get("schema"),
        "source_corpus_sha256":src.get("source_corpus_sha256"),
        "selected_count":len(rows),
        "class_counts":dict(sorted(counts.items())),
        "initial_implementation":{
            "count":len(initial),
            "pass_count":len(initial_pass),
            "nonpass_count":len(initial_nonpass),
            "nonpass_rows":initial_nonpass,
        },
        "continuation_or_overlay":{
            "count":len(continuation),
            "prior_effective_date_count":len(continuation_prior),
            "rows":continuation,
        },
        "other_or_ambiguous_rows":other,
        "rows":rows,
        "adjudication":{
            "transition_title_taxonomy":"SUPPORTED_DIAGNOSTIC" if all_accounted else "NOT VERIFIED",
            "initial_implementation_effective_date_evidence":"SUPPORTED" if initial and len(initial_pass)==len(initial) else "NOT VERIFIED",
            "continuation_notice_classification":"SUPPORTED_DIAGNOSTIC" if continuation else "NOT VERIFIED",
            "bse_removal_event_history":"NOT VERIFIED",
            "bse_effective_state_reconstruction":"NOT VERIFIED",
            "bse_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
        "boundary":(
            "Continuation/overlay announcements are not new implementation transitions. "
            "An earlier effective date in a continuation notice may describe the already-active warning state "
            "and must not be rejected as if it were a new transition. This taxonomy does not invent a missing "
            "effective date, does not supply removal history, and does not promote BSE/full historical ST PIT."
        ),
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "selected_count":report["selected_count"],
        "class_counts":report["class_counts"],
        "initial_implementation":report["initial_implementation"],
        "continuation_or_overlay":report["continuation_or_overlay"],
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0 if all_accounted else 2

if __name__=="__main__":
    raise SystemExit(main())
