"""Independent finite arithmetic checks; no old lottery data."""
from fractions import Fraction
import math
import unittest
from research.ssq_dlt_d2_negative_audit.statistics import binomial_upper,holm,permutation_check,legal,rescore_family

class StatisticsTests(unittest.TestCase):
    def test_small_exact_tails_against_rational_enumeration(self):
        for n in range(1,12):
            for hits in range(n+1):
                p=Fraction(2,7)
                expected=sum((Fraction(math.comb(n,i))*p**i*(1-p)**(n-i) for i in range(hits,n+1)),Fraction(0))
                self.assertAlmostEqual(binomial_upper(hits,n,p),float(expected),places=14)
    def test_original_tail_is_retained(self):
        self.assertAlmostEqual(binomial_upper(69,2880,Fraction(10,595)),.002845112172280603,places=12)
    def test_invalid_tails(self):
        for args in ((True,10,Fraction(1,2)),(-1,10,Fraction(1,2)),(2,1,Fraction(1,2)),(1,10,.5),(1,10,Fraction(0))):
            with self.assertRaises(ValueError):binomial_upper(*args)
    def test_holm_stepdown_and_ties(self):
        self.assertEqual(holm({'a':.01,'b':.04,'c':.05}),{'a':.03,'b':.08,'c':.08})
        self.assertEqual(holm({'b':.01,'a':.01}),{'a':.02,'b':.02})
    def test_holm_invalid(self):
        for value in ({},{'a':float('nan')},{'a':-1},{'a':True}):
            with self.assertRaises(ValueError):holm(value)
    def test_exhaustive_all_latent_sets(self):
        self.assertEqual(permutation_check(5,2)['mappings'],1200)
        self.assertEqual(permutation_check()['mappings'],14400)
    def test_exhaustive_bound_is_not_silently_expanded(self):
        with self.assertRaises(ValueError):permutation_check(7,3)
    def test_legality_rejects_duplicates_bool_and_range(self):
        for nums in ([1,1],[True,2],[0,2],[1,36],[1]):
            with self.assertRaises(ValueError):legal(nums,2,35)
    def test_missing_family_rejected(self):
        with self.assertRaises(ValueError):rescore_family(dict(periods=[],summaries=[]))
    def test_future_or_duplicate_period_rejected_before_tails(self):
        row=dict(scenario='FAIR',game='DLT',draw_front=[1,2,3,4,5],replication=0,index=240,training_end=240)
        with self.assertRaisesRegex(ValueError,'BOUNDARY'):rescore_family(dict(periods=[row],summaries=[]))
