import hashlib
import json
import sys
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(PACKAGE_ROOT))

from stock_ai.historical_pit import evaluate_historical_st_pit, load_historical_st_pit_subset


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_file(root: Path, rel: str, payload: bytes) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return sha(p)


def write_claim(root: Path, obj: dict):
    p = root / "cache" / "historical_st_pit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def complete(root: Path):
    canonical_path = "cache/historical_st_pit_daily_state.jsonl"
    source_manifest_path = "cache/historical_st_pit_sources.json"
    canonical_sha = make_file(
        root, canonical_path,
        b'{"date":"2026-09-30","market":"SSE","code":"600000","st":false,"suspended":false}\n',
    )
    source_manifest_sha = make_file(
        root, source_manifest_path,
        b'{"sources":["SSE","SZSE","BSE"],"point_in_time_only":true}\n',
    )

    markets = {}
    for market in ("SSE", "SZSE", "BSE"):
        rel = f"cache/historical_st_pit_{market.lower()}.json"
        evidence_sha = make_file(
            root, rel,
            json.dumps(
                {"market": market, "st_identity": "PASS", "suspension_state": "PASS"},
                sort_keys=True,
            ).encode("utf-8") + b"\n",
        )
        markets[market] = {
            "st_identity": "PASS",
            "suspension_state": "PASS",
            "trading_calendar": "PASS",
            "daily_state": "PASS",
            "evidence_path": rel,
            "evidence_sha256": evidence_sha,
            "source_count": 1,
        }

    return {
        "schema": "stock-ai-historical-st-pit-v1",
        "status": "PASS",
        "full_historical_st_pit": "PASS",
        "daily_state_complete": True,
        "point_in_time_only": True,
        "future_leakage_violations": 0,
        "window_start": "2018-01-01",
        "window_end": "2026-09-30",
        "canonical_path": canonical_path,
        "canonical_sha256": canonical_sha,
        "source_manifest_path": source_manifest_path,
        "source_manifest_sha256": source_manifest_sha,
        "markets": markets,
    }


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert meta["reason"] == "evidence_missing"

    x = complete(root)
    del x["markets"]["BSE"]
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert meta["market_failures"]["BSE"] == ["missing"]

    x = complete(root)
    x["future_leakage_violations"] = 1
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "future_leakage_violations" in meta["failures"]

    x = complete(root)
    x["window_end"] = "2026-09-29"
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "freshness" in meta["failures"]

    # A syntactically valid but fabricated SHA-256 must not count as evidence.
    x = complete(root)
    x["canonical_sha256"] = "a" * 64
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "canonical_binding" in meta["failures"]
    assert meta["bindings"]["canonical"]["reason"] == "hash_mismatch"

    # Evidence bytes changed after the claim was signed must fail closed.
    x = complete(root)
    write_claim(root, x)
    (root / x["markets"]["SSE"]["evidence_path"]).write_text("tampered\n", encoding="utf-8")
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "evidence_binding" in meta["market_failures"]["SSE"]
    assert meta["bindings"]["SSE"]["reason"] == "hash_mismatch"

    # Paths must stay under the product evidence root.
    x = complete(root)
    x["canonical_path"] = "../escape.bin"
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "canonical_binding" in meta["failures"]
    assert meta["bindings"]["canonical"]["reason"] == "path_escape"

    x = complete(root)
    write_claim(root, x)
    status, detail, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "PASS"
    assert not meta["failures"]
    assert all(v["status"] == "PASS" for v in meta["bindings"].values())
    assert "SSE/SZSE/BSE" in detail
    assert "字节哈希绑定" in detail

    states, subset = load_historical_st_pit_subset(
        root, {("2026-09-30", "600000")}, "2026-09-30"
    )
    assert states[("2026-09-30", "600000")] == {
        "market": "SSE", "st": False, "suspended": False
    }
    assert subset["status"] == "PASS"
    assert subset["required_key_count"] == 1
    assert subset["found_key_count"] == 1

    try:
        load_historical_st_pit_subset(
            root, {("2026-09-30", "600001")}, "2026-09-30"
        )
    except RuntimeError as exc:
        assert "state missing" in str(exc)
    else:
        raise AssertionError("missing historical PIT key did not fail closed")

print("HISTORICAL ST PIT REAL-BYTE HASH-BINDING + CONSUMPTION CONTRACT TEST PASS")
