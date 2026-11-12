"""Adversarial source, cutoff, evidence, and future-scoring tests (offline)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from research.supercompute import official_probe as probe
from research.supercompute import official_prospective as core

SSQ_OLD = {
    "issue": "2026129", "draw_date": "2026-11-10",
    "front": [3, 9, 16, 20, 25, 30], "back": [5],
}
SSQ_NEW = {
    "issue": "2026130", "draw_date": "2026-11-12",
    "front": [1, 2, 3, 9, 12, 28], "back": [15],
}
DLT_OLD = {
    "issue": "26129", "draw_date": "2026-11-11",
    "front": [2, 12, 14, 17, 33], "back": [7, 8],
}
OLD_TIME = datetime(2026, 11, 12, 11, tzinfo=timezone.utc)
NEW_TIME = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def observation_sources(root, game, draw):
    result = []
    raw = Path(root)
    raw.mkdir(parents=True, exist_ok=True)
    for n, source_id in enumerate(core.SOURCE_IDS[game]):
        data = f"real-source-fixture:{source_id}:{draw['issue']}".encode()
        sha = hashlib.sha256(data).hexdigest()
        (raw / (sha + ".bin")).write_bytes(data)
        result.append({
            "source_id": source_id, "status": "PASS",
            "draw": draw,
            "raw_records": [{
                "source": source_id,
                "url": f"https://example.org/{source_id}",
                "http_status": 200, "sha256": sha,
                "bytes": len(data),
                "parser_version": "test-only-not-official",
            }],
        })
    return result


class OfficialGateTests(TestCase):
    def test_two_distinct_issuer_agreement_and_raw_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"
            source = core.latest_consensus(
                "ssq", observation_sources(raw, "ssq", SSQ_OLD),
                observed_at=OLD_TIME)
            self.assertEqual(source["draw"], SSQ_OLD)
            self.assertEqual(source["formal_A"], 0)
            self.assertFalse(source["independent_tsa_verified"])
            self.assertEqual(core.inspect_manifest(source, raw), source)
            changed = dict(source)
            changed["formal_A"] = 1
            with self.assertRaises(ValueError):
                core.inspect_manifest(changed, raw)
            raw_file = next(raw.glob("*.bin"))
            raw_file.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                core.inspect_manifest(source, raw)

    def test_missing_source_conflict_stale_and_wrong_date_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = observation_sources(Path(tmp) / "raw", "ssq", SSQ_OLD)
            with self.assertRaisesRegex(ValueError, "two separately"):
                core.latest_consensus("ssq", records[:1], observed_at=OLD_TIME)
            changed = json.loads(json.dumps(records))
            changed[1]["draw"]["back"] = [7]
            with self.assertRaisesRegex(ValueError, "disagree"):
                core.latest_consensus("ssq", changed, observed_at=OLD_TIME)
            with self.assertRaisesRegex(ValueError, "stale"):
                core.latest_consensus(
                    "ssq", records, observed_at=OLD_TIME + timedelta(days=6))
            bad = dict(SSQ_OLD, draw_date="2026-11-11")
            with self.assertRaises(ValueError):
                core.check_draw("ssq", bad)
            bad_dlt = dict(DLT_OLD, draw_date="2026-11-10")
            with self.assertRaises(ValueError):
                core.check_draw("dlt", bad_dlt)

    def test_jiangsu_publication_date_cannot_be_used_as_draw_date(self):
        listing = """<h1>大乐透</h1><table>
        <tr><th>发布日期</th><th>期号</th><th>开奖号码</th><th>详细</th></tr>
        <tr><td>2026-11-12</td><td>26129</td>
        <td>02 12 14 17 33 07 08</td>
        <td><a href="/cms/post-148233.html">详细</a></td></tr></table>"""
        choice = probe.js_listing_latest(listing.encode())
        self.assertEqual(choice["issue"], "26129")
        self.assertNotIn("draw_date", choice)
        official = """<h2>中国体育彩票超级大乐透第26129期开奖公告</h2>
        <p>发布时间: 2026-11-12</p><p>开奖日期：2026年11月11日</p>
        <table><tr><td>本期开奖号码：</td><td>02 12 14 17 33</td>
        <td>07 08</td></tr></table>"""
        parsed = probe.parse_jiangsu_detail(official.encode())
        self.assertEqual(parsed["draw_date"], "2026-11-11")
        self.assertEqual(parsed["front"], DLT_OLD["front"])
        with self.assertRaises(probe.IntakeError):
            probe.parse_jiangsu_detail(
                official.replace("开奖日期：2026年11月11日", "发布日期：2026年11月12日").encode())

    def test_shadow_freeze_before_claimed_cutoff_once_and_score_only_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            before = core.latest_consensus(
                "ssq", observation_sources(raw, "ssq", SSQ_OLD),
                observed_at=OLD_TIME)
            ticket = {
                "model_id": "FIXED_RESEARCH_EXPERT",
                "model_sha256": "a" * 64,
                "front": [1, 2, 3, 4, 5, 6], "back": [10],
                "d2_pair": [1, 2],
            }
            ledger = root / "ledger"
            cutoff = "2026-11-12T12:00:00+00:00"
            freeze = core.freeze_shadow(
                ledger, before, ticket, "2026130", cutoff, now=OLD_TIME)
            self.assertEqual(freeze["target_issue"], "2026130")
            self.assertFalse(freeze["formal_prediction"])
            self.assertFalse(freeze["cutoff_authority_verified"])
            with self.assertRaises(FileExistsError):
                core.freeze_shadow(
                    ledger, before, ticket, "2026130", cutoff, now=OLD_TIME)
            with self.assertRaises(ValueError):
                core.freeze_shadow(
                    root / "late", before, ticket, "2026130", cutoff,
                    now=OLD_TIME + timedelta(hours=2))
            with self.assertRaises(ValueError):
                core.freeze_shadow(
                    root / "skipped", before, ticket, "2026131", cutoff,
                    now=OLD_TIME)
            self.assertEqual(core.audit_ledger(ledger)["games"]["ssq"],
                             {"frozen_total": 1, "scored": 0, "pending": 1,
                              "d2_hits": 0, "full_hits": 0})
            # Old source cannot be used to score the future draw.
            self.assertEqual(core.score_available(ledger, before)["unscored"][0]["issue"],
                             "2026130")
            self.assertEqual(core.audit_ledger(ledger)["games"]["ssq"]["scored"], 0)
            after = core.latest_consensus(
                "ssq", observation_sources(raw, "ssq", SSQ_NEW),
                observed_at=NEW_TIME)
            score = core.score_available(ledger, after)
            self.assertEqual(score["scored"][0]["state"], "NEW_SHADOW_SCORE")
            self.assertEqual(score["scored"][0]["d2_hit"], 1)
            self.assertEqual(core.audit_ledger(ledger)["games"]["ssq"]["d2_hits"], 1)
            repeated = core.score_available(ledger, after)
            self.assertEqual(repeated["scored"][0]["state"], "ALREADY_SCORED")
            self.assertEqual(core.audit_ledger(ledger)["games"]["ssq"]["scored"], 1)

    def test_forecast_and_scoring_tamper_fails_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obs = core.latest_consensus(
                "ssq", observation_sources(root / "raw", "ssq", SSQ_OLD),
                observed_at=OLD_TIME)
            ticket = {
                "model_id": "TEST", "model_sha256": "b" * 64,
                "front": [1, 2, 3, 4, 5, 6], "back": [10],
                "d2_pair": [1, 2],
            }
            ledger = root / "ledger"
            core.freeze_shadow(
                ledger, obs, ticket, "2026130",
                "2026-11-12T12:00:00Z", now=OLD_TIME)
            after = core.latest_consensus(
                "ssq", observation_sources(root / "raw", "ssq", SSQ_NEW),
                observed_at=NEW_TIME)
            core.score_available(ledger, after)
            path = ledger / "research/official_prospective/scores/ssq/2026130.json"
            score = core.load(path)
            score["score"]["d2_hit"] = 0
            # Attacker rehashes the score to make a self-consistent but false receipt.
            score["sha256"] = core.digest({k: v for k, v in score.items()
                                           if k != "sha256"})
            path.write_bytes(core.json_bytes(score))
            with self.assertRaisesRegex(ValueError, "replay"):
                core.audit_ledger(ledger)
            path.unlink()
            with self.assertRaises(ValueError):
                core.load(core._test_missing_file) if False else core.checked(
                    {"sha256": "a" * 64, "foo": 1})

    def test_strict_duplicates_nonfinite_and_orphan_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"sha256": "a", "sha256": "b"}')
            with self.assertRaises(ValueError):
                core.load(path)
            with self.assertRaises(ValueError):
                core.strict_object_pairs([("x", 1), ("x", 2)])
            with self.assertRaises(ValueError):
                core.check_ticket("ssq", {
                    "front": [1, 1, 2, 3, 4, 5], "back": [5], "d2_pair": [1, 2],
                })
            p = Path(tmp) / "ledger/research/official_prospective/scores/ssq/2026130.json"
            p.parent.mkdir(parents=True)
            p.write_bytes(core.json_bytes(core.receipt({
                "issue": "2026130", "game": "ssq", "score": {},
            })))
            with self.assertRaisesRegex(ValueError, "orphaned"):
                core.audit_ledger(Path(tmp) / "ledger")

    def test_network_failure_is_archived_not_called_verified(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                probe, "probe_ssq", side_effect=RuntimeError("HTTP 403")):
            result = probe.probe_game("ssq", Path(td) / "attempt")
            self.assertEqual(result["status"], "SOURCE_BLOCKED")
            report = core.load(Path(td) / "attempt" / "attempt.json")
            self.assertEqual(report["status"], "SOURCE_BLOCKED")
            self.assertFalse(
                (Path(td) / "attempt" / "verified_latest.json").exists())


if __name__ == "__main__":
    import unittest
    unittest.main()
