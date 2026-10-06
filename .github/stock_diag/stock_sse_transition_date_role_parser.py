from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
FULL = HERE / "stock_sse_primary_transition_full_corpus.py"
spec = importlib.util.spec_from_file_location("fullmod", FULL)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load full corpus module")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
s = m.s
OUT = Path("stock_sse_transition_date_role_parser.json")

DATE = r"(20\d{2})年(\d{1,2})月(\d{1,2})日"
RISK = r"(?:退市风险警示|其他风险警示|风险警示)"

# Keep implementation and cancellation evidence separate.  A cancellation
# bulletin frequently recites the historical implementation date; mixing both
# action families is therefore a direct source of false multi-date ambiguity.
ROLE_PATTERNS = [
    (
        "effective_from_implementation",
        "implementation",
        re.compile(
            r"(?:自|于|从)\s*" + DATE
            + r"\s*(?:起|开始)?[^。；，,]{0,32}(?:被)?(?:实施|实行)" + RISK
        ),
    ),
    (
        "implementation_effective_on",
        "implementation",
        re.compile(
            r"(?:被)?(?:实施|实行)" + RISK
            + r"[^。；，,]{0,48}(?:自|于|从)?\s*" + DATE + r"\s*(?:起|开始)?"
        ),
    ),
    (
        "effective_from_cancellation",
        "cancellation",
        re.compile(
            r"(?:自|于|从)\s*" + DATE
            + r"\s*(?:起|开始)?[^。；，,]{0,32}(?:撤销|取消|解除)" + RISK
        ),
    ),
    (
        "cancellation_effective_on",
        "cancellation",
        re.compile(
            r"(?:撤销|取消|解除)" + RISK
            + r"[^。；，,]{0,48}(?:自|于|从)?\s*" + DATE + r"\s*(?:起|开始)?"
        ),
    ),
]

# Exclusions apply to the exact matched clause, not a broad surrounding
# paragraph.  Broad-context exclusion was over-rejecting true effective
# clauses merely because the same paragraph mentioned an earlier application.
EXCLUDE_MATCH_TERMS = (
    "董事会",
    "股东大会",
    "收到",
    "披露",
    "公告日",
    "审计报告",
    "年度报告",
    "申请撤销",
    "申请实施",
    "提交申请",
)

EXPECTED_ACTION = {
    "actual_implementation_candidate": "implementation",
    "actual_cancel_candidate": "cancellation",
}


def iso(groups):
    y, mo, d = map(int, groups)
    return f"{y:04d}-{mo:02d}-{d:02d}"


def extract_role_dates(text):
    compact = re.sub(r"\s+", "", text or "")
    hits = []
    for role, action, pat in ROLE_PATTERNS:
        for mt in pat.finditer(compact):
            groups = mt.groups()
            date_groups = groups[-3:]
            matched = mt.group(0)
            context = compact[max(0, mt.start() - 80): min(len(compact), mt.end() + 120)]
            hits.append(
                {
                    "role": role,
                    "action": action,
                    "date": iso(date_groups),
                    "match_sha256": hashlib.sha256(matched.encode()).hexdigest(),
                    "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
                    "excluded_match_terms": [
                        x for x in EXCLUDE_MATCH_TERMS if x in matched
                    ],
                }
            )
    dedup = {}
    for h in hits:
        dedup[
            (
                h["role"],
                h["action"],
                h["date"],
                h["match_sha256"],
                h["context_sha256"],
            )
        ] = h
    return [dedup[k] for k in sorted(dedup)]


def build_candidates(session):
    corpus = s.build_corpus(session)
    out = []
    for row in corpus:
        klass = s.inventory.classify(row.get("title") or "")
        if klass in m.TARGET_CLASSES:
            out.append({**row, "transition_title_class": klass})
    return sorted(
        out,
        key=lambda x: (
            x["transition_title_class"],
            str(x.get("date") or ""),
            str(x.get("security_code") or ""),
            str(x.get("url") or ""),
        ),
    )


def main():
    session = requests.Session()
    candidates = build_candidates(session)
    records = []

    for i, row in enumerate(candidates, 1):
        klass = row["transition_title_class"]
        expected_action = EXPECTED_ACTION[klass]
        bulletin_date = str(row.get("date") or "")
        rec = {
            "ordinal": i,
            "security_code": row.get("security_code"),
            "date": bulletin_date,
            "title": row.get("title"),
            "url": row.get("url"),
            "class": klass,
            "expected_action": expected_action,
            "status": "NOT VERIFIED",
        }

        raw = None
        for url in s.candidate_urls(str(row.get("url") or "")):
            try:
                resp, meta = s.fetch_pdf(session, url)
                if resp.content.startswith(b"%PDF"):
                    raw = resp.content
                    rec["pdf_url"] = url
                    rec["pdf_sha256"] = hashlib.sha256(raw).hexdigest()
                    break
            except Exception as exc:
                rec.setdefault("download_errors", []).append(
                    f"{type(exc).__name__}: {exc}"
                )

        if raw is None:
            rec["status"] = "DOWNLOAD_NOT_VERIFIED"
            records.append(rec)
            continue

        try:
            text, pages = s.extract_text(raw)
        except Exception as exc:
            rec["status"] = "TEXT_NOT_VERIFIED"
            rec["error"] = f"{type(exc).__name__}: {exc}"
            records.append(rec)
            continue

        hits = extract_role_dates(text)
        expected_hits = [h for h in hits if h["action"] == expected_action]
        clean_expected_hits = [
            h for h in expected_hits if not h["excluded_match_terms"]
        ]

        # Effective transition evidence in an announcement must not be a
        # historical date earlier than the bulletin itself.  Earlier matches
        # are retained in evidence but rejected from the candidate set.
        chronological_hits = [
            h
            for h in clean_expected_hits
            if bulletin_date and h["date"] >= bulletin_date
        ]
        dates = sorted({h["date"] for h in hits})
        expected_dates = sorted({h["date"] for h in expected_hits})
        clean_expected_dates = sorted({h["date"] for h in clean_expected_hits})
        candidate_dates = sorted({h["date"] for h in chronological_hits})

        rec.update(
            {
                "pages": pages,
                "role_hits": hits,
                "role_dates": dates,
                "expected_action_dates": expected_dates,
                "clean_expected_action_dates": clean_expected_dates,
                "candidate_effective_dates": candidate_dates,
                "role_date_count": len(dates),
                "expected_action_date_count": len(expected_dates),
                "candidate_effective_date_count": len(candidate_dates),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )

        if len(candidate_dates) == 1:
            rec["status"] = "UNIQUE_EXPECTED_CHRONOLOGICAL_ROLE_DATE"
        elif len(candidate_dates) > 1:
            rec["status"] = "MULTI_EXPECTED_CHRONOLOGICAL_ROLE_DATE"
        elif clean_expected_dates and not candidate_dates:
            rec["status"] = "EXPECTED_ROLE_DATE_ONLY_BEFORE_BULLETIN"
        elif expected_dates and not clean_expected_dates:
            rec["status"] = "EXPECTED_ROLE_DATE_EXCLUDED"
        elif dates:
            rec["status"] = "ONLY_OPPOSITE_OR_NONQUALIFYING_ROLE_DATE"
        else:
            rec["status"] = "NO_ROLE_DATE"
        records.append(rec)

    counts = dict(sorted(Counter(x["status"] for x in records).items()))
    unique = sum(
        1
        for x in records
        if x["status"] == "UNIQUE_EXPECTED_CHRONOLOGICAL_ROLE_DATE"
    )
    ambiguous = sum(
        1
        for x in records
        if x["status"] == "MULTI_EXPECTED_CHRONOLOGICAL_ROLE_DATE"
    )

    report = {
        "schema": "stock-sse-transition-date-role-parser-v2",
        "selected": len(records),
        "status_counts": counts,
        "unique_expected_chronological_role_date": unique,
        "multi_expected_chronological_role_date": ambiguous,
        "records": records,
        "adjudication": {
            "role_parser_diagnostic": "SUPPORTED" if records else "NOT VERIFIED",
            "action_conditioning": "SUPPORTED_DIAGNOSTIC" if records else "NOT VERIFIED",
            "chronology_filter": "SUPPORTED_DIAGNOSTIC" if records else "NOT VERIFIED",
            "unique_effective_date_mapping": "NOT VERIFIED",
            "primary_document_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "The parser now conditions primary-document dates on the transition "
            "action implied by the bulletin title and rejects historical dates "
            "earlier than the bulletin date. This reduces a known false-ambiguity "
            "mode but remains diagnostic. Any unresolved row, replay inconsistency, "
            "or missing market requires fail-closed Historical ST/PIT."
        ),
    }

    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "selected": len(records),
                "status_counts": counts,
                "unique_expected_chronological_role_date": unique,
                "multi_expected_chronological_role_date": ambiguous,
                "adjudication": report["adjudication"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0 if records else 2


if __name__ == "__main__":
    raise SystemExit(main())
