"""Regression cases reproduced during independent review of PR #472."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from research import ssqdlt_research_ledger_audit as audit
from test_ssqdlt_research_ledger_audit import forecast, tick, fake_api, write_json


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       stderr=subprocess.PIPE).decode().strip()

    def init(self):
        self.git('init', '-q')
        self.git('config', 'user.name', 'Audit test')
        self.git('config', 'user.email', 'audit@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        p = write_json(self.root, 'research/forecasts/SSQ-2026130.json', forecast())
        p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
        self.git('add', '.')
        self.git('commit', '-qm', 'original')

    def merge_setup(self):
        self.init()
        write_json(self.root, 'research/forecasts/DLT-26130.json', forecast('DLT', 26130))
        self.git('add', '.')
        self.git('commit', '-qm', 'second original')
        self.git('branch', 'side')
        (self.root / 'main.txt').write_text('main')
        self.git('add', '.')
        self.git('commit', '-qm', 'main unrelated')
        main = self.git('branch', '--show-current')
        self.git('checkout', '-q', 'side')
        (self.root / 'side.txt').write_text('side')
        self.git('add', '.')
        self.git('commit', '-qm', 'side unrelated')
        self.git('checkout', '-q', main)
        self.git('merge', '--no-ff', '--no-commit', 'side')

    def test_merge_cannot_rehash_original_forecast(self):
        self.merge_setup()
        value = forecast()
        value['prediction']['front'] = [1, 2, 3, 4, 5, 7]
        value['content_sha256'] = hashlib.sha256(json.dumps(
            {k:v for k,v in value.items() if k != 'content_sha256'},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        write_json(self.root, 'research/forecasts/SSQ-2026130.json', value)
        self.git('add', '.')
        self.git('commit', '-qm', 'merge hides changed forecast')
        with self.assertRaisesRegex(audit.GateError, 'NON_APPEND'):
            audit.validate_git_append_only(self.root)

    def test_merge_cannot_delete_original_receipt(self):
        self.merge_setup()
        self.git('rm', 'research/forecasts/DLT-26130.json')
        self.git('add', '.')
        self.git('commit', '-qm', 'merge hides deletion')
        with self.assertRaisesRegex(audit.GateError, 'NON_APPEND'):
            audit.validate_git_append_only(self.root)

    def test_clean_git_status_does_not_certify_crlf_changed_bytes(self):
        self.init()
        self.git('config', 'core.autocrlf', 'true')
        p = self.root / 'research/forecasts/SSQ-2026130.json'
        p.unlink()
        self.git('checkout', '--', 'research/forecasts/SSQ-2026130.json')
        self.assertIn(b'\r\n', p.read_bytes())
        self.assertEqual(self.git('status', '--porcelain'), '')
        with self.assertRaisesRegex(audit.GateError, 'GIT_BLOB_BYTES'):
            audit.validate_git_append_only(self.root)

    def test_nested_forecast_cannot_escape_pinned_replay_roster(self):
        write_json(self.root, 'research/forecasts/nested/SSQ-2026130.json', forecast())
        with self.assertRaisesRegex(audit.GateError, 'NONCANONICAL'):
            audit.scan_ledger(self.root)

    def fake_score(self, nested=False):
        doc = forecast()
        write_json(self.root, 'research/forecasts/SSQ-2026130.json', doc)
        h = hashlib.sha256(b'not a lottery result').hexdigest()
        for channel in ('issuer-primary', 'issuer-secondary'):
            write_json(self.root, f'research/raw/SSQ/{channel}/{h}.json', {
                'schema':'SSQDLT_SOURCE_RAW_BYTES_V1', 'game':'SSQ',
                'source_id':channel, 'claimed_url':audit.SOURCES['SSQ'][channel],
                'raw_sha256':h, 'size_bytes':20,
                'raw_base64':base64.b64encode(b'not a lottery result').decode(),
                'origin_authenticity':'NOT_INDEPENDENTLY_PROVEN'})
        path = 'research/scores/' + ('nested/' if nested else '') + 'SSQ-2026130.json'
        write_json(self.root, path, {
            'schema':audit.SCORE_SCHEMA, 'game':'SSQ', 'issue':2026130,
            'formal_A':0, 'edge':'NO_EDGE',
            'original_prediction_ledger_record':doc['content_sha256'],
            'issuer_primary_html_sha256':h, 'issuer_second_html_sha256':h,
            'scoring':{'research_full_hit':1,'research_d2_hit':1,
                       'research_null_full_hit':0,'research_null_d2_hit':0}})

    def test_nested_score_cannot_be_counted_while_replayer_skips_it(self):
        self.fake_score(nested=True)
        with self.assertRaisesRegex(audit.GateError, 'NONCANONICAL'):
            audit.overall_report(self.root)

    def test_score_bits_cannot_pass_without_pinned_raw_replay(self):
        self.fake_score()
        with self.assertRaisesRegex(audit.GateError, 'SCORE_REPLAY_REQUIRED'):
            audit.overall_report(self.root)

    def test_replay_roster_disagreement_blocks_acceptance(self):
        write_json(self.root, 'research/forecasts/SSQ-2026130.json', forecast())
        with self.assertRaisesRegex(audit.GateError, 'REPLAY'):
            audit.scan_ledger(self.root, score_replayer=lambda: {
                'status':'PASS_RESEARCH_REPLAY_NOT_FORMAL', 'formal_A':0,
                'edge':'NO_EDGE', 'forecast_issues':0, 'scored_issues':0})

    def test_retry_receipt_is_distinct_and_old_receipt_stays_identical(self):
        from research.ssqdlt_research_tick import save_tick_attempt
        old = write_json(self.root, 'research/ticks/43071336351.json', tick())
        before = old.read_bytes()
        newer = tick(); newer['github_run_attempt'] = '2'
        path = save_tick_attempt(self.root, newer)
        self.assertEqual(path.name, '43071336351-attempt-2.json')
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(audit.scan_ledger(self.root)['tick_count'], 2)
        self.assertEqual(save_tick_attempt(self.root, newer), path)
        altered = deepcopy(newer); altered['report']['paid_model_calls'] = 1
        with self.assertRaises((audit.GateError, ValueError, FileExistsError)):
            save_tick_attempt(self.root, altered)

    def test_two_attempts_do_not_become_two_scheduled_triggers(self):
        first = tick('123456', 'schedule')
        second = deepcopy(first); second['github_run_attempt'] = '2'
        r = audit.verify_actions_ticks([first,second],
            lambda rid, attempt: fake_api(rid,'schedule',attempt=attempt))
        self.assertEqual(r['verified_schedule_runs'], 1)
        self.assertEqual(r['schedule_two_trigger_gate'], 'UNVERIFIED')

    def test_failed_attempt_kept_but_not_counted_as_scheduler_success(self):
        first = tick('123456', 'schedule')
        second = deepcopy(first); second['github_run_attempt'] = '2'
        r = audit.verify_actions_ticks([first,second], lambda rid, attempt:
            fake_api(rid,'schedule',attempt=attempt,
                     conclusion='failure' if attempt == 1 else 'success'))
        self.assertEqual(r['verified_schedule_runs'], 1)
        self.assertEqual(r['failed_attempt_count'], 1)
        self.assertEqual(len(r['actions_evidence']), 2)

    def test_attempt_lookup_uses_immutable_endpoint_without_requiring_private_token(self):
        class Response(io.BytesIO):
            status = 200
        def reply(request, timeout):
            self.assertEqual(request.full_url,
                'https://api.github.com/repos/douluo511/Geometry-Lotto-Pro/actions/runs/123456/attempts/1')
            self.assertIsNone(request.get_header('Authorization'))
            return Response(json.dumps(fake_api('123456','schedule')).encode())
        with patch.dict(os.environ, {}, clear=True), patch.object(audit.urllib.request, 'urlopen', reply):
            got = audit._fetch_github_run('123456', 1)
        self.assertEqual(got['run_attempt'], 1)

    def test_pinned_replay_executes_commit_bytes_despite_changed_checkout(self):
        self.init()
        module = self.root / 'research/inverse_formula/rolling_research.py'
        module.parent.mkdir(parents=True)
        module.write_text("def verify_saved_research_ledger(root):\n    return {'origin': 'committed'}\n")
        self.git('add', '.')
        self.git('commit', '-qm', 'trusted scorer')
        trusted = self.git('rev-parse', 'HEAD')
        module.write_text("raise RuntimeError('MUTABLE CHECKOUT EXECUTED')\n")
        with patch.object(audit, 'PINNED_SCORER_SHA', trusted):
            self.assertEqual(audit.replay_pinned_scores(self.root, self.root),
                             {'origin': 'committed'})

    def test_failed_flush_leaves_no_published_attempt_and_retry_recovers(self):
        from research.ssqdlt_research_tick import save_tick_attempt
        with patch('research.ssqdlt_research_tick.os.fsync', side_effect=OSError('lost flush')):
            with self.assertRaises(OSError):
                save_tick_attempt(self.root, tick())
        self.assertEqual(list((self.root / 'research/ticks').glob('*.json')), [])
        self.assertTrue(save_tick_attempt(self.root, tick()).is_file())

    def test_concurrent_same_attempt_publishes_only_one_complete_receipt(self):
        from research.ssqdlt_research_tick import save_tick_attempt
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: save_tick_attempt(self.root, tick()), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(audit.scan_ledger(self.root)['tick_count'], 1)


if __name__ == '__main__':
    unittest.main()
