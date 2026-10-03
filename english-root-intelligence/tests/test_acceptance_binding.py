from __future__ import annotations

import base64
import copy
import hashlib
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from final_artifact_gate import validate as validate_final
from software_release_gate import validate as validate_release
from physical_gui_evidence import LABELS, validate_physical
from release_gate import HARD_GATES, validate_mother
from updater_evidence import UPDATER_CHECKS, validate_atomic_checks

HEAD, RUN, ATTEMPT = "a" * 40, "100", "2"
REPOSITORY = "example/english-root-independent"


def receipt(raw, url):
    return {"url": url, "final_url": url, "http_status": 200,
            "sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw),
            "raw_b64": base64.b64encode(raw).decode(), "fetched_at": "2026-10-03T00:00:00Z",
            "attempt_ledger": [{"attempt": 1, "outcome": "HTTP_RESPONSE", "status_code": 200}]}


def release_fixture():
    artifact = b"MZ-test-only-candidate"
    old, updater = b"MZ-test-only-old", b"MZ-test-only-updater"
    old_hash, new_hash, updater_hash = (hashlib.sha256(raw).hexdigest() for raw in (old, artifact, updater))
    manifest = {"schema": "english-root-software-update-manifest-v1", "version": "0.4.1",
                "artifact_url": f"https://github.com/{REPOSITORY}/releases/download/v0.4.1/Main.exe", "artifact_sha256": new_hash,
                "artifact_bytes": len(artifact)}
    result = {"schema": "english-root-real-software-update-v1", "status": "PASS", "repository": REPOSITORY,
              "source_sha": HEAD, "github_run_id": RUN, "github_run_attempt": ATTEMPT,
              "producer": "english-root-physical-release-workflow-v1",
              "release_n": {"version": "0.4.0", "main_exe_sha256": old_hash, "updater_exe_sha256": updater_hash,
                            "release_url": f"https://github.com/{REPOSITORY}/releases/tag/v0.4.0"},
              "release_n1": {"version": "0.4.1", "main_exe_sha256": new_hash, "updater_exe_sha256": updater_hash,
                             "release_url": f"https://github.com/{REPOSITORY}/releases/tag/v0.4.1"},
              "release_config": {"schema": "english-root-software-update-config-v1", "trusted_hosts": ["updates.example", "github.com"],
                                 "manifest_url": "https://updates.example/latest.json"},
              "updater_result": {"status": "PASS", "action": "UPDATED", "operation": "software_update",
                                 "rollback_performed": False, "old_exe_sha256": old_hash, "new_exe_sha256": new_hash,
                                 "from_version": "0.4.0", "to_version": "0.4.1",
                                 "manifest_receipt": receipt(json.dumps(manifest).encode(), "https://updates.example/latest.json"),
                                 "artifact_receipt": receipt(artifact, manifest["artifact_url"])},
              "updater_execution": {"independent_process": True, "updater_exe_sha256": updater_hash, "pid": 123},
              "physical_update_click": {"status": "PASS", "label": "一键更新", "method": "physical_mouse",
                                        "from_exe_sha256": old_hash, "to_exe_sha256": new_hash},
              "post_update_self_test": {"status": "PASS", "exe_sha256": new_hash}}
    for key, tag, assets in (
        ("release_n", "v0.4.0", [(f"https://github.com/{REPOSITORY}/releases/download/v0.4.0/Main.exe", old_hash, old), (f"https://github.com/{REPOSITORY}/releases/download/v0.4.0/Updater.exe", updater_hash, updater)]),
        ("release_n1", "v0.4.1", [(manifest["artifact_url"], new_hash, artifact), (f"https://github.com/{REPOSITORY}/releases/download/v0.4.1/Updater.exe", updater_hash, updater)]),
    ):
        item = result[key]
        api = {"tag_name": tag, "html_url": item["release_url"], "draft": False, "prerelease": False,
               "id": 100, "published_at": "2026-10-03T00:00:00Z",
               "assets": [{"id": index + 1, "state": "uploaded", "browser_download_url": url, "digest": "sha256:" + digest, "size": len(raw)} for index, (url, digest, raw) in enumerate(assets)]}
        item["tag"] = tag
        item["api_receipt"] = receipt(json.dumps(api).encode(), f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}")
        item["source_sha"] = HEAD if key == "release_n1" else "b" * 40
        commit = {"sha": item["source_sha"], "html_url": f"https://github.com/{REPOSITORY}/commit/{item['source_sha']}"}
        item["commit_receipt"] = receipt(json.dumps(commit).encode(), f"https://api.github.com/repos/{REPOSITORY}/commits/{tag}")
    result["release_n"]["main_exe_receipt"] = receipt(old, f"https://github.com/{REPOSITORY}/releases/download/v0.4.0/Main.exe")
    result["release_n"]["updater_exe_receipt"] = receipt(updater, f"https://github.com/{REPOSITORY}/releases/download/v0.4.0/Updater.exe")
    result["release_n1"]["updater_exe_receipt"] = receipt(updater, f"https://github.com/{REPOSITORY}/releases/download/v0.4.1/Updater.exe")
    return result


class AcceptanceBindingTests(unittest.TestCase):
    def setUp(self):
        self.images = tempfile.TemporaryDirectory()
        self.addCleanup(self.images.cleanup)

    def physical_fixture(self, main_hash):
        report = {"github_sha": HEAD, "github_run_id": RUN, "github_run_attempt": ATTEMPT,
                  "status": "PASS", "schema": "english-root-physical-gui-bound-v1",
                  "activation": "foreground cursor + mouse_event LEFTDOWN/LEFTUP",
                  "update_mode": "ConfiguredRelease", "exe_sha256": main_hash, "buttons": [], "service_actions": []}
        for index, label in enumerate(LABELS, 1):
            button = {"button_index": index, "status": "PASS", "visual_changed": True, "target_pid": index + 100,
                      "clicked_at": "2026-10-03T00:00:00+00:00", "completed_at": "2026-10-03T00:00:02+00:00"}
            for phase in ("before", "after"):
                image = Path(self.images.name) / f"{index}.{phase}.test-parser-bytes"
                raw = f"test-parser-only-{index}-{phase}".encode()
                image.write_bytes(raw)
                button[phase + "_screenshot"] = str(image)
                button[phase + "_sha256"] = hashlib.sha256(raw).hexdigest()
            result = {"status": "PASS"}
            if index == 1:
                result.update(root_count=3, morphemes=["dict", "spect", "port"])
            elif index == 2:
                result.update(action="UPDATER_HANDOFF", operation="software_update", updater_pid=999, requires_parent_exit=True)
            elif index == 3:
                result.update(checks=[["Knowledge DB", "PASS", "validated"], ["User Progress", "PASS", "validated"]])
            else:
                result.update(stats={"root_total": 10, "coverage_pct": 0, "practice_repetitions": 0, "word_analyses": 1})
            action = {"label": label, "process_id": index + 100, "exe_sha256": main_hash, "source_sha": HEAD,
                      "github_run_id": RUN, "github_run_attempt": ATTEMPT, "recorded_at": "2026-10-03T00:00:01+00:00", "result": result}
            report["buttons"].append(button)
            report["service_actions"].append(action)
        return report

    def check_release(self, value):
        return validate_release(value, repository=REPOSITORY, source_sha=HEAD, run_id=RUN, run_attempt=ATTEMPT)

    def test_complete_fixture_exercises_parser_only(self):
        value = release_fixture()
        self.assertEqual(self.check_release(value)["new_exe_sha256"], value["release_n1"]["main_exe_sha256"])

    def test_release_counterexamples_fail_closed(self):
        cases = []
        def change(path, value):
            fixture = release_fixture()
            cursor = fixture
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            cases.append(fixture)
        change(["source_sha"], "b" * 40)
        change(["github_run_attempt"], "1")
        change(["repository"], "douluo511/Geometry-Lotto-Pro")
        change(["release_n1", "version"], "0.4.0")
        change(["release_n1", "release_url"], "https://github.com/another/repo/releases/tag/v0.4.1")
        change(["release_n1", "source_sha"], "b" * 40)
        change(["release_n1", "updater_exe_sha256"], "0" * 64)
        change(["release_n1", "commit_receipt", "raw_b64"], base64.b64encode(b'{}').decode())
        change(["updater_execution", "independent_process"], False)
        change(["physical_update_click", "to_exe_sha256"], "0" * 64)
        change(["post_update_self_test", "exe_sha256"], "0" * 64)
        change(["updater_result", "artifact_receipt", "raw_b64"], base64.b64encode(b"tampered").decode())
        change(["updater_result", "artifact_receipt", "final_url"], "https://evil.example/Main.exe")
        change(["updater_result", "artifact_receipt", "attempt_ledger"], [])
        change(["release_config", "manifest_url"], "https://updates.example/other.json")
        for index, value in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.check_release(value)

    def final_fixture(self):
        identity = {"github_sha": HEAD, "github_run_id": RUN, "github_run_attempt": ATTEMPT, "status": "PASS"}
        reports = {key: dict(identity) for key in ("repository", "release", "exact", "gui", "updater")}
        main_hash, updater_hash = "2" * 64, "3" * 64
        reports["repository"]["repository"] = REPOSITORY
        reports["release"].update(repository=REPOSITORY, accepted={"new_exe_sha256": main_hash, "updater_exe_sha256": updater_hash})
        reports["exact"]["exe_sha256"] = main_hash
        reports["gui"] = self.physical_fixture(main_hash)
        reports["updater"].update(updater_exe_sha256=updater_hash, same_hash=True, exit_code=0, self_test={"status": "PASS"})
        return reports, [main_hash, main_hash, updater_hash, updater_hash]

    @patch.dict("os.environ", {"GITHUB_RUN_ID": RUN, "GITHUB_RUN_ATTEMPT": ATTEMPT})
    def test_final_rejects_stale_run_even_when_all_statuses_pass(self):
        reports, hashes = self.final_fixture()
        self.assertEqual(validate_final(reports, hashes, HEAD)["status"], "PASS")
        for key in reports:
            stale = copy.deepcopy(reports)
            stale[key]["github_run_attempt"] = "1"
            self.assertEqual(validate_final(stale, hashes, HEAD)["status"], "FAIL")

    @patch.dict("os.environ", {"GITHUB_RUN_ID": RUN, "GITHUB_RUN_ATTEMPT": ATTEMPT})
    def test_final_rejects_release_hash_mismatch(self):
        reports, hashes = self.final_fixture()
        reports["release"]["accepted"]["new_exe_sha256"] = "4" * 64
        self.assertEqual(validate_final(reports, hashes, HEAD)["status"], "FAIL")

    @patch.dict("os.environ", {"GITHUB_RUN_ID": RUN, "GITHUB_RUN_ATTEMPT": ATTEMPT})
    def test_external_blocker_does_not_hide_internal_failure(self):
        reports, hashes = self.final_fixture()
        reports["release"]["status"] = "BLOCKED"
        self.assertEqual(validate_final(reports, hashes, HEAD)["status"], "BLOCKED")
        hashes[1] = "4" * 64
        self.assertEqual(validate_final(reports, hashes, HEAD)["status"], "FAIL")

    @patch.dict("os.environ", {"GITHUB_RUN_ID": RUN, "GITHUB_RUN_ATTEMPT": ATTEMPT})
    def test_blocked_update_physical_click_cannot_be_final_pass(self):
        reports, hashes = self.final_fixture()
        reports["gui"]["update_mode"] = "BlockedRelease"
        reports["gui"]["service_actions"][1]["result"] = {"status": "BLOCKED", "error": "release config absent"}
        self.assertTrue(validate_physical(reports["gui"], HEAD))
        self.assertFalse(validate_physical(reports["gui"], HEAD, require_configured=True))
        self.assertEqual(validate_final(reports, hashes, HEAD)["status"], "FAIL")

    @patch.dict("os.environ", {"GITHUB_RUN_ID": RUN, "GITHUB_RUN_ATTEMPT": ATTEMPT})
    def test_gui_rejects_empty_forged_or_unbound_service_results(self):
        report = self.physical_fixture("2" * 64)
        self.assertTrue(validate_physical(report, HEAD))
        cases = []
        for index in range(4):
            row = copy.deepcopy(report)
            row["service_actions"][index]["result"] = {"status": "PASS"}
            cases.append(row)
        row = copy.deepcopy(report)
        row["service_actions"][0]["process_id"] = 777
        cases.append(row)
        row = copy.deepcopy(report)
        row["buttons"][0]["after_sha256"] = "0" * 64
        cases.append(row)
        row = copy.deepcopy(report)
        row["service_actions"][0]["recorded_at"] = "2026-10-03T00:00:05+00:00"
        cases.append(row)
        for value in cases:
            self.assertFalse(validate_physical(value, HEAD))

    @patch.dict("os.environ", {"GITHUB_RUN_ID": RUN, "GITHUB_RUN_ATTEMPT": ATTEMPT})
    def test_final_gate_rejects_stale_identity_missing_gate_or_forged_percentage(self):
        value = {"schema": "english-root-mother-gate-input-v1", "status": "PASS", "github_sha": HEAD,
                 "github_run_id": RUN, "github_run_attempt": ATTEMPT, "hard_fail_count": 0,
                 "engineering_completion": 100, "business_completion": 100, "combined_completion": 100,
                 "gates": dict.fromkeys(HARD_GATES, "PASS")}
        self.assertEqual(validate_mother(value, HEAD)["final_gate"], "PASS")
        for key, bad in (("github_run_attempt", "1"), ("engineering_completion", 99), ("status", "FAIL")):
            altered = copy.deepcopy(value)
            altered[key] = bad
            self.assertEqual(validate_mother(altered, HEAD)["final_gate"], "FAIL")
        for gate in HARD_GATES:
            altered = copy.deepcopy(value)
            del altered["gates"][gate]
            self.assertEqual(validate_mother(altered, HEAD)["final_gate"], "FAIL")

    def test_atomic_gate_requires_every_named_scenario(self):
        report = {"schema": "english-root-updater-gate-v1", "status": "PASS", "checks": {key: {"status": "PASS"} for key in UPDATER_CHECKS}}
        self.assertTrue(validate_atomic_checks(report))
        forged = copy.deepcopy(report)
        forged["checks"] = {str(index): {"status": "PASS"} for index in range(13)}
        self.assertFalse(validate_atomic_checks(forged))
        for scenario in UPDATER_CHECKS:
            missing = copy.deepcopy(report)
            del missing["checks"][scenario]
            self.assertFalse(validate_atomic_checks(missing))
            failed = copy.deepcopy(report)
            failed["checks"][scenario]["status"] = "FAIL"
            self.assertFalse(validate_atomic_checks(failed))


if __name__ == "__main__":
    unittest.main()
