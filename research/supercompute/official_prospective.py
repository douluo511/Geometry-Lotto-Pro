"""Fail-closed source-consensus, create-only shadow freeze, future read-only scoring.

This extends the existing SSQDLT research evidence workflow; it is NOT a new
formal V4.7 producer. GitHub timestamps are not independent RFC3161 evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from research.supercompute.engine import SPECS

SCHEMA = "SSQDLT_OFFICIAL_CONSENSUS_SHADOW_V1"
ZERO = "0" * 64
CHINA = ZoneInfo("Asia/Shanghai")
SOURCE_IDS = {
    "ssq": ("SHANGHAI_FULI", "HEBEI_FULI"),
    "dlt": ("JIANGSU_SPORT", "GANSU_SPORT"),
}
OFFICIAL_HOSTS = {
    "SHANGHAI_FULI": ("www.swlc.net.cn",),
    "HEBEI_FULI": ("www.yzfcw.com",),
    "JIANGSU_SPORT": ("www.js-lottery.com", "api.js-lottery.com"),
    "GANSU_SPORT": ("www.gstc.org.cn",),
}
MAX_AGE_DAYS = 5
MAX_BYTES = 8 * 1024 * 1024


def json_bytes(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(obj):
    return hashlib.sha256(json_bytes(obj)).hexdigest()


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware UTC timestamp required")
    return dt.astimezone(timezone.utc)


def receipt(payload):
    if "sha256" in payload:
        raise ValueError("digest cannot be supplied by caller")
    return {**payload, "sha256": digest(payload)}


def checked(obj):
    if not isinstance(obj, dict):
        raise ValueError("receipt must be a JSON object")
    sha = obj.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("missing or malformed SHA256")
    if digest({k: v for k, v in obj.items() if k != "sha256"}) != sha:
        raise ValueError("receipt changed after sealing")
    return obj


def strict_object_pairs(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError("duplicate JSON key: " + k)
        obj[k] = v
    return obj


def load(path):
    raw = Path(path).read_bytes()
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("empty or oversized receipt")
    return checked(json.loads(raw, object_pairs_hook=strict_object_pairs,
                              parse_constant=lambda x: (_ for _ in ()).throw(
                                  ValueError("nonfinite JSON literal"))))


def create_once(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_symlink() or any(x.is_symlink() for x in p.parents if x.exists()):
        raise ValueError("refuse symlinked output path")
    data = json_bytes(obj)
    # Exclusive create: crashes may leave partial files, which then fail closed.
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    return p


def check_issue(game, issue):
    if game not in SPECS or not isinstance(issue, str):
        raise ValueError("invalid game/issue")
    pattern = r"20\d{5}" if game == "ssq" else r"\d{5}"
    if not re.fullmatch(pattern, issue):
        raise ValueError("invalid issue identity")
    return issue


def check_ticket(game, ticket):
    if game not in SPECS or not isinstance(ticket, dict):
        raise ValueError("ticket requires game and object")
    fm, fp, bm, bp = SPECS[game]
    for key, limit, pick in (("front", fm, fp), ("back", bm, bp)):
        arr = ticket.get(key)
        if (type(arr) is not list or len(arr) != pick
                or any(type(x) is not int or not 1 <= x <= limit for x in arr)
                or sorted(set(arr)) != arr):
            raise ValueError("invalid " + key + " ball set")
    pair = ticket.get("d2_pair")
    if (type(pair) is not list or len(pair) != 2
            or sorted(set(pair)) != pair
            or not set(pair).issubset(ticket["front"])):
        raise ValueError("D2 pair must be two sorted front balls")
    return {k: list(ticket[k]) for k in ("front", "back", "d2_pair")}


def check_draw(game, item):
    issue = check_issue(game, item.get("issue"))
    date_string = item.get("draw_date")
    if not isinstance(date_string, str) or not re.fullmatch(
            r"20\d{2}-\d{2}-\d{2}", date_string):
        raise ValueError("explicit draw date missing")
    date = datetime.strptime(date_string, "%Y-%m-%d").date()
    if (game == "ssq" and date.weekday() not in (1, 3, 6)
            or game == "dlt" and date.weekday() not in (0, 2, 5)):
        raise ValueError("date not on scheduled draw weekday; holiday exceptions require review")
    if issue.startswith("20") and date_string[:4] != issue[:4]:
        raise ValueError("issue/year inconsistency")
    fm, fp, bm, bp = SPECS[game]
    front, back = item.get("front"), item.get("back")
    if (type(front) is not list or type(back) is not list
            or len(front) != fp or len(back) != bp
            or sorted(set(front)) != front or sorted(set(back)) != back
            or any(type(x) is not int or not 1 <= x <= fm for x in front)
            or any(type(x) is not int or not 1 <= x <= bm for x in back)):
        raise ValueError("invalid official draw numbers")
    return {"issue": issue, "draw_date": date_string,
            "front": list(front), "back": list(back)}


def latest_consensus(game, sources, *, observed_at=None):
    """Require two distinct official lottery-centre groups and same explicit date."""
    if game not in SOURCE_IDS:
        raise ValueError("unsupported game")
    now = observed_at or utc_now()
    if now.tzinfo is None:
        raise ValueError("observation clock timezone required")
    if len(sources) != 2 or {x.get("source_id") for x in sources} != set(SOURCE_IDS[game]):
        raise ValueError("exactly two separately governed official centres required")
    for item in sources:
        if item.get("status") != "PASS":
            raise ValueError("source did not pass network and parser checks")
        if not item.get("raw_records"):
            raise ValueError("source must preserve original raw HTTP evidence")
        from urllib.parse import urlparse
        allowed = set(OFFICIAL_HOSTS[item["source_id"]])
        for record in item["raw_records"]:
            url = urlparse(str(record.get("url", "")))
            if (url.scheme != "https" or url.hostname not in allowed
                    or url.username or url.password
                    or record.get("http_status") != 200
                    or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
                    or type(record.get("bytes")) is not int
                    or not 0 < record["bytes"] <= MAX_BYTES):
                raise ValueError("invalid raw observation")
    a = check_draw(game, sources[0]["draw"])
    b = check_draw(game, sources[1]["draw"])
    if a != b:
        raise ValueError("independent centres disagree in issue, date or balls")
    draw_time = datetime.strptime(a["draw_date"], "%Y-%m-%d").replace(
        tzinfo=CHINA)
    delta = now.astimezone(CHINA) - draw_time
    if not timedelta(0) <= delta <= timedelta(days=MAX_AGE_DAYS):
        raise ValueError("official draw too stale or from the future")
    return receipt({
        "schema": SCHEMA, "game": game,
        "state": "TWO_CENTRE_PUBLIC_SITE_CONSENSUS",
        "observed_utc_untrusted": now.astimezone(timezone.utc).isoformat(),
        "draw": a,
        "raw_source_records": sources,
        "independent_issuer_groups": list(SOURCE_IDS[game]),
        "official_result_authentication": "TWO_PUBLIC_OFFICIAL_CENTRES_NO_DIGITAL_SIGNATURE",
        "independent_tsa_verified": False,
        "authoritative_next_target_verified": False,
        "authoritative_sales_cutoff_verified": False,
        "formal_A": 0, "edge": "NO_EDGE",
    })


def inspect_manifest(snapshot, raw_root):
    checked(snapshot)
    game = snapshot["game"]
    if snapshot.get("schema") != SCHEMA:
        raise ValueError("wrong source contract")
    expected = latest_consensus(
        game, snapshot["raw_source_records"],
        observed_at=iso_utc(snapshot["observed_utc_untrusted"]))
    if expected != snapshot:
        raise ValueError("consensus state altered")
    for source in snapshot["raw_source_records"]:
        for record in source["raw_records"]:
            p = Path(raw_root) / (record["sha256"] + ".bin")
            if not p.is_file() or p.is_symlink():
                raise ValueError("original official response bytes missing")
            raw = p.read_bytes()
            if (len(raw) != record["bytes"]
                    or hashlib.sha256(raw).hexdigest() != record["sha256"]):
                raise ValueError("official raw bytes do not match observation")
    return snapshot


def freeze_shadow(ledger, source, candidate, target_issue, cutoff_utc, *,
                  now=None):
    """Shadow-only model freeze. Caller cutoff is never official authentication."""
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("timezone-aware clock required")
    source = checked(source)
    game = source["game"]
    if source.get("state") != "TWO_CENTRE_PUBLIC_SITE_CONSENSUS":
        raise ValueError("source consensus missing")
    check_issue(game, target_issue)
    if int(target_issue) != int(source["draw"]["issue"]) + 1:
        raise ValueError("target identity cannot be silently skipped or inferred")
    seen = iso_utc(source["observed_utc_untrusted"])
    if not seen <= now.astimezone(timezone.utc) <= seen + timedelta(days=MAX_AGE_DAYS):
        raise ValueError("freshness gate failed")
    cutoff = iso_utc(cutoff_utc)
    if not now.astimezone(timezone.utc) < cutoff:
        raise ValueError("past or reached claimed sales cutoff; freeze refused")
    prediction = check_ticket(game, candidate)
    model_id = candidate.get("model_id")
    model_sha = candidate.get("model_sha256")
    if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", model_id):
        raise ValueError("missing model identity")
    if not isinstance(model_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", model_sha):
        raise ValueError("missing model code SHA256")
    seal = receipt({
        "schema": "SSQDLT_SHADOW_PRE_DRAW_FREEZE_V1",
        "game": game, "target_issue": target_issue,
        "asof_issue": source["draw"]["issue"],
        "source_sha256": source["sha256"],
        "model_id": model_id,
        "model_sha256": model_sha,
        "candidate": prediction,
        "observed_at_utc_untrusted": now.astimezone(timezone.utc).isoformat(),
        "claimed_cutoff_utc_unverified": cutoff.isoformat(),
        "target_authority_verified": False,
        "cutoff_authority_verified": False,
        "predraw_independent_tsa_verified": False,
        "formal_prediction": False, "formal_A": 0, "edge": "NO_EDGE",
    })
    path = Path(ledger) / "research/official_prospective/forecasts" / game / (target_issue + ".json")
    create_once(path, seal)
    return seal


def score_ticket(ticket, result):
    ff = len(set(ticket["front"]) & set(result["front"]))
    bb = len(set(ticket["back"]) & set(result["back"]))
    return {
        "front_hits": ff, "back_hits": bb,
        "d2_hit": int(set(ticket["d2_pair"]).issubset(result["front"])),
        "full_hit": int(ticket["front"] == result["front"]
                        and ticket["back"] == result["back"]),
        "d1_to_d5": {f"D{i}": int(ff >= i) for i in range(1, 6)},
    }


def score_available(ledger, source):
    """Read existing forecasts only. Missing past freezes never get generated."""
    checked(source)
    game = source["game"]
    actual = check_draw(game, source["draw"])
    base = Path(ledger) / "research/official_prospective"
    fdir = base / "forecasts" / game
    sdir = base / "scores" / game
    scored, blocked = [], []
    for path in sorted(fdir.glob("*.json")):
        fc = load(path)
        if fc.get("schema") != "SSQDLT_SHADOW_PRE_DRAW_FREEZE_V1":
            raise ValueError("unexpected prediction record")
        if (fc.get("game") != game or path.name != fc.get("target_issue") + ".json"):
            raise ValueError("forecast filename identity tampered")
        check_ticket(game, fc["candidate"])
        if fc.get("formal_A") != 0 or fc.get("formal_prediction") is not False:
            raise ValueError("formal forecast mixed into research-only ledger")
        if fc["target_issue"] != actual["issue"]:
            blocked.append({"issue": fc["target_issue"], "state": "PENDING_OR_NOT_IN_LATEST_OBSERVATION"})
            continue
        seal_at = iso_utc(fc["observed_at_utc_untrusted"])
        cutoff = iso_utc(fc["claimed_cutoff_utc_unverified"])
        if seal_at >= cutoff:
            raise ValueError("forecast sealed after claimed cutoff")
        # Conservative fraud check, not proof of official cutoff: reject seals
        # observed on or after the game's draw-day local 20:00.
        day = datetime.strptime(actual["draw_date"], "%Y-%m-%d").replace(
            hour=20, tzinfo=CHINA)
        if seal_at >= day.astimezone(timezone.utc):
            raise ValueError("post-cutoff or postdraw historical freeze rejected")
        score_path = sdir / path.name
        if score_path.exists():
            old = load(score_path)
            if old.get("forecast_sha256") != fc["sha256"]:
                raise ValueError("existing score tied to changed forecast")
            scored.append({"issue": actual["issue"], "state": "ALREADY_SCORED"})
            continue
        result = receipt({
            "schema": "SSQDLT_SHADOW_FUTURE_SCORE_V1",
            "game": game, "issue": actual["issue"],
            "forecast_sha256": fc["sha256"],
            "official_consensus_sha256": source["sha256"],
            "official_draw": actual,
            "score": score_ticket(fc["candidate"], actual),
            "formally_admitted": False, "formal_A": 0, "edge": "NO_EDGE",
        })
        create_once(score_path, result)
        scored.append({"issue": actual["issue"], "state": "NEW_SHADOW_SCORE",
                       "d2_hit": result["score"]["d2_hit"]})
    return {"game": game, "scored": scored, "unscored": blocked,
            "formal_A": 0, "prospective_formal_scored": 0, "edge": "NO_EDGE"}


def audit_ledger(ledger):
    """Reject orphaned scores, duplicate or changed receipt, do not drop pending."""
    root = Path(ledger) / "research/official_prospective"
    out = {}
    for game in ("ssq", "dlt"):
        forecasts = {}
        for path in sorted((root / "forecasts" / game).glob("*.json")):
            obj = load(path)
            check_issue(game, obj["target_issue"])
            if path.name != obj["target_issue"] + ".json" or obj["game"] != game:
                raise ValueError("forecast path mismatch")
            check_ticket(game, obj["candidate"])
            if obj.get("formal_A") != 0 or obj.get("formal_prediction") is not False:
                raise ValueError("formal data cannot enter shadow")
            forecasts[obj["target_issue"]] = obj
        scores = {}
        for path in sorted((root / "scores" / game).glob("*.json")):
            obj = load(path)
            issue = check_issue(game, obj["issue"])
            if path.name != issue + ".json" or issue not in forecasts:
                raise ValueError("orphaned score")
            if obj.get("forecast_sha256") != forecasts[issue]["sha256"]:
                raise ValueError("score missing frozen forecast anchor")
            d = check_draw(game, obj["official_draw"])
            if d["issue"] != issue or obj.get("score") != score_ticket(
                    forecasts[issue]["candidate"], d):
                raise ValueError("score differs from immutable forecast replay")
            if obj.get("formal_A") != 0 or obj.get("formally_admitted") is not False:
                raise ValueError("unauthorized formal admission")
            scores[issue] = obj
        out[game] = {"frozen_total": len(forecasts), "scored": len(scores),
                     "pending": len(forecasts) - len(scores),
                     "d2_hits": sum(x["score"]["d2_hit"] for x in scores.values()),
                     "full_hits": sum(x["score"]["full_hit"] for x in scores.values())}
    return {"status": "SHADOW_LEDGER_AUDITED", "games": out,
            "formal_A": 0, "edge": "NO_EDGE"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    cmd = p.add_subparsers(dest="mode", required=True)
    f = cmd.add_parser("freeze")
    f.add_argument("--ledger", type=Path, required=True)
    f.add_argument("--source", type=Path, required=True)
    f.add_argument("--raw", type=Path, required=True)
    f.add_argument("--candidate", type=Path, required=True)
    f.add_argument("--target-issue", required=True)
    f.add_argument("--cutoff-utc", required=True)
    s = cmd.add_parser("score")
    s.add_argument("--ledger", type=Path, required=True)
    s.add_argument("--source", type=Path, required=True)
    s.add_argument("--raw", type=Path, required=True)
    a = cmd.add_parser("audit")
    a.add_argument("--ledger", type=Path, required=True)
    opt = p.parse_args(argv)
    if opt.mode == "audit":
        result = audit_ledger(opt.ledger)
    else:
        source = inspect_manifest(load(opt.source), opt.raw)
        if opt.mode == "freeze":
            candidate = json.loads(opt.candidate.read_text(encoding="utf-8"),
                                   object_pairs_hook=strict_object_pairs)
            result = freeze_shadow(opt.ledger, source, candidate, opt.target_issue,
                                   opt.cutoff_utc)
        else:
            result = score_available(opt.ledger, source)
            result["audit"] = audit_ledger(opt.ledger)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
