from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SRC = Path("stock_sse_primary_transition_full_corpus.json")
OUT = Path("stock_sse_transition_action_taxonomy.json")

KNOWN_ACTIONS = {
    "initial_implementation",
    "overlay_implementation",
    "continuation_notice",
    "actual_cancel",
    "mixed_cancel_continue",
    "cancel_application",
    "descriptive_nontransition",
    "trigger_condition_notice",
}

DATE_REQUIRED_ACTIONS = {
    "initial_implementation",
    "overlay_implementation",
    "actual_cancel",
    "mixed_cancel_continue",
}


def classify_title(title: str) -> str:
    text = "".join(str(title or "").split())

    if "申请" in text and "撤销" in text:
        return "cancel_application"

    if any(token in text for token in ("撤销", "取消", "终止实施", "不再实施")):
        if "继续" in text or "叠加" in text:
            return "mixed_cancel_continue"
        return "actual_cancel"

    if "预审计" in text or "专项说明" in text:
        return "descriptive_nontransition"

    if "触发" in text and "风险警示" in text:
        return "trigger_condition_notice"

    if "继续" in text and ("风险警示" in text or "实行" in text):
        return "continuation_notice"

    if "叠加" in text and "风险警示" in text:
        return "overlay_implementation"

    if ("实施" in text or "实行" in text) and "风险警示" in text:
        return "initial_implementation"

    return "UNCLASSIFIED"


def main() -> int:
    if not SRC.exists():
        raise SystemExit("missing stock_sse_primary_transition_full_corpus.json")

    src = json.loads(SRC.read_text(encoding="utf-8"))
    rows = []
    counts = Counter()
    unclassified = []

    for rec in src.get("records") or []:
        action = classify_title(str(rec.get("title") or ""))
        counts[action] += 1
        item = {
            "ordinal": rec.get("ordinal"),
            "security_code": rec.get("security_code"),
            "announcement_date": rec.get("date"),
            "title": rec.get("title"),
            "prior_title_class": rec.get("transition_title_class"),
            "action": action,
            "requires_new_effective_date": action in DATE_REQUIRED_ACTIONS,
            "prior_status": rec.get("status"),
            "prior_candidate_date_count": rec.get("candidate_date_count"),
            "prior_candidate_dates": rec.get("candidate_dates"),
        }
        rows.append(item)
        if action == "UNCLASSIFIED":
            unclassified.append(item)

    classified = len(rows) - len(unclassified)
    required = [row for row in rows if row["requires_new_effective_date"]]
    non_transition = [row for row in rows if not row["requires_new_effective_date"]]

    expected_total = len(rows)
    accounted = (
        expected_total > 0
        and classified == expected_total
        and all(action in KNOWN_ACTIONS for action in counts)
        and sum(counts.values()) == expected_total
    )

    report = {
        "schema": "stock-sse-transition-action-taxonomy-v1",
        "source_schema": src.get("schema"),
        "source_event_corpus": src.get("source_event_corpus"),
        "selected_documents": expected_total,
        "action_counts": dict(sorted(counts.items())),
        "effective_date_required_count": len(required),
        "non_new_transition_count": len(non_transition),
        "effective_date_required_actions": sorted(DATE_REQUIRED_ACTIONS),
        "rows": rows,
        "unclassified": unclassified,
        "adjudication": {
            "title_action_taxonomy": "SUPPORTED_DIAGNOSTIC" if accounted else "NOT VERIFIED",
            "effective_date_denominator_defined": "SUPPORTED_DIAGNOSTIC" if accounted else "NOT VERIFIED",
            "primary_document_action_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "Title taxonomy only defines which announcements plausibly create a new risk-warning state transition. "
            "Continuation notices, applications, audit explanations and trigger-condition notices are not promoted "
            "to new effective dates. Primary PDFs must still validate action semantics and unique effective dates "
            "for all date-required actions before state replay can be attempted."
        ),
    }

    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "selected_documents": expected_total,
        "action_counts": report["action_counts"],
        "effective_date_required_count": len(required),
        "non_new_transition_count": len(non_transition),
        "unclassified_count": len(unclassified),
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))

    return 0 if accounted else 2


if __name__ == "__main__":
    raise SystemExit(main())
