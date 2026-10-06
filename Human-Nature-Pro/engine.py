from __future__ import annotations
from core import analyze as _analyze, format_report as _format_report

class HumanNatureEngine:
    def __init__(self, knowledge: dict | None = None):
        self.knowledge = knowledge or {}
    def set_knowledge(self, knowledge: dict):
        self.knowledge = knowledge
    def analyze(self, text: str, goal: str):
        return _analyze(text, goal, self.knowledge)
    def format_report(self, result: dict):
        return _format_report(result)
