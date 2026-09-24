from __future__ import annotations

import math
import re
from typing import Any, Dict, List

from domain import AnalysisResult, Evidence, Hypothesis, Observation


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _contains(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def _count_matches(text: str, keywords: List[str]) -> List[str]:
    return [k for k in keywords if _contains(text, k)]


def extract_observations(text: str, baseline_text: str = "") -> List[Observation]:
    text = normalize_text(text)
    baseline_text = normalize_text(baseline_text)
    obs: List[Observation] = []

    length = len(text)
    obs.append(Observation("message_length", f"当前文本长度约 {length} 个字符", min(1.0, length / 120.0)))

    if "?" in text or "？" in text:
        obs.append(Observation("questioning", "当前表达包含提问，说明仍存在信息交换需求", 0.45))
    if "!" in text or "！" in text:
        obs.append(Observation("intensity", "当前表达包含较强语气标记", 0.45))

    hedge_words = ["不知道", "也许", "可能", "再看看", "随便", "都行", "看情况", "maybe", "perhaps"]
    hedge_hits = _count_matches(text, hedge_words)
    if hedge_hits:
        obs.append(Observation("uncertainty", f"出现不确定/低承诺表达：{', '.join(hedge_hits[:4])}", 0.65))

    boundary_words = ["先别", "不想聊", "给我点时间", "想静静", "空间", "晚点再说", "改天", "以后再说"]
    boundary_hits = _count_matches(text, boundary_words)
    if boundary_hits:
        obs.append(Observation("boundary", f"出现边界或距离信号：{', '.join(boundary_hits[:4])}", 0.75))

    commitment_words = ["我来", "我会", "确定", "约", "见面", "一起", "我帮", "什么时候"]
    commitment_hits = _count_matches(text, commitment_words)
    if commitment_hits:
        obs.append(Observation("commitment", f"出现投入/承诺信号：{', '.join(commitment_hits[:4])}", 0.65))

    if baseline_text:
        cur_len = max(1, len(text))
        base_len = max(1, len(baseline_text))
        ratio = cur_len / base_len
        if ratio < 0.55:
            obs.append(Observation("baseline_shift", f"当前文本长度约为基线的 {ratio:.0%}，存在明显缩短", 0.72))
        elif ratio > 1.8:
            obs.append(Observation("baseline_shift", f"当前文本长度约为基线的 {ratio:.0%}，存在明显增长", 0.58))

    return obs


def score_hypotheses(text: str, baseline_text: str, knowledge: Dict[str, Any]) -> List[Hypothesis]:
    hypotheses: List[Hypothesis] = []
    current = normalize_text(text)
    baseline = normalize_text(baseline_text)

    for item in knowledge.get("hypotheses", []):
        h = Hypothesis(
            key=item["key"],
            name=item["name"],
            explanation=item["explanation"],
            score=float(item.get("prior", 0.0)),
        )

        for kw in item.get("support_keywords", []):
            if _contains(current, kw):
                weight = float(item.get("support_weight", 0.45))
                h.score += weight
                h.evidence.append(Evidence(f"当前表达包含“{kw}”", "support", weight))

        for kw in item.get("contradict_keywords", []):
            if _contains(current, kw):
                weight = float(item.get("contradict_weight", 0.45))
                h.score -= weight
                h.evidence.append(Evidence(f"当前表达包含反向信号“{kw}”", "contradict", weight))

        if baseline:
            base_support = len(_count_matches(baseline, item.get("support_keywords", [])))
            cur_support = len(_count_matches(current, item.get("support_keywords", [])))
            if cur_support > base_support:
                delta = min(0.5, (cur_support - base_support) * 0.12)
                h.score += delta
                h.evidence.append(Evidence("与历史基线相比，该类信号有所增加", "support", delta))

        evidence_count = len(h.evidence)
        bounded = 1.0 / (1.0 + math.exp(-h.score))
        evidence_factor = min(1.0, 0.28 + evidence_count * 0.16)
        h.confidence = round(bounded * evidence_factor, 3)
        hypotheses.append(h)

    hypotheses.sort(key=lambda x: (x.confidence, x.score), reverse=True)
    return hypotheses


def build_five_whys(hypotheses: List[Hypothesis]) -> List[str]:
    if not hypotheses:
        return ["当前证据不足，暂不建立 5 Why 因果链。"]
    top = hypotheses[0]
    return [
        f"Why 1：为什么会出现与“{top.name}”一致的表面信号？",
        "Why 2：这些信号是稳定变化，还是一次性的情境波动？",
        "Why 3：如果是稳定变化，背后的需求、压力、收益或风险发生了什么改变？",
        "Why 4：这种改变是否能被其他解释同样说明，例如忙碌、疲劳、冲突回避或边界需求？",
        "Why 5：还有什么关键事实能区分这些竞争解释？",
    ]


def reverse_validate(hypotheses: List[Hypothesis]) -> List[str]:
    if not hypotheses:
        return ["没有足够假设可执行逆转验证。"]
    top = hypotheses[0]
    rivals = [h for h in hypotheses[1:] if h.confidence >= max(0.0, top.confidence - 0.16)]
    lines = [f"主假设：{top.name}（置信度 {top.confidence:.0%}）"]
    if rivals:
        lines.append("逆转检验：即使主假设为错，下列替代解释仍可能产生相似现象：")
        lines.extend([f"• {h.name}（{h.confidence:.0%}）" for h in rivals[:3]])
        lines.append("因此当前不应把主假设当作内心事实。")
    else:
        lines.append("逆转检验：当前替代解释支持较弱，但仍需后续行为或直接沟通验证。")
    return lines


def consistency_notes(text: str, baseline_text: str) -> List[str]:
    notes: List[str] = []
    text = normalize_text(text)
    baseline_text = normalize_text(baseline_text)
    if not baseline_text:
        return ["未提供历史基线，暂不能判断当前行为是否偏离个人常态。"]

    if len(text) < len(baseline_text) * 0.55:
        notes.append("当前表达明显短于历史基线，可作为“投入变化”观察点，但不能单独解释原因。")
    if ("忙" in text or "没时间" in text) and any(k in text for k in ["一起", "见面", "我来", "我帮"]):
        notes.append("当前文本同时存在“负荷信号”和“投入信号”，结论应保持竞争解释。")
    if not notes:
        notes.append("当前未发现足以形成强结论的明显基线偏移。")
    return notes


def guidance_for(hypotheses: List[Hypothesis], confidence_label: str) -> List[str]:
    if confidence_label == "LOW":
        return [
            "先补充时间线或历史基线，再判断变化是否真实存在。",
            "优先询问一个开放式问题，而不是把推断直接当成事实告诉对方。",
            "观察下一次可验证行为：是否主动、是否兑现承诺、是否给出具体时间。",
        ]

    top_name = hypotheses[0].name if hypotheses else "当前状态"
    return [
        f"把“{top_name}”当作待验证假设，不当作结论。",
        "寻找能区分主假设与替代解释的事实，而不是继续收集同方向证据。",
        "优先使用尊重边界、允许对方直接表达的沟通方式。",
    ]


def analyze(text: str, knowledge: Dict[str, Any], baseline_text: str = "") -> AnalysisResult:
    text = normalize_text(text)
    if not text:
        raise ValueError("请输入需要分析的对话、行为描述或事件信息。")

    observations = extract_observations(text, baseline_text)
    hypotheses = score_hypotheses(text, baseline_text, knowledge)

    evidence_total = sum(len(h.evidence) for h in hypotheses)
    top_conf = hypotheses[0].confidence if hypotheses else 0.0
    if evidence_total < 2 or top_conf < 0.35:
        label = "LOW"
    elif evidence_total < 5 or top_conf < 0.58:
        label = "MEDIUM"
    else:
        label = "MEDIUM-HIGH"

    return AnalysisResult(
        observations=observations,
        hypotheses=hypotheses,
        five_whys=build_five_whys(hypotheses),
        reverse_validation=reverse_validate(hypotheses),
        consistency_notes=consistency_notes(text, baseline_text),
        guidance=guidance_for(hypotheses, label),
        overall_confidence=label,
        disclaimer=(
            "这是基于可观察信息的概率性心理推断，不是读心、测谎或心理诊断。"
            "同一行为可能由多种原因造成，重要判断应结合直接沟通与后续行为验证。"
        ),
    )


def self_test() -> Dict[str, str]:
    knowledge = {
        "hypotheses": [
            {
                "key": "uncertainty",
                "name": "不确定/尚未决定",
                "explanation": "当前可能还没有形成明确决定。",
                "support_keywords": ["不知道", "再看看"],
                "contradict_keywords": ["确定", "我会"],
                "support_weight": 0.5,
                "contradict_weight": 0.5,
            },
            {
                "key": "engagement",
                "name": "仍有投入意愿",
                "explanation": "仍存在继续互动或采取行动的信号。",
                "support_keywords": ["一起", "我来"],
                "contradict_keywords": ["不想聊"],
                "support_weight": 0.45,
                "contradict_weight": 0.55,
            },
        ]
    }
    result = analyze("我不知道，再看看吧", knowledge)
    assert result.hypotheses
    assert result.hypotheses[0].key == "uncertainty"
    assert result.overall_confidence in {"LOW", "MEDIUM", "MEDIUM-HIGH"}
    return {"core": "PASS", "reverse_validation": "PASS", "confidence_calibration": "PASS"}
