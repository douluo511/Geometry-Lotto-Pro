"""Synthetic attacks on the real helpers and on audit receipt semantics."""
import copy
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research.ssq_dlt_asof_audit import audit
from research.ssq_dlt_asof_audit import acceptance


def read(path):return audit.parse(Path(path).read_bytes())
def overwrite(path,value):Path(path).write_text(audit.canonical(value)+'\n',encoding='utf-8',newline='\n')


class CaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=TemporaryDirectory();cls.root=Path(cls.temp.name).resolve()
        cls.protocol=audit.PACKAGE/'diagnostic-protocol.json'
        cls.output=cls.root/'complete'
        cls.receipt=audit.execute(cls.protocol,cls.output)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def rows(self,case):
        return [read(self.output/'cases'/case/g/'result.json') for g in audit.GAMES]

    def test_complete_two_game_rectangle_is_only_diagnostic_success(self):
        self.assertEqual(self.receipt['status'],'PASS_DIAGNOSTIC_EXPECTATIONS_ONLY')
        self.assertEqual(self.receipt['case_count'],16)
        self.assertFalse(self.receipt['prediction_effect_improvement_tested'])
        self.assertFalse(self.receipt['complete_runtime_or_physical_p0_tested'])
        self.assertEqual(self.receipt['asof_qualification'],'BLOCKED')

    def test_clean_history_has_no_target_or_trusted_availability(self):
        for row in self.rows('C0'):
            stage=row['history_stage_games'][row['game']]
            self.assertEqual(stage['status'],'HISTORY_CHECKED')
            self.assertIsNone(stage['target']);self.assertIs(stage['publication_asof_verified'],False)

    def test_future_date_rejected_by_both_real_helpers(self):
        for row in self.rows('C1'):
            self.assertEqual(row['loader']['reason'],'F01_FUTURE_OR_INTRADAY_UNPROVEN_DRAW')
            self.assertEqual(row['history_stage_games'][row['game']]['status'],'BLOCKED')
            self.assertEqual(row['agreement']['status'],'NOT_RUN_DEPENDENCY_BLOCKED')

    def test_repinning_accepts_actual_tainted_values_but_does_not_admit_asof(self):
        for row in self.rows('C2'):
            stage=row['history_stage_games'][row['game']]
            self.assertEqual(stage['rows'][0]['front'],audit.attack_value(row['game'])['front'])
            self.assertEqual(stage['rows'][0]['back'],audit.attack_value(row['game'])['back'])
            self.assertTrue(row['tainted_old_value_retained'])
            self.assertIn('NOT_DETECTION_SUCCESS',row['finding'])
            self.assertIs(stage['publication_asof_verified'],False)

    def test_changed_content_without_new_pin_is_rejected(self):
        for row in self.rows('C3'):
            self.assertEqual(row['loader']['reason'],'HISTORY_SHA_MISMATCH')
            self.assertEqual(row['agreement']['status'],'NOT_RUN_DEPENDENCY_BLOCKED')

    def test_forged_row_timestamp_and_boolean_do_not_grant_qualification(self):
        for row in self.rows('C4'):
            stage=row['history_stage_games'][row['game']]
            self.assertTrue(row['tainted_old_value_retained'])
            self.assertNotIn('tsa_verified',row['loader']['value'][0])
            self.assertIs(stage['publication_asof_verified'],False)

    def test_real_agreement_rejects_conflict_separately_from_offline_stage(self):
        for row in self.rows('C5'):
            self.assertEqual(row['agreement']['reason'],'OFFICIAL_SOURCE_CONFLICT')
            self.assertEqual(row['history_stage_games'][row['game']]['status'],'HISTORY_CHECKED')
            self.assertIn('OFFLINE_STAGE_TAINT_RETAINED_PROVENANCE_LIMITATION',row['finding'])

    def test_late_self_asserted_metadata_is_not_a_live_tsa_test(self):
        for row in self.rows('C6'):
            self.assertFalse(row['trusted_asof_admission'])
            self.assertEqual(row['network_calls'],0)
            self.assertEqual(row['finding'],'SELF_ASSERTED_LATE_METADATA_DOES_NOT_GRANT_ASOF')
        self.assertFalse(self.receipt['trusted_time_or_source_authenticity_tested'])

    def test_matching_recent_overlap_does_not_prove_older_value_provenance(self):
        for row in self.rows('C7'):
            self.assertEqual(len(row['capture_pair_mock_calls']),2)
            self.assertTrue(all(not c['actual_official_source'] for c in row['capture_pair_mock_calls']))
            self.assertEqual(len(row['agreement']['value']),2)
            self.assertEqual(len(row['history_stage_games'][row['game']]['rows']),4)
            self.assertTrue(row['tainted_old_value_retained'])

    def test_verify_reads_only_and_preserves_every_artifact(self):
        before={p.relative_to(self.output).as_posix():p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        with patch.object(audit.sources,'load_pinned',side_effect=AssertionError('reexecuted loader')), \
             patch.object(audit.sources,'agree',side_effect=AssertionError('reexecuted agree')), \
             patch.object(audit.workflow,'history_stage',side_effect=AssertionError('reexecuted stage')):
            result=audit.verify(self.output)
        after={p.relative_to(self.output).as_posix():p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(before,after);self.assertFalse(result['helpers_reexecuted'])


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.protocol=self.root/'protocol.json'
        self.protocol.write_bytes((audit.PACKAGE/'diagnostic-protocol.json').read_bytes())
        self.output=self.root/'run'

    def tearDown(self):self.temp.cleanup()

    def run_complete(self):return audit.execute(self.protocol,self.output)
    def reseal(self):overwrite(self.output/'SHA256.json',audit._artifact_files(self.output))
    def change_record(self,change):
        path=self.output/'cases/C2/SSQ/result.json';row=read(path);change(row);overwrite(path,row)
        receipt=read(self.output/'receipt.json')
        for item in receipt['results']:
            if (item['case'],item['game'])==('C2','SSQ'):item['result_sha256']=audit.digest(row)
        overwrite(self.output/'receipt.json',receipt);self.reseal()

    def test_existing_completed_output_cannot_be_retried(self):
        self.run_complete();before=(self.output/'receipt.json').read_bytes()
        with self.assertRaises(FileExistsError):self.run_complete()
        self.assertEqual(before,(self.output/'receipt.json').read_bytes())

    def test_unknown_interruption_is_retained_and_cannot_be_retried(self):
        with patch.object(audit,'_run_case',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.run_complete()
        self.assertTrue((self.output/'STARTED.json').is_file())
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_EXECUTION'):audit.verify(self.output)
        with self.assertRaises(FileExistsError):self.run_complete()

    def test_exception_receipt_stays_failed(self):
        with patch.object(audit,'_run_case',side_effect=RuntimeError('injected local exception')):
            receipt=self.run_complete()
        self.assertEqual(receipt['status'],'FAIL');self.assertEqual(receipt['case_count'],0)
        self.assertTrue((self.output/'EXECUTION_ERROR.json').is_file())
        with self.assertRaisesRegex(ValueError,'RECORDED_EXECUTION_NOT_PASS'):audit.verify(self.output)

    def test_source_drift_is_retained_as_failure_without_editing_real_source(self):
        before=audit.source_manifest();changed=copy.deepcopy(before)
        changed[next(iter(changed))]='0'*64
        with patch.object(audit,'source_manifest',side_effect=[before,changed]):receipt=self.run_complete()
        self.assertEqual(receipt['status'],'FAIL');self.assertFalse(receipt['source_unchanged'])
        with self.assertRaisesRegex(ValueError,'SOURCE_MANIFEST_DRIFT'):audit.verify(self.output)

    def test_unsealed_artifact_mutation_fails_hash_verification(self):
        self.run_complete();(self.output/'cases/C0/SSQ/attack.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_SHA'):audit.verify(self.output)

    def test_rehashed_false_summary_cannot_claim_improved_predictions(self):
        self.run_complete();receipt=read(self.output/'receipt.json')
        receipt['prediction_effect_improvement_tested']=True;overwrite(self.output/'receipt.json',receipt);self.reseal()
        with self.assertRaisesRegex(ValueError,'SUMMARY_CHANGED'):audit.verify(self.output)

    def test_rehashed_case_cannot_assert_taint_retention_without_actual_values(self):
        self.run_complete()
        def change(row):row['history_stage_games']['SSQ']['rows'][0]['front']=audit.fixture('SSQ')['draws'][0]['front']
        self.change_record(change)
        with self.assertRaisesRegex(ValueError,'CASE_ASSESSMENT'):audit.verify(self.output)

    def test_rehashed_case_cannot_grant_self_asserted_target(self):
        self.run_complete();self.change_record(lambda row:row['history_stage_games']['SSQ'].update(target='FAKE-TARGET'))
        with self.assertRaisesRegex(ValueError,'CASE_ASSESSMENT'):audit.verify(self.output)

    def test_companion_game_cannot_be_silently_promoted(self):
        self.run_complete();self.change_record(lambda row:row['history_stage_games']['DLT'].update(target='FAKE',publication_asof_verified=True))
        with self.assertRaisesRegex(ValueError,'CASE_ASSESSMENT'):audit.verify(self.output)

    def test_mock_source_receipt_cannot_claim_live_official_network_capture(self):
        self.run_complete();path=self.output/'cases/C7/SSQ/result.json';row=read(path)
        row['capture_pair_mock_calls'][0].update(actual_official_source=True,network_calls=999)
        overwrite(path,row);receipt=read(self.output/'receipt.json')
        next(r for r in receipt['results'] if (r['case'],r['game'])==('C7','SSQ'))['result_sha256']=audit.digest(row)
        overwrite(self.output/'receipt.json',receipt);self.reseal()
        with self.assertRaisesRegex(ValueError,'CASE_ASSESSMENT'):audit.verify(self.output)

    def test_loader_rejection_cannot_hide_a_promoted_metadata_flag(self):
        self.run_complete();path=self.output/'cases/C1/SSQ/result.json';row=read(path)
        row['trusted_asof_admission']=True;overwrite(path,row);receipt=read(self.output/'receipt.json')
        next(r for r in receipt['results'] if (r['case'],r['game'])==('C1','SSQ'))['result_sha256']=audit.digest(row)
        overwrite(self.output/'receipt.json',receipt);self.reseal()
        with self.assertRaisesRegex(ValueError,'CASE_ASSESSMENT'):audit.verify(self.output)

    def test_rehashed_start_metadata_cannot_be_relabeled_tsa_trusted(self):
        self.run_complete();path=self.output/'STARTED.json';started=read(path);started['time_trust']='TSA_VERIFIED'
        overwrite(path,started);self.reseal()
        with self.assertRaisesRegex(ValueError,'EXECUTION_START_METADATA'):audit.verify(self.output)

    def test_rehashed_config_pin_is_checked_against_fixed_fixture(self):
        self.run_complete();path=self.output/'cases/C2/SSQ/config.json';config=read(path)
        config['history']['SSQ']['sha256']='0'*64;overwrite(path,config);self.reseal()
        with self.assertRaisesRegex(ValueError,'FIXTURE_CONFIG_OR_COMPANION'):audit.verify(self.output)

    def test_rehashed_companion_fixture_is_not_ignored(self):
        self.run_complete();path=self.output/'cases/C2/SSQ/companion-clean.json';companion=read(path)
        companion['fixture_metadata']['synthetic']=False;overwrite(path,companion);self.reseal()
        with self.assertRaisesRegex(ValueError,'FIXTURE_CONFIG_OR_COMPANION'):audit.verify(self.output)

    def test_nested_sha_filename_cannot_escape_artifact_inventory(self):
        self.run_complete();path=self.output/'cases/C2/SSQ/SHA256.json';path.write_bytes(b'{}\n');self.reseal()
        self.assertIn('cases/C2/SSQ/SHA256.json',read(self.output/'SHA256.json'))
        with self.assertRaisesRegex(ValueError,'UNEXPECTED_ARTIFACT_LAYOUT'):audit.verify(self.output)

    def test_changed_original_protocol_is_rejected(self):
        self.run_complete();protocol=read(self.protocol);protocol['cases'][0]['expected']='changed after execution'
        overwrite(self.protocol,protocol)
        with self.assertRaisesRegex(ValueError,'REGISTERED_PROTOCOL_MISMATCH'):audit.verify(self.output)

    def test_runtime_identity_change_blocks_verification(self):
        self.run_complete();started=read(self.output/'STARTED.json');started['python']['version']='other runtime'
        overwrite(self.output/'STARTED.json',started);self.reseal()
        with self.assertRaisesRegex(ValueError,'PYTHON_RUNTIME_DRIFT'):audit.verify(self.output)

    def test_missing_final_receipt_stays_incomplete(self):
        self.run_complete();(self.output/'receipt.json').unlink()
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_EXECUTION'):audit.verify(self.output)

    def test_output_must_be_absolute_and_outside_repository(self):
        with self.assertRaisesRegex(ValueError,'ABSOLUTE_NEW_OUTPUT'):audit.execute(self.protocol,Path('relative'))
        with self.assertRaisesRegex(ValueError,'SEPARATE_FROM_SOURCE'):audit.execute(self.protocol,audit.ROOT/'forbidden-unit-output')
        self.assertFalse((audit.ROOT/'forbidden-unit-output').exists())

    def test_changed_case_rectangle_is_not_new_registration(self):
        protocol=read(self.protocol);protocol['cases'].pop();overwrite(self.protocol,protocol)
        with self.assertRaisesRegex(ValueError,'REGISTERED_PROTOCOL_MISMATCH'):self.run_complete()
        self.assertFalse(self.output.exists())

    def test_acceptance_rejects_relative_and_source_tree_outputs_before_writing(self):
        with self.assertRaisesRegex(ValueError,'ABSOLUTE_OUTPUT_REQUIRED'):acceptance.main(['--output','relative'])
        forbidden=audit.PACKAGE/'forbidden-unit-receipt'
        with self.assertRaisesRegex(ValueError,'SEPARATE_FROM_SOURCE'):acceptance.main(['--output',str(forbidden)])
        self.assertFalse(forbidden.exists())

    def test_acceptance_timeout_keeps_partial_log_and_failed_receipt(self):
        out=self.root/'timed-out-tests'
        failure=subprocess.TimeoutExpired('unittest',120,output=b'partial stdout\n',stderr=b'partial stderr\n')
        real_run=subprocess.run
        def timeout_only_unittest(cmd,*args,**kwargs):
            if isinstance(cmd,list) and cmd[1:3]==['-m','unittest']:raise failure
            return real_run(cmd,*args,**kwargs)
        with patch.object(acceptance.subprocess,'run',side_effect=timeout_only_unittest):code=acceptance.main(['--output',str(out)])
        self.assertEqual(code,1);receipt=read(out/'acceptance.json')
        self.assertEqual(receipt['status'],'FAIL');self.assertTrue(receipt['timed_out'])
        self.assertIn('partial stdout',(out/'tests.log').read_text());self.assertIn('partial stderr',(out/'tests.log').read_text())


if __name__=='__main__':unittest.main()
