"""No-charge research preflight, content sealing, and post-result scoring.

This module never contacts external services, reads API secrets or touches V4.7.
SHA256 protects JSON content integrity, NOT trusted pre-draw timestamps.
The result source is supplied by the caller, not authenticated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from research.inverse_formula.probe import DLT, SSQ, Draw, Game, load_history, compare
from research.inverse_formula.live_models import parse_agents, verify_six_gpt6_agents

VERSION = "RESEARCH_CLOSURE_V1"
AGENT_FILE = Path(__file__).with_name("multi_provider_agents.example.json")


def digest(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_digest(document: dict, field: str = "sha256") -> None:
    if not isinstance(document, dict) or not isinstance(document.get(field), str):
        raise ValueError("missing audit digest")
    if digest({k: v for k, v in document.items() if k != field}) != document[field]:
        raise ValueError("audit digest mismatch")


def _game(name: str) -> Game:
    return {"ssq": SSQ, "dlt": DLT}[name.lower()]


def validate_ticket(ticket: object, game: Game, *, require_d2: bool = True) -> dict:
    if not isinstance(ticket, dict):
        raise ValueError("ticket must be a JSON object")
    result = {}
    for key, n, maximum in (("front", game.front_pick, game.front_max),
                            ("back", game.back_pick, game.back_max)):
        nums = ticket.get(key)
        if (not isinstance(nums, (tuple, list)) or len(nums) != n
                or any(type(x) is not int or not 1 <= x <= maximum for x in nums)
                or list(nums) != sorted(set(nums))):
            raise ValueError("illegal " + key + " numbers")
        result[key] = list(nums)
    if require_d2:
        nums = ticket.get("d2_pair")
        if (not isinstance(nums, (list, tuple)) or len(nums) != 2
                or any(type(x) is not int for x in nums)
                or list(nums) != sorted(set(nums))
                or not set(nums).issubset(result["front"])):
            raise ValueError("invalid D2 pair")
        result["d2_pair"] = list(nums)
    return result


def preflight(history: Path, agents_path: Path, game: Game) -> dict:
    """Offline configuration and integrity checks; not API entitlement checks."""
    agents = parse_agents(json.loads(agents_path.read_text(encoding="utf-8")))
    verify_six_gpt6_agents(agents)
    rows, history_sha256 = load_history(history, game)
    result = {
        "protocol": VERSION,
        "kind": "OFFLINE_PREFLIGHT",
        "game": game.name,
        "asof_issue": rows[-1].issue,
        "target_issue": rows[-1].issue + 1,
        "history_count": len(rows),
        "history_sha256": history_sha256,
        "agent_config_sha256": hashlib.sha256(agents_path.read_bytes()).hexdigest(),
        "roles": [{"role": a.role, "model": a.model,
                   "reasoning_effort": a.reasoning_effort} for a in agents],
        "checks": {
            "contiguous_valid_history": "PASS",
            "six_gpt6_high_config": "PASS",
            "live_model_entitlements": "UNVERIFIED",
            "official_source_authentication": "UNVERIFIED",
            "prospective_pre_draw_timestamp": "UNVERIFIED",
        },
        "network_requests": 0,
        "model_requests": 0,
        "paid_authorization": False,
        "research_status": "NO_EDGE",
        "formal_v47_promotion": False,
    }
    result["sha256"] = digest(result)
    return result


def _extract_candidate(source: dict, game: Game) -> tuple[dict, str]:
    """Accept the existing deterministic committee archive or live receipt."""
    if game.name in source and isinstance(source[game.name], dict):
        wrapper = source[game.name]
        if "committee" not in wrapper:
            raise ValueError("archive entry missing committee")
        inner = wrapper["committee"]
        if not isinstance(inner, dict):
            raise ValueError("invalid committee archive")
        if not isinstance(wrapper.get("source_sha256"), str):
            raise ValueError("archive missing source hash")
        history_hash = wrapper["source_sha256"]
    else:
        inner = source
        history_hash = source.get("source_sha256")
    if inner.get("protocol") == "SSQDLT_RESEARCH_COMMITTEE_V1":
        verify_digest(inner, "receipt_sha256")
        if inner.get("implementation") != (
                "DETERMINISTIC_ROLE_SIMULATION_NOT_INDEPENDENT_LLM_AGENTS"):
            raise ValueError("unexpected committee implementation")
        decision = inner.get("decision", {})
        if (decision.get("research_only") is not True
                or decision.get("promote_to_formal_v47") is not False
                or decision.get("status") != "NO_EDGE"):
            raise ValueError("committee is not isolated research")
        guards = inner.get("guards", {})
        if (guards.get("official_v47_modified") is not False
                or guards.get("fixed_random_null_modified") is not False):
            raise ValueError("V4.7 guards failed")
        prediction = decision.get("proposal")
        reference = inner["receipt_sha256"]
        execution = "DETERMINISTIC_SIMULATION"
    elif inner.get("protocol") == "MULTI_PROVIDER_FORMULA_COUNCIL_V1":
        verify_digest(inner)
        if inner.get("execution") != "LIVE_PROVIDER_CALLS":
            raise ValueError("mock council may not be frozen as live")
        guards = inner.get("guards", {})
        if guards.get("formal_v47_modified") is not False:
            raise ValueError("formal V4.7 guard failed")
        if inner.get("decision") != "NO_EDGE_REQUIRES_PROSPECTIVE_VALIDATION":
            raise ValueError("invalid research-only decision")
        prediction = inner.get("proposed_ticket")
        reference = inner["sha256"]
        execution = "LIVE_CLAIM_FROM_SOURCE_RECEIPT_NOT_AUTHENTICATED"
    else:
        raise ValueError("unsupported candidate receipt protocol")
    if not isinstance(history_hash, str) or len(history_hash) != 64:
        raise ValueError("candidate missing history hash")
    if inner.get("game") != game.name:
        raise ValueError("candidate game mismatch")
    if (type(inner.get("asof_issue")) is not int
            or type(inner.get("target_issue")) is not int
            or inner["target_issue"] != inner["asof_issue"] + 1):
        raise ValueError("candidate cutoff mismatch")
    candidate = {"ticket": validate_ticket(prediction, game),
                 "asof_issue": inner["asof_issue"],
                 "target_issue": inner["target_issue"],
                 "reference": reference, "execution": execution}
    if inner.get("revision") in ("REVIEWED_DAN_SHA_V2", "TIERED_REVIEWED_DAN_SHA_V3"):
        selections = inner.get("research_dan_sha")
        if not isinstance(selections, dict):
            raise ValueError("reviewed council missing dan/sha selections")
        for side, max_value, full_size, dan_size, sha_size in (
            ("front", game.front_max, game.front_pick, 2, 8),
            ("back", game.back_max, game.back_pick, 1,
             3 if game.name == "SSQ" else 2),
        ):
            dan, sha_list = selections.get(side+"_dan"), selections.get(side+"_sha")
            if any(not isinstance(x, list) for x in (dan, sha_list)):
                raise ValueError("dan/sha must be lists")
            if len(dan) != dan_size or len(sha_list) != sha_size:
                raise ValueError("unexpected dan/sha capacity")
            if (any(type(n) is not int or not 1 <= n <= max_value
                    for n in dan+sha_list)
                    or dan != sorted(set(dan))
                    or sha_list != sorted(set(sha_list))
                    or set(dan) & set(sha_list)
                    or not set(dan).issubset(candidate["ticket"][side])
                    or set(sha_list) & set(candidate["ticket"][side])):
                raise ValueError("dan/sha conflict with selected ticket")
        candidate["research_dan_sha"] = selections
    return candidate, history_hash


def freeze(preflight_report: dict, candidate_archive: dict, game: Game) -> dict:
    """Seal one research candidate. Does not certify when it was published."""
    verify_digest(preflight_report)
    if (preflight_report.get("protocol") != VERSION
            or preflight_report.get("kind") != "OFFLINE_PREFLIGHT"
            or preflight_report.get("game") != game.name
            or preflight_report.get("checks", {}).get("six_gpt6_high_config") != "PASS"
            or preflight_report.get("checks", {}).get("contiguous_valid_history") != "PASS"):
        raise ValueError("preflight is not valid")
    candidate, history_sha = _extract_candidate(candidate_archive, game)
    if (history_sha != preflight_report["history_sha256"]
            or candidate["asof_issue"] != preflight_report["asof_issue"]
            or candidate["target_issue"] != preflight_report["target_issue"]):
        raise ValueError("candidate was not derived from preflight cutoff")
    sealed = {
        "protocol": VERSION,
        "kind": "RESEARCH_CONTENT_SEAL",
        "game": game.name,
        "asof_issue": candidate["asof_issue"],
        "target_issue": candidate["target_issue"],
        "history_sha256": history_sha,
        "preflight_sha256": preflight_report["sha256"],
        "candidate_receipt_sha256": candidate["reference"],
        "candidate_execution": candidate["execution"],
        "ticket": candidate["ticket"],
        "status": "NO_EDGE_RESEARCH_ONLY_NOT_AN_AUTHENTICATED_PREDRAW_FREEZE",
        "trusted_predraw_timestamp": False,
        "official_v47_modified": False,
    }
    if "research_dan_sha" in candidate:
        sealed["research_dan_sha"] = candidate["research_dan_sha"]
    sealed["sha256"] = digest(sealed)
    return sealed


def _read_result(value: dict, game: Game) -> tuple[Draw, str]:
    if (not isinstance(value, dict) or value.get("game") != game.name
            or type(value.get("issue")) is not int):
        raise ValueError("result identity invalid")
    ticket = validate_ticket(value, game, require_d2=False)
    source_url = value.get("source_url")
    parsed = urlsplit(source_url) if isinstance(source_url, str) else None
    if not parsed or parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("result must have an HTTPS provenance URL")
    return Draw(value["issue"], tuple(ticket["front"]), tuple(ticket["back"])), source_url


def score(frozen: dict, result: dict, game: Game) -> dict:
    """Arithmetic only. Never edits the frozen receipt or a formal ledger."""
    verify_digest(frozen)
    if (frozen.get("protocol") != VERSION
            or frozen.get("kind") != "RESEARCH_CONTENT_SEAL"
            or frozen.get("game") != game.name
            or frozen.get("trusted_predraw_timestamp") is not False
            or frozen.get("official_v47_modified") is not False):
        raise ValueError("invalid research freeze")
    if frozen.get("target_issue") != frozen.get("asof_issue") + 1:
        raise ValueError("invalid issue boundary")
    ticket = validate_ticket(frozen.get("ticket"), game)
    actual, source = _read_result(result, game)
    if actual.issue != frozen["target_issue"]:
        raise ValueError("target issue is not the result issue")
    matches = compare((tuple(ticket["front"]), tuple(ticket["back"])), actual)
    body = {
        "protocol": VERSION,
        "kind": "RESEARCH_POST_RESULT_SCORE",
        "game": game.name,
        "asof_issue": frozen["asof_issue"],
        "target_issue": actual.issue,
        "frozen_sha256": frozen["sha256"],
        "result_source_url": source,
        "result_input_sha256": digest(result),
        "result_source_authenticated": False,
        "trusted_predraw_timestamp": False,
        "metrics": {
            "full_hit": matches["full"],
            "front_hits": matches["front_hits"],
            "back_hits": matches["back_hits"],
            "d2_hit": int(set(ticket["d2_pair"]).issubset(actual.front)),
        },
        "comparison": "RESEARCH_ONLY_NO_EDGE_NO_PROSPECTIVE_ATTESTATION",
        "formal_v47_modified": False,
    }
    body["sha256"] = digest(body)
    return body


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _write_once(path: Path, data: dict) -> None:
    """Exclusive-create output: never overwrite a sealed file or score."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        json.dump(data, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    cmds = ap.add_subparsers(dest="command", required=True)
    p = cmds.add_parser("preflight")
    p.add_argument("--game", choices=("ssq", "dlt"), required=True)
    p.add_argument("--history", type=Path, required=True)
    p.add_argument("--agents", type=Path, default=AGENT_FILE)
    p.add_argument("--out", type=Path, required=True)
    p = cmds.add_parser("freeze")
    p.add_argument("--game", choices=("ssq", "dlt"), required=True)
    p.add_argument("--preflight", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = cmds.add_parser("score")
    p.add_argument("--game", choices=("ssq", "dlt"), required=True)
    p.add_argument("--frozen", type=Path, required=True)
    p.add_argument("--actual", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    game = _game(args.game)
    if args.command == "preflight":
        report = preflight(args.history, args.agents, game)
    elif args.command == "freeze":
        report = freeze(_load(args.preflight), _load(args.candidate), game)
    else:
        report = score(_load(args.frozen), _load(args.actual), game)
    _write_once(args.out, report)
    print(json.dumps({"kind": report["kind"], "game": game.name,
                      "target_issue": report["target_issue"],
                      "sha256": report["sha256"], "status": "RESEARCH_ONLY"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
