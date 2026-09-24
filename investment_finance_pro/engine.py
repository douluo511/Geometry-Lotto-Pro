from __future__ import annotations
import legacy_backend as legacy

class InvestmentEngine:
    def compute_metrics(self, rows):
        return legacy.compute_metrics(rows)

    def rank(self, metrics):
        return legacy.rank_research(metrics)

    def deterministic_self_test(self):
        return legacy.deterministic_self_test()
