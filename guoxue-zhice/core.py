"""Backward-compatible facade; production UI routes through Service."""
from domain import APP_NAME, APP_VERSION, validate_knowledge
from engine import GoalEngine, ReviewEngine
from service import GuoxueService, self_test
from storage import Store
class MaintenanceEngine:
    def __init__(self, store: Store): self.service=GuoxueService(store=store)
    def one_click_update(self): return self.service.one_click_update()
    def one_click_repair(self): return self.service.one_click_repair()
