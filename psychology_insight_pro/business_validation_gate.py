from __future__ import annotations

import json
from pathlib import Path

from core import analyze

ROOT = Path(__file__).resolve().parent


def by_key(result, key: str):
    for h in result.hypotheses:
        if h.key == key:
            return h
    raise KeyError(key)


def main() -> int:
    knowledge = json.loads((ROOT / "knowledge.json").read_text(encoding="utf-8"))

    ambiguous = analyze(
        "最近很忙，可能改天再说，不过有空我会联系你，我们再看看具体时间。",
        knowledge,
        "以前通常会直接约具体时间并主动确认。",
    )
    committed = analyze(
        "我已经确定了，明天见面，我来安排具体时间，也会提前告诉你。",
        knowledge,
        "以前经常不确定，会说再看看。",
    )
    no_baseline = analyze("最近很忙，改天再说。", knowledge)
    with_baseline = analyze("最近很忙，改天再说。", knowledge, "以前会主动约具体时间，一起见面。")

    amb_uncertainty = by_key(ambiguous, "uncertainty")
    committed_uncertainty = by_key(committed, "uncertainty")
    amb_engagement = by_key(ambiguous, "engagement")
    committed_engagement = by_key(committed, "engagement")

    checks = {
        "business_multiple_competing_hypotheses": len(ambiguous.hypotheses) >= 5,
        "business_no_mindreading_boundary": "不是读心" in ambiguous.disclaimer and "不是心理诊断" in ambiguous.disclaimer,
        "business_confidence_is_bounded": max(h.confidence for h in ambiguous.hypotheses) < 0.90,
        "business_reverse_validation_present": len(ambiguous.reverse_validation) >= 2,
        "counterexample_uncertainty_reverses": committed_uncertainty.confidence < amb_uncertainty.confidence,
        "counterexample_engagement_strengthens": committed_engagement.confidence > amb_engagement.confidence,
        "counterexample_baseline_changes_interpretation": no_baseline.consistency_notes != with_baseline.consistency_notes,
        "reversal_names_main_hypothesis": bool(ambiguous.reverse_validation) and ambiguous.reverse_validation[0].startswith("主假设："),
        "reversal_preserves_alternatives_or_requires_validation": any(
            ("替代解释" in line) or ("仍需" in line) or ("验证" in line)
            for line in ambiguous.reverse_validation[1:]
        ),
        "real_user_value_guidance": len(ambiguous.guidance) >= 3,
    }

    business_validation = all(
        checks[k] for k in (
            "business_multiple_competing_hypotheses",
            "business_no_mindreading_boundary",
            "business_confidence_is_bounded",
            "business_reverse_validation_present",
            "real_user_value_guidance",
        )
    )
    counterexample_validation = all(
        checks[k] for k in (
            "counterexample_uncertainty_reverses",
            "counterexample_engagement_strengthens",
            "counterexample_baseline_changes_interpretation",
        )
    )
    reversal_validation = all(
        checks[k] for k in (
            "reversal_names_main_hypothesis",
            "reversal_preserves_alternatives_or_requires_validation",
        )
    )

    report = {
        "schema": "psychology-business-validation-v1",
        "status": "PASS" if business_validation and counterexample_validation and reversal_validation else "FAIL",
        "business_validation": "PASS" if business_validation else "FAIL",
        "counterexample_validation": "PASS" if counterexample_validation else "FAIL",
        "reversal_validation": "PASS" if reversal_validation else "FAIL",
        "checks": checks,
        "observations": {
            "ambiguous_uncertainty": amb_uncertainty.confidence,
            "committed_uncertainty": committed_uncertainty.confidence,
            "ambiguous_engagement": amb_engagement.confidence,
            "committed_engagement": committed_engagement.confidence,
            "overall_confidence": ambiguous.overall_confidence,
        },
    }
    (ROOT / "business_validation_gate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
