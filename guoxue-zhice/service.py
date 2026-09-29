from __future__ import annotations

from pathlib import Path
from typing import Any

from core import APP_NAME, APP_VERSION, GoalEngine, MaintenanceEngine, ReviewEngine, Store, self_test
from net_client import NetClient

class GuoxueService:
    def __init__(self, store: Store, net: NetClient | None = None):
        self.store = store
        self.goal = GoalEngine(store)
        self.review = ReviewEngine(store)
        self.maintenance = MaintenanceEngine(store, net=net)

    def analyze_goal(self, goal: str) -> dict[str, Any]:
        return self.goal.analyze(goal)

    def save_review(self, goal: str, action: str, result: str, lesson: str) -> dict[str, Any]:
        return self.review.save(goal, action, result, lesson)

    def recent_reviews(self, limit: int = 5):
        return self.review.recent(limit)

    def stats(self) -> dict[str, Any]:
        return self.goal.stats()

    def one_click_update(self) -> dict[str, Any]:
        return self.maintenance.one_click_update()

    def one_click_repair(self) -> dict[str, Any]:
        return self.maintenance.one_click_repair()

def create_service(root: Path | None = None, net: NetClient | None = None) -> GuoxueService:
    return GuoxueService(Store(root), net=net)

__all__ = ["APP_NAME", "APP_VERSION", "GuoxueService", "create_service", "self_test"]
