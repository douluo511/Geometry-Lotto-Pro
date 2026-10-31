"""TEST_ONLY original frozen roster statistics, never formal draws."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from research.harness_v46 import closed_loop, core
from research.harness_v46.tests.test_core import fixture

class IndependentGameStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws=Path(self.tmp.name)/'workspace'

    def freeze(self,game,issue='29999'):
        snapshot=fixture(game);snapshot['target_issue']=issue
        clock='2026-10-20T08:00:00+00:00'
        if issue=='30000':
            snapshot.update(as_of='2026-10-24T00:00:00+00:00',
                            sales_cutoff='2026-10-25T12:00:00+08:00',
                            target_draw_at='2026-10-25T21:00:00+08:00')
            clock='2026-10-24T08:00:00+00:00'
        frozen=closed_loop.advance_game_workspace(self.ws,snapshot=snapshot,
                    observed_at=datetime.fromisoformat(clock))
        return snapshot,frozen

    def publish_hot_win(self,snapshot,frozen):
        cards={p['model']:p for p in frozen['frozen_cards']}
        hot=set(cards['hot60']['primary_d2']);null=set(cards['random_null']['primary_d2'])
        forbidden=next(iter(null-hot))
        rule=core.RULES[snapshot['lottery']]
        front=sorted(hot|set([n for n in range(1,rule['pool']+1)
                             if n not in hot and n!=forbidden][:rule['front']-2]))
        # Independent set containment establishes literal H=1,R=0.
        self.assertTrue(hot.issubset(front));self.assertFalse(null.issubset(front))
        result={'lottery':snapshot['lottery'],'issue':snapshot['target_issue'],
                'front':front,'back':list(range(1,rule['back']+1)),
                'drawn_at':snapshot['target_draw_at']}
        path=self.ws/'outcomes_by_game'/snapshot['lottery']/(snapshot['target_issue']+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result),encoding='utf-8')

    def score(self,game):
        return closed_loop.advance_game_workspace(self.ws,game=game,
                    observed_at=datetime.fromisoformat('2026-10-26T08:00:00+00:00'))

    def require_statistics(self,report):
        self.assertTrue('local_d2_statistics' in report,'V47G replay must reach existing full statistics')
        return report['local_d2_statistics']

    def test_each_game_known_win_has_exact_counts_ci_paired_delta_and_full_holm_family(self):
        for game in ('SSQ','DLT'):
            with self.subTest(game=game):
                snap,frozen=self.freeze(game)
                self.publish_hot_win(snap,frozen)
                report=self.score(game);summary=self.require_statistics(report)
                self.assertEqual(summary['scope'],'THIS_GAME_ONLY')
                self.assertEqual(summary['lottery'],game)
                self.assertEqual(summary['frozen_issues_at_read'],['29999'])
                self.assertEqual(summary['formal_A'],0)
                self.assertEqual(summary['decision'],'NO_EDGE')
                analysis=summary['statistical_analysis']
                self.assertEqual(analysis['family_size'],12)
                self.assertEqual({r['hypothesis_id'] for r in analysis['results']},
                    {'V47-'+g+'-'+m for g in ('SSQ','DLT') for m in core.MODELS})
                hot=next(r for r in analysis['results'] if r['lottery']==game and r['model']=='hot60')
                self.assertEqual((hot['draws'],hot['hits'],hot['paired_wins_vs_null'],
                                  hot['paired_losses_vs_null']),(1,1,1,0))
                self.assertEqual(hot['paired_rate_difference_vs_null'],1.0)
                self.assertAlmostEqual(hot['d2_rate_exact_ci95'][0],0.025,places=10)
                self.assertEqual(hot['d2_rate_exact_ci95'][1],1.0)
                self.assertEqual(hot['p_exact_paired_vs_null'],0.5)
                self.assertEqual(hot['holm_adjusted_p_unverified_family'],1.0)
                self.assertAlmostEqual(hot['paired_rate_difference_ci95_conservative'][0],-.975,places=10)
                self.assertEqual(hot['paired_rate_difference_ci95_conservative'][1],1.0)
                other=next(g for g in ('SSQ','DLT') if g!=game)
                self.assertEqual(summary['other_game_scope'][other],
                                 'NOT_INCLUDED_REAL_DENOMINATOR_NOT_VERIFIED')
                for row in analysis['results']:
                    if row['lottery']==other:
                        self.assertTrue(row['report_placeholder_only'])
                        self.assertIsNone(row['d2_rate'])
                        self.assertEqual(row['p_joint_intersection_union'],1.0)

    def test_retry_keeps_original_db_and_score_receipt_bytes(self):
        snap,frozen=self.freeze('SSQ');self.publish_hot_win(snap,frozen)
        first=self.score('SSQ');self.require_statistics(first)
        before={p:p.read_bytes() for p in self.ws.rglob('*') if p.is_file()}
        second=self.score('SSQ')
        self.assertEqual(second['local_d2_statistics'],first['local_d2_statistics'])
        self.assertEqual({p:p.read_bytes() for p in self.ws.rglob('*') if p.is_file()},before)

    def test_pending_issue_blocks_summary_then_two_original_issues_are_counted(self):
        a,f=self.freeze('SSQ');self.publish_hot_win(a,f);self.score('SSQ')
        b,f2=self.freeze('SSQ','30000')
        pending=self.score('SSQ')
        self.assertEqual(pending['pending_issues'],['30000'])
        self.assertNotIn('local_d2_statistics',pending)
        self.publish_hot_win(b,f2)
        full=self.require_statistics(self.score('SSQ'))
        self.assertEqual(full['frozen_issues_at_read'],['29999','30000'])
        hot=next(r for r in full['statistical_analysis']['results']
                 if r['lottery']=='SSQ' and r['model']=='hot60')
        self.assertEqual((hot['draws'],hot['hits'],hot['paired_wins_vs_null']),(2,2,2))

if __name__=='__main__': unittest.main()

