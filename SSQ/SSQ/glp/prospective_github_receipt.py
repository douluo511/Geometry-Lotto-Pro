"""Read-only GitHub server-time / immutable-commit SSQ Freeze receipt verification.

This is an evidence acquisition primitive, NOT a prediction promotion authority.
Git commit author/committer dates are user controlled. GitHub Actions created_at
plus an immutable head_sha and Git-blob binding are independently retrievable,
but a separate official 6+1 outcome verifier, full cohort completeness and
external governance are still required before any Replay can be counted.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from glp.constants import BACK_MAX, BACK_PICK, FRONT_MAX, FRONT_PICK
from glp.net_client import NetClient
from glp.util import sha256_json

_REPO = "douluo511/Geometry-Lotto-Pro"  # monorepo research STAGING, not independent Release
_BRANCH = "evidence/ssq-prospective-freezes"
_WORKFLOW = ".github/workflows/ssq-prospective-freeze.yml@refs/heads/" + _BRANCH
_API = "https://api.github.com/repos/" + _REPO
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ISSUE = re.compile(r"20[0-9]{5}\Z")
_UTC8 = timezone(timedelta(hours=8))


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("GitHub/Freeze timestamp must be UTC Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("malformed GitHub/Freeze UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError("non-UTC timestamp")
    return parsed


def _json_get(client: NetClient, url: str) -> dict[str, Any]:
    response = client.get(
        url,
        allow_redirects=False,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    data = response.content
    if not isinstance(data, bytes) or len(data) > 350000:
        raise ValueError("GitHub evidence response bytes invalid or oversized")
    try:
        parsed = json.loads(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed GitHub evidence JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("GitHub evidence must be an object")
    return parsed


def verify_github_freeze_receipt(
    *,
    run_id: int,
    target_issue: str,
    client: NetClient | None = None,
) -> dict[str, Any]:
    """Independently read GitHub run and frozen JSON from the run's exact SHA.

    All inputs except run_id and target_issue are retrieved over bounded HTTPS.
    A caller-provided run JSON, a commit's forgeable date, local hashes and a
    self-declared verified flag are never trusted as timestamp authority.

    Explicit output is CANDIDATE_ONLY with qualified_count=0; never wire this
    directly to Evidence Court as verified historical/predictive performance.
    """
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("invalid GitHub run id")
    if not isinstance(target_issue, str) or not _ISSUE.fullmatch(target_issue):
        raise ValueError("invalid SSQ target issue")
    net = client if client is not None else NetClient(
        connect_timeout=8, read_timeout=15, max_attempts=2,
        max_redirects=0,
    )
    run = _json_get(net, f"{_API}/actions/runs/{run_id}")
    repo = run.get("repository")
    if (
        run.get("id") != run_id
        or not isinstance(repo, dict)
        or repo.get("full_name") != _REPO
        or run.get("event") != "push"
        or run.get("head_branch") != _BRANCH
        or run.get("path") != _WORKFLOW
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise ValueError("GitHub run is not an authorized successful pre-draw receipt")
    sha = run.get("head_sha")
    if not isinstance(sha, str) or not _HEX40.fullmatch(sha):
        raise ValueError("GitHub run lacks an exact immutable commit SHA")
    observed_at = _utc(run.get("created_at"))  # GitHub SERVER time, not git author date

    path = f"SSQ/prospective_ledger/freezes/{target_issue}.json"
    source = _json_get(net, f"{_API}/contents/{path}?ref={sha}")
    if (
        source.get("type") != "file"
        or source.get("path") != path
        or source.get("encoding") != "base64"
    ):
        raise ValueError("GitHub commit does not bind expected immutable Freeze path")
    blob_sha = source.get("sha")
    if not isinstance(blob_sha, str) or not _HEX40.fullmatch(blob_sha):
        raise ValueError("GitHub Freeze blob sha missing")
    try:
        raw = base64.b64decode(source.get("content"), validate=False)
    except (ValueError, binascii.Error, TypeError) as exc:
        raise ValueError("malformed GitHub Freeze blob content") from exc
    if not raw or len(raw) > 50000 or len(raw) != source.get("size"):
        raise ValueError("GitHub Freeze blob has unexpected size")
    computed_git_blob = hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()
    if computed_git_blob != blob_sha:
        raise ValueError("GitHub Freeze blob content SHA does not match exact commit")
    try:
        freeze = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("malformed frozen SSQ prediction JSON") from exc
    if not isinstance(freeze, dict) or freeze.get("schema") != "ssq-prospective-freeze-v1":
        raise ValueError("unexpected SSQ research freeze schema")
    prediction = freeze.get("prediction")
    if not isinstance(prediction, dict):
        raise ValueError("missing frozen prediction payload")
    date_text = prediction.get("target_date")
    try:
        target_date = date.fromisoformat(date_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid target date") from exc
    if (
        prediction.get("target_issue") != target_issue
        or target_date.year != int(target_issue[:4])
        or observed_at.astimezone(_UTC8).date() >= target_date
        or _utc(prediction.get("created_at")) > observed_at
    ):
        raise ValueError("target mismatch or GitHub server attestation after draw-day cutoff")

    for key in ("canonical_hash", "score_hash", "model_hash", "selector_hash"):
        if not isinstance(prediction.get(key), str) or not _HEX64.fullmatch(prediction[key]):
            raise ValueError(f"missing frozen prediction {key}")
    commit = freeze.get("model_source_commit")
    if not isinstance(commit, str) or not _HEX40.fullmatch(commit):
        raise ValueError("model source commit not pinned")
    if prediction.get("edge_state") != "NO_EDGE" or prediction.get("dan_state") != "NULL_DAN":
        raise ValueError("research receipt cannot self-promote an unverified model")

    front = prediction.get("front_ranking")
    back = prediction.get("back_ranking")
    if not isinstance(front, dict) or not isinstance(back, dict):
        raise ValueError("missing complete model rankings")
    fr, br = front.get("numbers"), back.get("numbers")
    if (
        not isinstance(fr, list)
        or not isinstance(br, list)
        or any(type(x) is not int for x in fr + br)
        or len(fr) != FRONT_MAX
        or set(fr) != set(range(1, FRONT_MAX + 1))
        or len(br) != BACK_MAX
        or set(br) != set(range(1, BACK_MAX + 1))
        or prediction.get("front") != fr[:FRONT_PICK]
        or prediction.get("back") != br[:BACK_PICK]
    ):
        raise ValueError("invalid frozen ranking permutation/combination")

    score_hash = prediction["score_hash"]
    if prediction.get("prediction_id") != sha256_json(
        {"score_hash": score_hash, "created_for": target_issue}
    )[:32]:
        raise ValueError("frozen prediction id differs from score hash")
    freeze_core = {
        "prediction_id": prediction["prediction_id"],
        "target_issue": target_issue,
        "target_date": date_text,
        "canonical_hash": prediction["canonical_hash"],
        "model_hash": prediction["model_hash"],
        "selector_hash": prediction["selector_hash"],
        "score_hash": score_hash,
        "edge_state": "NO_EDGE",
        "dan_state": "NULL_DAN",
    }
    if prediction.get("freeze_hash") != sha256_json(freeze_core):
        raise ValueError("frozen prediction hash mismatch")

    return {
        "schema": "ssq-github-predraw-receipt-v1",
        "authority": "GITHUB_SERVER_RUN_PLUS_EXACT_COMMIT_BLOB",
        "github_run_id": run_id,
        "github_run_created_at": run["created_at"],
        "head_sha": sha,
        "git_blob_sha1": blob_sha,
        "target_issue": target_issue,
        "target_date": date_text,
        "model_source_commit": commit,
        "freeze_hash": prediction["freeze_hash"],
        "verified_scope": "PRE_DRAW_EXISTENCE_CANDIDATE_ONLY",
        # Official draw receipt, cohort completeness, immutable governance,
        # score recomputation and external independent repository all remain.
        "qualified_count": 0,
        "official_outcome_verified": False,
        "promotion_authorized": False,
        "production_rho": 0.0,
    }
