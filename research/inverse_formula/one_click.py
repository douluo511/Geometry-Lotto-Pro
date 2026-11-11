"""One GitHub click => official-data checks => TWO live six-GPT meetings.

Only executes billed calls with BOTH --live and a separately configured
standing opt-in SSQDLT_PAID_APPROVED=true. No billing via test paths.
Outputs research tickets with explicit dan/sha heuristic lists for both games.
Never alters frozen V4.7 rules or ledger.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from research.inverse_formula.closure import preflight, freeze, _write_once
from research.inverse_formula.fresh_history import sync_fixture
from research.inverse_formula.live_models import (
    parse_agents, verify_six_gpt6_agents, require_keys, sha
)
from research.inverse_formula.live_council_v2 import run_reviewed_council
from research.inverse_formula.neural_audit import distill_decision
from research.inverse_formula.probe import DLT, SSQ, load_history

ROOT = Path(__file__).parent
DEFAULT_AGENTS = ROOT / "multi_provider_agents.example.json"


def prepare_all(out: Path, agents: Path = DEFAULT_AGENTS) -> dict:
    """Run both official-source checks BEFORE any paid model invocation."""
    council = parse_agents(json.loads(agents.read_text(encoding="utf-8")))
    verify_six_gpt6_agents(council)
    output: dict = {}
    for game, name in ((SSQ, "ssq"), (DLT, "dlt")):
        source_fixture = ROOT / f"{name}_2026.txt"
        dest = out / f"{name}-synced-history.txt"
        synced = sync_fixture(source_fixture, game, dest)
        _write_once(out / f"{name}-source-audit.json", synced)
        pre = preflight(dest, agents, game)
        _write_once(out / f"{name}-preflight.json", pre)
        output[name] = {"game": game, "history": dest,
                        "source_audit": synced, "preflight": pre}
    return output


def _numbers(nums: list[int]) -> str:
    return " ".join(f"{n:02d}" for n in nums)


def render_meetings(meetings: dict) -> str:
    lines = [
        "# SSQ + DLT｜六智能体独立研究会议",
        "",
        "状态：RESEARCH_ONLY / NO_EDGE / 非正式 V4.7 预测",
        "",
        "会议每个彩种六角色，第一轮独立提案、第二轮交叉审查。"
        "全部候选为研究性建议，不保证任何号码出现或排除。",
        "",
    ]
    for name in ("ssq", "dlt"):
        block = meetings[name]
        receipt = block["receipt"]
        sync = block["source_audit"]
        lines.extend([
            f"## {name.upper()} 下一期研究建议",
            f"- 已核对的数据截止期：{sync['asof_issue']}",
            f"- 研究目标期：{sync['target_issue']}",
            f"- 来源：{sync['source_url']}（最新开奖 {sync['latest_published_date']}）",
            f"- 六角色会议：{receipt['meeting_status']}；"
            f"提案 {len(receipt['independent_proposals'])}，"
            f"互评 {len(receipt['cross_reviews'])}，"
            f"通过否决门槛 {len(receipt['accepted_formula_ids'])}",
        ])
        if receipt["meeting_status"] == "RESEARCH_CANDIDATE_ONLY":
            p, rec = receipt["proposed_ticket"], receipt["research_dan_sha"]
            lines.extend([
                f"- 完整研究候选：{_numbers(p['front'])} + {_numbers(p['back'])}",
                f"- D2 双胆码：{_numbers(p['d2_pair'])}",
                f"- 前区胆码：{_numbers(rec['front_dan'])}",
                f"- 前区杀码：{_numbers(rec['front_sha'])}",
                f"- {'蓝球' if name == 'ssq' else '后区'}参考胆码：{_numbers(rec['back_dan'])}",
                f"- {'蓝球' if name == 'ssq' else '后区'}参考杀码：{_numbers(rec['back_sha'])}",
                f"- 研究封存 SHA256：{block['seal']['sha256']}",
            ])
        else:
            lines.append("- 本次专家否决过多：不发布虚构的胆码、杀码或完整候选。")
        trace = block["neural_trace"]
        lines.extend([
            f"- 可审计的专家证据图：独立提案 {trace['edges']['independent_proposal_edges']}，"
            f"跨角色审查 {trace['edges']['cross_review_edges']}，"
            f"否决公式 {trace['edges']['vetoed_formulas']}。",
            "- 思维链蒸馏：只公开可检验的公式、提案摘要、"
            "逐条反对理由与筛选依据，不包含模型私有推理。",
            "- 历史边界：确定性公式库的 past-only 结果与本次新提出的"
            "模型公式分开；本次新公式还没有独立前瞻命中证据。",
            f"- 专家证据图 SHA256：{trace['sha256']}",
            f"- 会议回执 SHA256：{receipt['sha256']}",
            f"- 数据 SHA256：{sync['merged_history_sha256']}",
            "",
        ])
    lines.extend([
        "## 研究有效性边界",
        "本次是基于官方省级发行机构公开网页的结果比对，"
        "并非对所有历史开奖记录的独立官方认证。",
        "GitHub Run/Issue 的时间记录可辅助审计，不等于可信第三方时间戳。",
        "胆码和杀码只是根据模型公式候选与交叉评价排名得出的选择，"
        "其未来命中率优势尚未证实。NO_EDGE。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="requests real billed API calls, never in CI")
    parser.add_argument("--agents", type=Path, default=DEFAULT_AGENTS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("actual meeting requires explicit --live; no mock fallback")
    if os.environ.get("SSQDLT_PAID_APPROVED") != "true":
        parser.error("set standing paid-cost permission via GitHub Actions variable")
    agents = parse_agents(json.loads(args.agents.read_text(encoding="utf-8")))
    verify_six_gpt6_agents(agents)
    require_keys(agents)  # checks only existence, never prints or records secrets
    args.out.mkdir(parents=True, exist_ok=True)
    if any(args.out.iterdir()):
        parser.error("output directory must be empty, to prevent overwriting")
    prepared = prepare_all(args.out, args.agents)  # BOTH games checked before costs
    meetings: dict = {}
    for name, data in prepared.items():
        game = data["game"]
        rows, source_sha = load_history(data["history"], game)
        council = run_reviewed_council(rows, game, agents, live_authorized=True)
        neural_trace = distill_decision(council, rows, game)
        neural_trace["input_source_sha256"] = source_sha
        neural_trace["sha256"] = sha({k: v for k, v in neural_trace.items()
                                      if k != "sha256"})
        _write_once(args.out / f"{name}-six-expert-evidence-graph.json", neural_trace)
        council["source_sha256"] = source_sha
        council["source_audit_sha256"] = sha(data["source_audit"])
        council["sha256"] = sha({k: v for k, v in council.items() if k != "sha256"})
        _write_once(args.out / f"{name}-six-gpt-meeting.json", council)
        meetings[name] = {"receipt": council, "source_audit": data["source_audit"],
                          "neural_trace": neural_trace}
        if council["meeting_status"] == "RESEARCH_CANDIDATE_ONLY":
            sealed = freeze(data["preflight"], council, game)
            _write_once(args.out / f"{name}-research-content-seal.json", sealed)
            meetings[name]["seal"] = sealed
        else:
            meetings[name]["seal"] = None
    if any(v["seal"] is None for v in meetings.values()):
        raise RuntimeError("reviewer veto prevented one or both recommendations")
    report = render_meetings(meetings)
    path = args.out / "ssq-dlt-next-report.md"
    with path.open("x", encoding="utf-8") as file:
        file.write(report)
    manifest = {
        "protocol": "SSQDLT_ONECLICK_GPT6_RESEARCH_V1",
        "games": {key: {
            "asof_issue": val["source_audit"]["asof_issue"],
            "target_issue": val["source_audit"]["target_issue"],
            "six_model_receipt_sha256": val["receipt"]["sha256"],
            "six_expert_evidence_graph_sha256": val["neural_trace"]["sha256"],
            "content_seal_sha256": val["seal"]["sha256"],
            "candidate": val["receipt"]["proposed_ticket"],
            "dan_sha": val["receipt"]["research_dan_sha"],
        } for key, val in meetings.items()},
        "rounds_per_game": 2,
        "roles_per_game": 6,
        "expected_provider_requests": 24,
        "execution": "LIVE_PROVIDER_CALLS",
        "formal_v47_modified": False,
        "research_status": "NO_EDGE",
        "trusted_external_timestamp": False,
    }
    manifest["sha256"] = sha(manifest)
    _write_once(args.out / "manifest.json", manifest)
    print(report)
    print("MANIFEST_SHA256=" + manifest["sha256"])


if __name__ == "__main__":
    main()
