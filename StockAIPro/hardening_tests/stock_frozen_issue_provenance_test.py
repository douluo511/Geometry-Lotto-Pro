"""Fail-first freeze provenance test: all bytes are synthetic, no live price data.

The historical chain must not certify a forged issue day simply because
payload SHA-256 values match. A manifest is metadata AND a provenance claim.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(PROJECT))
from stock_ai.storage import REQUIRED_PREDICTION_PAYLOADS, verify_prediction_chain


def prepare(root: Path, day="2026-09-30"):
    directory = root / "predictions" / day
    directory.mkdir(parents=True)
    files = {}
    for name in sorted(REQUIRED_PREDICTION_PAYLOADS):
        content = json.dumps({"asof": day, "source": "synthetic-fixture"}) if name == "summary.json" else "test-only bytes\n"
        (directory / name).write_text(content, encoding="utf-8")
        files[name] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": 2,
        "created_at": "2026-09-29T15:00:00+08:00",
        "asof": day,
        "chain_sequence": 1,
        "previous_manifest_sha256": None,
        "files": files,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory, manifest


with tempfile.TemporaryDirectory(prefix="stock-freeze-issue-identity-") as temp:
    root = Path(temp)
    issue, manifest = prepare(root)
    ok, reason, count = verify_prediction_chain(root)
    assert ok and count == 1, ("valid synthetic control rejected", reason, count)

    # Forge only the manifest-declared trade date. Every listed payload SHA
    # still matches; old verifier falsely counts the historical chain as PASS.
    forged = dict(manifest, asof="2026-10-01")
    (issue / "manifest.json").write_text(json.dumps(forged), encoding="utf-8")
    ok, reason, count = verify_prediction_chain(root)
    assert not ok, (
        "FALSE EVIDENCE PASS: manifest asof disagrees with exact issue dir",
        reason, count,
    )
    (issue / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Directory name itself must remain the true frozen issue identity.
    moved = issue.rename(issue.with_name("2026-10-01"))
    ok, reason, count = verify_prediction_chain(root)
    assert not ok, (
        "FALSE EVIDENCE PASS: renamed issue directory retains valid old manifest",
        reason, count,
    )
    issue = moved.rename(moved.with_name("2026-09-30"))

    # A manifest whose summary.json claims another issue is equally invalid,
    # even when an attacker rewrites its corresponding SHA coherently.
    new_summary = json.dumps({"asof": "2026-10-01", "source": "synthetic-fixture"})
    (issue / "summary.json").write_text(new_summary, encoding="utf-8")
    forged_files = dict(manifest["files"], **{"summary.json": hashlib.sha256(new_summary.encode("utf-8")).hexdigest()})
    (issue / "manifest.json").write_text(json.dumps(dict(manifest, files=forged_files)), encoding="utf-8")
    ok, reason, count = verify_prediction_chain(root)
    assert not ok, (
        "FALSE EVIDENCE PASS: self-rehashed summary date contradicts frozen issue",
        reason, count,
    )

# Legacy 32-gate Windows offline suite detected a second-order regression:
# malformed but syntactically valid JSON top-level manifest caused a runtime
# AttributeError when the new verifier accessed m.get("asof"). It must fail
# closed with a normal (False, reason, 0) decision, never crash monitoring.
for invalid in ("[]", "null", '"not-an-object"', "42"):
    with tempfile.TemporaryDirectory(prefix="stock-bad-manifest-root-") as temp:
        root = Path(temp)
        issue, manifest = prepare(root)
        (issue / "manifest.json").write_text(invalid, encoding="utf-8")
        try:
            ok, reason, count = verify_prediction_chain(root)
        except Exception as exc:
            raise AssertionError(
                "UNHANDLED MANIFEST FORMAT: " + repr(invalid) + " " + type(exc).__name__
            ) from exc
        assert ok is False and count == 0 and reason, (
            "FALSE EVIDENCE PASS for malformed manifest root", invalid, ok, reason, count)
print("STOCK FROZEN MANIFEST INVALID ROOT TYPE 4/4 PASS")
print("STOCK FROZEN ISSUE MANIFEST/DATE PROVENANCE 3/3 PASS")
