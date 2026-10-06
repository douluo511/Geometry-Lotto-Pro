from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

@dataclass
class ScoreCard:
    observation:int; pov:int; concise:int; humor:int; story:int; rhythm:int; interaction:int
    def as_dict(self): return asdict(self)
    def weakest(self): return min(self.as_dict().items(), key=lambda x:x[1])
    def strongest(self): return max(self.as_dict().items(), key=lambda x:x[1])

@dataclass
class AnalysisResult:
    score: ScoreCard
    strengths: List[str]
    improvements: List[str]
    next_task: str
    evidence: Dict
