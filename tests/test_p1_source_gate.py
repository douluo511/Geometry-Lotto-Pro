"""Offline adversarial contracts for P1 live-source intake; no network calls."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research.p1_source_gate import (
    PINNED_V47_COMMIT, assess, check_guard, strict_json
)


def bundle():
    return {
        "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
        "games": {
            game: {
                "status": "HISTORY_CROSSCHECK_LIMITED",
                "formal_A": 0,
                "official_target_admission": "BLOCKED",
                "decision": "NO_EDGE",
            }
            for game in ("SSQ", "DLT")
        },
        "formal_A": 0, "official_target_admission": "BLOCKED",
        "external_tsa": "NOT_RUN", "decision": "NO_EDGE",
    }


def audit():
    return {
        "schema": "V47-INTAKE-BUNDLE-AUDIT-1",
        "status": "PASS",
        "purpose": "BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY",
        "admission_guard": {
            "official_target_admission": "BLOCKED",
            "external_tsa": "NOT_RUN",
            "formal_A": 0,
            "decision": "NO_EDGE",
        },
        "verified_artifact_records": 7,
        "diagnostic_non_200_responses": 2,
        "bundle_manifest_sha256": "a" * 64,
    }


class P1EvidenceTests(unittest.TestCase):
    def test_source_and_audit_are_only_raw_custody_not_prediction_admission(self):
        receipt = assess(bundle(), audit(), PINNED_V47_COMMIT)
        self.assertEqual(receipt["status"], "RAW_CUSTODY_PASS_TARGET_BLOCKED")
        self.assertEqual(receipt["official_target_and_cutoff"], "BLOCKED")
        self.assertEqual(receipt["trusted_predraw_seal"], "NOT_RUN")
        self.assertEqual(receipt["p1_forecast_gate"], "UNVERIFIED")
        self.assertEqual(receipt["paid_model_calls"], 0)
        self.assertEqual(receipt["raw_body_records_verified"], 7)

    def test_single_game_source_is_never_complete_cohort(self):
        data = bundle()
        del data["games"]["DLT"]
        with self.assertRaisesRegex(ValueError, "BOTH_GAMES_REQUIRED"):
            check_guard(data)

    def test_both_game_formal_approval_is_rejected(self):
        data = bundle()
        data["formal_A"] = 1
        with self.assertRaisesRegex(ValueError, "BUNDLE_FORMAL_ADMISSION_BYPASS"):
            check_guard(data)
        data = bundle()
        data["games"]["SSQ"]["official_target_admission"] = "PASS"
        with self.assertRaisesRegex(ValueError, "GAME_FORMAL_ADMISSION_BYPASS"):
            check_guard(data)

    def test_fail_closed_for_auditor_claim_or_missing_raw_bytes(self):
        proof = audit()
        proof["status"] = "FAIL"
        with self.assertRaisesRegex(ValueError, "BUNDLE_BYTES_NOT_INDEPENDENTLY_VERIFIED"):
            assess(bundle(), proof, PINNED_V47_COMMIT)
        proof = audit()
        proof["verified_artifact_records"] = 0
        with self.assertRaisesRegex(ValueError, "NO_VERIFIABLE_HTTP_BYTES"):
            assess(bundle(), proof, PINNED_V47_COMMIT)
        proof = audit()
        proof["admission_guard"]["formal_A"] = 1
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_AUDITOR_ADMISSION_BYPASS"):
            assess(bundle(), proof, PINNED_V47_COMMIT)

    def test_unreviewed_current_head_cannot_impersonate_pinned_code(self):
        with self.assertRaisesRegex(ValueError, "UNREVIEWED_V47_CODE"):
            assess(bundle(), audit(), "f" * 40)

    def test_negative_and_boolean_formal_A_are_not_zero(self):
        for value in (False, -1, "0", None):
            data = bundle()
            data["formal_A"] = value
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "BUNDLE_FORMAL_ADMISSION_BYPASS"
            ):
                check_guard(data)

    def test_duplicate_keys_and_nonfinite_payloads_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "file.json"
            for raw, message in [
                ('{"x":1,"x":2}', "DUPLICATE_JSON_KEY"),
                ('{"x":NaN}', "NONFINITE_JSON"),
                ('{"x":Infinity}', "NONFINITE_JSON"),
                ('[]', "ROOT_MUST_BE_OBJECT"),
            ]:
                p.write_text(raw, encoding="utf-8")
                with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, message):
                    strict_json(p)

    def test_json_roundtrip_for_two_game_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "intake.json"
            p.write_text(json.dumps(bundle()), encoding="utf-8")
            source = strict_json(p)
            result = assess(source, audit(), PINNED_V47_COMMIT)
            self.assertEqual(set(result["official_history_status_by_game"]),
                             {"SSQ", "DLT"})


if __name__ == "__main__":
    unittest.main()
