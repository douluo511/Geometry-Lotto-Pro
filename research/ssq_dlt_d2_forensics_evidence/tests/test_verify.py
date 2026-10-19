"""Presentation-adapter regressions, using tiny synthetic evidence only."""
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from research.ssq_dlt_d2_forensics_evidence import verify as adapter
from research.ssq_dlt_v45.store import Store, canonical, digest, parse


PREFIX = '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>Audit</title><h1>Fixed title</h1>'
HEADER = '<tr><th>Model</th><th>Hits</th></tr>'
ROW_A = '<tr><td>R46-CBPAIR-SHRINK</td><td>11/240</td></tr>'
ROW_B = '<tr><td>R45-RANDOM-NULL</td><td>5/240</td></tr>'
PRE_A = '[{"game":"DLT","calibration":{"mse":0.02,"parts":[1,2],"ok":true}}]'
PRE_B = '[{"calibration":{"ok":true,"parts":[1,2],"mse":0.02},"game":"DLT"}]'


def report(rows=(ROW_A, ROW_B), pre=PRE_A):
    return PREFIX + '<table class="fixed">' + HEADER + ''.join(rows) + '</table><pre>' + pre + '</pre></html>'


class SemanticHTMLTests(unittest.TestCase):
    def test_only_whole_rows_and_nested_object_keys_may_reorder(self):
        check = adapter.assert_semantic_html_equal(report(), report((ROW_B, ROW_A), PRE_B))
        self.assertFalse(check['byte_identical'])
        self.assertEqual(check['data_rows'], 2)
        self.assertEqual(check['json_pre_blocks'], 1)

    def test_numeric_title_label_attribute_script_and_cell_changes_fail(self):
        baseline = report()
        changes = [baseline.replace('11/240', '12/240'),
                   baseline.replace('Fixed title', 'Changed title'),
                   baseline.replace('R45-RANDOM-NULL', 'R45-RANDOM-EDGE'),
                   baseline.replace('class="fixed"', 'class="other"'),
                   baseline.replace('lang="zh-Hant"', 'lang="en"'),
                   baseline.replace('</html>', '<script>alert(1)</script></html>'),
                   baseline.replace('<td>11/240</td>', '<td data-x="1">11/240</td>'),
                   baseline.replace('0.02', '0.03'),
                   baseline.replace('0.02', '0.020'),
                   baseline.replace('[1,2]', '[2,1]'),
                   baseline.replace('true', '1'),
                   baseline.replace('</title>', '</TITLE>'),
                   baseline.replace('<th>Model</th><th>Hits</th>', '<th>Hits</th><th>Model</th>')]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(adapter.EvidenceMismatch):
                adapter.assert_semantic_html_equal(baseline, changed)

    def test_duplicate_counts_missing_rows_and_cross_row_cell_swaps_fail(self):
        baseline = report((ROW_A, ROW_B, ROW_A))
        adapter.assert_semantic_html_equal(baseline, report((ROW_B, ROW_A, ROW_A), PRE_B))
        for changed in (report((ROW_A, ROW_B)), report((ROW_A, ROW_B, ROW_B)),
                        report((ROW_A.replace('11/240', '5/240'), ROW_B.replace('5/240', '11/240'), ROW_A))):
            with self.assertRaises(adapter.EvidenceMismatch):
                adapter.assert_semantic_html_equal(baseline, changed)

    def test_pre_array_order_duplicate_keys_nonfinite_and_nested_markup_fail(self):
        baseline = report()
        for changed in (report(pre=PRE_A.replace('[1,2]', '[2,1]')),
                        report(pre='{"x":1,"x":1}'), report(pre='{"x":NaN}'),
                        report(pre='<span>' + PRE_A + '</span>')):
            with self.assertRaises(adapter.EvidenceMismatch):
                adapter.assert_semantic_html_equal(baseline, changed)
        array = report(pre='[{"a":1},{"b":2}]')
        with self.assertRaises(adapter.EvidenceMismatch):
            adapter.assert_semantic_html_equal(array, report(pre='[{"b":2},{"a":1}]'))

    def test_existing_scripts_text_comments_and_structure_remain_fixed(self):
        baseline = report().replace('</html>', '<script>const a=1;</script><!--fixed--></html>')
        for changed in (baseline.replace('a=1', 'a=2'), baseline.replace('<!--fixed-->', '<!--other-->'),
                        baseline.replace('</table>', '</td></table>')):
            with self.assertRaises(adapter.EvidenceMismatch):
                adapter.assert_semantic_html_equal(baseline, changed)


class AdapterIntegrityTests(unittest.TestCase):
    def fixture(self, directory):
        directory.mkdir()
        result = {'html': report()}
        (directory / 'result.json').write_text(canonical(result), encoding='utf-8')
        saved = report((ROW_B, ROW_A), PRE_B)
        (directory / 'report.html').write_text(saved, encoding='utf-8')
        db = sqlite3.connect(directory / 'research.sqlite3')
        db.execute('CREATE TABLE events(kind,key,payload,sha256)')
        db.execute('INSERT INTO events VALUES(?,?,?,?)', ('test', 'one', canonical({'v': 1}), digest({'v': 1})))
        db.commit()
        db.close()
        fake = SimpleNamespace(parse=parse, canonical=canonical, Store=Store,
                               source_manifest=lambda: {'pinned.py': 'unchanged'},
                               render=lambda value: value['html'],
                               readonly_events=lambda _: (_ for _ in ()).throw(AssertionError('must use snapshot')))

        def native_verify(where):
            value = parse((Path(where) / 'result.json').read_bytes())
            if fake.render(value) != (Path(where) / 'report.html').read_text(encoding='utf-8'):
                raise ValueError('REPORT_RESULT_MISMATCH')
            events = fake.readonly_events(where)
            if events != [(1, 'test', 'one', {'v': 1})]:
                raise ValueError('EVENTS_MISMATCH')
            return {'status': 'PASS_NATIVE_TINY_FIXTURE', 'formal_A': 0, 'decision': 'NO_EDGE'}

        fake.verify = native_verify
        return fake

    def test_adapter_calls_original_verifier_on_immutable_copy_and_preserves_every_byte(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            study, receipt = root / 'study', root / 'receipt.json'
            fake = self.fixture(study)
            old_render, old_readonly = fake.render, fake.readonly_events
            before = adapter._input_manifest(study)
            answer = adapter.verify_study(study, receipt, protocol=fake)
            self.assertEqual(answer['native_report_check']['status'], 'FAIL_REPORT_RESULT_MISMATCH')
            self.assertTrue(answer['original_native_failure_retained'])
            self.assertEqual(answer['adapter_calls'], {'validated_render_calls': 1, 'immutable_ledger_reads': 1})
            self.assertEqual(answer['study_sha256_after'], before)
            self.assertIs(fake.render, old_render)
            self.assertIs(fake.readonly_events, old_readonly)
            self.assertTrue(receipt.is_file())
            self.assertEqual(json.loads(receipt.read_text(encoding='utf-8'))['decision'], 'NO_EDGE')
            with self.assertRaises(FileExistsError):
                adapter.verify_study(study, receipt, protocol=fake)

    def test_rejects_receipt_inside_study_and_nonempty_wal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            study = root / 'study'
            fake = self.fixture(study)
            with self.assertRaisesRegex(ValueError, 'OUTSIDE_FROZEN_STUDY'):
                adapter.verify_study(study, study / 'receipt.json', protocol=fake)
            (study / 'research.sqlite3-wal').write_bytes(b'not checkpointed')
            with self.assertRaisesRegex(adapter.EvidenceMismatch, 'UNCHECKPOINTED_WAL'):
                adapter.verify_study(study, root / 'receipt.json', protocol=fake)

    def test_adapter_restores_functions_on_failure_and_checks_candidate_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            study = root / 'study'
            fake = self.fixture(study)
            old_render, old_readonly = fake.render, fake.readonly_events
            value = parse((study / 'result.json').read_bytes())
            with self.assertRaisesRegex(adapter.EvidenceMismatch, 'RESULT_CHANGED'):
                with adapter.presentation_adapter(fake, study, study / 'research.sqlite3', value,
                                                   (study / 'report.html').read_text(encoding='utf-8')):
                    fake.render({'html': report().replace('11/240', '99/240')})
            self.assertIs(fake.render, old_render)
            self.assertIs(fake.readonly_events, old_readonly)

    def test_verifier_side_effects_cannot_receive_a_pass_receipt(self):
        for changed in ('study', 'source'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                study, receipt = root / 'study', root / 'receipt.json'
                fake = self.fixture(study)
                old_render, old_readonly, native = fake.render, fake.readonly_events, fake.verify

                def mutating_verifier(where):
                    result = native(where)
                    if changed == 'study':
                        (Path(where) / 'report.html').write_text('tampered', encoding='utf-8')
                    else:
                        fake.source_manifest = lambda: {'pinned.py': 'tampered'}
                    return result

                fake.verify = mutating_verifier
                with self.assertRaisesRegex(adapter.EvidenceMismatch, 'CHANGED_DURING_VERIFICATION'):
                    adapter.verify_study(study, receipt, protocol=fake)
                self.assertFalse(receipt.exists())
                self.assertIs(fake.render, old_render)
                self.assertIs(fake.readonly_events, old_readonly)


if __name__ == '__main__':
    unittest.main()
