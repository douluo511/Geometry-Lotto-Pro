"""Schedule-only cloud live-issuer ledger: two runs, prior recovery and score tests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.supercompute.v47_models import canonical
from research.supercompute.v47_live_ledger import record, verify, next_nominal_draw


class LiveScheduleLedgerTests(unittest.TestCase):
    def make_sources(self, root, issues=None):
        sources = root / "sources"
        sources.mkdir(exist_ok=True)
        issues = issues or {"ssq": ("2026130", "2026-11-12"),
                            "dlt": ("26129", "2026-11-11")}
        receipt = {"schema": "SSQDLT_V47_LIVE_ISSUER_INGEST_V1",
                   "status": "OVERLAP_VERIFIED",
                   "publisher_issues_matched": True, "games": {}}
        for game, (issue, day) in issues.items():
            balls = {"front": [1, 3, 7, 10, 20, 31], "back": [5]} if game == "ssq" \
                else {"front": [2, 5, 11, 19, 30], "back": [4, 12]}
            rows = [{"issue": issue, "draw_date": day, **balls}]
            (sources / f"{game}-verified-history.json").write_bytes(
                canonical({"game": game.upper(), "draws": rows}))
            raw = (game + " official-html").encode()
            (sources / f"{game}-publisher-raw.html").write_bytes(raw)
            receipt["games"][game] = {
                "history_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "new_target_issue": str(int(issue) + 1),
                "source_url": "https://official.example/" + game}
        (sources / "official-ingest-receipt.json").write_bytes(canonical(receipt))
        return sources

    def make_forecast(self, command, **kwargs):
        game = command[command.index("--game") + 1]
        target = command[command.index(f"--{game}-target") + 1]
        output = Path(command[command.index("--output") + 1])
        directory = Path(command[command.index("--freeze-dir") + 1])
        directory.mkdir(parents=True, exist_ok=True)
        tickets = [{"front": [1, 3, 7, 10, 20, 31], "back": [5],
                    "dan2": [1, 3]}] if game == "ssq" else [
                    {"front": [2, 5, 11, 19, 30], "back": [4, 12],
                     "dan2": [2, 5]}]
        report = {"schema": "SSQDLT_V47_UNIFIED_11_V1", "game": game,
                  "target_issue": target, "ticket_count": 11,
                  "validation": {"M2": {str(n): {} for n in range(11)},
                                 "M3": {str(n): {} for n in range(11)}},
                  "proposed_tickets": tickets * 11}
        outer = {"schema": "SSQDLT_V47_UNIFIED_RUN_V1",
                 "games": {game: report}}
        output.write_bytes(canonical(outer))
        (directory / f"{game}-{target}-v47-unified.json").write_bytes(
            canonical({"schema": "SSQDLT_V47_UNIFIED_FROZEN_V1",
                       "created_utc": "2026-11-14T02:00:00+00:00",
                       "source": report}))
        class P:
            returncode = 0
        return P()

    def make_hedge_forecast(self, command, **kwargs):
        if not any(str(arg).endswith(".v47_hedge") for arg in command):
            return self.make_forecast(command, **kwargs)
        game = command[command.index("--game") + 1]
        source_path = Path(command[command.index("--" + game + "-data") + 1])
        data = json.loads(source_path.read_bytes())
        target = command[command.index("--" + game + "-target") + 1]
        outpath = Path(command[command.index("--output") + 1])
        freezedir = Path(command[command.index("--freeze-dir") + 1])
        freezedir.mkdir(parents=True, exist_ok=True)
        has_prior = "--previous" in command
        prior = json.loads(Path(command[command.index("--previous") + 1]).read_bytes()) \
            if has_prior else None
        from research.supercompute.v47_registry import REGISTRY
        from research.supercompute.v47_models import canonical
        one = {"front": [1, 3, 7, 10, 20, 31], "back": [5],
               "dan2": [1, 3]} if game == "ssq" else {
               "front": [2, 5, 11, 19, 30], "back": [4, 12],
               "dan2": [2, 5]}
        models = {}
        champions = {}
        for i, cls in enumerate(REGISTRY, 1):
            for sign in ("+", "-"):
                name = f"M{i:02d}{sign}"
                pred = {"ticket": one}
                if sign == "-":
                    pred["excluded_pair"] = [15, 16]
                    genome = {"blend": .25, "recent_weight": .3,
                              "pair_weight": .1}
                    champions[cls.label] = genome
                    ancestry = []
                    if has_prior:
                        old = prior["games"][game]["evolution"][
                            "negative_champions"][cls.label]
                        ancestry.append({"origin": "inherited", "genes": old})
                    fit = {"cell_evolution": {"lineage": [
                        {"evaluated": ancestry}]}}
                else:
                    fit = {"inherited": has_prior}
                models[name] = {
                    "base_name": cls.label,
                    "fit": fit,
                    "direction": "subset" if sign == "+" else "disjoint",
                    "prediction": pred}
        game_report = {"schema": "SSQDLT_V47_HEDGE22_GAME_V2",
                       "game": game, "target_issue": target,
                       "ticket_count": 22, "model_count": 22, "models": models,
                       "joint_search": {
                           "schema": "SSQDLT_V47_JOINT_HARD_CONSTRAINT_V1",
                           "game": game,
                           "constraints": {
                               "required": [1, 3] if game == "ssq" else [2, 5],
                               "excluded": [15, 16]},
                           "tickets": [one] * 8,
                           "fair_probability_constraints_all_correct": .02},
                       "interval_search": {
                           "schema": "SSQDLT_V47_FOUR_AREA_INTERVAL_SEARCH_V1",
                           "game": game,
                           "profile": {
                               "front_include": 2, "front_exclude": 2,
                               "back_include": 0, "back_exclude": 0},
                           "areas": {
                               "front": {"required": [1, 3] if game == "ssq"
                                         else [2, 5], "excluded": [15, 16]},
                               "back": {"required": [], "excluded": []}},
                           "tickets": [one] * 8,
                           "retained_full_ticket_combinations": 100,
                           "calibration": {
                               "validation_independent_of_selection": True}},
                       "history_sha256": hashlib.sha256(
                           canonical(data["draws"])).hexdigest(),
                       "historical_validation": {"models":
                           {name: {} for name in models}},
                       "evolution": {
                           "base_champion": {"mix": .4},
                           "negative_champions": champions}}
        freezedir.joinpath(f"{game}-{target}-hedge22.json").write_bytes(
            canonical({"schema": "SSQDLT_V47_HEDGE22_FROZEN_V2",
                       "created_utc": "2026-11-14T02:00:00+00:00",
                       "source": game_report}))
        outpath.write_bytes(canonical({
            "schema": "SSQDLT_V47_HEDGE22_RUN_V2",
            "ticket_count": 22, "games": {game: game_report}}))
        return type("P", (), {"returncode": 0})()

    def test_real_issue_44_remote_receipts_and_postdraw_score(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            sources = self.make_sources(home)
            first_now = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run",
                       side_effect=self.make_hedge_forecast) as process:
                first = record(home, sources, 333301, 1, "c"*40, "schedule",
                               first_now, include_hedge44=True)
                self.assertEqual(process.call_count, 4)
                self.assertEqual(len(first["hedge44_generated"]), 2)
                self.assertEqual(first["hedge44_scored"], [])
                self.assertFalse(any(x["previous_champion_inherited"]
                                     for x in first["hedge44_generated"]))
            self.assertTrue(verify(home)["hedge44_index_verified"])
            with patch("research.supercompute.v47_live_ledger.subprocess.run") as process:
                second = record(home, sources, 333302, 1, "c"*40, "schedule",
                                first_now, include_hedge44=True)
                self.assertEqual(second["hedge44_generated"], [])
                self.assertEqual(second["hedge44_pending"][0]["status"],
                                 "ALREADY_FROZEN")
                self.assertEqual(process.call_count, 0)
            self.assertEqual(verify(home)["count"], 2)
            # Once the publisher posts the next draw, the formerly frozen
            # two 22-arm reports become independently scoreable without
            # changing the original prediction or its frozen hash.
            dates = {"ssq": "2026-11-15", "dlt": "2026-11-14"}
            for game, current in (("ssq", "2026131"), ("dlt", "26130")):
                file = sources / f"{game}-verified-history.json"
                report = json.loads(file.read_bytes())
                latest = dict(report["draws"][-1], issue=current,
                              draw_date=dates[game])
                report["draws"].append(latest)
                file.write_bytes(canonical(report))
                receipt_path = sources / "official-ingest-receipt.json"
                receipt = json.loads(receipt_path.read_bytes())
                receipt["games"][game]["history_sha256"] = hashlib.sha256(
                    canonical(report["draws"])).hexdigest()
                receipt["games"][game]["new_target_issue"] = str(int(current) + 1)
                receipt_path.write_bytes(canonical(receipt))
            late = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run",
                       side_effect=self.make_hedge_forecast):
                third = record(home, sources, 333303, 1, "c"*40, "schedule",
                               late, include_hedge44=True)
            self.assertEqual(len(third["hedge44_scored"]), 2)
            self.assertEqual([x["count"] for x in third["hedge44_scored"]], [22,22])
            self.assertEqual(len(third["hedge44_generated"]), 1)
            self.assertEqual(third["hedge44_generated"][0]["game"], "ssq")
            self.assertTrue(third["hedge44_generated"][0]["previous_champion_inherited"])
            ledger = home / "research/v47_live_ledger"
            for game, target in (("ssq", "2026131"), ("dlt", "26130")):
                score = json.loads((ledger / f"hedge44/scores/{game}-{target}.json").read_bytes())
                self.assertEqual(score["status"],
                                 "OFFICIAL_PUBLISHER_HTML_OVERLAP_SCORED")
                self.assertEqual(score["count"], 22)
                self.assertEqual(len(score["models"]), 22)
                self.assertTrue(score["strict_disjoint_verified"])
                self.assertIn("joint", score)
                self.assertIn("interval", score)
                self.assertIn("all_area_constraints_survived", score["interval"])
                self.assertFalse(score["trusted_predraw_seal"])
            self.assertEqual(verify(home)["count"], 3)
            item = next((ledger / "hedge44/frozen").glob("ssq-*-hedge22.json"))
            item.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                verify(home)

    def test_mismatched_draw_dates_freeze_only_new_dlt_and_score_prior_dlt(self):
        """SSQ stays on its frozen Sunday issue while DLT advances on Saturday."""
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            sources = self.make_sources(home)
            original = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run",
                       side_effect=self.make_hedge_forecast):
                first = record(home, sources, 555501, 1, "d"*40, "schedule",
                               original, include_hedge44=True)
            self.assertEqual(len(first["hedge44_generated"]), 2)
            # DLT published Saturday's numbers, SSQ Sunday's target is still
            # pending. This is the normal real-world case, not a bad partial
            # pair, and must NEVER block a new DLT ticket/score.
            path = sources / "dlt-verified-history.json"
            data = json.loads(path.read_bytes())
            data["draws"].append(dict(data["draws"][-1],
                                      issue="26130", draw_date="2026-11-14"))
            path.write_bytes(canonical(data))
            rec_path = sources / "official-ingest-receipt.json"
            receipt = json.loads(rec_path.read_bytes())
            receipt["games"]["dlt"]["history_sha256"] = hashlib.sha256(
                canonical(data["draws"])).hexdigest()
            receipt["games"]["dlt"]["new_target_issue"] = "26131"
            rec_path.write_bytes(canonical(receipt))
            later = datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run",
                       side_effect=self.make_hedge_forecast) as process:
                result = record(home, sources, 555502, 1, "d"*40, "schedule",
                                later, include_hedge44=True)
                self.assertEqual(process.call_count, 2)
            self.assertEqual([x["game"] for x in result["hedge44_generated"]],
                             ["dlt"])
            self.assertEqual(result["hedge44_generated"][0]["target_issue"], "26131")
            self.assertTrue(
                result["hedge44_generated"][0]["previous_champion_inherited"])
            self.assertEqual(result["hedge44_pending"][0]["game"], "ssq")
            self.assertEqual(result["hedge44_pending"][0]["status"], "ALREADY_FROZEN")
            self.assertEqual(result["hedge44_scored"][0]["game"], "dlt")
            self.assertEqual(result["hedge44_scored"][0]["issue"], "26130")
            self.assertEqual(result["hedge44_scored"][0]["count"], 22)
            self.assertEqual(verify(home)["count"], 2)

    def test_two_genuine_context_receipts_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = self.make_sources(root)
            now = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run",
                       side_effect=self.make_forecast) as calls:
                first = record(root, source, 123400, 1, "a"*40, "schedule", now)
                self.assertEqual(first["count"], 1)
                self.assertEqual(len(first["generated"]), 2)
                self.assertEqual(calls.call_count, 2)
            restored = verify(root)
            self.assertEqual(restored["count"], 1)
            with patch("research.supercompute.v47_live_ledger.subprocess.run") as calls:
                second = record(root, source, 123401, 1, "a"*40, "schedule", now)
                self.assertEqual(second["count"], 2)
                self.assertEqual(second["generated"], [])
                self.assertEqual(len(second["pending"]), 2)
                self.assertEqual(calls.call_count, 0)
            self.assertEqual(verify(root)["run_ids"], [123400, 123401])
            with self.assertRaises(ValueError):
                record(root, source, 123401, 1, "a"*40, "schedule", now)
            with self.assertRaises(ValueError):
                record(root, source, 123402, 1, "a"*40, "workflow_dispatch", now)
            entry = next((root / "research/v47_live_ledger/events").glob("*.json"))
            doc = json.loads(entry.read_bytes())
            doc["event_hash"] = "0" * 64
            entry.write_bytes(canonical(doc))
            with self.assertRaises(ValueError):
                verify(root)

    def test_after_nominal_draw_halts_if_publisher_not_updated(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = self.make_sources(root)
            after = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
            with patch("research.supercompute.v47_live_ledger.subprocess.run") as calls:
                result = record(root, source, 123499, 1, "b"*40, "schedule", after)
                self.assertEqual(result["generated"], [])
                self.assertEqual(len(result["pending"]), 2)
                self.assertTrue(all(x["reason"] ==
                    "PUBLISHER_STALE_AFTER_NOMINAL_DRAW" for x in result["pending"]))
                calls.assert_not_called()

    def test_nominal_time_for_both_games(self):
        self.assertEqual(next_nominal_draw("2026-11-12", "ssq").date().isoformat(),
                         "2026-11-15")
        self.assertEqual(next_nominal_draw("2026-11-11", "dlt").date().isoformat(),
                         "2026-11-14")


if __name__ == "__main__":
    unittest.main()
