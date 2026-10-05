from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import requests

CONTRACT = Path(".github/stock_diag/stock_bse_company_announcement_contract.py")
OUT = Path("stock_bse_marketwide_risk_warning_history.json")
BEGIN = "2018-01-01"
END = "2026-09-30"
KEYWORDS = [
    ("risk_warning", "风险警示"),
    ("delisting_risk_warning", "退市风险警示"),
    ("cancel_risk_warning", "撤销风险警示"),
]
MAX_TYPES = 60
MAX_PAGES_PER_QUERY = 300


def load_contract():
    spec = importlib.util.spec_from_file_location("bse_contract", CONTRACT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load BSE contract helper")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def canonical_sha(rows):
    payload = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def norm_record(r, keyword, dtype):
    title = str(r.get("disclosureTitle") or "") + str(r.get("disclosurePostTitle") or "")
    return {
        "companyCd": str(r.get("companyCd") or "").strip(),
        "companyName": str(r.get("companyName") or "").strip(),
        "title": title.strip(),
        "publishDate": str(r.get("publishDate") or "").strip(),
        "destFilePath": str(r.get("destFilePath") or "").strip(),
        "fileExt": str(r.get("fileExt") or "").strip(),
        "xxzrlx": str(r.get("xxzrlx") or "").strip(),
        "query_keyword": keyword,
        "disclosure_type": dtype,
    }


def identity(r):
    return (
        r["companyCd"],
        r["publishDate"],
        r["destFilePath"],
        r["title"],
    )


def as_int(value, default=-1):
    try:
        return int(value)
    except Exception:
        return default


def query_page(mod, session, dtype, keyword, page_no):
    base = {
        "callback": "stockAiBseMarketCb",
        "disclosureSubtype": "",
        "page": page_no,
        "companyCd": "",
        "isNewThree": 1,
        "startTime": BEGIN,
        "endTime": END,
        "keyword": keyword,
        "hyType": "",
    }
    pairs = list(base.items())
    pairs += [("disclosureType[]", dtype), ("xxfcbj[]", "2")]
    pairs += [("needFields[]", field) for field in mod.NEED_FIELDS]
    obj, meta = mod.request_variant(
        session,
        f"marketwide_{keyword}_{dtype}_page_{page_no}",
        "POST",
        pairs,
    )
    if obj is None:
        raise RuntimeError(
            f"query failed dtype={dtype!r} keyword={keyword!r} page={page_no}: {meta}"
        )
    records = mod.find_records(obj)
    pm = mod.list_info_meta(obj)
    return records, pm, meta


def fetch_combination(mod, session, dtype, keyword):
    first_records, first_pm, first_meta = query_page(mod, session, dtype, keyword, 0)
    total_pages = as_int(first_pm.get("totalPages"), 0)
    total_elements = as_int(first_pm.get("totalElements"), 0)
    size = as_int(first_pm.get("size"), 0)
    number = as_int(first_pm.get("number"), -1)

    if number not in (-1, 0):
        raise RuntimeError(
            f"page echo mismatch dtype={dtype!r} keyword={keyword!r}: {number}"
        )
    if total_pages < 0 or total_elements < 0:
        raise RuntimeError("negative server denominator")
    if total_pages > MAX_PAGES_PER_QUERY:
        raise RuntimeError(
            f"server totalPages={total_pages} exceeds cap={MAX_PAGES_PER_QUERY}"
        )
    if total_elements == 0:
        if total_pages not in (0, 1) or first_records:
            raise RuntimeError("empty denominator contradicts returned rows/pages")
        return {
            "disclosure_type": dtype,
            "keyword": keyword,
            "server": first_pm,
            "page_count": 0,
            "record_count": 0,
            "canonical_sha256": canonical_sha([]),
            "pages": [],
            "records": [],
        }

    if total_pages <= 0:
        raise RuntimeError("positive totalElements with non-positive totalPages")

    all_records = []
    seen = set()
    pages = []
    for page_no in range(total_pages):
        if page_no == 0:
            records, pm, meta = first_records, first_pm, first_meta
        else:
            records, pm, meta = query_page(mod, session, dtype, keyword, page_no)

        if as_int(pm.get("number"), -1) not in (-1, page_no):
            raise RuntimeError(
                f"page echo mismatch requested={page_no} got={pm.get('number')}"
            )
        if as_int(pm.get("totalPages"), -1) != total_pages:
            raise RuntimeError(f"totalPages drift at page={page_no}")
        if as_int(pm.get("totalElements"), -1) != total_elements:
            raise RuntimeError(f"totalElements drift at page={page_no}")

        number_of_elements = as_int(pm.get("numberOfElements"), len(records))
        if number_of_elements != len(records):
            raise RuntimeError(
                f"numberOfElements mismatch page={page_no}: "
                f"server={number_of_elements} parsed={len(records)}"
            )

        normalized = [norm_record(r, keyword, dtype) for r in records]
        ids = [identity(r) for r in normalized]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"duplicate identity within page={page_no}")
        overlap = seen & set(ids)
        if overlap:
            raise RuntimeError(
                f"cross-page duplicate identities page={page_no} count={len(overlap)}"
            )
        seen.update(ids)
        all_records.extend(normalized)
        pages.append(
            {
                "page": page_no,
                "row_count": len(records),
                "server": pm,
                "payload_sha256": meta.get("payload_sha256"),
                "first_identity": list(ids[0]) if ids else None,
                "last_identity": list(ids[-1]) if ids else None,
            }
        )

    if len(all_records) != total_elements:
        raise RuntimeError(
            f"exhaustive count mismatch server={total_elements} parsed={len(all_records)}"
        )

    return {
        "disclosure_type": dtype,
        "keyword": keyword,
        "server": {
            "totalPages": total_pages,
            "totalElements": total_elements,
            "size": size,
        },
        "page_count": total_pages,
        "record_count": len(all_records),
        "canonical_sha256": canonical_sha(all_records),
        "pages": pages,
        "records": all_records,
    }


def main():
    report = {
        "schema": "stock-bse-marketwide-risk-warning-history-v1",
        "window": {"begin": BEGIN, "end": END},
        "queries": [],
        "errors": [],
        "adjudication": {
            "bse_marketwide_risk_warning_query_surface": "NOT VERIFIED",
            "exhaustive_bse_event_corpus": "NOT VERIFIED",
            "event_semantics_complete": "NOT VERIFIED",
            "effective_state_reconstruction": "NOT VERIFIED",
            "bse_historical_st_pit": "NOT VERIFIED",
            "bse_historical_suspension_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
    }

    try:
        mod = load_contract()
        session = requests.Session()
        type_obj, type_meta = mod.get_control_json(session, mod.TYPE_ENDPOINT, {"type": 6})
        types = mod.collect_values(
            type_obj, {"distype", "dvalue", "disclosureType", "value"}
        )
        types = list(dict.fromkeys(types))
        if not types:
            raise RuntimeError("official disclosure_type.do returned no usable values")
        if len(types) > MAX_TYPES:
            raise RuntimeError(f"type count {len(types)} exceeds cap {MAX_TYPES}")

        report["classification"] = {
            "source": mod.TYPE_ENDPOINT,
            "transport": type_meta,
            "type_count": len(types),
            "types": types,
        }

        combined = {}
        for label, keyword in KEYWORDS:
            for dtype in types:
                item = fetch_combination(mod, session, dtype, keyword)
                records = item.pop("records")
                report["queries"].append(
                    {"label": label, **item}
                )
                for record in records:
                    combined[identity(record)] = record

        corpus = [combined[k] for k in sorted(combined)]
        if not corpus:
            raise RuntimeError("all market-wide risk-warning queries returned empty corpus")

        report["corpus"] = {
            "unique_event_rows": len(corpus),
            "unique_codes": len({r["companyCd"] for r in corpus if r["companyCd"]}),
            "canonical_sha256": canonical_sha(corpus),
            "st_named_company_rows": sum(
                1 for r in corpus if "ST" in r["companyName"].upper()
            ),
            "title_contains_risk_warning_rows": sum(
                1 for r in corpus if "风险警示" in r["title"]
            ),
        }
        report["adjudication"][
            "bse_marketwide_risk_warning_query_surface"
        ] = "SUPPORTED"
        report["adjudication"]["exhaustive_bse_event_corpus"] = "SUPPORTED"
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")

    report["boundary"] = (
        "This can prove exhaustive retrieval only for the frozen keyword/type query matrix "
        "returned by first-party BSE controls. Event titles/publication dates are not treated "
        "as effective daily ST/PIT state. PIT, suspension state, event semantics, Advanced "
        "Business and Final remain NOT VERIFIED unless separate evidence closes them."
    )
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "classification": report.get("classification"),
                "query_count": len(report["queries"]),
                "corpus": report.get("corpus"),
                "errors": report["errors"],
                "adjudication": report["adjudication"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    ok = (
        not report["errors"]
        and report["adjudication"]["exhaustive_bse_event_corpus"] == "SUPPORTED"
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
