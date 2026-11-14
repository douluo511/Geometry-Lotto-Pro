"""Official-source provenance and no-gap append-only input acceptance."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from research.supercompute.v47_merge_history import build, validate_delta

ROOT = Path(__file__).resolve().parents[3]
SEEDS = {
    "ssq": ROOT / "SSQ/SSQ/resources/official_seed.json",
    "dlt": ROOT / "DLT/src/resources/official_seed.json",
}
DELTA = ROOT / "research/supercompute/data/v47_20261114_draw_delta.json"


class HistoricalMergeAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seeds = {game: json.loads(path.read_bytes())
                     for game, path in SEEDS.items()}
        cls.delta = json.loads(DELTA.read_bytes())

    def test_no_gaps_or_pseudo_official_input(self):
        expected = {"ssq": ("2026109", "2026130"),
                    "dlt": ("26108", "26129")}
        for game, (previous, current) in expected.items():
            self.assertEqual(self.seeds[game]["draws"][-1]["issue"], previous)
            merged, quality = validate_delta(self.seeds[game], self.delta, game)
            self.assertEqual(merged[-1]["issue"], current)
            self.assertEqual(len(merged),
                             len(self.seeds[game]["draws"]) + 21)
            self.assertEqual(sum(quality.values()), 21)
        self.assertEqual(self.delta["target_issues"],
                         {"ssq": "2026131", "dlt": "26130"})

    def test_secondary_inputs_are_not_silently_authenticity_verified(self):
        with tempfile.TemporaryDirectory() as d:
            receipt = build(SEEDS, DELTA, Path(d) / "receipts")
            self.assertFalse(receipt["live_official_source_verified"])
            self.assertEqual(receipt["games"]["dlt"][
                "secondary_rows_require_confirmation"], 0)
            self.assertEqual(receipt["games"]["dlt"]["source_tier_counts"]["ISSUER_PROVINCIAL"], 21)
            self.assertEqual(receipt["games"]["ssq"]["added_draws"], 21)
            for game in ("ssq", "dlt"):
                output = json.loads((Path(d) / "receipts" /
                                     f"{game}-merged-history.json").read_bytes())
                self.assertEqual(output["draws"][-1]["issue"],
                                 receipt["games"][game]["last_merged_issue"])
            with self.assertRaises(FileExistsError):
                build(SEEDS, DELTA, Path(d) / "receipts")

    def test_reject_gap_and_bad_provenance_and_duplicate_draw(self):
        for game in ("ssq", "dlt"):
            modified = copy.deepcopy(self.delta)
            modified["records"][game][1]["issue"] = "9"
            with self.assertRaises(ValueError):
                validate_delta(self.seeds[game], modified, game)
            modified = copy.deepcopy(self.delta)
            modified["records"][game][0]["source_url"] = "http://bad.example"
            with self.assertRaises(ValueError):
                validate_delta(self.seeds[game], modified, game)
            modified = copy.deepcopy(self.delta)
            modified["records"][game][0]["draw_date"] = \
                self.seeds[game]["draws"][-1]["draw_date"]
            with self.assertRaises(ValueError):
                validate_delta(self.seeds[game], modified, game)


if __name__ == "__main__":
    unittest.main()
