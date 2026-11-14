"""Real issue-specific scoring only after an official HTML overlap receipt."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.v47_official_score import (
    score_issued_frozen, score_directory,
)
from research.supercompute.v47_models import canonical


def mock_data(game):
    front = [1, 3, 7, 10, 20, 31] if game == "ssq" else [2, 5, 11, 19, 30]
    back = [5] if game == "ssq" else [4, 12]
    return {"issue": "1008", "draw_date": "2026-10-08",
            "front": front, "back": back}


class PublishedScoringTests(unittest.TestCase):
    def make_data(self, root):
        source = root / "live"
        frozen = root / "frozen"
        source.mkdir()
        frozen.mkdir()
        receipt = {"schema": "SSQDLT_V47_LIVE_ISSUER_INGEST_V1",
                   "status": "OVERLAP_VERIFIED", "publisher_issues_matched": True,
                   "games": {}}
        paths = {}
        for game in ("ssq", "dlt"):
            actual = mock_data(game)
            rows = [actual]
            (source / f"{game}-verified-history.json").write_bytes(
                canonical({"game": game.upper(), "draws": rows}))
            receipt["games"][game] = {
                "history_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
                "source_url": "https://publisher.test/" + game,
                "raw_sha256": "b" * 64}
            ticket = {**actual, "dan2": actual["front"][:2]}
            tickets = [dict(ticket, model_name=f"Model_{i}", model_number=i)
                       for i in range(1, 12)]
            doc = {"schema": "SSQDLT_V47_UNIFIED_FROZEN_V1",
                   "created_utc": "2026-10-08T06:00:00+00:00",
                   "source": {"game": game, "target_issue": "1008",
                              "ticket_count": 11, "proposed_tickets": tickets}}
            path = frozen / f"{game}-1008-v47-unified.json"
            path.write_bytes(canonical(doc))
            paths[game] = path
        (source / "official-ingest-receipt.json").write_bytes(canonical(receipt))
        return source, frozen, paths

    def test_scoring_eleven_each_and_hash_trace(self):
        with tempfile.TemporaryDirectory() as d:
            source, frozen, paths = self.make_data(Path(d))
            scores = score_directory(frozen, source, Path(d) / "scores")
            self.assertEqual(len(scores), 2)
            for game in ("ssq", "dlt"):
                saved = json.loads((Path(d) / f"scores/{game}-1008-score.json").read_bytes())
                self.assertEqual(saved["count"], 11)
                self.assertTrue(saved["frozen_before_nominal_draw"])
                self.assertFalse(saved["trusted_predraw_seal"])
                self.assertEqual(sum(row["d2_hit"] for row in saved["model_scores"]), 11)
                self.assertEqual(saved["frozen_sha256"],
                                 hashlib.sha256(paths[game].read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                score_directory(frozen, source, Path(d) / "scores")

    def test_missing_issue_is_pending_not_pretend_score(self):
        with tempfile.TemporaryDirectory() as d:
            source, frozen, paths = self.make_data(Path(d))
            data = json.loads(paths["ssq"].read_bytes())
            data["source"]["target_issue"] = "1010"
            paths["ssq"].write_bytes(canonical(data))
            result = score_issued_frozen("ssq", paths["ssq"],
                source / "ssq-verified-history.json",
                source / "official-ingest-receipt.json")
            self.assertEqual(result["status"], "DRAW_NOT_YET_IN_PUBLISHER_TABLE")

    def test_reject_tampered_draws_and_postdraw_freeze_warning(self):
        with tempfile.TemporaryDirectory() as d:
            source, frozen, paths = self.make_data(Path(d))
            changed = json.loads((source / "dlt-verified-history.json").read_bytes())
            changed["draws"][0]["front"] = [1, 5, 11, 19, 30]
            (source / "dlt-verified-history.json").write_bytes(canonical(changed))
            with self.assertRaises(ValueError):
                score_issued_frozen("dlt", paths["dlt"],
                    source / "dlt-verified-history.json",
                    source / "official-ingest-receipt.json")
            data = json.loads(paths["ssq"].read_bytes())
            data["created_utc"] = "2026-10-09T09:00:00+00:00"
            paths["ssq"].write_bytes(canonical(data))
            out = score_issued_frozen("ssq", paths["ssq"],
                source / "ssq-verified-history.json",
                source / "official-ingest-receipt.json")
            self.assertFalse(out["frozen_before_nominal_draw"])
            self.assertFalse(out["trusted_predraw_seal"])


if __name__ == "__main__":
    unittest.main()
