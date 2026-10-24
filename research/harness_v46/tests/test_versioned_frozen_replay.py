"""Native isolated A->B replay; all draws/outcomes are invented SHADOW data."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from research.harness_v46 import closed_loop


WORKER = r'''
import json, sys
from datetime import datetime, timezone
from pathlib import Path
from research.harness_v46 import closed_loop, core
from research.harness_v46.tests.test_core import fixture
from research.harness_v46.tests.test_observed_snapshot import observed_fixture
root, operation, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
make = observed_fixture if mode == 'observed' else fixture
before = datetime(2026,10,20,8,tzinfo=timezone.utc)
after = datetime(2026,10,23,15,tzinfo=timezone.utc)
def outcome(s):
    return dict(lottery=s['lottery'], issue=s['target_issue'],
                front=s['draws'][-2]['front'], back=s['draws'][-2]['back'],
                drawn_at=s['target_draw_at'])
if operation == 'read':
    # A version-bound read must not invoke today's model/scorer after upgrade.
    def forbidden(*a, **k): raise AssertionError('CURRENT_CORE_USED_FOR_OLD_CARD')
    core.forecast = core.score = forbidden
    core.validate_study_snapshot = forbidden
reports = {}
for game in ('SSQ', 'DLT'):
    ws = root / game
    s = make(game)
    if operation == 'freeze':
        closed_loop.advance_game_workspace(ws, snapshot=s, observed_at=before)
        p = ws / 'outcomes_by_game' / game
        p.mkdir(parents=True)
        (p/(s['target_issue']+'.json')).write_text(json.dumps(outcome(s)),encoding='utf-8')
    reports[game] = closed_loop.advance_game_workspace(ws, game=game, observed_at=after)
if mode != 'observed':
    ws = root / 'dual'
    if operation == 'freeze':
        ss = {g: make(g) for g in ('SSQ','DLT')}
        frozen = closed_loop.advance_workspace(ws,snapshots=ss,observed_at=before)
        p=ws/'outcomes'; p.mkdir()
        (p/(frozen['run_ids'][0]+'.json')).write_text(
            json.dumps({g:outcome(s) for g,s in ss.items()}),encoding='utf-8')
    reports['dual'] = closed_loop.advance_workspace(ws,observed_at=after)
print(json.dumps(reports,sort_keys=True))
'''


class VersionedFrozenReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        package = Path(closed_loop.__file__).parent
        self.package = self.source / 'research' / 'harness_v46'
        shutil.copytree(package, self.package,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        repo = package.parents[1]
        for name in ('SSQ/SSQ/glp', 'DLT/src/glp'):
            shutil.copytree(repo / name, self.source / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.workspace = self.root / 'evidence'

    def run_worker(self, operation, mode='ordinary', ok=True):
        env = dict(os.environ, PYTHONPATH=str(self.source), PYTHONDONTWRITEBYTECODE='1')
        p = subprocess.run([sys.executable, '-B', '-c', WORKER,
                            str(self.workspace), operation, mode],
                           cwd=self.source, env=env, capture_output=True,
                           text=True, encoding='utf-8', timeout=60)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)
        self.assertNotEqual(p.returncode, 0)
        return p.stderr

    def bytes_of_evidence(self):
        return {str(p.relative_to(self.workspace)): p.read_bytes()
                for p in self.workspace.rglob('*') if p.is_file()}

    def upgrade(self):
        core = self.package / 'core.py'
        core.write_bytes(core.read_bytes() + b'\n# harmless installed version B\n')

    def test_old_six_arm_cards_and_legacy_scores_survive_real_core_upgrade(self):
        original = self.run_worker('freeze')
        evidence = self.bytes_of_evidence()
        self.upgrade()
        replayed = self.run_worker('read')
        self.assertEqual(replayed, original)
        self.assertEqual(self.bytes_of_evidence(), evidence)
        for game in ('SSQ', 'DLT'):
            self.assertEqual(len(replayed[game]['frozen_cards']), 6)
            self.assertEqual(replayed[game]['formal_A'], 0)

    def test_exact_crlf_and_lf_historical_identities_are_both_preserved(self):
        core = self.package / 'core.py'
        lf = core.read_bytes().replace(b'\r\n', b'\n')
        for source in (lf, lf.replace(b'\n', b'\r\n')):
            with self.subTest(sha=hashlib.sha256(source).hexdigest()):
                self.workspace = self.root / hashlib.sha256(source).hexdigest()
                core.write_bytes(source)
                original = self.run_worker('freeze')
                evidence = self.bytes_of_evidence()
                self.upgrade()
                self.assertEqual(self.run_worker('read'), original)
                self.assertEqual(self.bytes_of_evidence(), evidence)

    def test_observed_snapshot_dependency_is_pinned_with_old_core(self):
        original = self.run_worker('freeze', 'observed')
        evidence = self.bytes_of_evidence()
        self.upgrade()
        validator = self.package / 'observed_snapshot.py'
        validator.write_bytes(validator.read_bytes() +
                              b'\ndef validate_observed_snapshot(s):\n    raise AssertionError("UPGRADED_VALIDATOR_USED")\n')
        self.assertEqual(self.run_worker('read', 'observed'), original)
        self.assertEqual(self.bytes_of_evidence(), evidence)

    def test_missing_or_tampered_archive_fails_before_scoring(self):
        self.run_worker('freeze')
        self.upgrade()
        artifacts = sorted((self.package / 'model_versions').glob('core_*.source'))
        self.assertTrue(artifacts, 'trusted original source artifacts are absent')
        for artifact in artifacts:
            artifact.write_bytes(artifact.read_bytes() + b'\n# tamper\n')
        before = self.bytes_of_evidence()
        self.assertIn('REPLAY_SOURCE_ARTIFACT_HASH_MISMATCH', self.run_worker('read', ok=False))
        self.assertEqual(self.bytes_of_evidence(), before)
        for artifact in artifacts:
            artifact.unlink()
        self.assertIn('REPLAY_SOURCE_ARTIFACT_MISSING', self.run_worker('read', ok=False))

    def test_unknown_or_mixed_rehashed_source_cannot_select_arbitrary_code(self):
        self.run_worker('freeze')
        self.upgrade()
        db = self.workspace / 'SSQ' / 'ledger.sqlite3'
        with closing(sqlite3.connect(db)) as c:
            c.execute('DROP TRIGGER protect_game_predictions_update')
            rows = c.execute('SELECT model,payload FROM game_predictions').fetchall()
            for model, raw in rows:
                p = json.loads(raw)
                p['model_source_sha256'] = '0' * 64
                payload = json.dumps(p, ensure_ascii=False, sort_keys=True,separators=(',',':'))
                c.execute('UPDATE game_predictions SET payload=?,prediction_sha256=? WHERE model=?',
                          (payload,hashlib.sha256(payload.encode()).hexdigest(),model))
            c.commit()
        before = self.bytes_of_evidence()
        self.assertIn('REPLAY_SOURCE_NOT_REGISTERED', self.run_worker('read', ok=False))
        self.assertEqual(self.bytes_of_evidence(), before)


if __name__ == '__main__':
    unittest.main()
