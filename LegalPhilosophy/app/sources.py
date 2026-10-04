from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import hashlib
import html
import re

from pypdf import PdfReader

from .domain import SourceDocument
from .netclient import NetClient


PRIMARY_SOURCE_ID = "hegel_dyde_1896_primary"
PRIMARY_SCAN_URL = "https://upload.wikimedia.org/wikipedia/commons/6/67/Hegel%27s_Philosophy_of_right_%28IA_cu31924014578979%29.pdf"
PRIMARY_REQUIRED_PREFIXES = (
    "EDITION:DYDE_1896:",
    "SECTION:Preface / Introduction:1-32:",
    "SECTION:Abstract Right:34-104:",
    "SECTION:Morality:105-141:",
    "SECTION:Family:158-181:",
    "SECTION:Civil Society:182-256:",
    "SECTION:State:257-360:",
    "SECTION:International Law:330-340:",
    "SECTION:World History:341-360:",
)


SOURCE_SPECS = (
    {
        "source_id": PRIMARY_SOURCE_ID,
        "title": "Hegel's Philosophy of Right — S. W. Dyde translation (1896)",
        "url": PRIMARY_SCAN_URL,
        "role": "PRIMARY_TEXT",
        "format": "primary_pdf",
        "markers": (),
    },
    {
        "source_id": "sep_hegel_social_political",
        "title": "Hegel's Social and Political Philosophy — Stanford Encyclopedia of Philosophy",
        "url": "https://plato.stanford.edu/entries/hegel-social-political/",
        "role": "AUTHORITATIVE_SCHOLARSHIP",
        "markers": (
            "Elements of the Philosophy of Right",
            "Abstract Right",
            "Civil Society",
            "Conservativism and Progressive Readings",
            "Metaphysical and Non-Metaphysical Readings",
        ),
    },
    {
        "source_id": "iep_hegel_social_political",
        "title": "Hegel: Social and Political Thought — Internet Encyclopedia of Philosophy",
        "url": "https://iep.utm.edu/hegelsoc/",
        "role": "AUTHORITATIVE_SCHOLARSHIP",
        "markers": (
            "nationalistic apologist for the Prussian State",
            "objective freedom",
            "subjective freedom",
        ),
    },
    {
        "source_id": "un_udhr",
        "title": "Universal Declaration of Human Rights — United Nations",
        "url": "https://www.un.org/en/about-us/universal-declaration-of-human-rights",
        "role": "LEGAL_AUTHORITY",
        "markers": ("Universal Declaration of Human Rights", "Article 1", "Article 29"),
    },
    {
        "source_id": "nara_brown_v_board",
        "title": "Brown v. Board of Education (1954) — National Archives",
        "url": "https://www.archives.gov/milestone-documents/brown-v-board-of-education",
        "role": "CASE",
        "markers": ("Brown v. Board of Education", "347 U.S. 483", "Record Group 267"),
    },
    {
        "source_id": "loc_plessy_v_ferguson",
        "title": "Plessy v. Ferguson, 163 U.S. 537 (1896) — U.S. Reports / Library of Congress",
        "url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep163/usrep163537/usrep163537.pdf",
        "role": "CASE",
        "format": "pdf",
        "markers": ("PLESSY v. FERGUSON", "No. 210", "Fourteenth Amendment"),
    },
    {
        "source_id": "loc_barnette",
        "title": "West Virginia State Board of Education v. Barnette, 319 U.S. 624 (1943) — U.S. Reports / Library of Congress",
        "url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep319/usrep319624/usrep319624.pdf",
        "role": "CASE",
        "format": "pdf",
        "markers": ("WEST VIRGINIA STATE BOARD OF EDUCATION", "No. 591", "First and Fourteenth Amendments"),
    },
    {
        "source_id": "loc_obergefell_v_hodges",
        "title": "Obergefell v. Hodges, 576 U.S. 644 (2015) — U.S. Reports / Library of Congress",
        "url": "https://tile.loc.gov/storage-services/service/ll/usrep/usrep576/usrep576644/usrep576644.pdf",
        "role": "CASE",
        "format": "pdf",
        "markers": ("OBERGEFELL", "Fourteenth Amendment", "same-sex couples"),
    },
)

CASE_CORPUS_IDS = frozenset({
    "loc_plessy_v_ferguson",
    "loc_barnette",
    "nara_brown_v_board",
    "loc_obergefell_v_hodges",
})

PRIMARY_EDITION = {
    "catalog_url": "https://openlibrary.org/books/OL14055643M/Hegel%27s_Philosophy_of_right",
    "scan_url": "https://upload.wikimedia.org/wikipedia/commons/6/67/Hegel%27s_Philosophy_of_right_%28IA_cu31924014578979%29.pdf",
    "open_library_id": "OL14055643M",
    "internet_archive_id": "cu31924014578979",
    "lccn": "12013791",
    "oclc": "1802772",
    "year": 1896,
    "publisher": "G. Bell and sons",
    "translator": "S. W. Dyde",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _plain_text(markup: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", markup)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    normalized = _normalize_text(html.unescape(without_tags))
    if len(normalized) < 500:
        raise ValueError("validated source text unexpectedly short")
    return normalized


def _pdf_pages(payload: bytes) -> list[str]:
    if not payload.startswith(b"%PDF-"):
        raise ValueError("validated PDF source is missing PDF magic")
    reader = PdfReader(BytesIO(payload), strict=False)
    pages = [_normalize_text(page.extract_text() or "") for page in reader.pages]
    if len(pages) < 1 or sum(len(page) for page in pages) < 1000:
        raise ValueError("validated PDF source text unexpectedly short")
    return pages


def _pdf_text(payload: bytes) -> str:
    return _normalize_text("\n".join(_pdf_pages(payload)))


def _find_page(pages: list[str], tokens: tuple[str, ...], label: str) -> int:
    folded = tuple(token.casefold() for token in tokens)
    for index, page in enumerate(pages):
        candidate = page.casefold()
        if all(token in candidate for token in folded):
            return index
    raise ValueError(f"primary-edition lineage marker not found for {label}: {tokens}")


def _primary_pdf_text_and_hits(payload: bytes) -> tuple[str, tuple[str, ...]]:
    pages = _pdf_pages(payload)
    if len(pages) != 410:
        raise ValueError(f"unexpected primary-edition page count {len(pages)}; expected 410")

    edition_page = _find_page(
        pages,
        ("HEGEL'S", "PHILOSOPHY OF", "RIGHT", "TRANSLATED BY", "S. W. DYDE", "GEORGE BELL AND SONS", "1896"),
        "Dyde 1896 title page",
    )
    sections = (
        ("Preface / Introduction", "1-32", ("Author's Preface", "Conception of the Will, of Freedom, and of Right", "1-32")),
        ("Abstract Right", "34-104", ("FIRST PART.", "abstract right.", "34-104")),
        ("Morality", "105-141", ("SECOND PART.", "MORALITY.", "105-141")),
        ("Family", "158-181", ("First Section. The Family", "158-181")),
        ("Civil Society", "182-256", ("Second Section. The Civic Community", "182-256")),
        ("State", "257-360", ("Third Section. The State", "257-360")),
        ("International Law", "330-340", ("B. International Law", "330-340")),
        ("World History", "341-360", ("C. World-history", "341-360")),
    )
    hits = [f"EDITION:DYDE_1896:PDF_PAGE:{edition_page}"]
    for name, section_range, tokens in sections:
        page = _find_page(pages, tokens, f"{name} §§ {section_range}")
        hits.append(f"SECTION:{name}:{section_range}:PDF_PAGE:{page}")
    return _normalize_text("\n".join(pages)), tuple(hits)


def _fetch_source_text(client: NetClient, spec: dict):
    if spec.get("format") in {"pdf", "primary_pdf"}:
        payload, receipt = client.get_bytes(
            spec["url"],
            allowed_content_types=("application/pdf",),
            max_bytes=15_000_000 if spec.get("format") == "primary_pdf" else 30_000_000,
            accept="application/pdf",
        )
        if spec.get("format") == "primary_pdf":
            text, hits = _primary_pdf_text_and_hits(payload)
            return text, receipt, hits
        return _pdf_text(payload), receipt, None
    markup, receipt = client.get_text(spec["url"])
    return _plain_text(markup), receipt, None

def fetch_current_sources(client: NetClient) -> tuple[list[SourceDocument], dict[str, str]]:
    docs: list[SourceDocument] = []
    texts: dict[str, str] = {}
    for spec in SOURCE_SPECS:
        try:
            text, receipt, prevalidated_hits = _fetch_source_text(client, spec)
            if prevalidated_hits is None:
                lower = text.casefold()
                hits = tuple(marker for marker in spec["markers"] if marker.casefold() in lower)
                if len(hits) != len(spec["markers"]):
                    missing = sorted(set(spec["markers"]) - set(hits))
                    raise ValueError(f"semantic markers missing: {missing}")
            else:
                hits = prevalidated_hits
        except Exception as exc:
            raise RuntimeError(
                f"source validation failed for {spec['source_id']} ({spec['url']}): {exc}"
            ) from exc
        doc = SourceDocument(
            source_id=spec["source_id"],
            title=spec["title"],
            url=spec["url"],
            role=spec["role"],
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            payload_sha256=str(receipt.payload_sha256),
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            content_type=str(receipt.content_type),
            validation_status="PASS",
            marker_hits=hits,
        )
        docs.append(doc)
        texts[doc.source_id] = text
    return docs, texts


def primary_lineage_status(docs: list[SourceDocument]) -> str:
    primary = [
        doc for doc in docs
        if doc.source_id == PRIMARY_SOURCE_ID
        and doc.role == "PRIMARY_TEXT"
        and doc.validation_status == "PASS"
        and doc.content_type == "application/pdf"
    ]
    if len(primary) != 1:
        return "NOT VERIFIED"
    doc = primary[0]
    if len(doc.payload_sha256) != 64 or len(doc.text_sha256) != 64:
        return "NOT VERIFIED"
    hits = tuple(doc.marker_hits)
    if not all(any(hit.startswith(prefix) for hit in hits) for prefix in PRIMARY_REQUIRED_PREFIXES):
        return "NOT VERIFIED"
    return "PASS"

def fetch_primary_edition(client: NetClient) -> tuple[dict, str, bytes]:
    catalog_markup, catalog_receipt = client.get_text(PRIMARY_EDITION["catalog_url"])
    catalog_text = _plain_text(catalog_markup)
    lower = catalog_text.casefold()
    required_catalog_markers = (
        PRIMARY_EDITION["open_library_id"],
        PRIMARY_EDITION["internet_archive_id"],
        PRIMARY_EDITION["lccn"],
        PRIMARY_EDITION["oclc"],
        PRIMARY_EDITION["publisher"],
        str(PRIMARY_EDITION["year"]),
    )
    missing = [marker for marker in required_catalog_markers if str(marker).casefold() not in lower]
    if missing:
        raise ValueError(f"primary-edition catalog markers missing: {missing}")

    scan, scan_receipt = client.get_bytes(
        PRIMARY_EDITION["scan_url"],
        allowed_content_types=("application/pdf",),
        max_bytes=20_000_000,
        accept="application/pdf",
    )
    if not scan.startswith(b"%PDF-"):
        raise ValueError("primary-edition scan is not a PDF")
    if len(scan) < 1_000_000:
        raise ValueError("primary-edition scan is implausibly small")
    if PRIMARY_EDITION["internet_archive_id"] not in PRIMARY_EDITION["scan_url"]:
        raise ValueError("primary-edition scan/catalog identifier mismatch")

    evidence = {
        "status": "IDENTITY_ONLY",
        "source_role": "PRIMARY_TEXT",
        "work": "Hegel's Philosophy of right",
        "edition_year": PRIMARY_EDITION["year"],
        "publisher": PRIMARY_EDITION["publisher"],
        "translator": PRIMARY_EDITION["translator"],
        "identifiers": {
            "open_library": PRIMARY_EDITION["open_library_id"],
            "internet_archive": PRIMARY_EDITION["internet_archive_id"],
            "lccn": PRIMARY_EDITION["lccn"],
            "oclc": PRIMARY_EDITION["oclc"],
        },
        "catalog": {
            "url": PRIMARY_EDITION["catalog_url"],
            "payload_sha256": catalog_receipt.payload_sha256,
            "text_sha256": hashlib.sha256(catalog_text.encode("utf-8")).hexdigest(),
            "retrieved_at": catalog_receipt.retrieved_at,
            "content_type": catalog_receipt.content_type,
            "markers": list(required_catalog_markers),
        },
        "scan": {
            "url": PRIMARY_EDITION["scan_url"],
            "payload_sha256": scan_receipt.payload_sha256,
            "retrieved_at": scan_receipt.retrieved_at,
            "content_type": scan_receipt.content_type,
            "bytes": len(scan),
            "pdf_magic": "PASS",
        },
        "identity_crosscheck": "PASS",
        "section_lineage": "NOT VERIFIED",
        "quotation_boundary": (
            "Catalog/scan identity alone does not satisfy primary section lineage and cannot authorize quotations; "
            "production PASS requires the exact PDF title-page plus frozen section-range evidence."
        ),
    }
    return evidence, catalog_text, scan


def build_conflict_registry(docs: list[SourceDocument]) -> dict:
    by_id = {doc.source_id: doc for doc in docs if doc.validation_status == "PASS"}
    sep = by_id.get("sep_hegel_social_political")
    iep = by_id.get("iep_hegel_social_political")
    if not sep or not iep:
        return {"status": "NOT VERIFIED", "reason": "two independent scholarship sources are required"}
    sep_markers = set(sep.marker_hits)
    iep_markers = set(iep.marker_hits)
    if not {
        "Conservativism and Progressive Readings",
        "Metaphysical and Non-Metaphysical Readings",
    }.issubset(sep_markers):
        return {"status": "NOT VERIFIED", "reason": "SEP debate markers are incomplete"}
    if not {
        "nationalistic apologist for the Prussian State",
        "objective freedom",
        "subjective freedom",
    }.issubset(iep_markers):
        return {"status": "NOT VERIFIED", "reason": "IEP interpretation markers are incomplete"}
    return {
        "status": "PASS",
        "rule": "PRESERVE_TENSION_NO_AUTOMATIC_RESOLUTION",
        "sources": [sep.source_id, iep.source_id],
        "tensions": [
            {
                "topic": "political classification of Hegel's state",
                "sep_evidence": "conservative versus progressive readings are explicitly presented as a debate",
                "iep_evidence": "the Prussian-apologist characterization is recorded while freedom remains central to the state account",
                "resolution": "NOT AUTO-RESOLVED",
            },
            {
                "topic": "systematic/metaphysical dependence of Philosophy of Right",
                "sep_evidence": "metaphysical and non-metaphysical readings are explicitly separated",
                "iep_evidence": "state analysis is presented through objective and subjective freedom",
                "resolution": "NOT AUTO-RESOLVED",
            },
        ],
    }
