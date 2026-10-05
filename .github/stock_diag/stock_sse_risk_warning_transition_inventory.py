from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import requests

BASE = Path(__file__).with_name("stock_sse_marketwide_risk_warning_history.py")
spec = importlib.util.spec_from_file_location("marketwide", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load market-wide SSE diagnostic module")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PROSPECTIVE = ("可能", "拟", "将被", "将实施", "预计", "触及", "风险提示")
PROGRESS = ("进展", "提示性公告", "风险提示公告", "继续实施")
APPLY_CANCEL = ("申请撤销", "拟申请撤销")
CANCEL_RE = re.compile(r"撤销.*(?:退市|其他)?风险警示|风险警示.*撤销")
IMPLEMENT_RE = re.compile(r"(?:被|实施|实行).{0,12}(?:退市|其他)?风险警示|风险警示.{0,12}(?:实施|实行)")


def classify(title: str) -> str:
    compact = re.sub(r"\s+", "", title or "")
    if any(x in compact for x in APPLY_CANCEL):
        return "application_to_cancel"
    if any(x in compact for x in PROSPECTIVE):
        return "prospective_or_risk_notice"
    if any(x in compact for x in PROGRESS):
        return "progress_or_reminder"
    if CANCEL_RE.search(compact):
        return "actual_cancel_candidate"
    if IMPLEMENT_RE.search(compact):
        return "actual_implementation_candidate"
    return "other_or_ambiguous"


def main() -> int:
    session = requests.Session()
    combined: dict[tuple[str, str, str, str], dict] = {}
    source_summaries = []

    for label, keyword in m.KEYWORDS:
        item = m.fetch_keyword(session, label, keyword)
        records = item["records"]
        source_summaries.append({
            "label": label,
            "keyword": keyword,
            "raw_rows": item["raw_rows"],
            "a_share_rows": item["a_share_rows"],
            "b_share_rows": item["b_share_rows"],
            "server": item["server"],
            "canonical_sha256": item["canonical_sha256"],
        })
        for row in records:
            ident = m.identity(row)
            if ident not in combined:
                combined[ident] = {**row, "source_labels": []}
            combined[ident]["source_labels"].append(label)

    corpus = [combined[k] for k in sorted(combined)]
    buckets: dict[str, list[dict]] = {}
    for row in corpus:
        category = classify(row["title"])
        row = {**row, "transition_title_class": category}
        buckets.setdefault(category, []).append(row)

    counts = Counter({k: len(v) for k, v in buckets.items()})
    sample_limit = 25
    samples = {
        k: [
            {
                "security_code": x["security_code"],
                "security_name": x["security_name"],
                "date": x["date"],
                "title": x["title"],
                "url": x["url"],
                "source_labels": x["source_labels"],
            }
            for x in v[:sample_limit]
        ]
        for k, v in sorted(buckets.items())
    }

    all_accounted = sum(counts.values()) == len(corpus) and len(corpus) > 0
    source_complete = all(
        x["raw_rows"] == int(x["server"]["total"])
        for x in source_summaries
    )

    report = {
        "schema": "stock-sse-risk-warning-transition-inventory-v1",
        "window": {"begin": m.BEGIN, "end": m.END},
        "source_summaries": source_summaries,
        "corpus": {
            "unique_a_share_event_rows": len(corpus),
            "unique_codes": len({x["security_code"] for x in corpus}),
            "missing_security_name_rows": sum(1 for x in corpus if not x["security_name"]),
            "canonical_sha256": m.canonical_sha(corpus),
        },
        "title_transition_inventory": {
            "counts": dict(sorted(counts.items())),
            "samples_per_class_limit": sample_limit,
            "samples": samples,
        },
        "adjudication": {
            "source_pagination_complete": "PASS" if source_complete else "FAIL",
            "title_transition_inventory": "SUPPORTED_DIAGNOSTIC" if all_accounted and source_complete else "NOT VERIFIED",
            "title_semantics_are_effective_dates": "FALSE",
            "primary_document_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "Title classification is an inventory for deciding which primary SSE PDFs must be "
            "validated next. A title bucket is not an effective-date transition and cannot promote "
            "Shanghai historical ST/PIT, Advanced Business, or Final."
        ),
    }

    Path("stock_sse_risk_warning_transition_inventory.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "corpus": report["corpus"],
        "counts": report["title_transition_inventory"]["counts"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))
    return 0 if report["adjudication"]["title_transition_inventory"] == "SUPPORTED_DIAGNOSTIC" else 2


if __name__ == "__main__":
    raise SystemExit(main())

# workflow-trigger: v1
