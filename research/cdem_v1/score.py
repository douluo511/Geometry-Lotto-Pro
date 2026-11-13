"""Create-only CDEM post-draw scoring receipt.
Validates externally supplied draw numbers; DOES NOT fetch/authenticate official results.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SPECS = {"ssq": (33, 6, 16, 1), "dlt": (35, 5, 12, 2)}

def validate_numbers(numbers: list[int], ceiling: int, pick: int, name: str) -> None:
    if len(numbers) != pick or numbers != sorted(set(numbers)):
        raise ValueError(f"{name} must contain {pick} increasing distinct numbers")
    if any(type(n) is not int or not 1 <= n <= ceiling for n in numbers):
        raise ValueError(f"{name} contains an out-of-range number")

def make_receipt(seal_bytes: bytes, issue: str, front: list[int], back: list[int],
                 evidence_url: str, evidence_sha256: str) -> dict:
    seal = json.loads(seal_bytes)
    if seal.get("schema") != "CDEM_V1_SEALED_CANDIDATE":
        raise ValueError("unknown CDEM seal schema")
    game = seal.get("game")
    if game not in SPECS:
        raise ValueError("unknown game")
    fm, fp, bm, bp = SPECS[game]
    if seal.get("target_issue") != issue:
        raise ValueError("actual issue does not match frozen target")
    validate_numbers(front, fm, fp, "front")
    validate_numbers(back, bm, bp, "back")
    if not evidence_url.startswith("https://"):
        raise ValueError("an HTTPS evidence URL is required")
    if len(evidence_sha256) != 64 or any(c not in "0123456789abcdef" for c in evidence_sha256):
        raise ValueError("evidence SHA-256 must be 64 lowercase hex chars")
    ticket = seal["prediction"]
    validate_numbers(ticket["front"], fm, fp, "frozen front")
    validate_numbers(ticket["back"], bm, bp, "frozen back")
    if len(ticket["dan2"]) != 2 or not set(ticket["dan2"]).issubset(ticket["front"]):
        raise ValueError("invalid frozen dan2")
    front_hits = sorted(set(front) & set(ticket["front"]))
    back_hits = sorted(set(back) & set(ticket["back"]))
    return {
        "schema": "CDEM_V1_POSTDRAW_RECEIPT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "game": game, "target_issue": issue,
        "seal_sha256": hashlib.sha256(seal_bytes).hexdigest(),
        "model_id": seal["model_id"],
        "frozen_prediction": ticket,
        "observed_draw": {"front": front, "back": back},
        "score": {
            "front_hits": front_hits, "front_count": len(front_hits),
            "back_hits": back_hits, "back_count": len(back_hits),
            "dan2_hits": sorted(set(ticket["dan2"]) & set(front)),
            "dan2_success": set(ticket["dan2"]).issubset(front),
            "full_ticket_success": len(front_hits) == fp and len(back_hits) == bp,
        },
        "source_evidence": {"url": evidence_url, "sha256": evidence_sha256,
                            "status": "PROVIDED_NOT_NETWORK_VERIFIED_BY_THIS_SCRIPT"},
        "edge_state": "NO_EDGE",
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--front", nargs="+", type=int, required=True)
    parser.add_argument("--back", nargs="+", type=int, required=True)
    parser.add_argument("--evidence-url", required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args(argv)
    receipt = make_receipt(a.seal.read_bytes(), a.issue, a.front, a.back,
                           a.evidence_url, a.evidence_sha256)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with a.out.open("x", encoding="utf-8") as f:
        f.write(data)
    print(json.dumps({"saved": str(a.out), "sha256": hashlib.sha256(data.encode()).hexdigest(),
                      "score": receipt["score"]}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
