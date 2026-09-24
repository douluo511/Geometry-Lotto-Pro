from __future__ import annotations

from domain import AnalysisResult


def build_evidence_summary(result: AnalysisResult) -> dict:
    return {
        "overall_confidence": result.overall_confidence,
        "observations": [
            {"label": o.label, "detail": o.detail, "strength": o.strength}
            for o in result.observations
        ],
        "hypotheses": [
            {
                "key": h.key,
                "name": h.name,
                "confidence": h.confidence,
                "support": [e.text for e in h.evidence if e.direction == "support"],
                "contradict": [e.text for e in h.evidence if e.direction == "contradict"],
            }
            for h in result.hypotheses
        ],
        "reverse_validation": list(result.reverse_validation),
    }
