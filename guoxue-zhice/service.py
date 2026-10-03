from __future__ import annotations

from pathlib import Path
from typing import Any

from core import APP_NAME, APP_VERSION, GoalEngine, MaintenanceEngine, ReviewEngine, Store, self_test
from net_client import NetClient
from software_update import launch_independent_updater, software_update_environment_status

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

    def refresh_knowledge(self) -> dict[str, Any]:
        """Refresh the knowledge corpus only; this is not a software update."""
        return self.maintenance.one_click_update()

    def one_click_update(self) -> dict[str, Any]:
        """Frozen UI contract: hand off software replacement to the independent Updater."""
        return launch_independent_updater(
            data_root=self.store.root,
            current_version=APP_VERSION,
        )

    def software_update_status(self, *, main_exe: Path) -> dict[str, Any]:
        return software_update_environment_status(
            main_exe=main_exe,
            current_version=APP_VERSION,
        )

    def one_click_repair(self) -> dict[str, Any]:
        return self.maintenance.one_click_repair()

def create_service(root: Path | None = None, net: NetClient | None = None) -> GuoxueService:
    return GuoxueService(Store(root), net=net)

__all__ = ["APP_NAME", "APP_VERSION", "GuoxueService", "create_service", "self_test"]
