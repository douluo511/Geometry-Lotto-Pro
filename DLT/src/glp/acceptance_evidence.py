"""Preserve exact live-response bytes before a disposable acceptance Store exits."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import uuid

from .util import atomic_json, sha256_bytes, sha256_json, utc_now


def preserve_live_evidence(store, result_file: str, exe_sha256: str) -> dict:
    if len(exe_sha256) != 64 or any(c not in "0123456789abcdef" for c in exe_sha256):
        raise ValueError("current exact EXE identity is required")
    evidence_bytes = store.evidence_path.read_bytes()
    canonical_bytes = store.history_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    canonical = json.loads(canonical_bytes)
    if (canonical.get("game") != "DLT" or not isinstance(canonical.get("draws"), list)
            or not canonical["draws"]
            or sha256_json(canonical["draws"]) != canonical.get("canonical_hash")):
        raise ValueError("canonical bytes do not match their declared identity")
    if (evidence.get("network_gate") != "PASS" or evidence.get("freshness_gate") != "PASS"
            or evidence.get("crosscheck_status") != "PASS"
            or canonical.get("canonical_hash") != evidence.get("canonical_hash")):
        raise ValueError("live dataset/evidence binding is not PASS")
    records = []

    def visit(value, location):
        if isinstance(value, dict):
            if "body_b64" in value:
                raw = base64.b64decode(value["body_b64"], validate=True)
                digest = sha256_bytes(raw)
                if (not raw or digest != value.get("sha256")
                        or type(value.get("bytes")) is not int or len(raw) != value["bytes"]
                        or value.get("validation_result") != "PASS"
                        or type(value.get("http_status")) is not int
                        or not 200 <= value["http_status"] < 300
                        or not str(value.get("final_url", "")).startswith("https://")
                        or not value.get("fetched_at") or not value.get("parser_version")):
                    raise ValueError("raw response bytes/provenance failed verification")
                records.append((location, value, raw, digest))
            for key, child in value.items():
                if key != "body_b64":
                    visit(child, location + "/" + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, location + "/" + str(index))

    visit(evidence, "source_evidence")
    if not records:
        raise ValueError("live raw response bodies are missing")
    result = Path(result_file).resolve()
    destination = result.parent / (result.stem + "-live-" + uuid.uuid4().hex)
    destination.mkdir(parents=True, exist_ok=False)
    raw_dir = destination / "raw_responses"
    raw_dir.mkdir()
    raw_records = []
    for location, metadata, raw, digest in records:
        raw_path = raw_dir / (digest + ".bin")
        raw_path.write_bytes(raw)
        if sha256_bytes(raw_path.read_bytes()) != digest:
            raise OSError("persisted raw bytes differ")
        raw_records.append({
            "location": location, "artifact": "raw_responses/" + raw_path.name,
            **{key: metadata[key] for key in ("sha256", "bytes", "http_status",
                                             "final_url", "fetched_at", "parser_version")},
        })
    for name, data in (("canonical_history.json", canonical_bytes), ("source_evidence.json", evidence_bytes)):
        (destination / name).write_bytes(data)
        if (destination / name).read_bytes() != data:
            raise OSError("persisted dataset evidence differs")
    manifest = {
        "schema": "dlt-exact-live-evidence-v1", "status": "PASS", "preserved_at": utc_now(),
        "github_sha": os.environ.get("GITHUB_SHA"), "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "exe_sha256": exe_sha256, "canonical_hash": evidence["canonical_hash"],
        "canonical_file_sha256": sha256_bytes(canonical_bytes),
        "source_evidence_sha256": sha256_bytes(evidence_bytes),
        "raw_responses": raw_records, "final_release_gate": "PENDING",
    }
    path = destination / "manifest.json"
    atomic_json(path, manifest)
    return {"status": "PASS", "directory": destination.name,
            "manifest_sha256": sha256_bytes(path.read_bytes()),
            "raw_response_count": len(raw_records), "exe_sha256": exe_sha256}
