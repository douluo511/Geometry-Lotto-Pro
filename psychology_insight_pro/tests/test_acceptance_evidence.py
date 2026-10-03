from pathlib import Path
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import collect_final_gates
from bind_gui_operations import validate_operations
from real_release_evidence import validate_real_release_evidence

class AcceptanceEvidenceTests(unittest.TestCase):
    def records(self):
        payloads = [
            ('analysis', 'PASS', {'hypothesis_count': 3, 'disclaimer': '不是心理诊断'}),
            ('update', 'BLOCKED', {'action': 'RELEASE_DEPENDENCY_UNAVAILABLE'}),
            ('repair', 'PASS', {'repair_action': 'RESTORED_VALIDATED_BUNDLE', 'post_repair_self_test': {'status': 'PASS'}}),
            ('advanced', 'PASS', {'core': 'PASS', 'reverse_validation': 'PASS', 'confidence_calibration': 'PASS'}),
        ]
        return [{'operation': op, 'status': status, 'result': result, 'process_id': 100 + i,
                 'source_sha': 'a' * 40, 'github_run_id': '123', 'github_run_attempt': '1'}
                for i, (op, status, result) in enumerate(payloads)]
    def test_current_mouse_process_and_backend_binding(self):
        buttons = [{'gui_process_id': 100 + i} for i in range(4)]
        records = self.records()
        self.assertEqual(set(validate_operations(records, buttons, 'a'*40, '123', '1')), {'analysis', 'update', 'repair', 'advanced'})
        for key, bad in [('process_id', 999), ('github_run_id', 'old'), ('github_run_attempt', '0'), ('source_sha', 'b'*40)]:
            altered = copy.deepcopy(records)
            altered[0][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_operations(altered, buttons, 'a'*40, '123', '1')
    def test_open_view_cannot_substitute_analysis_and_duplicate_cannot_pass(self):
        buttons = [{'gui_process_id': 100 + i} for i in range(4)]
        records = self.records()
        records[0]['result'] = {}
        with self.assertRaises(ValueError):
            validate_operations(records, buttons, 'a'*40, '123', '1')
    def test_blocked_click_cannot_substitute_configured_handoff(self):
        buttons = [{'gui_process_id': 100 + i} for i in range(4)]
        with self.assertRaises(ValueError):
            validate_operations(self.records(), buttons, 'a'*40, '123', '1', 'ConfiguredRelease')
        records = self.records()
        records[1].update({'status': 'PASS', 'result': {'action': 'UPDATER_HANDOFF', 'requires_parent_exit': True}})
        validate_operations(records, buttons, 'a'*40, '123', '1', 'ConfiguredRelease')
        with self.assertRaises(ValueError):
            validate_operations(records, buttons, 'a'*40, '123', '1', 'BlockedRelease')
        records = self.records()
        records.append(copy.deepcopy(records[0]))
        with self.assertRaises(ValueError):
            validate_operations(records, buttons, 'a'*40, '123', '1')
    def test_missing_updater_and_same_sha_old_run_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # PASS labels from another run must not become current engineering evidence.
            for name in ['architecture_gate', 'business_gate', 'unit_gate', 'contract_gate', 'fault_gate', 'integration_gate', 'real_network_evidence', 'business_validation_gate', 'exact_candidate_gate']:
                (root / (name+'.json')).write_text(json.dumps({'status': 'PASS', 'github_sha': 'a'*40, 'github_run_id': 'old', 'github_run_attempt': '1'}), encoding='utf-8')
            output = root / 'mother.json'
            argv = ['collector', '--exe', str(root/'absent.exe'), '--final-exe', str(root/'absent-final.exe'), '--physical-gui', str(root/'physical.json'), '--repository-evidence', str(root/'repo.json'), '--output', str(output)]
            with patch.object(collect_final_gates, 'ROOT', root), patch.object(sys, 'argv', argv), patch.dict(os.environ, {'PSYCHOLOGY_SOURCE_SHA': 'a'*40, 'GITHUB_RUN_ID': 'new', 'GITHUB_RUN_ATTEMPT': '1'}):
                self.assertEqual(collect_final_gates.main(), 2)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'FAIL')
            self.assertFalse(report['current_run_binding']['unit'])
            for key in ('updater_process', 'updater_exact_exe', 'updater_atomic_rollback', 'updater_real_network', 'updater_same_hash'):
                self.assertNotEqual(report['gates'][key], 'PASS')
    def test_fake_declared_release_pass_cannot_replace_release_receipts(self):
        result = validate_real_release_evidence({'status': 'PASS', 'schema': 'psychology-real-software-update-v1'}, repository='douluo511/Geometry-Lotto-Pro', source_sha='a'*40, run_id='123', run_attempt='1')
        self.assertEqual(result['status'], 'FAIL')

if __name__ == '__main__':
    unittest.main()
