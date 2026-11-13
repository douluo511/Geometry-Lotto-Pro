"""Write a create-only, replayable mother V1 batch, never overwrite records.

Usage:
  python -m research.mother_v1.cli --input two_games.json --out ./new_batch
  python -m research.mother_v1.cli --input two_games.json --out ./new_batch --physical-ledger ./research/physical_evidence_v1
Output: predictions.json, audit_receipt.json. No tickets bought or sent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .mother import MotherBlocked, forecast_all, _bytes, sha


def _load_object(path: Path) -> dict:
    def unique_pairs(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise MotherBlocked("INPUT_DUPLICATE_JSON_KEY")
            obj[k] = v
        return obj
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise MotherBlocked("INPUT_FILE_MISSING_OR_TOO_LARGE")
    try:
        data = json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              MotherBlocked("NONFINITE_JSON_INPUT")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MotherBlocked("INPUT_JSON_INVALID") from exc
    if not isinstance(data, dict):
        raise MotherBlocked("INPUT_NOT_OBJECT")
    return data


def _create_once(path: Path, content: bytes) -> None:
    with path.open("xb") as target:
        target.write(content)
        target.flush()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--physical-ledger", type=Path)
    p.add_argument("--print-summary", action="store_true")
    args = p.parse_args(argv)
    if args.out.exists():
        raise MotherBlocked("CREATE_ONLY_OUTPUT_ALREADY_EXISTS")
    source = _load_object(args.input)
    forecast = forecast_all(source, physical_ledger=args.physical_ledger)
    # Canonical calculations are deterministic. The local execution clock and
    # hashes belong in the receipt, never self-reported as trusted predraw TSA.
    predictions = _bytes(forecast) + b"\n"
    receipt = {
        "schema": "MOTHER_V1_LOCAL_EXECUTION_RECEIPT",
        "created_utc_untrusted": datetime.now(timezone.utc).isoformat(),
        "input_file_sha256": sha256(args.input.read_bytes()).hexdigest(),
        "input_contract_sha256": sha(source),
        "forecast_sha256": sha256(predictions).hexdigest(),
        "mother_source_sha256": sha256(Path(__file__).with_name("mother.py").read_bytes()).hexdigest(),
        "registry_source_sha256": sha256(Path(__file__).with_name("registry.py").read_bytes()).hexdigest(),
        "game_count": 2, "models_each": 16,
        "physical_provenance": "SOURCE_GATED_NO_PREDRAW_MECHANICAL_EDGE",
        "formal_A": 0, "decision": "NO_EDGE",
        "official_source_authenticity": "UNVERIFIED",
        "run_is_a_trusted_predraw_seal": False,
    }
    # Abort on any existing destination or path traversal; only fresh folder.
    args.out.mkdir(parents=True, exist_ok=False)
    _create_once(args.out / "predictions.json", predictions)
    _create_once(args.out / "audit_receipt.json", _bytes(receipt) + b"\n")
    if args.print_summary:
        print(json.dumps({
            "out": str(args.out), "forecast_sha256": receipt["forecast_sha256"],
            "ssq": forecast["games"]["SSQ"]["target_issue"],
            "dlt": forecast["games"]["DLT"]["target_issue"],
            "arms_each": 16,
            "physical_statuses": {
                g: [m["status"] for m in forecast["games"][g]["models"]
                    if m["name"].startswith("physical_")]
                for g in ("SSQ", "DLT")
            },
            "decision": "NO_EDGE", "formal_A": 0,
        }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
