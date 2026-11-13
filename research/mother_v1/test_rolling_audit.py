"""Safety and determinism tests for full mother retrospective audit."""
import math
import unittest

from research.harness_v46 import core
from research.mother_v1 import rolling_audit
from research.mother_v1.mother import _one_regular
from research.mother_v1.registry import ALL_MODELS


class RollingAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.sha = rolling_audit.load_pinned()

    def test_registered_models_exactly_fourteen_plus_two_abstain(self):
        self.assertEqual(16, len(ALL_MODELS))
        self.assertEqual(14, len(rolling_audit.ACTIVE))
        self.assertEqual(2, len(rolling_audit.PHYSICAL))
        self.assertFalse(any(model.startswith("native_") for model in ALL_MODELS))

    def test_exact_historical_splits_and_fixed_hash(self):
        self.assertEqual("3d4399da45529ab458ae926dad682cf01a6a2c4af3e4780bd8bbee6df1c0792c",
                         core.digest(self.bundle))
        self.assertEqual(2079, len(self.bundle["SSQ"]))
        self.assertEqual(2938, len(self.bundle["DLT"]))
        for game in ("SSQ", "DLT"):
            n = rolling_audit.WINDOWS[game]
            self.assertTrue(len(self.bundle[game]) > 120+2*n)

    def test_every_production_ticket_and_d2_matches_mother_at_one_real_issue(self):
        for game in ("SSQ", "DLT"):
            rows = self.bundle[game]
            at = len(rows) - 1
            ctx = {"target_issue": rows[at]["issue"], "history": rows[:at]}
            for name in rolling_audit.ACTIVE:
                with self.subTest(game=game, name=name):
                    expected = _one_regular(ctx, game, name)
                    actual = rolling_audit.one_ticket(game, rows[:at], name, rows[at]["issue"])
                    self.assertEqual(expected["ticket"], {
                        "front":actual["front"], "back":actual["back"]})
                    self.assertEqual(expected["primary_d2"], actual["d2"])

    def test_no_leak_from_future_label(self):
        for game in ("SSQ", "DLT"):
            rows=self.bundle[game]
            i=120
            name="ewma"
            original=rolling_audit.one_ticket(game, rows[:i], name, rows[i]["issue"])
            # A later target label is never admitted via history[:i].
            future=list(rows)
            future[i] = {**rows[i], "front":list(reversed(rows[i]["front"]))}
            copy=rolling_audit.one_ticket(game, future[:i], name, rows[i]["issue"])
            self.assertEqual(original,copy)

    def test_random_theory_and_multiple_testing_bounds(self):
        for game in ("SSQ", "DLT"):
            r=core.RULES[game]
            fair=math.comb(r["front"],2)/math.comb(r["pool"],2)
            self.assertAlmostEqual(r["d2"],fair,places=12)
            kill_safe=math.comb(r["pool"]-r["front"],3)/math.comb(r["pool"],3)
            self.assertGreater(kill_safe,0)
            self.assertLess(kill_safe,1)
        self.assertAlmostEqual(.5,rolling_audit._paired_p(1,0))
        self.assertEqual(1.,rolling_audit._paired_p(0,0))
        self.assertEqual(1.,rolling_audit._tail(0,30,.05))
        self.assertTrue(all(0 <= v <= 1 for v in rolling_audit._holms({"a":.02,"b":.8}).values()))

    def test_fixed_manual_future_inputs_and_physical_abstention(self):
        from research.mother_v1 import historical_example
        future = historical_example.build()
        self.assertEqual(("2026131","26130"),
                         (future["SSQ"]["target_issue"],future["DLT"]["target_issue"]))
        for game in ("SSQ","DLT"):
            context=future[game]
            for model in rolling_audit.ACTIVE:
                candidate=rolling_audit.one_ticket(game,context["history"],model,
                                                   context["target_issue"])
                self.assertEqual(len(candidate["d2"]),2)
                if candidate["kill3"] is not None:
                    self.assertEqual(len(candidate["kill3"]),3)
                    self.assertFalse(set(candidate["front"]).intersection(candidate["kill3"]))


if __name__=="__main__":
    unittest.main()
