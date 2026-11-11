from __future__ import annotations

from pathlib import Path
import sys

from head_intelligence.engine import APP_VERSION, InformationEngine
from head_intelligence.software_update import launch_independent_updater


class InformationService:
    """Application boundary consumed by the UI. UI must not implement domain logic."""

    def __init__(self, engine: InformationEngine | None = None):
        self.engine = engine or InformationEngine()

    def update(self) -> dict:
        return self.engine.one_click_update().to_dict()

    def repair(self) -> dict:
        from head_intelligence.repair import repair_data
        return repair_data(self.engine, main_exe=Path(sys.executable))

    def software_update(self) -> dict:
        return launch_independent_updater(data_root=self.engine.data_dir, current_version=APP_VERSION)

    def current_judgment(self) -> dict | None:
        return self.engine.load_latest_snapshot()

    def advanced_analysis(self) -> dict:
        snapshot=self.engine.load_latest_snapshot()
        return {
            "health": self.engine.health_check(),
            "business_dimensions":["source_authority","freshness","deduplication","topic","corroboration","decision_relevance"],
            "source_count":len(self.engine.sources),
            "snapshot": snapshot,
        }

    def self_test(self) -> dict:
        return self.engine.self_test()

    def network_smoke_test(self) -> dict:
        report = self.engine.one_click_update(limit_per_source=5)
        return report.to_dict()
