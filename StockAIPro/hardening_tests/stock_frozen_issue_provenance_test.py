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


# A producer must not corrupt an existing forward hash-chain by deliberately
# forcing a past issue once a later dated issue already exists. This is tested
# against the REAL storage.freeze_prediction, without pandas or network data.
from unittest.mock import patch
from stock_ai import storage as producer

class _ToyFrame:
    empty = False
    def to_csv(self, path, index=False, encoding="utf-8-sig"):
        Path(path).write_text("code,final_score\\n000001,1.0\\n", encoding=encoding)

def _put(day, *, forced=False, summary_day=None):
    f = _ToyFrame()
    return producer.freeze_prediction(
        day, f, {"balanced": f, "offense": f, "defense": f},
        {"asof": day if summary_day is None else summary_day},
        {"rank_ic": 0}, {"regime": "NEUTRAL"}, {"good_ratio": 1},
        force=forced,
    )

with tempfile.TemporaryDirectory(prefix="stock-frozen-producer-invariant-") as temp:
    root = Path(temp)
    with patch.object(producer, "ROOT", root):
        first = _put("2026-09-01")
        second = _put("2026-09-02")
        assert producer.verify_prediction_chain(root)[0]
        first_manifest = (first / "manifest.json").read_bytes()
        second_manifest = (second / "manifest.json").read_bytes()
        head_bytes = (root / "state" / "prediction_chain.json").read_bytes()
        alias_manifest = (root / "predictions" / "latest" / "manifest.json").read_bytes()
        # A force flag is NOT authorization to break a later certified link.
        try:
            _put("2026-09-01", forced=True)
        except ValueError:
            pass
        else:
            raise AssertionError("FALSE PROVENANCE: force rewriting old issue broke later chain")
        # A delayed or backfilled issue must not silently reorder the chain.
        try:
            _put("2026-08-31")
        except ValueError:
            pass
        else:
            raise AssertionError("FALSE PROVENANCE: backdated insertion broke frozen chain")
        # Prevent writing a currently invalid, date-mismatched issue that
        # cannot pass the downstream immutable issue verifier.
        try:
            _put("2026-09-03", summary_day="2026-09-04")
        except ValueError:
            pass
        else:
            raise AssertionError("FALSE PROVENANCE: producer froze mismatched summary date")
        assert (first / "manifest.json").read_bytes() == first_manifest
        assert (second / "manifest.json").read_bytes() == second_manifest
        assert (root / "state" / "prediction_chain.json").read_bytes() == head_bytes
        assert (root / "predictions" / "latest" / "manifest.json").read_bytes() == alias_manifest
        assert not (root / "predictions" / "2026-08-31").exists()
        assert not (root / "predictions" / "2026-09-03").exists()
        assert not (root / "predictions" / "_forced_backups").exists()
        assert producer.verify_prediction_chain(root)[0]
print("STOCK FREEZE PRODUCER NO BACKDATE / CHAIN DESTRUCTION 3/3 PASS")
