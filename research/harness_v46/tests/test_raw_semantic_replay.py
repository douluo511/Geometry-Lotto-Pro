"""Adversarial raw-replay tests. Invented histories; no official admission."""
import base64
import copy
import hashlib
import json
import subprocess
import sys
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
    def collect_with_real_replay(self, payload):
        """Replace network collection only; execute the actual offline child."""
        original_run = subprocess.run

        def run(command, **kwargs):
            if "--worker" in command:
                return subprocess.CompletedProcess(
                    command, 0, json.dumps(payload), ""
                )
            return original_run(command, **kwargs)

        with patch.object(oi.subprocess, "run", side_effect=run) as runner:
            result = oi.collect_live_history("SSQ", timeout_seconds=30)
        self.assertEqual(runner.call_count, 2)
        return result

    def assert_quarantined_with_raw(self, result, payload):
        self.assertEqual(result["status"], "SECOND_PROCESS_RAW_REPLAY_BLOCKED")
        self.assertEqual(result["official_history_admission"], "BLOCKED")
        self.assertEqual(result["official_target_admission"], "BLOCKED")
        self.assertEqual(result["consensus_draws"], [])
        self.assertEqual(result["primary_history_draws"], [])
        self.assertEqual(result["formal_A"], 0)
        self.assertEqual(result["decision"], "NO_EDGE")
        self.assertEqual(
            result["sources"][0]["raw_artifacts"][0]["raw_base64"],
            payload["sources"][0]["raw_artifacts"][0]["raw_base64"],
        )

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

    def test_partial_valid_source_runs_real_second_process_and_stays_partial(self):
        payload = synthetic_national_ssq()
        result = self.collect_with_real_replay(payload)
        self.assertEqual(result["status"], "SOURCE_FETCH_PARTIAL")
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["official_history_admission"], "BLOCKED")
        self.assertEqual(result["consensus_draws"], [])
        self.assertEqual(result["second_process_raw_replay"]["verified_source_ids"],
                         ["national"])
        self.assertEqual(
            result["second_process_raw_replay"]["replayed_rows_sha256"],
            {"national": oi._rows_sha256(payload["sources"][0]["draws"])},
        )
        self.assertEqual(result["parser_to_raw_binding"],
                         "SECOND_PROCESS_SAME_PARSER_REPLAY_MATCHED")
        self.assertEqual(result["formal_A"], 0)
        self.assertEqual(result["decision"], "NO_EDGE")

    def test_unicode_partial_error_runs_real_replay_under_cp1252_locale(self):
        payload = synthetic_national_ssq()
        payload["errors"] = {"shanghai": "源站错误"}
        payload["sources"][1]["error"] = payload["errors"]["shanghai"]
        with patch.object(subprocess, "_text_encoding", return_value="cp1252"):
            result = self.collect_with_real_replay(payload)
        self.assertEqual(result["status"], "SOURCE_FETCH_PARTIAL")
        self.assertEqual(result["errors"], {"shanghai": "源站错误"})
        self.assertEqual(result["second_process_raw_replay"]["verified_source_ids"],
                         ["national"])

    def test_worker_and_replay_unicode_streams_round_trip_under_cp1252_locale(self):
        payload = synthetic_national_ssq()
        payload["errors"] = {"shanghai": "源站错误"}
        original_run = subprocess.run
        completed_children = {}

        def run(command, **kwargs):
            if "--worker" in command:
                # An offline child emits the worker fixture through real pipes.
                # It exercises both ends of the worker transport without fetching.
                code = ("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); "
                        "sys.stderr.write('worker:\\u6e90\\u7ad9\\u9519\\u8bef')")
                kwargs["input"] = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                child = original_run([sys.executable, "-c", code], **kwargs)
                completed_children["worker"] = child
                return child
            code = ("import sys; "
                    "from research.harness_v46.raw_semantic_replay import main; "
                    "sys.stderr.write('replay:\\u590d\\u6838\\u8bca\\u65ad'); "
                    "raise SystemExit(main())")
            child = original_run([sys.executable, "-c", code, "--game", "SSQ"],
                                 **kwargs)
            completed_children["replay"] = child
            return child

        with patch.object(oi.subprocess, "run", side_effect=run):
            with patch.object(subprocess, "_text_encoding", return_value="cp1252"):
                result = oi.collect_live_history("SSQ", timeout_seconds=30)
        self.assertEqual(result["status"], "SOURCE_FETCH_PARTIAL")
        self.assertEqual(result["errors"], {"shanghai": "源站错误"})
        self.assertEqual(json.loads(completed_children["worker"].stdout), payload)
        self.assertEqual(completed_children["worker"].stderr, "worker:源站错误".encode("utf-8"))
        self.assertEqual(completed_children["replay"].stderr, "replay:复核诊断")
        self.assertEqual(result["second_process_raw_replay"]["decision"], "NO_EDGE")

    def test_partial_invalid_raw_runs_real_second_process_and_is_quarantined(self):
        payload = synthetic_national_ssq()
        raw = b"self-consistent HTTP 200 hash, but no actual lottery history"
        artifact = payload["sources"][0]["raw_artifacts"][0]
        artifact.update(raw_base64=base64.b64encode(raw).decode("ascii"),
                        raw_sha256=hashlib.sha256(raw).hexdigest(),
                        size_bytes=len(raw))
        result = self.collect_with_real_replay(payload)
        self.assert_quarantined_with_raw(result, payload)
        self.assertIn("RAW_REPARSE_FAILED",
                      result["errors"]["second_process_replay"])

    def test_partial_without_claimed_rows_does_not_launch_replay(self):
        payload = synthetic_national_ssq()
        payload["sources"][0].update(draws=[], receipt=None,
                                     raw_reparse_status="NOT_RUN")
        worker = subprocess.CompletedProcess(["worker"], 0, json.dumps(payload), "")
        with patch.object(oi.subprocess, "run", return_value=worker) as runner:
            result = oi.collect_live_history("SSQ", timeout_seconds=10)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(result["status"], "SOURCE_FETCH_PARTIAL")
        self.assertEqual(result["source_count"], 0)
        self.assertNotIn("second_process_raw_replay", result)

    def test_replay_timeout_and_launch_error_preserve_raw_for_writing(self):
        for failure in (subprocess.TimeoutExpired(["replay"], 10),
                        OSError("synthetic replay launch failure")):
            with self.subTest(failure=type(failure).__name__):
                payload = _payload("SSQ")
                worker = subprocess.CompletedProcess(["worker"], 0,
                                                       json.dumps(payload), "")
                with patch.object(oi.subprocess, "run", side_effect=[worker, failure]):
                    result = oi.collect_live_history("SSQ", timeout_seconds=10)
                self.assert_quarantined_with_raw(result, payload)
                self.assertIn(type(failure).__name__,
                              result["errors"]["second_process_replay"])
                with tempfile.TemporaryDirectory() as root:
                    manifest = oi.write_bundle({"games": {"SSQ": result}},
                                               Path(root) / "failed-replay")
                    written = json.loads(manifest.read_text(encoding="utf-8"))
                    artifact = written["games"]["SSQ"]["sources"][0]["raw_artifacts"][0]
                    self.assertEqual(
                        (manifest.parent / artifact["artifact_path"]).read_bytes(),
                        base64.b64decode(payload["sources"][0]["raw_artifacts"][0]["raw_base64"]),
                    )

    def test_collect_both_retains_raw_when_second_process_cannot_run(self):
        ssq, dlt = _payload("SSQ"), _payload("DLT")
        workers = [subprocess.CompletedProcess(["worker"], 0, json.dumps(p), "")
                   for p in (ssq, dlt)]
        with patch.object(oi.subprocess, "run", side_effect=[
            workers[0], subprocess.TimeoutExpired(["replay"], 10),
            workers[1], OSError("synthetic replay launch failure"),
        ]):
            bundle = oi.collect_both()
        for game, payload in (("SSQ", ssq), ("DLT", dlt)):
            with self.subTest(game=game):
                self.assert_quarantined_with_raw(bundle["games"][game], payload)
                self.assertIn(game, bundle["errors"])

    def test_complete_receipt_contract_is_required(self):
        payload = synthetic_national_ssq()
        valid_receipt = verify_sources(payload, fake_parser(payload))
        replacements = {
            "replayed_rows_sha256": {"national": "0" * 64},
            "decision": "EDGE_CONFIRMED",
            "source_origin_authenticity": "VERIFIED",
            "publication_time_authenticity": "VERIFIED",
            "official_G01": "PASS",
            "formal_A": False,
            "verified_source_ids": ["national", "shanghai"],
            "worker_payload_sha256": "0" * 64,
        }
        mutations = [(name, {**valid_receipt, name: value})
                     for name, value in replacements.items()]
        missing_map = copy.deepcopy(valid_receipt)
        missing_map.pop("replayed_rows_sha256")
        mutations.append(("missing row map", missing_map))
        extra_source = copy.deepcopy(valid_receipt)
        extra_source["replayed_rows_sha256"]["shanghai"] = "0" * 64
        mutations.append(("extra source in row map", extra_source))
        for name, receipt in mutations:
            with self.subTest(field=name):
                worker = subprocess.CompletedProcess(["worker"], 0,
                                                       json.dumps(payload), "")
                replay = subprocess.CompletedProcess(["replay"], 0,
                                                       json.dumps(receipt), "")
                with patch.object(oi.subprocess, "run", side_effect=[worker, replay]):
                    result = oi.collect_live_history("SSQ", timeout_seconds=10)
                self.assert_quarantined_with_raw(result, payload)
                self.assertEqual(result["errors"]["second_process_replay"],
                                 "SECOND_PROCESS_RAW_REPLAY_RECEIPT_MISMATCH")

    def test_source_hash_change_during_replay_quarantines_raw(self):
        payload = synthetic_national_ssq()
        receipt = verify_sources(payload, fake_parser(payload))
        hashes = payload["source_files_sha256"]
        changed = {**hashes, "SSQ/SSQ/glp/sources.py": "0" * 64}
        worker = subprocess.CompletedProcess(["worker"], 0, json.dumps(payload), "")
        replay = subprocess.CompletedProcess(["replay"], 0, json.dumps(receipt), "")
        with patch.object(oi.subprocess, "run", side_effect=[worker, replay]):
            with patch.object(oi, "source_file_hashes",
                              side_effect=[hashes, hashes, hashes, changed]):
                result = oi.collect_live_history("SSQ", timeout_seconds=10)
        self.assert_quarantined_with_raw(result, payload)
        self.assertEqual(result["errors"]["second_process_replay"],
                         "PARSER_FILES_CHANGED_DURING_RAW_REPLAY")

    def test_missing_parser_after_replay_quarantines_raw(self):
        payload = synthetic_national_ssq()
        receipt = verify_sources(payload, fake_parser(payload))
        hashes = payload["source_files_sha256"]
        worker = subprocess.CompletedProcess(["worker"], 0, json.dumps(payload), "")
        replay = subprocess.CompletedProcess(["replay"], 0, json.dumps(receipt), "")
        for failure in (GateError("PARSER_DEPENDENCY_MISSING:synthetic"),
                        OSError("synthetic parser file became unreadable")):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(oi.subprocess, "run", side_effect=[worker, replay]):
                    with patch.object(oi, "source_file_hashes", side_effect=[
                        hashes, hashes, hashes, failure,
                    ]):
                        result = oi.collect_live_history("SSQ", timeout_seconds=10)
                self.assert_quarantined_with_raw(result, payload)
                self.assertIn("PARSER_FILES_UNAVAILABLE_AFTER_RAW_REPLAY",
                              result["errors"]["second_process_replay"])

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
