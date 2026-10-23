"""Synthetic date-only contract fixtures; no real target or source admission."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from research.harness_v46 import core, convergence, prospective_cycle, schedule
from research.harness_v46.tests.test_core import fixture


CONTRACT = "V47-DATE-OBSERVED-SHADOW-1"


def rows_sha256(rows):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def observed_fixture(lottery="SSQ"):
    """Only synthetic rows and explicitly claimed future scheduling fields."""
    snapshot = fixture(lottery, size=120)
    snapshot["snapshot_contract"] = CONTRACT
    snapshot["draws"] = [
        {"issue": row["issue"], "draw_date": row["drawn_at"][:10],
         "front": row["front"], "back": row["back"]}
        for row in snapshot["draws"]
    ]
    snapshot["capture_observation"] = {
        "schema": "V47-RAW-OBSERVATION-1",
        "manifest_sha256": "a" * 64,
        "parser_source_sha256": "b" * 64,
        "raw_sha256s": ["c" * 64, "d" * 64],
        "observed_at_local_untrusted": "2026-10-19T23:59:00+00:00",
        "history_policy": "LATEST_120_VALIDATED_DRAWS_V1",
        "selected_rows_sha256": rows_sha256(snapshot["draws"]),
    }
    snapshot["provenance"] = {
        "source_authenticity": "CALLER_UNVERIFIED",
        "publication_time": "UNKNOWN",
        "evidence_class": "SHADOW",
        "formal_A": 0,
        "decision": "NO_EDGE",
        "official_G01": "BLOCKED",
        "fixture": "SYNTHETIC_NOT_OFFICIAL_TARGET_OR_SOURCE",
    }
    return snapshot


def resync_rows(snapshot):
    snapshot["capture_observation"]["selected_rows_sha256"] = rows_sha256(snapshot["draws"])


class ObservedSnapshotTests(unittest.TestCase):
    def test_explicit_date_contract_admits_120_rows_without_fabricated_times(self):
        snapshot = observed_fixture()
        try:
            actual = core.validate_study_snapshot(snapshot)
        except (core.GateError, KeyError) as exc:
            self.fail(f"explicit observed-availability SHADOW contract rejected: {exc}")
        self.assertEqual(actual, rows_sha256(snapshot))
        self.assertNotIn("drawn_at", snapshot["draws"][0])
        self.assertNotIn("published_at", snapshot["draws"][0])

    def test_unknown_contract_cannot_silently_use_legacy_path(self):
        snapshot = fixture(size=120)
        snapshot["snapshot_contract"] = "UNKNOWN-CONTRACT"
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_absent_marker_keeps_strict_legacy_publication_requirement(self):
        snapshot = fixture(size=120)
        self.assertEqual(core.validate_snapshot(snapshot), rows_sha256(snapshot))
        del snapshot["draws"][0]["published_at"]
        with self.assertRaises((core.GateError, KeyError)):
            core.validate_snapshot(snapshot)

    def test_alternate_schema_rejects_mixed_timestamp_rows(self):
        for field in ("drawn_at", "published_at", "date"):
            snapshot = observed_fixture()
            snapshot["draws"][0][field] = "2026-01-01T21:00:00+08:00"
            resync_rows(snapshot)
            with self.subTest(field=field), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)

    def test_row_count_is_exactly_the_declared_latest_120_policy(self):
        for count in (0, 119, 121):
            snapshot = observed_fixture()
            if count > 120:
                snapshot["draws"].append(copy.deepcopy(snapshot["draws"][-1]))
            else:
                snapshot["draws"] = snapshot["draws"][:count]
            resync_rows(snapshot)
            with self.subTest(count=count), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)

    def test_after_asof_capture_is_rejected_even_for_old_draw_dates(self):
        snapshot = observed_fixture()
        snapshot["capture_observation"]["observed_at_local_untrusted"] = "2026-10-20T00:00:00.000001+00:00"
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_same_china_date_row_is_rejected_across_utc_date_boundary(self):
        snapshot = observed_fixture()
        snapshot["as_of"] = "2026-10-20T17:00:00+00:00"  # China Oct 21
        snapshot["capture_observation"]["observed_at_local_untrusted"] = "2026-10-20T16:30:00+00:00"
        snapshot["draws"][-1]["draw_date"] = "2026-10-21"
        resync_rows(snapshot)
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_prior_china_date_row_is_valid_at_midnight_boundary(self):
        snapshot = observed_fixture()
        snapshot["as_of"] = "2026-10-20T16:00:00+00:00"  # China Oct 21 00:00
        snapshot["capture_observation"]["observed_at_local_untrusted"] = snapshot["as_of"]
        snapshot["draws"][-1]["draw_date"] = "2026-10-20"
        resync_rows(snapshot)
        try:
            core.validate_snapshot(snapshot)
        except (core.GateError, KeyError) as exc:
            self.fail(f"conservative previous-China-date boundary rejected: {exc}")

    def test_dates_require_exact_valid_date_and_increasing_source_order(self):
        for invalid in ("2026-1-01", "20260101", "2026-02-30", "2026-01-01T00:00:00Z", None):
            snapshot = observed_fixture()
            snapshot["draws"][0]["draw_date"] = invalid
            resync_rows(snapshot)
            with self.subTest(invalid=invalid), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)
        snapshot = observed_fixture()
        snapshot["draws"][1]["draw_date"] = snapshot["draws"][0]["draw_date"]
        resync_rows(snapshot)
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_issue_fields_are_canonical_positive_ascii_digits_and_ordered(self):
        for issue in ("0", "-1", "1.0", "26001 ", "026001", "２６００１", 26001, True):
            snapshot = observed_fixture()
            snapshot["draws"][0]["issue"] = issue
            resync_rows(snapshot)
            with self.subTest(issue=issue), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)
        snapshot = observed_fixture()
        snapshot["draws"][1]["issue"] = snapshot["draws"][0]["issue"]
        resync_rows(snapshot)
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_target_issue_is_strictly_future_without_mapping_guesses(self):
        for target in ("26120", "26119", "２９９９９", "029999", 29999):
            snapshot = observed_fixture()
            snapshot["target_issue"] = target
            with self.subTest(target=target), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)

    def test_source_balls_keep_existing_legality_rules(self):
        cases = ([1, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], [6, 5, 4, 3, 2, 1], [True, 2, 3, 4, 5, 6])
        for balls in cases:
            snapshot = observed_fixture()
            snapshot["draws"][0]["front"] = balls
            resync_rows(snapshot)
            with self.subTest(balls=balls), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)

    def test_every_time_is_aware_and_cutoff_is_strict(self):
        cases = (
            ("as_of", "2026-10-20T00:00:00"),
            ("sales_cutoff", "2026-10-20T00:00:00+00:00"),
            ("target_draw_at", "2026-10-22T00:00:00+00:00"),
        )
        for field, value in cases:
            snapshot = observed_fixture()
            snapshot[field] = value
            with self.subTest(field=field), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)
        snapshot = observed_fixture()
        snapshot["capture_observation"]["observed_at_local_untrusted"] = "2026-10-19T23:59:00"
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_capture_observation_is_exact_and_cannot_claim_publication_time(self):
        for field, value in (("published_at", "2026-01-01T00:00:00Z"),
                             ("schema", "OTHER"), ("history_policy", "ALL_CAPTURED_ROWS")):
            snapshot = observed_fixture()
            snapshot["capture_observation"][field] = value
            with self.subTest(field=field), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)
        for field in observed_fixture()["capture_observation"]:
            snapshot = observed_fixture()
            del snapshot["capture_observation"][field]
            with self.subTest(missing=field), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)

    def test_capture_hashes_are_nonempty_unique_lowercase_sha256(self):
        for field in ("manifest_sha256", "parser_source_sha256", "selected_rows_sha256"):
            for bad in ("", "A" * 64, "0" * 63, None):
                snapshot = observed_fixture()
                snapshot["capture_observation"][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(core.GateError):
                    core.validate_snapshot(snapshot)
        for raw_hashes in ([], ["c" * 64, "c" * 64], ["X" * 64], "c" * 64):
            snapshot = observed_fixture()
            snapshot["capture_observation"]["raw_sha256s"] = raw_hashes
            with self.subTest(raw_hashes=raw_hashes), self.assertRaises(core.GateError):
                core.validate_snapshot(snapshot)

    def test_selected_row_digest_cannot_be_swapped_independently(self):
        snapshot = observed_fixture()
        snapshot["draws"][0]["back"] = [1 if snapshot["draws"][0]["back"] != [1] else 2]
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_caller_provenance_cannot_grant_formal_source_or_time_authority(self):
        mutations = {"source_authenticity": "VERIFIED", "publication_time": "VERIFIED",
                     "evidence_class": "A", "formal_A": 1, "decision": "EDGE",
                     "official_G01": "PASS"}
        for field, value in mutations.items():
            snapshot = observed_fixture()
            snapshot["provenance"][field] = value
            with self.subTest(field=field), self.assertRaises(core.GateError):
                core.forecast(snapshot, "hot60")
        snapshot = observed_fixture()
        snapshot["provenance"]["formal_A"] = False
        with self.assertRaises(core.GateError):
            core.validate_snapshot(snapshot)

    def test_all_six_model_selections_match_strict_equivalent_history(self):
        for game in ("SSQ", "DLT"):
            strict, observed = fixture(game, size=120), observed_fixture(game)
            for model in core.MODELS:
                with self.subTest(game=game, model=model):
                    expected = core.forecast(strict, model)
                    try:
                        actual = core.forecast(observed, model)
                    except (core.GateError, KeyError) as exc:
                        self.fail(f"date-only model input rejected: {exc}")
                    for field in ("candidates_1_to_5", "primary_d2", "ticket", "parameters_sha256", "null_seed_id"):
                        self.assertEqual(actual[field], expected[field])
                    self.assertEqual(actual["evidence_class"], "SHADOW")
                    self.assertIs(actual["formal_a_eligible"], False)
                    self.assertNotEqual(actual["snapshot_sha256"], expected["snapshot_sha256"])
                    self.assertTrue(core.validate_forecast(actual, observed))

    def test_capture_metadata_is_bound_to_snapshot_and_forecast_identity(self):
        first = observed_fixture()
        try:
            prediction = core.forecast(first, "hot60")
        except (core.GateError, KeyError) as exc:
            self.fail(f"date-only baseline rejected: {exc}")
        second = copy.deepcopy(first)
        second["capture_observation"]["manifest_sha256"] = "e" * 64
        self.assertNotEqual(core.validate_snapshot(first), core.validate_snapshot(second))
        with self.assertRaises(core.GateError):
            core.validate_forecast(prediction, second)

    def test_synthetic_dual_game_freeze_show_and_existing_score_are_readonly(self):
        snapshots = {game: observed_fixture(game) for game in ("SSQ", "DLT")}
        try:
            manifest = convergence.manifest(snapshots)
        except (core.GateError, KeyError) as exc:
            self.fail(f"date-only manifest construction rejected: {exc}")
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "synthetic_observed.sqlite3"
            receipt = schedule.scheduled_once(
                snapshots, database, now=datetime(2026, 10, 21, tzinfo=timezone.utc),
                require_delivery_window=False,
            )
            self.assertEqual(receipt["run_id"], manifest["run_id"])
            self.assertEqual(receipt["formal_A"], 0)
            self.assertEqual(receipt["external_tsa"], "NOT_VERIFIED")
            self.assertEqual(receipt["gate_status"], "BLOCKED")
            frozen_bytes = database.read_bytes()
            shown = prospective_cycle.frozen_forecast_report(database, receipt["run_id"])
            self.assertEqual(shown["formal_A"], 0)
            with closing(sqlite3.connect(database)) as connection:
                for game in snapshots:
                    self.assertEqual(core.load_registered_snapshot(connection, receipt["run_id"], game), snapshots[game])
            for game in snapshots:
                self.assertEqual(len(shown["games"][game]["models"]), 6)
                result = {"lottery": game, "issue": "29999",
                          "front": list(range(1, core.RULES[game]["front"] + 1)),
                          "back": list(range(1, core.RULES[game]["back"] + 1))}
                scored = convergence.score_readonly(database, receipt["run_id"], result)
                self.assertEqual(scored["formal_A"], 0)
                self.assertEqual(scored["outcome_source"], "CALLER_UNVERIFIED")
                self.assertEqual(set(scored["scores"]), set(core.MODELS))
            self.assertEqual(database.read_bytes(), frozen_bytes)


if __name__ == "__main__":
    unittest.main()
