from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BASE = HERE / "stock_sse_primary_transition_semantics_sample.py"
spec = importlib.util.spec_from_file_location("samplemod", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load sample diagnostic module")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

OUT = Path("stock_sse_primary_transition_full_corpus.json")
TARGET_CLASSES = {"actual_implementation_candidate", "actual_cancel_candidate"}

IMPLEMENT_ACTION_RE = re.compile(
    r"(?:被|予以|决定)?实施.{0,18}?(?:退市|其他)?风险警示|"
    r"(?:退市|其他)?风险警示.{0,18}?(?:实施|实行)"
)
CANCEL_ACTION_RE = re.compile(
    r"(?:决定)?撤销.{0,24}?(?:退市|其他)?风险警示|"
    r"(?:退市|其他)?风险警示.{0,18}?撤销"
)
CLAUSE_BOUNDARIES = "。；;！？!?"


def _iso_date(match) -> str:
    y, mo, day = map(int, match.groups())
    return f"{y:04d}-{mo:02d}-{day:02d}"


def _clause_around(compact: str, start: int, end: int) -> tuple[str, int]:
    left_candidates = [compact.rfind(ch, 0, start) for ch in CLAUSE_BOUNDARIES]
    left = max(left_candidates) + 1
    right_candidates = [compact.find(ch, end) for ch in CLAUSE_BOUNDARIES]
    right_candidates = [x for x in right_candidates if x >= 0]
    right = min(right_candidates) if right_candidates else min(len(compact), end + 180)
    return compact[left:right], left


def semantic_transition_dates(text: str, klass: str) -> list[dict]:
    """Conservatively bind dates to an actual implementation/cancellation clause.

    A date is accepted only when the same punctuation-bounded clause has exactly
    one date, or when a multi-date clause contains an explicit 自/于/从...日起 or
    日期/时间为 relation tightly bound to the transition action. Ambiguity remains
    fail-closed; this diagnostic does not promote historical ST/PIT by itself.
    """
    compact = re.sub(r"\s+", "", text or "")
    action_re = IMPLEMENT_ACTION_RE if klass == "actual_implementation_candidate" else CANCEL_ACTION_RE
    out = []
    for action in action_re.finditer(compact):
        local_prefix = compact[max(0, action.start() - 14):action.start()]
        if klass == "actual_cancel_candidate" and re.search(r"(?:申请|拟申请|计划|可能|预计)$", local_prefix):
            continue
        if klass == "actual_implementation_candidate" and re.search(r"(?:拟|计划|可能|预计)$", local_prefix):
            continue

        clause, clause_start = _clause_around(compact, action.start(), action.end())
        dates = list(s.DATE_RE.finditer(clause))
        if not dates:
            continue

        rel_action_start = action.start() - clause_start
        rel_action_end = action.end() - clause_start
        accepted = []
        for d in dates:
            iso = _iso_date(d)
            relation = None
            if len(dates) == 1:
                relation = "single_date_same_clause"
            else:
                before = clause[max(0, d.start() - 12):d.start()]
                after = clause[d.end():d.end() + 8]
                if re.search(r"(?:自|于|从)$", before) and re.match(r"^(?:起|开始)", after):
                    relation = "explicit_from_date_start"
                elif d.end() <= rel_action_start:
                    bridge = clause[d.end():rel_action_start]
                    if len(bridge) <= 64 and re.match(r"^(?:起|开始|，|,|起，|起,)", bridge):
                        relation = "date_precedes_action_tightly"
                elif d.start() >= rel_action_end:
                    bridge = clause[rel_action_end:d.start()]
                    if len(bridge) <= 48 and re.search(r"(?:日期|时间|起始日|实施日|撤销日).{0,8}(?:为|是|：|:|自|于)$", bridge):
                        relation = "action_declares_date"
            if relation:
                accepted.append({
                    "date": iso,
                    "relation": relation,
                    "distance": min(abs(d.end() - rel_action_start), abs(d.start() - rel_action_end)),
                })

        if accepted:
            out.append({
                "transition": action.group(0),
                "dates": sorted({x["date"] for x in accepted}),
                "relations": accepted,
                "clause_sha256": hashlib.sha256(clause.encode("utf-8")).hexdigest(),
            })

    dedup = {}
    for item in out:
        key = (item["transition"], tuple(item["dates"]), item["clause_sha256"])
        dedup[key] = item
    return list(dedup.values())


def main() -> int:
    session = requests.Session()
    corpus = s.build_corpus(session)
    candidates = []
    for row in corpus:
        klass = s.inventory.classify(row.get("title") or "")
        if klass in TARGET_CLASSES:
            candidates.append({**row, "transition_title_class": klass})
    candidates.sort(
        key=lambda x: (
            str(x.get("transition_title_class") or ""),
            str(x.get("date") or ""),
            str(x.get("security_code") or ""),
            str(x.get("url") or ""),
        )
    )

    records = []
    for idx, row in enumerate(candidates, start=1):
        rec = {
            "ordinal": idx,
            "security_code": row.get("security_code"),
            "security_name": row.get("security_name"),
            "date": row.get("date"),
            "title": row.get("title"),
            "url": row.get("url"),
            "transition_title_class": row.get("transition_title_class"),
            "status": "NOT VERIFIED",
            "attempts": [],
        }
        raw = None
        for url in s.candidate_urls(str(row.get("url") or "")):
            try:
                response, meta = s.fetch_pdf(session, url)
                attempt = {"url": url, "status": "PASS", "meta": meta}
                if not response.content.startswith(b"%PDF"):
                    attempt["status"] = "NOT_PDF"
                    rec["attempts"].append(attempt)
                    continue
                rec["attempts"].append(attempt)
                raw = response.content
                rec["pdf_url"] = url
                rec["pdf_sha256"] = hashlib.sha256(raw).hexdigest()
                rec["pdf_bytes"] = len(raw)
                break
            except Exception as exc:
                rec["attempts"].append({
                    "url": url,
                    "status": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                })
        if raw is None:
            rec["status"] = "DOWNLOAD_NOT_VERIFIED"
            records.append(rec)
            continue

        try:
            text, pages = s.extract_text(raw)
        except Exception as exc:
            rec["status"] = "TEXT_NOT_VERIFIED"
            rec["extract_error"] = f"{type(exc).__name__}: {exc}"
            records.append(rec)
            continue

        transitions = s.near_transition_dates(text)
        broad_dates = sorted({d for item in transitions for d in item.get("dates", [])})
        semantic = semantic_transition_dates(text, str(row.get("transition_title_class") or ""))
        semantic_dates = sorted({d for item in semantic for d in item.get("dates", [])})
        rec["pages"] = pages
        rec["text_chars"] = len(text)
        rec["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["transition_evidence"] = transitions
        rec["broad_candidate_dates"] = broad_dates
        rec["broad_candidate_date_count"] = len(broad_dates)
        rec["semantic_transition_evidence"] = semantic
        rec["semantic_candidate_dates"] = semantic_dates
        rec["semantic_candidate_date_count"] = len(semantic_dates)
        rec["candidate_dates"] = semantic_dates
        rec["candidate_date_count"] = len(semantic_dates)
        if not semantic_dates:
            rec["status"] = "NO_SEMANTIC_TRANSITION_DATE"
        elif len(semantic_dates) == 1:
            rec["status"] = "SEMANTIC_UNIQUE_DATE_CANDIDATE"
        else:
            rec["status"] = "SEMANTIC_MULTI_DATE_AMBIGUOUS"
        records.append(rec)

    selected = len(records)
    downloaded = sum(1 for x in records if x.get("pdf_sha256"))
    text_ok = sum(1 for x in records if x.get("text_sha256"))
    broad_with_dates = sum(1 for x in records if x.get("broad_candidate_date_count", 0) >= 1)
    semantic_with_dates = sum(1 for x in records if x.get("semantic_candidate_date_count", 0) >= 1)
    semantic_unique_dates = sum(1 for x in records if x.get("semantic_candidate_date_count") == 1)
    semantic_ambiguous = sum(1 for x in records if x.get("semantic_candidate_date_count", 0) > 1)
    status_counts = dict(sorted(Counter(x["status"] for x in records).items()))
    by_class = {}
    for klass in sorted(TARGET_CLASSES):
        subset = [x for x in records if x["transition_title_class"] == klass]
        by_class[klass] = {
            "selected": len(subset),
            "pdf_downloaded": sum(1 for x in subset if x.get("pdf_sha256")),
            "text_extractable": sum(1 for x in subset if x.get("text_sha256")),
            "broad_has_transition_date_candidate": sum(1 for x in subset if x.get("broad_candidate_date_count", 0) >= 1),
            "semantic_has_transition_date_candidate": sum(1 for x in subset if x.get("semantic_candidate_date_count", 0) >= 1),
            "semantic_unique_date_candidate": sum(1 for x in subset if x.get("semantic_candidate_date_count") == 1),
            "semantic_multi_date_ambiguous": sum(1 for x in subset if x.get("semantic_candidate_date_count", 0) > 1),
        }

    transport_complete = selected > 0 and downloaded == selected and text_ok == selected
    date_candidate_complete = selected > 0 and broad_with_dates == selected
    unique_complete = selected > 0 and semantic_unique_dates == selected

    report = {
        "schema": "stock-sse-primary-transition-full-corpus-v2",
        "source_window": {"begin": s.market.BEGIN, "end": s.market.END},
        "source_event_corpus": {
            "unique_a_share_event_rows": len(corpus),
            "canonical_sha256": s.market.canonical_sha(corpus),
        },
        "full_candidate_corpus": {
            "selected_documents": selected,
            "pdf_downloaded": downloaded,
            "text_extractable": text_ok,
            "broad_with_transition_date_candidate": broad_with_dates,
            "semantic_with_transition_date_candidate": semantic_with_dates,
            "semantic_unique_date_candidate": semantic_unique_dates,
            "semantic_multi_date_ambiguous": semantic_ambiguous,
            "status_counts": status_counts,
            "by_class": by_class,
        },
        "records": records,
        "adjudication": {
            "full_primary_pdf_transport_and_text": "PASS" if transport_complete else "NOT VERIFIED",
            "full_transition_date_candidate_coverage": "SUPPORTED" if date_candidate_complete else "NOT VERIFIED",
            "semantic_transition_date_resolution": "SUPPORTED_DIAGNOSTIC" if semantic_unique_dates > 0 else "NOT VERIFIED",
            "unique_transition_date_mapping": "SUPPORTED" if unique_complete else "NOT VERIFIED",
            "primary_document_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This exhausts the title-derived implementation/cancellation candidate set and measures official PDF "
            "transport, text extraction, and transition-date candidate coverage. Even complete date-candidate "
            "coverage does not prove that a candidate date is the unique effective transition date. "
            "Primary-document semantics, state reconstruction, historical ST PIT, Advanced Business and Final "
            "remain NOT VERIFIED until ambiguity is resolved and state replay is independently cross-checked."
        ),
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "full_candidate_corpus": report["full_candidate_corpus"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))

    # Diagnostic execution success is distinct from business semantic qualification.
    # If every selected primary PDF was fetched and text-extracted, this diagnostic
    # completed its job. Missing/ambiguous effective-date semantics stay encoded
    # above as NOT VERIFIED and must not be converted into a workflow transport FAIL.
    return 0 if transport_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
