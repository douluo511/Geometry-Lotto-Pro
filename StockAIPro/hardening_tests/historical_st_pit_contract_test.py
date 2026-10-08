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
        (
            b'{"date":"2026-09-30","market":"SSE","code":"600000","st":false,"suspended":false}\n'
            b'{"date":"2026-09-30","market":"SZSE","code":"000001","st":false,"suspended":false}\n'
            b'{"date":"2026-09-30","market":"BSE","code":"920001","st":false,"suspended":false}\n'
        ),
    )
    source_manifest_sha = make_file(
        root, source_manifest_path,
        b'{"sources":["SSE","SZSE","BSE"],"point_in_time_only":true}\n',
    )

    calendar_manifest_path = "cache/historical_market_calendar.json"
    calendar_manifest_sha = make_file(
        root,
        calendar_manifest_path,
        (json.dumps({
            "schema": "stock-ai-historical-market-calendar-v1",
            "window_start": "2026-09-30",
            "window_end": "2026-09-30",
            "markets": {
                market: {"status": "PASS", "source_count": 1, "dates": ["2026-09-30"]}
                for market in ("SSE", "SZSE", "BSE")
            },
        }, sort_keys=True) + "\n").encode("utf-8"),
    )
    denominator_markets = {}
    code_by_market = {"SSE": "600000", "SZSE": "000001", "BSE": "920001"}
    for market in ("SSE", "SZSE", "BSE"):
        code = code_by_market[market]
        lifecycle_rel = f"cache/historical_st_pit_{market.lower()}_lifecycle.jsonl"
        lifecycle_sha = make_file(
            root, lifecycle_rel,
            (json.dumps({
                "market": market, "code": code,
                "listing_date": "2026-09-30", "delisting_date": "2026-09-30",
            }, sort_keys=True) + "\n").encode("utf-8"),
        )
        expected_rel = f"cache/historical_st_pit_{market.lower()}_expected_keys.txt"
        expected_payload = f"2026-09-30|{market}|{code}\n".encode("ascii")
        expected_sha = make_file(root, expected_rel, expected_payload)
        raw_rel = f"cache/raw_{market.lower()}_fixture.json"
        raw_sha = make_file(
            root, raw_rel,
            (json.dumps({
                "schema": "stock-ai-security-lifecycle-source-v1",
                "market": market,
                "point_in_time_only": True,
                "securities": [{
                    "code": code,
                    "listing_date": "2026-09-30",
                    "delisting_date": "2026-09-30",
                }],
            }, sort_keys=True) + "\n").encode("utf-8"),
        )
        provenance_rel = f"cache/historical_st_pit_{market.lower()}_provenance.json"
        provenance_sha = make_file(
            root, provenance_rel,
            (json.dumps({
                "market": market,
                "point_in_time_only": True,
                "raw_files": [{"path": raw_rel, "sha256": raw_sha}],
            }, sort_keys=True) + "\n").encode("utf-8"),
        )
        denominator_markets[market] = {
            "status": "PASS", "source_count": 1,
            "lifecycle_path": lifecycle_rel, "lifecycle_sha256": lifecycle_sha,
            "expected_keys_path": expected_rel, "expected_keys_sha256": expected_sha,
            "expected_key_count": 1,
            "provenance_path": provenance_rel, "provenance_sha256": provenance_sha,
        }
    denominator_manifest_path = "cache/historical_st_pit_denominator.json"
    denominator_manifest_sha = make_file(
        root, denominator_manifest_path,
        (json.dumps({
            "schema": "stock-ai-historical-pit-denominator-v1",
            "window_start": "2026-09-30",
            "window_end": "2026-09-30",
            "calendar_manifest_sha256": calendar_manifest_sha,
            "source_manifest_sha256": source_manifest_sha,
            "universe_definition": "all_eligible_mainland_equities_with_listing_delisting_boundaries",
            "nonlisted_policy": "exclude_pre_listing_and_post_delisting",
            "st_effective_date_rule": "point_in_time_effective_date_only",
            "suspension_effective_date_rule": "point_in_time_effective_date_only",
            "completeness_formula": "canonical_unique_expected_keys/expected_keys",
            "raw_provenance_required": True,
            "point_in_time_only": True,
            "future_leakage_violations": 0,
            "source_gap_count": 0,
            "semantic_ambiguity_count": 0,
            "markets": denominator_markets,
        }, sort_keys=True) + "\n").encode("utf-8"),
    )
    markets = {}
    for market in ("SSE", "SZSE", "BSE"):
        rel = f"cache/historical_st_pit_{market.lower()}.json"
        evidence_sha = make_file(
            root, rel,
            json.dumps(
                {
                    "market": market,
                    "st_identity": "PASS",
                    "suspension_state": "PASS",
                    "trading_calendar": "PASS",
                    "daily_state": "PASS",
                    "point_in_time_only": True,
                    "future_leakage_violations": 0,
                    "window_start": "2026-09-30",
                    "window_end": "2026-09-30",
                    "canonical_sha256": canonical_sha,
                    "source_count": 1,
                },
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
        "window_start": "2026-09-30",
        "window_end": "2026-09-30",
        "canonical_path": canonical_path,
        "canonical_sha256": canonical_sha,
        "source_manifest_path": source_manifest_path,
        "source_manifest_sha256": source_manifest_sha,
        "calendar_manifest_path": calendar_manifest_path,
        "calendar_manifest_sha256": calendar_manifest_sha,
        "denominator_manifest_path": denominator_manifest_path,
        "denominator_manifest_sha256": denominator_manifest_sha,
        "markets": markets,
    }


def rebind_canonical(root: Path, claim: dict, payload: bytes):
    canonical = root / claim["canonical_path"]
    canonical.write_bytes(payload)
    claim["canonical_sha256"] = sha(canonical)
    for market in ("SSE", "SZSE", "BSE"):
        evidence_path = root / claim["markets"][market]["evidence_path"]
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["canonical_sha256"] = claim["canonical_sha256"]
        evidence_path.write_text(
            json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8"
        )
        claim["markets"][market]["evidence_sha256"] = sha(evidence_path)


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

    # All bytes and hashes are internally consistent, but a one-market
    # canonical dataset must not masquerade as a complete three-market bundle.
    x = complete(root)
    rebind_canonical(
        root,
        x,
        b'{"date":"2026-09-30","market":"SSE","code":"600000","st":false,"suspended":false}\n',
    )
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "canonical_semantics" in meta["failures"]
    assert meta["bindings"]["canonical"]["semantic_reason"].startswith("missing_markets:")

    # A rebound source-manifest hash is still insufficient if the bound
    # manifest omits required markets.
    x = complete(root)
    source_manifest = root / x["source_manifest_path"]
    source_manifest.write_text(
        json.dumps({"sources": ["SSE"], "point_in_time_only": True}) + "\n",
        encoding="utf-8",
    )
    x["source_manifest_sha256"] = sha(source_manifest)
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "source_manifest_semantics" in meta["failures"]

    # A byte-consistent three-market bundle with only one observed date must
    # not claim a multi-year daily-state window.
    x = complete(root)
    x["window_start"] = "2018-01-01"
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "canonical_semantics" in meta["failures"]
    assert meta["bindings"]["canonical"]["semantic_reason"].startswith("date_axis_too_sparse:")

    # A missing denominator binding must block a self-declared full PASS.
    x = complete(root)
    del x["denominator_manifest_sha256"]
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "denominator_manifest_binding" in meta["failures"]

    # Rebinding a denominator that shrinks the exact count must still fail:
    # the evaluator recomputes the denominator from lifecycle x bound calendar.
    x = complete(root)
    denominator_path = root / x["denominator_manifest_path"]
    denominator = json.loads(denominator_path.read_text(encoding="utf-8"))
    denominator["markets"]["SSE"]["expected_key_count"] = 0
    denominator_path.write_text(json.dumps(denominator, sort_keys=True) + "\n", encoding="utf-8")
    x["denominator_manifest_sha256"] = sha(denominator_path)
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "denominator_manifest_semantics" in meta["failures"]
    assert "expected_key_count:SSE" in meta["bindings"]["denominator_manifest"]["semantic_reason"]

    # Source gaps / semantic ambiguity cannot be hand-waved by rebinding bytes.
    x = complete(root)
    denominator_path = root / x["denominator_manifest_path"]
    denominator = json.loads(denominator_path.read_text(encoding="utf-8"))
    denominator["source_gap_count"] = 1
    denominator_path.write_text(json.dumps(denominator, sort_keys=True) + "\n", encoding="utf-8")
    x["denominator_manifest_sha256"] = sha(denominator_path)
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "denominator_manifest_semantics" in meta["failures"]
    assert meta["bindings"]["denominator_manifest"]["semantic_reason"] == "source_gap_count"

    # Raw provenance must semantically reproduce the lifecycle denominator.
    # Rebinding every affected hash must still fail if authoritative raw
    # lifecycle bytes contain an additional eligible security omitted from the
    # lifecycle/expected/canonical denominator.
    x = complete(root)
    denominator_path = root / x["denominator_manifest_path"]
    denominator = json.loads(denominator_path.read_text(encoding="utf-8"))
    provenance_path = root / denominator["markets"]["SSE"]["provenance_path"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    raw_path = root / provenance["raw_files"][0]["path"]
    raw_obj = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_obj["securities"].append({
        "code": "600001",
        "listing_date": "2026-09-30",
        "delisting_date": "2026-09-30",
    })
    raw_path.write_text(json.dumps(raw_obj, sort_keys=True) + "\n", encoding="utf-8")
    provenance["raw_files"][0]["sha256"] = sha(raw_path)
    provenance_path.write_text(json.dumps(provenance, sort_keys=True) + "\n", encoding="utf-8")
    denominator["markets"]["SSE"]["provenance_sha256"] = sha(provenance_path)
    denominator_path.write_text(json.dumps(denominator, sort_keys=True) + "\n", encoding="utf-8")
    x["denominator_manifest_sha256"] = sha(denominator_path)
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "denominator_manifest_semantics" in meta["failures"]
    assert meta["bindings"]["denominator_manifest"]["semantic_reason"] == "raw_lifecycle_mismatch:SSE"

    # Raw provenance bytes are first-class evidence and must hash-match.
    x = complete(root)
    denominator = json.loads((root / x["denominator_manifest_path"]).read_text(encoding="utf-8"))
    provenance_path = root / denominator["markets"]["SSE"]["provenance_path"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    raw_path = root / provenance["raw_files"][0]["path"]
    raw_path.write_text("tampered raw bytes\n", encoding="utf-8")
    write_claim(root, x)
    status, _, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert "denominator_manifest_semantics" in meta["failures"]
    assert "raw_file_binding" in meta["bindings"]["denominator_manifest"]["semantic_reason"]

    # Even a completely SHA-consistent three-market synthetic test fixture
    # cannot pretend to be an independently authenticated historical exchange
    # source. Internal structure/denominator checks may pass individually, but
    # PRODUCT qualification stays WARN pending real native source adapters.
    x = complete(root)
    write_claim(root, x)
    status, detail, meta = evaluate_historical_st_pit(root, "2026-09-30")
    assert status == "WARN"
    assert meta["failures"] == ["native_source_authority_unverified"], meta["failures"]
    assert all(v["status"] == "PASS" for v in meta["bindings"].values())
    assert meta["denominator"]["total_expected_key_count"] == 3
    assert meta["denominator"]["completeness_ratio"] == 1.0
    assert "native_source_authority_unverified" in detail

    # Downstream code cannot escape the trust boundary by asking for a subset
    # of the otherwise self-consistent made-up canonical states.
    for code in ("600000", "600001"):
        try:
            load_historical_st_pit_subset(
                root, {("2026-09-30", code)}, "2026-09-30"
            )
        except RuntimeError as exc:
            assert "not qualified" in str(exc), (code, str(exc))
            assert "native_source_authority_unverified" in str(exc)
        else:
            raise AssertionError("untrusted historical PIT subset bypassed authority gate")

print("HISTORICAL ST PIT REAL-BYTE HASH-BINDING + EXTERNAL-NATIVE-AUTHORITY REFUSAL CONTRACT PASS")
