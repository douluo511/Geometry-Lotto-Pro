from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import re

from .domain import SourceDocument
from .netclient import NetClient


SOURCE_SPECS = (
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
)

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


def _plain_text(markup: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", markup)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    normalized = re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
    if len(normalized) < 500:
        raise ValueError("validated source text unexpectedly short")
    return normalized


def fetch_current_sources(client: NetClient) -> tuple[list[SourceDocument], dict[str, str]]:
    docs: list[SourceDocument] = []
    texts: dict[str, str] = {}
    for spec in SOURCE_SPECS:
        markup, receipt = client.get_text(spec["url"])
        text = _plain_text(markup)
        lower = text.casefold()
        hits = tuple(marker for marker in spec["markers"] if marker.casefold() in lower)
        if len(hits) != len(spec["markers"]):
            missing = sorted(set(spec["markers"]) - set(hits))
            raise ValueError(f"source semantic markers missing for {spec['source_id']}: {missing}")
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
        "status": "PASS",
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
        "quotation_boundary": (
            "Edition lineage is verified, but this gate does not authorize invented quotations or section claims; "
            "quoted text still requires text/page-level evidence."
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
