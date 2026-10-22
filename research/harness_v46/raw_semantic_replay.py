"""Second-process raw-byte semantic replay for V4.7 SHADOW history collection.

This validates that preserved successful HTTP bodies actually decode to the rows
asserted by a data worker. It reuses the repository's pinned official-source
parser implementations; it is NOT an independent parser implementation, a
cryptographic source-origin proof, a trusted publication timestamp or G01 PASS.
No fetches, predictions or ledger mutation occur in this process.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import official_intake as oi
from .core import GateError, digest


def verify_sources(payload: dict, source_module) -> dict:
    """Reconstruct successfully claimed rows from retained raw bytes, not claims."""
    if not isinstance(payload, dict) or payload.get("schema") != oi.WORKER_SCHEMA:
        raise GateError("RAW_REPLAY_WORKER_SCHEMA_INVALID")
    game = payload.get("lottery")
    if game not in oi.SOURCE_IDS:
        raise GateError("RAW_REPLAY_LOTTERY_INVALID")
    if payload.get("status") not in {"WORKER_FETCH_COMPLETE", "WORKER_FETCH_PARTIAL"}:
        raise GateError("RAW_REPLAY_STATUS_INVALID")
    source_hashes = oi.source_file_hashes(game)
    if payload.get("source_files_sha256") != source_hashes:
        raise GateError("RAW_REPLAY_SOURCE_HASH_MISMATCH")
    parser_version = payload.get("parser_version")
    if parser_version != oi._expected_parser_version(game):
        raise GateError("RAW_REPLAY_PARSER_VERSION_MISMATCH")
    if str(getattr(source_module, "PARSER_VERSION", "")) != parser_version:
        raise GateError("RAW_REPLAY_IMPORTED_PARSER_VERSION_MISMATCH")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not oi._source_id_set_valid(game, sources):
        raise GateError("RAW_REPLAY_SOURCE_SET_INVALID")

    verified: dict[str, str] = {}
    for source in sources:
        source_id = source["source_id"]
        url = source.get("url")
        _, root = oi._root_for_url(game, url)
        if (source.get("source_root") != root or
                oi.EXPECTED_ROOTS[game].get(source_id) != root or
                source.get("source_name") != oi.EXPECTED_SOURCE_NAMES[game][source_id]):
            raise GateError("RAW_REPLAY_SOURCE_IDENTITY_MISMATCH")
        status = source.get("raw_reparse_status")
        if status != "PASS":
            continue
        if not source.get("draws"):
            raise GateError("RAW_REPLAY_PASS_WITHOUT_DRAW_ROWS")
        raw_list = source.get("raw_artifacts")
        if not isinstance(raw_list, list) or not raw_list:
            raise GateError("RAW_REPLAY_REQUIRES_RAW_BYTES")
        artifacts = oi._validate_artifacts(game, source, parser_version)
        if not any(a["http_status"] == 200 and a["size_bytes"] > 0
                   for a in artifacts):
            raise GateError("RAW_REPLAY_REQUIRES_NONEMPTY_HTTP_200")
        observed = oi._reparse_raw_history(game, source_module, source_id, artifacts)
        expected = oi._canonical_draws(
            game, source["draws"], minimum=oi._source_minimum(game, source_id)
        )
        if observed != expected:
            raise GateError("SECOND_PROCESS_REPARSE_DIFFERS_FROM_CLAIM:" + source_id)
        claimed_sha = source.get("raw_reparse_sha256")
        sha = oi._rows_sha256(observed)
        if claimed_sha != sha:
            raise GateError("SECOND_PROCESS_REPARSE_SHA_MISMATCH:" + source_id)
        verified[source_id] = sha
    if not verified:
        raise GateError("SECOND_PROCESS_NO_SUCCESSFUL_SOURCE_TO_VERIFY")
    return {
        "schema": "V47-SECOND-PROCESS-SEMANTIC-REPLAY-1",
        "lottery": game,
        "worker_payload_sha256": digest(payload),
        "parser_source_hashes": source_hashes,
        "verified_source_ids": sorted(verified),
        "replayed_rows_sha256": verified,
        "status": "SECOND_PROCESS_SAME_PARSER_REPLAY_MATCHED",
        "source_origin_authenticity": "NOT_VERIFIED",
        "publication_time_authenticity": "NOT_VERIFIED",
        "official_G01": "BLOCKED",
        "formal_A": 0,
        "decision": "NO_EDGE",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="V4.7 offline SHADOW raw semantic replay")
    parser.add_argument("--game", choices=("SSQ", "DLT"), required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if payload.get("lottery") != args.game:
            raise GateError("RAW_REPLAY_GAME_MISMATCH")
        # A separate interpreter is required: the two lottery projects both
        # expose a package called glp and must never share module state.
        source_dir = oi.REPO_ROOT / ("SSQ/SSQ" if args.game == "SSQ" else "DLT/src")
        sys.path.insert(0, str(source_dir))
        source_module = importlib.import_module("glp.sources")
        result = verify_sources(payload, source_module)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
