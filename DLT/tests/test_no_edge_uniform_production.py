from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from glp.domain import Draw, Ranking
from glp.engine import make_prediction


def fake_complete_space(_draws, area, _enabled_models=None, *, descending=False):
    maximum, pick = ((35, 5) if area == "front" else (12, 2))
    order = list(range(1, maximum + 1))
    if descending:
        order.reverse()
    return Ranking(numbers=sorted(order[:pick]), scores={
        number: float(maximum - index) for index, number in enumerate(order)
    })


class NoEdgeUniformProductionRegression(unittest.TestCase):
    def setUp(self):
        self.draws = [Draw(
            issue="26113", draw_date="2026-10-07",
            front=(1, 2, 3, 4, 5), back=(1, 2),
        )] * 240
        self.canonical_hash = "f" * 64

    def predict_with_research(self, *, descending=False, court=None):
        with patch("glp.engine.score_complete_space", side_effect=lambda draws, area, enabled_models=None:
                   fake_complete_space(draws, area, enabled_models, descending=descending)):
            return make_prediction(self.draws, self.canonical_hash, court)

    def test_no_edge_outputs_do_not_depend_on_research_ranking(self):
        first, first_trace = self.predict_with_research()
        opposite, opposite_trace = self.predict_with_research(descending=True)
        self.assertEqual(first_trace["production_weights"],
                         {"uniform_baseline": 1.0, "research_ensemble": 0.0})
        self.assertEqual(opposite_trace["production_weights"],
                         {"uniform_baseline": 1.0, "research_ensemble": 0.0})
        self.assertEqual(first.edge_state, "NO_EDGE")
        self.assertEqual(first.dan_state, "NULL_DAN")
        # This is the key adversarial contract: a production rho=0 output must NOT
        # change when only the speculative research rankings are swapped.
        self.assertEqual(first.front, opposite.front)
        self.assertEqual(first.back, opposite.back)
        self.assertNotEqual(first.front_ranking, opposite.front_ranking)
        self.assertNotEqual(first.back_ranking, opposite.back_ranking)

    def test_untrusted_edge_claim_remains_uniform(self):
        untrusted = {
            "edge_state": "EDGE_PROVEN", "edge_gate": "PASS",
            "scientific_gate": "FAIL", "software_verdict": "PASS",
            "dan_firewall": {"decision": "CERTIFIED_DAN"},
        }
        _, trace = self.predict_with_research(court=untrusted)
        self.assertEqual(trace["production_weights"]["research_ensemble"], 0.0)

    def test_uniform_numbers_legal_and_repeatable(self):
        first, trace = self.predict_with_research()
        repeat, _ = self.predict_with_research()
        self.assertEqual(first.front, repeat.front)
        self.assertEqual(first.back, repeat.back)
        self.assertEqual(trace["production_weights"]["uniform_baseline"], 1.0)
        self.assertEqual(len(first.front), 5)
        self.assertEqual(len(set(first.front)), 5)
        self.assertEqual(first.front, sorted(first.front))
        self.assertTrue(all(1 <= n <= 35 for n in first.front))
        self.assertEqual(len(first.back), 2)
        self.assertEqual(len(set(first.back)), 2)
        self.assertEqual(first.back, sorted(first.back))
        self.assertTrue(all(1 <= n <= 12 for n in first.back))

    def test_strong_evidence_requires_all_scientific_gates(self):
        proven = {
            "scientific_gate": "PASS", "software_verdict": "PASS",
            "edge_gate": "PASS", "edge_state": "EDGE_PROVEN",
            "dan_firewall": {"decision": "CERTIFIED_DAN"},
            "validated_components": ["simple_frequency"],
        }
        pred, trace = self.predict_with_research(court=proven)
        self.assertEqual(trace["production_weights"]["research_ensemble"], 1.0)
        self.assertEqual(pred.edge_state, "EDGE_PROVEN")
        self.assertEqual(pred.dan_state, "CERTIFIED_DAN")
        self.assertEqual(pred.front, [1, 2, 3, 4, 5])
        self.assertEqual(pred.back, [1, 2])


if __name__ == "__main__":
    unittest.main()
