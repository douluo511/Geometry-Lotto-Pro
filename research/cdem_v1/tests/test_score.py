import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from research.cdem_v1.score import make_receipt, main

class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.seal = json.dumps({
            "schema": "CDEM_V1_SEALED_CANDIDATE", "game": "ssq",
            "target_issue": "2026131", "model_id": "SSQ-G3-061",
            "prediction": {"front": [4, 5, 6, 10, 14, 30], "back": [1],
                           "dan2": [14, 30], "low_rank_front": [32, 20, 23, 11, 16]}
        }).encode()
    def test_hits(self):
        r = make_receipt(self.seal, "2026131", [2, 4, 5, 14, 25, 30], [1],
                         "https://example.org/official", "a"*64)
        self.assertTrue(r["score"]["dan2_success"])
        self.assertEqual(r["score"]["front_count"], 4)
        self.assertEqual(r["score"]["back_count"], 1)
        self.assertFalse(r["score"]["full_ticket_success"])
    def test_mismatched_issue(self):
        with self.assertRaises(ValueError):
            make_receipt(self.seal, "2026132", [2, 4, 5, 14, 25, 30], [1],
                         "https://example.org", "a"*64)
    def test_bad_numbers(self):
        with self.assertRaises(ValueError):
            make_receipt(self.seal, "2026131", [2, 4, 5, 14, 14, 30], [1],
                         "https://example.org", "a"*64)
    def test_create_only(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            seal = root / "seal.json"
            seal.write_bytes(self.seal)
            target = root / "receipt.json"
            args = ["--seal", str(seal), "--issue", "2026131", "--front",
                    "2", "4", "5", "14", "25", "30", "--back", "1",
                    "--evidence-url", "https://example.org", "--evidence-sha256",
                    "a"*64, "--out", str(target)]
            self.assertEqual(main(args), 0)
            self.assertTrue(target.exists())
            with self.assertRaises(FileExistsError):
                main(args)

if __name__ == "__main__":
    unittest.main()
