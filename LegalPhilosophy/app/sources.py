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
        "markers": ("Elements of the Philosophy of Right", "Abstract Right", "Civil Society"),
    },
    {
        "source_id": "un_udhr",
        "title": "Universal Declaration of Human Rights — United Nations",
        "url": "https://www.un.org/en/about-us/universal-declaration-of-human-rights",
        "role": "LEGAL_AUTHORITY",
        "markers": ("Universal Declaration of Human Rights", "Article 1", "Article 29"),
    },
)


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
