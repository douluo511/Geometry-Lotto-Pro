"""Real-issue research bot synthetic contracts. No network, no formal forecasts."""
from copy import deepcopy
import base64
import hashlib
from datetime import datetime
import json
from pathlib import Path

import pytest

from research.inverse_formula import rolling_research as roll
from research.inverse_formula.forward_preview import LATEST_DRAW
from research.inverse_formula.fresh_history import CHINA
from research.inverse_formula.probe import SSQ, DLT, load_history


def fake_primary(game, issue, date, front, back):
    values = "".join(f"{x:02d}" for x in front + back)
    if game == SSQ:
        return ("<table><tr><td>" + str(issue) + "</td><td>" + date +
                "</td><td>" + values[:12] + "</td><td>" +
                values[12:] + "</td></tr></table>")
    return ("<table><tr><td>" + date + "</td><td>" + str(issue) +
            "</td><td>" + values + "</td></tr></table>")


def fake_second(issue, date, front, back):
    balls = " ".join(f"{x:02d}" for x in front + back)
    return ("<html><body><h2>" + str(issue) + "</h2>" +
            "<p>开奖日期：" + date + " 开奖号码：" + balls +
            "</p></body></html>")


@pytest.mark.parametrize("game,info", [
    (SSQ, LATEST_DRAW["SSQ"]),
    (DLT, LATEST_DRAW["DLT"]),
])
def test_two_independent_issuer_rows_match_current_issue(game, info):
    html = fake_second(info["issue"], info["date"], info["front"], info["back"])
    roll.verify_independent_latest(game, info, html)


def test_mismatched_independent_issuer_never_promotes_a_forecast():
    info = LATEST_DRAW["DLT"]
    altered = fake_second(info["issue"], info["date"], [1, 2, 3, 4, 5], info["back"])
    with pytest.raises(ValueError, match="BALLS"):
        roll.verify_independent_latest(DLT, info, altered)
    altered = fake_second(info["issue"], "2026-11-10", info["front"], info["back"])
    with pytest.raises(ValueError, match="DATE"):
        roll.verify_independent_latest(DLT, info, altered)


def test_missing_lottery_issue_rejected():
    info = LATEST_DRAW["SSQ"]
    html = fake_second(info["issue"] - 1, info["date"], info["front"], info["back"])
    with pytest.raises(ValueError, match="SSQ_ANNOUNCEMENT_MISSING"):
        roll.verify_independent_latest(SSQ, info, html)


def test_sichuan_second_issuer_without_numeric_issue_still_requires_date_and_balls():
    info = LATEST_DRAW["SSQ"]
    balls = " ".join(f"{n:02d}" for n in info["front"] + info["back"])
    html = ("<html><body><h3>双色球开奖公告</h3>"
            "<p>开奖结果 开奖时间：" + info["date"] + "</p>"
            "<p>" + balls + "</p><p>本期中奖情况</p></body></html>")
    roll.verify_independent_latest(SSQ, info, html)
    with pytest.raises(ValueError, match="BALLS"):
        roll.verify_independent_latest(SSQ, info, html.replace("03 09", "01 09"))


def test_sichuan_second_issuer_wrong_latest_date_rejected():
    info = LATEST_DRAW["SSQ"]
    balls = " ".join(f"{n:02d}" for n in info["front"] + info["back"])
    html = ("双色球开奖公告 开奖结果 开奖时间：2026-11-08 " + balls)
    with pytest.raises(ValueError, match="SSQ_DATE_NOT_FOUND"):
        roll.verify_independent_latest(SSQ, info, html)


def test_first_step_reuses_only_existing_original_issue(tmp_path):
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    output = tmp_path / "out"
    info = LATEST_DRAW["SSQ"]
    p = fake_primary(SSQ, info["issue"], info["date"], info["front"], info["back"])
    q = fake_second(info["issue"], info["date"], info["front"], info["back"])
    now = datetime(2026, 11, 11, 8, 0, tzinfo=CHINA)
    result = roll.process_one(SSQ, ledger, output, first_html=p,
                              independent_html=q, now=now)
    assert result["status"] == "NEW_RESEARCH_PREVIEW_RECORDED", result
    assert result["target_issue"] == 2026130
    saved = ledger / "research" / "forecasts" / "SSQ-2026130.json"
    record = json.loads(saved.read_text())
    assert record["formal_A"] == 0
    assert record["official_sales_cutoff_verified"] is False
    assert record["external_predraw_tsa"] == "NOT_RUN"
    assert len(record["prediction"]["front"]) == 6
    verified = roll.verify_saved_research_ledger(ledger)
    assert verified["source_raw_envelopes"] == 2
    assert verified["scored_issues"] == 0
    assert record["research_null"]["not_formal_v47_null"] is True


def test_real_previous_snapshot_score_and_no_reissue(tmp_path):
    root = tmp_path / "ledger"
    path = root / "research" / "forecasts" / "original.json"
    path.parent.mkdir(parents=True)
    record = {
        "schema": "SSQDLT_RESEARCH_SNAPSHOT_2026_11_11_V1",
        "formal_A": 0,
        "issued": [{
            "game": "SSQ", "target_issue": 2026130,
            "content_sha256": "a" * 64,
            "prediction": {
                "front": [1, 2, 3, 4, 5, 6], "back": [7],
                "d2_pair": [1, 2],
            },
            "research_null": {},
        }],
    }
    from research.inverse_formula.formula_bank import _research_null
    ticket, pair = _research_null(2026130, SSQ)
    record["issued"][0]["research_null"] = {
        "front": list(ticket[0]), "back": list(ticket[1]),
        "d2_pair": list(pair),
    }
    path.write_text(json.dumps(record))
    latest = {
        "issue": 2026130, "date": "2026-11-12",
        "front": [1, 2, 3, 4, 5, 6], "back": [7]
    }
    known, _ = load_history(roll.Path(__file__).parents[1] /
                            "research/inverse_formula/ssq_2026.txt", SSQ)
    previous = known[-1]
    primary = (fake_primary(SSQ, previous.issue, "2026-11-10",
                            list(previous.front), list(previous.back))
               + fake_primary(SSQ, latest["issue"], latest["date"],
                              latest["front"], latest["back"]))
    secondary = fake_second(latest["issue"], latest["date"],
                            latest["front"], latest["back"])
    today = datetime(2026, 11, 13, 8, 0, tzinfo=CHINA)
    result = roll.process_one(SSQ, root, tmp_path / "out",
                              first_html=primary, independent_html=secondary,
                              now=today)
    assert result["status"] == "NEW_RESEARCH_PREVIEW_RECORDED", result
    assert result["scored_prior_issues"] == [2026130]
    score_path = root / "research" / "scores" / "SSQ-2026130.json"
    score = json.loads(score_path.read_text())
    assert score["scoring"]["research_full_hit"] == 1
    assert score["scoring"]["research_d2_hit"] == 1
    assert score["formal_A"] == 0
    assert (root / "research" / "forecasts" / "SSQ-2026131.json").is_file()
    audit = roll.verify_saved_research_ledger(root)
    assert audit["forecast_issues"] == 2
    assert audit["scored_issues"] == 1
    tampered = json.loads(score_path.read_text())
    tampered["scoring"]["research_full_hit"] = 0
    score_path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="SCORE_CHANGED"):
        roll.verify_saved_research_ledger(root)


def test_duplicate_issue_is_not_silently_counted(tmp_path):
    root = tmp_path / "ledger"
    directory = root / "research" / "forecasts"
    directory.mkdir(parents=True)
    entry = {
        "schema": "SSQDLT_ROLLING_RESEARCH_ISSUE_V1",
        "game": "DLT", "target_issue": 26130,
        "formal_A": 0, "prediction": {}, "research_null": {},
    }
    for f in ("a.json", "b.json"):
        (directory / f).write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="DUPLICATE_RESEARCH_FORECAST"):
        roll._replay_snapshot_targets(root)


def test_raw_source_custody_roundtrips_exact_bytes(tmp_path):
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    game = DLT
    data = b"\x00\\r\\nUnchanged <html>\x01"
    sha = roll.preserve_raw_http_once(
        ledger, game, "issuer-primary", roll.SOURCES["DLT"], data
    )
    assert sha == hashlib.sha256(data).hexdigest()
    p = ledger / "research" / "raw" / "DLT" / "issuer-primary" / (sha + ".json")
    saved = json.loads(p.read_text())
    assert base64.b64decode(saved["raw_base64"]) == data
    assert saved["size_bytes"] == len(data)
    assert roll.preserve_raw_http_once(
        ledger, game, "issuer-primary", roll.SOURCES["DLT"], data
    ) == sha
    saved["raw_base64"] = base64.b64encode(b"altered").decode("ascii")
    p.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="RAW_SOURCE_CHANGED"):
        roll.preserve_raw_http_once(
            ledger, game, "issuer-primary", roll.SOURCES["DLT"], data
        )


def test_forecast_must_be_issued_before_conservative_next_draw_window():
    # This is a research-only time bound, NOT an official sales cutoff.
    with pytest.raises(ValueError, match="WINDOW_ALREADY_PASSED"):
        roll.conservative_research_issue_window(
            DLT, "2026-11-11",
            datetime(2026, 11, 14, 20, 0, tzinfo=CHINA))
    assert roll.conservative_research_issue_window(
        SSQ, "2026-11-10",
        datetime(2026, 11, 11, 8, 0, tzinfo=CHINA)) == "2026-11-12"


def test_late_attempt_never_writes_new_forecast(tmp_path):
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    info = LATEST_DRAW["DLT"]
    existing, _ = load_history(Path(__file__).parents[1] /
                               "research/inverse_formula/dlt_2026.txt", DLT)
    previous = existing[-1]
    primary = (fake_primary(DLT, previous.issue, "2026-11-09",
                            list(previous.front), list(previous.back))
               + fake_primary(DLT, info["issue"], info["date"],
                              info["front"], info["back"]))
    secondary = fake_second(info["issue"], info["date"],
                            info["front"], info["back"])
    result = roll.process_one(
        DLT, ledger, tmp_path / "out",
        first_html=primary, independent_html=secondary,
        now=datetime(2026, 11, 14, 20, 0, tzinfo=CHINA))
    assert result["status"] == "BLOCKED"
    assert "WINDOW_ALREADY_PASSED" in result["error"]
    assert not (ledger / "research" / "forecasts").exists()


def test_create_only_write_cannot_modify_existing_receipt(tmp_path):
    p = tmp_path / "forecast.json"
    roll._save_once(p, {"first": 1})
    with pytest.raises(FileExistsError, match="overwrite"):
        roll._save_once(p, {"first": 2})
    assert json.loads(p.read_text()) == {"first": 1}


def test_blocked_second_issuer_writes_no_new_ticket(tmp_path):
    info = LATEST_DRAW["DLT"]
    root, output = tmp_path / "ledger", tmp_path / "out"
    root.mkdir()
    bad = fake_second(info["issue"], info["date"], [1, 2, 3, 4, 5], info["back"])
    first = fake_primary(DLT, info["issue"], info["date"], info["front"], info["back"])
    result = roll.process_one(DLT, root, output, first_html=first,
                              independent_html=bad,
                              now=datetime(2026, 11, 12, 8, 0, tzinfo=CHINA))
    assert result["status"] == "BLOCKED"
    assert not (root / "research" / "forecasts").exists()
    assert result["formal_A"] == 0
