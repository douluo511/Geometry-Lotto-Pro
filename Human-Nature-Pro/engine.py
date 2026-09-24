from __future__ import annotations
from core import analyze as _analyze, format_report as _format_report

class HumanNatureEngine:
    def analyze(self, text: str, goal: str):
        return _analyze(text, goal)

    def format_report(self, result: dict):
        return _format_report(result)
