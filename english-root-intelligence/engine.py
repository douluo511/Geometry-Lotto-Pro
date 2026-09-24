from __future__ import annotations
from core import LearningEngine
from storage import RootStorage

class EnglishRootEngine:
    def __init__(self,storage:RootStorage): self._legacy=LearningEngine(storage.store)
    def analyze(self,word): return self._legacy.analyze(word)
    def today_roots(self,count=3): return self._legacy.today_roots(count)
    def stats(self): return self._legacy.stats()
