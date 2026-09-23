from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

APP_VERSION = "0.1.0"
SCHEMA_VERSION = 1


@dataclass
class Hypothesis:
    name: str
    score: float
    evidence_for: List[str]
    evidence_against: List[str]
    missing_evidence: List[str]


@dataclass
class Strategy:
    name: str
    action: str
    goal_fit: int
    relationship_cost: int
    escalation_risk: int
    reversibility: int
    information_gain: int


EMOTION_SIGNALS = {
    "焦虑": ["焦虑", "担心", "紧张", "怕", "害怕", "不安", "催"],
    "愤怒": ["生气", "愤怒", "发火", "吵", "骂", "指责"],
    "失望": ["失望", "冷淡", "不理", "沉默", "疏远"],
    "防御": ["否认", "辩解", "回避", "躲", "拖延", "推脱"],
}

POWER_SIGNALS = {
    "对方资源权较强": ["老板", "客户", "甲方", "审批", "决定权", "付款方", "领导"],
    "你方替代权较强": ["多个客户", "替代", "备选", "不依赖", "可退出", "其他选择"],
    "信息不对称明显": ["不知道", "不清楚", "没说", "隐瞒", "信息", "内幕"],
}

COGNITIVE_SIGNALS = {
    "损失厌恶": ["亏", "损失", "不能失去", "舍不得", "怕失去"],
    "沉没成本": ["已经投入", "这么多年", "花了很多", "投入很多"],
    "确认偏误风险": ["肯定", "一定是", "就是因为", "绝对"],
    "锚定效应": ["原价", "第一次报价", "底价", "报价", "起价"],
}


def load_knowledge(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("knowledge schema mismatch")
    if not isinstance(data.get("rules"), list):
        raise ValueError("knowledge rules missing")
    return data


def _hits(text: str, mapping: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    low = text.lower()
    for label, words in mapping.items():
        found = [w for w in words if w.lower() in low]
        if found:
            out[label] = found
    return out


def extract_observations(text: str) -> List[str]:
    parts = re.split(r"[。！？!?；;\n]+", text)
    return [p.strip() for p in parts if p.strip()][:20]


def separate_fact_and_inference(observations: List[str]) -> Tuple[List[str], List[str]]:
    inference_markers = ("我觉得", "我认为", "肯定", "一定", "可能", "大概", "像是", "感觉", "故意", "就是因为")
    facts, inferences = [], []
    for item in observations:
        (inferences if any(m in item for m in inference_markers) else facts).append(item)
    return facts, inferences


def build_state(text: str, goal: str) -> dict:
    observations = extract_observations(text)
    facts, inferences = separate_fact_and_inference(observations)
    emotions = _hits(text, EMOTION_SIGNALS)
    power = _hits(text, POWER_SIGNALS)
    cognition = _hits(text, COGNITIVE_SIGNALS)

    incentive = []
    for label, kws in {
        "价格/金钱": ["钱", "价格", "报价", "付款", "工资", "成本", "预算"],
        "时间/效率": ["时间", "尽快", "拖延", "期限", "截止"],
        "机会/资源": ["机会", "资源", "客户", "职位", "名额", "合同"],
        "风险规避": ["风险", "责任", "担责", "安全", "损失"],
    }.items():
        if any(k in text for k in kws):
            incentive.append(label)

    relationship = "长期关系优先" if any(k in goal for k in ["长期", "合作", "修复", "关系", "朋友", "伴侣"]) else "结果导向但保留关系"
    context = "谈判/交易" if any(k in text for k in ["价格", "报价", "合同", "客户", "付款", "谈判"]) else "一般人际情境"

    return {
        "goal": goal.strip() or "在保护自身利益的同时，获得更多可靠信息并改善决策",
        "observations": observations,
        "facts": facts,
        "inferences": inferences,
        "incentive": incentive or ["当前利益结构尚不明确"],
        "emotion_signals": emotions or {"未识别到明确情绪信号": []},
        "identity": "若涉及面子、地位、承认错误或被否定，需要额外检查身份威胁。",
        "cognition": cognition or {"暂无强信号": []},
        "relationship": relationship,
        "power": power or {"权力结构信息不足": []},
        "context": context,
        "time": "建议补充最近一次变化发生的时间点与前后差异。",
        "uncertainty": "中等：文本只能提供行为线索，不能直接证明他人的内心状态。",
    }


def generate_hypotheses(text: str, state: dict) -> List[Hypothesis]:
    base = [
        Hypothesis("信息或理解差异", 0.25, [], [], ["双方掌握的信息是否一致？", "是否存在未说明的限制？"]),
        Hypothesis("利益或资源约束", 0.25, [], [], ["对方具体收益/损失是什么？", "预算、时间或权限是否受限？"]),
        Hypothesis("关系或身份防御", 0.25, [], [], ["是否发生过让对方失去面子或控制感的事件？"]),
        Hypothesis("策略性试探/议价", 0.25, [], [], ["对方在类似情境是否一贯如此？", "是否存在替代选择或底线测试？"]),
    ]

    def boost(idx: int, amount: float, evidence: str):
        base[idx].score += amount
        base[idx].evidence_for.append(evidence)

    if any(k in text for k in ["不知道", "没说", "误会", "没回复", "不清楚"]):
        boost(0, 0.18, "文本存在信息缺口/沟通不足信号")
    if any(k in text for k in ["价格", "钱", "预算", "付款", "资源", "期限", "成本"]):
        boost(1, 0.22, "文本存在明确资源或利益约束")
    if any(k in text for k in ["面子", "尊重", "否认", "指责", "冷淡", "生气", "不理"]):
        boost(2, 0.16, "文本出现关系/身份防御相关信号")
    if any(k in text for k in ["压价", "底价", "试探", "谈判", "条件", "威胁", "竞争"]):
        boost(3, 0.22, "文本出现策略性博弈/议价信号")

    total = sum(max(h.score, 0.01) for h in base)
    for h in base:
        h.score = round(h.score / total, 3)
        if not h.evidence_for:
            h.evidence_for.append("暂无直接证据，仅作为竞争解释保留")
        h.evidence_against.append("若出现稳定、可重复且与该解释矛盾的行为，应立即降权")
    return sorted(base, key=lambda h: h.score, reverse=True)


def build_strategies(goal: str, hypotheses: List[Hypothesis]) -> List[Strategy]:
    top = hypotheses[0].name
    return [
        Strategy(
            "先验证再行动",
            f"围绕“{top}”提出一个中性、可验证的问题，先补齐关键未知信息，不直接指控动机。",
            9, 2, 1, 10, 10,
        ),
        Strategy(
            "明确利益与边界",
            "把你的目标、可接受范围、不可接受范围和可交换条件说清楚，优先使用具体事实与可执行条件。",
            9, 4, 3, 8, 6,
        ),
        Strategy(
            "小步可逆试验",
            "先做一个成本低、可撤回的小动作，观察对方真实反应，再决定是否升级投入或对抗。",
            8, 2, 2, 10, 9,
        ),
    ]


def reverse_validation(h: Hypothesis) -> List[str]:
    return [
        f"如果“{h.name}”完全不成立，当前行为是否仍可能出现？",
        "去掉你最相信的一条证据后，结论是否明显改变？",
        "有没有一个更简单、非恶意的解释同样能解释现象？",
        "如果双方角色互换，你是否仍会做出同样判断？",
    ]


def five_why(text: str, hypotheses: List[Hypothesis]) -> List[str]:
    top = hypotheses[0].name
    return [
        f"Why 1：表面行为为什么会发生？当前优先检查：{top}。",
        "Why 2：是什么利益、限制或信息条件让这个行为变得合理？",
        "Why 3：谁掌握关键资源、信息、决定权或退出权？",
        "Why 4：关系历史、身份/面子或既有承诺是否在放大行为？",
        "Why 5：如果改变最底层约束，行为是否会随之改变？用实际行动验证。",
    ]


def analyze(text: str, goal: str) -> dict:
    if not text.strip():
        raise ValueError("请输入当前局面")
    state = build_state(text, goal)
    hypotheses = generate_hypotheses(text, state)
    strategies = build_strategies(state["goal"], hypotheses)
    return {
        "app_version": APP_VERSION,
        "state": state,
        "hypotheses": [asdict(x) for x in hypotheses],
        "information_gain": hypotheses[0].missing_evidence[0],
        "strategies": [asdict(x) for x in strategies],
        "reverse_validation": reverse_validation(hypotheses[0]),
        "five_why": five_why(text, hypotheses),
        "guardrail": "本系统用于理解、沟通、谈判、合作和边界管理；不把推测当事实，不提供欺骗、胁迫或针对个人脆弱性的恶意操控。",
    }


def format_report(result: dict) -> str:
    s = result["state"]
    lines = [
        "【目标】", s["goal"], "",
        "【事实 / 推测分离】",
        f"事实线索：{'；'.join(s['facts']) if s['facts'] else '暂无足够明确事实'}",
        f"主观推测：{'；'.join(s['inferences']) if s['inferences'] else '未检测到明显推测词'}", "",
        "【九层状态】",
        f"利益：{', '.join(s['incentive'])}",
        f"情绪信号：{', '.join(s['emotion_signals'].keys())}",
        f"身份：{s['identity']}",
        f"认知：{', '.join(s['cognition'].keys())}",
        f"关系：{s['relationship']}",
        f"权力：{', '.join(s['power'].keys())}",
        f"情境：{s['context']}",
        f"时间：{s['time']}",
        f"不确定度：{s['uncertainty']}", "",
        "【竞争假设】",
    ]
    for i, h in enumerate(result["hypotheses"], 1):
        lines.append(f"H{i} {h['name']}  {h['score']*100:.1f}%")
        lines.append(f"  支持：{'；'.join(h['evidence_for'])}")
        lines.append(f"  反证条件：{'；'.join(h['evidence_against'])}")
    lines += ["", "【下一步最有信息价值的问题】", result["information_gain"], "", "【策略候选】"]
    for i, st in enumerate(result["strategies"], 1):
        lines.append(f"S{i} {st['name']}：{st['action']}")
        lines.append(f"  目标匹配 {st['goal_fit']}/10｜关系成本 {st['relationship_cost']}/10｜升级风险 {st['escalation_risk']}/10｜可逆性 {st['reversibility']}/10｜信息增益 {st['information_gain']}/10")
    lines += ["", "【逆转验证】"] + [f"- {x}" for x in result["reverse_validation"]]
    lines += ["", "【5 Why】"] + [f"- {x}" for x in result["five_why"]]
    lines += ["", "【边界】", result["guardrail"]]
    return "\n".join(lines)
