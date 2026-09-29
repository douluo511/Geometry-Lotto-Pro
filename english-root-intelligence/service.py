from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from core import APP_NAME, APP_VERSION, MANIFEST_URLS, self_test as legacy_self_test
from contracts import validate_manifest, validate_roots
from engine import EnglishRootEngine
from evidence import EvidenceLedger
from net_client import NetClient
from storage import RootStorage

def _alternate_data_url(url: str) -> str:
    prefix = "https://raw.githubusercontent.com/douluo511/Geometry-Lotto-Pro/main/"
    if url.startswith(prefix):
        suffix = url[len(prefix):]
        return "https://github.com/douluo511/Geometry-Lotto-Pro/raw/refs/heads/main/" + suffix
    raise ValueError("cannot derive independent distribution path for data_url")

class EnglishRootService:
    def __init__(self, storage: RootStorage, net: NetClient, evidence: EvidenceLedger):
        self.storage = storage
        self.net = net
        self.evidence = evidence
        self.engine = EnglishRootEngine(storage)

    def analyze(self, word):
        r = self.engine.analyze(word)
        self.evidence.record("ENGINE", "PASS", word=r.get("word"), confidence=r.get("confidence"))
        return r

    def today_roots(self, count=3):
        return self.engine.today_roots(count)

    def stats(self):
        return self.engine.stats()

    def mark_practiced(self, m):
        return self.storage.mark_practiced(m)

    def one_click_update(self):
        manifest_receipts = []
        data_receipts = []
        try:
            if len(set(MANIFEST_URLS)) < 2:
                raise RuntimeError("trusted manifest distribution redundancy is not satisfied")

            manifests = []
            for idx, url in enumerate(MANIFEST_URLS, 1):
                value, receipt = self.net.get_json(url, source_id=f"manifest_path_{idx}")
                validate_manifest(value)
                manifests.append(value)
                manifest_receipts.append(receipt)

            canonical_manifests = {
                json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for v in manifests
            }
            if len(canonical_manifests) != 1:
                raise ValueError("trusted manifest distribution paths disagree")

            manifest = manifests[0]
            data_urls = [manifest["data_url"], _alternate_data_url(manifest["data_url"])]
            if len(set(data_urls)) < 2:
                raise RuntimeError("trusted data distribution redundancy is not satisfied")

            payloads = []
            validated_values = []
            for idx, url in enumerate(data_urls, 1):
                raw, receipt = self.net.get_bytes(url, source_id=f"data_path_{idx}")
                digest = hashlib.sha256(raw).hexdigest()
                if digest.lower() != manifest["sha256"].lower():
                    raise ValueError(f"data_path_{idx} SHA256 mismatch")
                value = validate_roots(json.loads(raw.decode("utf-8-sig")))
                payloads.append(raw)
                validated_values.append(value)
                data_receipts.append(receipt)

            if len({hashlib.sha256(x).hexdigest() for x in payloads}) != 1:
                raise ValueError("trusted data distribution paths disagree")
            if json.dumps(validated_values[0], sort_keys=True, ensure_ascii=False) != json.dumps(validated_values[1], sort_keys=True, ensure_ascii=False):
                raise ValueError("validated data semantics disagree")

            raw = payloads[0]
            digest = hashlib.sha256(raw).hexdigest()
            receipts = tuple(manifest_receipts + data_receipts)
            distinct_source_ids = sorted({x.source_id for x in receipts})
            if len(receipts) < 4 or len(distinct_source_ids) < 4:
                raise RuntimeError("source quorum evidence incomplete")

            evidence_row = self.evidence.make_row(
                "NETWORK",
                "PASS",
                network_gate="PASS",
                manifest_sources=[asdict(x) for x in manifest_receipts],
                data_sources=[asdict(x) for x in data_receipts],
                distinct_source_ids=distinct_source_ids,
                payload_hash=digest,
                manifest_hash=hashlib.sha256(
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            )
            value = self.storage.commit_update(
                raw,
                fetched_at=data_receipts[0].fetched_at,
                evidence_path=self.evidence.path,
                evidence_row=evidence_row,
            )
            return {
                "status": "PASS",
                "network_gate": "PASS",
                "version": value.get("version"),
                "roots": len(value["roots"]),
                "sha256": digest,
                "source_count": len(receipts),
                "distinct_source_ids": distinct_source_ids,
                "sources": [asdict(x) for x in receipts],
            }
        except Exception as exc:
            try:
                self.evidence.record(
                    "NETWORK",
                    "FAIL",
                    error=f"{type(exc).__name__}: {exc}",
                    attempts=list(getattr(exc, "glp_attempts", ()) or ()),
                    manifest_sources=[asdict(x) for x in manifest_receipts],
                    data_sources=[asdict(x) for x in data_receipts],
                )
            except Exception:
                pass
            raise

    def one_click_repair(self):
        r = self.storage.repair()
        self.evidence.record("STORAGE", r["status"], checks=r["checks"])
        return r

def create_service(root: Path | None = None, net: NetClient | None = None) -> EnglishRootService:
    s = RootStorage(root)
    return EnglishRootService(s, net or NetClient(), EvidenceLedger(s.root / "evidence.jsonl"))

def self_test(root: Path | None = None):
    return legacy_self_test(root)
