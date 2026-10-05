from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
FULL_PATH = HERE / "stock_sse_primary_transition_full_corpus.py"
OUT = Path("stock_sse_transition_action_taxonomy_current_product.json")

EXPECTED_SOURCE_ROWS = 2994
EXPECTED_SOURCE_SHA256 = "577c8c4caaf66f71b02f33bbba5158a46a408703d9bbdc5a131bca330c1068ef"
EXPECTED_SELECTED = 667
EXPECTED_SELECTED_IDENTITY_SHA256 = "f4ae97fc6338f0b97ea860e4fd1c7f2500e184ddfdf28af16ee0a9a012fe3862"

KNOWN_ACTIONS = {
    "initial_implementation",
    "overlay_implementation",
    "continuation_notice",
    "actual_cancel",
    "mixed_cancel_continue",
    "mixed_cancel_implement",
    "cancel_application",
    "descriptive_nontransition",
    "trigger_condition_notice",
}
DATE_REQUIRED_ACTIONS = {
    "initial_implementation",
    "overlay_implementation",
    "actual_cancel",
    "mixed_cancel_continue",
    "mixed_cancel_implement",
}

MIXED_CANCEL_IMPLEMENT_RE = re.compile(
    r"(?:撤销|取消|终止实施|不再实施).*(?:及|并|暨|同时)(?:被)?(?:叠加)?实施.*风险(?:警示)?"
)

def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

full = load_module(FULL_PATH, "current_full_corpus")

def classify_title(title: str) -> str:
    text = "".join(str(title or "").split())
    if "申请" in text and "撤销" in text:
        return "cancel_application"
    if any(token in text for token in ("撤销", "取消", "终止实施", "不再实施")):
        # A same-announcement cancellation followed by implementation of another
        # warning type is a distinct state transition, not a mere continuation.
        if MIXED_CANCEL_IMPLEMENT_RE.search(text):
            return "mixed_cancel_implement"
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

def selected_identity(rows: list[dict]) -> str:
    identity = [
        {
            "security_code": r.get("security_code"),
            "date": r.get("date"),
            "title": r.get("title"),
            "url": r.get("url"),
            "transition_title_class": r.get("transition_title_class"),
        }
        for r in rows
    ]
    payload = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def main() -> int:
    session = requests.Session()
    corpus = full.s.build_corpus(session)
    source_sha = full.s.market.canonical_sha(corpus)

    selected = []
    for row in corpus:
        klass = full.s.inventory.classify(row.get("title") or "")
        if klass in full.TARGET_CLASSES:
            selected.append({**row, "transition_title_class": klass})
    selected.sort(
        key=lambda x: (
            str(x.get("transition_title_class") or ""),
            str(x.get("date") or ""),
            str(x.get("security_code") or ""),
            str(x.get("url") or ""),
        )
    )
    selected_sha = selected_identity(selected)

    source_binding = (
        len(corpus) == EXPECTED_SOURCE_ROWS
        and source_sha == EXPECTED_SOURCE_SHA256
        and len(selected) == EXPECTED_SELECTED
        and selected_sha == EXPECTED_SELECTED_IDENTITY_SHA256
    )

    rows = []
    counts = Counter()
    unclassified = []
    for rec in selected:
        action = classify_title(str(rec.get("title") or ""))
        counts[action] += 1
        item = {
            "security_code": rec.get("security_code"),
            "announcement_date": rec.get("date"),
            "title": rec.get("title"),
            "url": rec.get("url"),
            "prior_title_class": rec.get("transition_title_class"),
            "action": action,
            "requires_new_effective_date": action in DATE_REQUIRED_ACTIONS,
        }
        rows.append(item)
        if action == "UNCLASSIFIED":
            unclassified.append(item)

    classified = len(rows) - len(unclassified)
    required = [r for r in rows if r["requires_new_effective_date"]]
    non_new = [r for r in rows if not r["requires_new_effective_date"]]
    accounted = (
        source_binding
        and len(rows) > 0
        and classified == len(rows)
        and all(action in KNOWN_ACTIONS for action in counts)
        and sum(counts.values()) == len(rows)
    )

    report = {
        "schema": "stock-sse-transition-action-taxonomy-current-product-v1",
        "source_binding": {
            "expected_source_rows": EXPECTED_SOURCE_ROWS,
            "observed_source_rows": len(corpus),
            "expected_source_sha256": EXPECTED_SOURCE_SHA256,
            "observed_source_sha256": source_sha,
            "expected_selected_documents": EXPECTED_SELECTED,
            "observed_selected_documents": len(selected),
            "expected_selected_identity_sha256": EXPECTED_SELECTED_IDENTITY_SHA256,
            "observed_selected_identity_sha256": selected_sha,
            "status": "PASS" if source_binding else "FAIL",
        },
        "selected_documents": len(rows),
        "action_counts": dict(sorted(counts.items())),
        "effective_date_required_count": len(required),
        "non_new_transition_count": len(non_new),
        "effective_date_required_actions": sorted(DATE_REQUIRED_ACTIONS),
        "unclassified_count": len(unclassified),
        "unclassified": unclassified,
        "rows": rows,
        "adjudication": {
            "current_source_binding": "PASS" if source_binding else "FAIL",
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
            "This is a title-level denominator refinement bound to the exact terminal #236 source corpus. "
            "It does not treat titles as effective-state truth. All date-required actions still need primary-document "
            "semantics and unique effective-date evidence before deterministic daily state replay."
        ),
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "source_binding": report["source_binding"],
        "selected_documents": report["selected_documents"],
        "action_counts": report["action_counts"],
        "effective_date_required_count": report["effective_date_required_count"],
        "non_new_transition_count": report["non_new_transition_count"],
        "unclassified_count": report["unclassified_count"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))

    # Technical execution only fails on source-identity drift. Classification
    # incompleteness remains explicit NOT VERIFIED evidence, not a transport failure.
    return 0 if source_binding else 2

if __name__ == "__main__":
    raise SystemExit(main())
