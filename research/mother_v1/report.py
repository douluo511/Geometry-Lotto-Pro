"""Chinese human-readable report for EVERY registered model, including abstentions."""
from __future__ import annotations

from .registry import ALL_MODELS, PHYSICAL


def _balls(numbers) -> str:
    return " ".join(f"{x:02d}" for x in numbers)


def markdown_report(result: dict) -> str:
    if result.get("registry") != list(ALL_MODELS):
        raise ValueError("REGISTRY_NOT_COMPLETE")
    lines = [
        "# SSQ + DLT 统一母体 V1｜全模型预测与物理证据审计",
        "",
        "**状态：SHADOW 研究输出；预测优势 NO_EDGE；正式前瞻资格 formal_A=0。**",
        "来源真实性和独立开奖前时间戳未获充分验证；不构成中奖承诺。",
        "",
    ]
    for game, label in (("SSQ", "双色球"), ("DLT", "大乐透")):
        data = result["games"][game]
        if len(data["models"]) != len(ALL_MODELS):
            raise ValueError("MISSING_MODEL_RESULT")
        lines.extend([
            f"## {label}｜第 {data['target_issue']} 期",
            "",
            f"历史截止：{data['last_training_issue']}期；样本 {data['history_count']} 期；"
            f"数据输入类别：{data['input_provenance']}。",
            "",
            "| 模型 | 所属模型族 | 前区/红球 | 后区/蓝球 | 状态 |",
            "|---|---|---|---|---|",
        ])
        for row in data["models"]:
            ticket = row["ticket"]
            if ticket is None:
                # Fallback is NOT a physical prediction. Keep separate label.
                fb = row["display_only_random_null_fallback"]
                front = "—（无物理预测）"
                back = "—"
                status = (row["status"] +
                          f"；仅随机对照占位：{_balls(fb['front'])} + {_balls(fb['back'])}")
            else:
                front, back = _balls(ticket["front"]), _balls(ticket["back"])
                status = row["status"]
            lines.append(f"| {row['name']} | {row['family']} | {front} | {back} | {status} |")
        lines.extend([
            "",
            f"本次物理历史有效样本：{data['physical_count']} 条。"
            "物理模型未通过时不得把随机占位号码作为物理模型预测。",
            "",
        ])
    lines.extend([
        "## 结果验收",
        "",
        f"- 模型注册总数：{len(ALL_MODELS)} / 彩种；输出不允许漏项。",
        "- 原始 V4.7 模型与固定 Random NULL 保持独立身份。",
        "- 物理出球顺序和球组条件模型必须独立验证；没有开奖前证据则 ABSTAIN。",
        "- 所有号码只用于可证伪研究，不证明超过公平随机开奖基线。",
        "- 本次没有下注、购买或更改历史封存预测。",
        "",
    ])
    return "\n".join(lines)
