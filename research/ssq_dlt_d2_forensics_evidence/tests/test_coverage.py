"""Coverage guard regressions: observed disagreement and honest completeness."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from research.ssq_dlt_v45.sources import agree
from research.ssq_dlt_d2_forensics_evidence import coverage

NOW=datetime(2026,10,19,tzinfo=timezone.utc)


def rows(game='SSQ', issues=None):
    issues=issues or (['2026117','2026118','2026119'] if game=='SSQ' else ['26116','26117','26118'])
    return [dict(game=game,issue=issue,draw_date=f'2026-10-{10+index:02}',
                 front=list(range(1,7 if game=='SSQ' else 6)),back=[1] if game=='SSQ' else [1,2])
            for index,issue in enumerate(issues)]


class CoverageTests(unittest.TestCase):
    def test_old_silently_removes_internal_issue_but_new_rejects_before_generation(self):
        a=rows(); b=[a[0],a[2]]
        self.assertEqual([r['issue'] for r in agree('SSQ',a,b)],['2026117','2026119'])
        generator=Mock(side_effect=AssertionError('must not generate'))
        with self.assertRaisesRegex(coverage.CoverageError,'INTERNAL_SOURCE_COVERAGE_DISAGREEMENT') as ctx:
            coverage.guarded_preview('SSQ',a,b,NOW,generator=generator)
        self.assertEqual(ctx.exception.details['left_only_within_shared_range'],['2026118'])
        generator.assert_not_called()

    def test_equal_sources_pass_only_observed_overlap_for_both_games(self):
        for game in ('SSQ','DLT'):
            with self.subTest(game=game):
                a=rows(game); before=deepcopy(a)
                accepted,evidence=coverage.strict_agree(game,a,deepcopy(a),NOW)
                self.assertEqual(accepted,a);self.assertEqual(a,before)
                self.assertEqual(evidence['status'],'PASS_OBSERVED_OVERLAP_ONLY')
                self.assertTrue(evidence['full_history_completeness'].startswith('BLOCKED'))
                self.assertFalse(evidence['publication_asof_verified'])
                self.assertEqual(evidence['formal_A'],0)

    def test_different_page_lengths_expose_discarded_prefix_in_both_directions(self):
        a=rows()
        for left,right,key in ((a,a[1:],'excluded_left_prefix'),(a[1:],a,'excluded_right_prefix')):
            with self.subTest(key=key):
                agreed,evidence=coverage.strict_agree('SSQ',left,right,NOW)
                self.assertEqual(agreed,a[1:])
                self.assertEqual(evidence[key],['2026117'])

    def test_internal_omissions_on_either_side_reject(self):
        a=rows();short=[a[0],a[2]]
        for left,right in ((a,short),(short,a)):
            with self.assertRaisesRegex(coverage.CoverageError,'INTERNAL_SOURCE_COVERAGE_DISAGREEMENT'):
                coverage.strict_agree('SSQ',left,right,NOW)

    def test_joint_observable_within_year_gap_is_blocked_before_generation(self):
        a=rows(); short=[a[0],a[2]]
        generator=Mock(side_effect=AssertionError('must not generate'))
        with self.assertRaisesRegex(ValueError,'INTRA_YEAR_ISSUE_GAP'):
            coverage.guarded_preview('SSQ',short,short,NOW,generator=generator)
        generator.assert_not_called()

    def test_latest_conflict_and_value_conflict_are_distinct(self):
        a=rows()
        with self.assertRaisesRegex(coverage.CoverageError,'LATEST_ISSUE_DISAGREEMENT'):
            coverage.strict_agree('SSQ',a,a[:-1],NOW)
        for field,value in (('front',[2,3,4,5,6,7]),('back',[2]),('draw_date','2026-10-13')):
            b=deepcopy(a);b[-1][field]=value
            with self.subTest(field=field), self.assertRaisesRegex(coverage.CoverageError,'OFFICIAL_SOURCE_CONFLICT'):
                coverage.strict_agree('SSQ',a,b,NOW)

    def test_duplicate_empty_future_and_illegal_numbers_fail_validation(self):
        a=rows();future=deepcopy(a);future[-1]['draw_date']='2026-10-20'
        illegal=deepcopy(a);illegal[-1]['front']=[1,1,2,3,4,5]
        for bad in ([],a+[a[0]],future,illegal):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                coverage.strict_agree('SSQ',a,bad,NOW)

    def test_cross_year_prefix_does_not_invent_final_year_issue(self):
        a=rows(issues=['2025151','2026001','2026002'])
        for row,day in zip(a,['2025-12-31','2026-01-04','2026-01-06']):row['draw_date']=day
        accepted,evidence=coverage.strict_agree('SSQ',a,a[1:],NOW)
        self.assertEqual([r['issue'] for r in accepted],['2026001','2026002'])
        self.assertEqual(evidence['excluded_left_prefix'],['2025151'])
        self.assertFalse(evidence['guessed_issue_numbers'])

    def test_game_label_wrong_width_and_year_are_not_normalized_away(self):
        a=rows()
        for field,value in (('game','DLT'),('issue','26117'),('issue','2025117')):
            bad=deepcopy(a);bad[0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                coverage.strict_agree('SSQ',bad,bad,NOW)

    def test_cross_year_joint_missing_final_issue_is_never_claimed_complete(self):
        a=rows(issues=['2025149','2026001','2026002'])
        for row,day in zip(a,['2025-12-20','2026-01-04','2026-01-06']):row['draw_date']=day
        _,evidence=coverage.strict_agree('SSQ',a,a,NOW)
        self.assertFalse(evidence['jointly_missing_cross_year_issues_detectable'])
        self.assertTrue(evidence['full_history_completeness'].startswith('BLOCKED'))

    def test_raw_sha_checked_before_parsing_and_no_forecast_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'raw.bin';path.write_bytes(b'not official bytes')
            with self.assertRaisesRegex(coverage.CoverageError,'RAW_SOURCE_SHA_MISMATCH'):
                coverage.load_raw_pair('SSQ',path,'0'*64,path,'0'*64,NOW)

    def test_explicit_guarded_preview_keeps_unassigned_and_zero_edge(self):
        a=rows();generator=Mock(return_value={'fixture':True})
        result=coverage.guarded_preview('SSQ',a,a,NOW,generator=generator)
        generator.assert_called_once_with('SSQ','UNASSIGNED',a)
        self.assertIsNone(result['target'])
        self.assertEqual(result['qualified_prospective_samples'],0)
        self.assertEqual(result['decision'],'NO_EDGE')


if __name__=='__main__':unittest.main()
