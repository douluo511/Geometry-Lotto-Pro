"""Adversarial raw-replay tests. Invented histories; no official admission."""
import base64
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from research.harness_v46 import official_intake as oi
from research.harness_v46.raw_semantic_replay import verify_sources
from research.harness_v46.core import GateError
from research.harness_v46.tests.test_official_intake import _payload


def synthetic_national_ssq():
    payload = _payload("SSQ")
    payload["status"] = "WORKER_FETCH_PARTIAL"
    national, shanghai = payload["sources"]
    rows = national["draws"]
    raw = json.dumps({"result": [
        {"code": d["issue"], "date": d["draw_date"],
         "red": d["front"], "blue": d["back"]}
        for d in rows
    ]}).encode("utf-8")
    artifact = national["raw_artifacts"][0]
    artifact["raw_base64"] = base64.b64encode(raw).decode("ascii")
    artifact["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    artifact["size_bytes"] = len(raw)
    national["raw_reparse_sha256"] = oi._rows_sha256(rows)
    shanghai["raw_reparse_status"] = "NOT_RUN"
    shanghai["draws"] = []
    shanghai["receipt"] = None
    return payload


def fake_parser(payload):
    def draw(issue, day, reds, blue):
        return SimpleNamespace(
            issue=str(issue), draw_date=str(day),
            front=tuple(sorted(int(n) for n in reds)),
            back=tuple(int(n) for n in blue),
        )
    return SimpleNamespace(
        PARSER_VERSION=payload["parser_version"], _draw=draw
    )


class IndependentRawReplayTests(unittest.TestCase):
    def test_positive_reparse_still_labels_formal_gate_blocked(self):
        payload = synthetic_national_ssq()
        receipt = verify_sources(payload, fake_parser(payload))
        self.assertEqual(receipt["verified_source_ids"], ["national"])
        self.assertEqual(receipt["status"], "SECOND_PROCESS_SAME_PARSER_REPLAY_MATCHED")
        self.assertEqual(receipt["official_G01"], "BLOCKED")
        self.assertEqual(receipt["formal_A"], 0)
        self.assertEqual(receipt["decision"], "NO_EDGE")

    def test_self_consistent_forged_draw_sha_does_not_override_raw(self):
        payload = synthetic_national_ssq()
        source = payload["sources"][0]
        # Attacker forges both the rows and their self-declared row SHA.
        source["draws"][3]["front"] = [1, 2, 3, 4, 5, 6]
        source["raw_reparse_sha256"] = oi._rows_sha256(source["draws"])
        with self.assertRaisesRegex(GateError, "SECOND_PROCESS_REPARSE_DIFFERS_FROM_CLAIM"):
            verify_sources(payload, fake_parser(payload))

    def test_false_http_200_with_self_consistent_sha_still_fails_decode(self):
        payload = _payload("SSQ")
        source = payload["sources"][0]
        raw = b"these bytes are not a valid history page"
        artifact = source["raw_artifacts"][0]
        artifact["raw_base64"] = base64.b64encode(raw).decode("ascii")
        artifact["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        artifact["size_bytes"] = len(raw)
        # Even if both URL allowlist and HTTP 200/body SHA pass, parsing must not.
        with self.assertRaisesRegex(GateError, "RAW_REPARSE_FAILED"):
            verify_sources(payload, fake_parser(payload))

    def test_all_claimed_valid_sources_must_have_raw_bytes(self):
        payload = synthetic_national_ssq()
        payload["sources"][0]["raw_artifacts"] = []
        with self.assertRaisesRegex(GateError, "RAW_REPLAY_REQUIRES_RAW_BYTES"):
            verify_sources(payload, fake_parser(payload))

    def test_second_process_failed_exit_blocks_history_collection(self):
        payload = _payload("SSQ")
        simulated_worker = subprocess.CompletedProcess(
            args=["worker"], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        simulated_replay = subprocess.CompletedProcess(
            args=["replay"], returncode=2, stdout="", stderr="RAW_REPARSE_FAILED"
        )
        with patch.object(oi.subprocess, "run",
                          side_effect=[simulated_worker, simulated_replay]) as runner:
            receipt = oi.collect_live_history("SSQ", timeout_seconds=10)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(receipt["status"], "SECOND_PROCESS_RAW_REPLAY_BLOCKED")
        self.assertEqual(receipt["official_history_admission"], "BLOCKED")
        self.assertEqual(receipt["formal_A"], 0)
        self.assertEqual(receipt["consensus_draws"], [])
        self.assertEqual(receipt["primary_history_draws"], [])
        self.assertIn("SECOND_PROCESS_RAW_REPLAY_BLOCKED",
                      receipt["errors"]["second_process_replay"])
        # Original bytes are retained for forensic review in a fresh bundle.
        with tempfile.TemporaryDirectory() as root:
            path = oi.write_bundle({
                "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
                "games": {"SSQ": receipt},
                "errors": {"SSQ": receipt["errors"]["second_process_replay"]},
                "formal_A": 0, "official_target_admission": "BLOCKED",
                "external_tsa": "NOT_RUN", "decision": "NO_EDGE",
            }, Path(root) / "source-evidence")
            written = json.loads(path.read_text(encoding="utf-8"))
            artifact = written["games"]["SSQ"]["sources"][0]["raw_artifacts"][0]
            self.assertEqual((path.parent / artifact["artifact_path"]).read_bytes(),
                             base64.b64decode(payload["sources"][0]["raw_artifacts"][0]["raw_base64"]))

    def test_fake_receipt_cannot_qualify_source_collection(self):
        payload = _payload("DLT")
        simulated_worker = subprocess.CompletedProcess(
            args=["worker"], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        simulated_replay = subprocess.CompletedProcess(
            args=["replay"], returncode=0,
            stdout=json.dumps({
                "schema": "V47-SECOND-PROCESS-SEMANTIC-REPLAY-1",
                "status": "SECOND_PROCESS_SAME_PARSER_REPLAY_MATCHED",
                "lottery": "DLT",
                "worker_payload_sha256": "0" * 64,
                "official_G01": "BLOCKED",
                "formal_A": 0,
            }),
            stderr=""
        )
        with patch.object(oi.subprocess, "run",
                          side_effect=[simulated_worker, simulated_replay]):
            receipt = oi.collect_live_history("DLT", timeout_seconds=10)
        self.assertEqual(receipt["status"], "SECOND_PROCESS_RAW_REPLAY_BLOCKED")
        self.assertEqual(receipt["official_history_admission"], "BLOCKED")
        self.assertEqual(receipt["consensus_draw_count"], 0)
        self.assertEqual(receipt["formal_A"], 0)
        self.assertEqual(receipt["errors"]["second_process_replay"],
                         "SECOND_PROCESS_RAW_REPLAY_RECEIPT_MISMATCH")

    def test_replay_parser_version_mismatch_fails_closed(self):
        payload = synthetic_national_ssq()
        fake = fake_parser(payload)
        fake.PARSER_VERSION = "tampered-version"
        with self.assertRaisesRegex(GateError, "RAW_REPLAY_IMPORTED_PARSER_VERSION_MISMATCH"):
            verify_sources(payload, fake)


if __name__ == "__main__":
    unittest.main()
