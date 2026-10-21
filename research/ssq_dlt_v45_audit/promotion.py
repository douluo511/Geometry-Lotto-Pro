"""Source-cohort quarantine, independent of model names and later lucky runs.

Integrity/reconstruction PASS cannot clear a failed scientific negative control.
No local boolean, different seed or unrelated comparison family is a clearance.
This component does not implement formal admission; every selection stays empty.
"""
from __future__ import annotations

import hashlib
import json
import re

ORIGINAL_PLAN_SHA256 = "5da88c9690bd288a0a384fd64871079926d7e92cb41ee9c2ccdddde57354287e"
ORIGINAL_SEMANTIC_SHA256 = "92fffcdbeaed359195a99244e65aa34dc215102f105f93d810e84301ccfa1fa9"
ORIGINAL_SYNTHETIC_SHA256 = "eb14efbbd3f645535d1e659e3b8143df04e7b8fcecba605f4d42ee41fd75b300"
ORIGINAL_DECISION_SHA256 = "4f2281a3452db40112feade81bb1f6ad7df247018de4dad6c4662d0f73153cb2"
TARGET = "SCRAMBLED_PAIR_STRONG|DLT|R46-REPLICATED-PAIR"
BOUNDARY = dict(formal_A=0, decision="NO_EDGE", qualified_prospective_samples=0,
                new_primary_challengers_activated=0, promotion_allowed=False)


class PromotionBlocked(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PromotionBlocked("EXACT_SHA256_IDENTITY_REQUIRED")
    return value


def registry():
    """Fresh immutable-by-copy evidence description, never a global name ban."""
    return dict(schema="V45_SOURCE_COHORT_QUARANTINE_1", cohorts=[dict(
        original_plan_sha256=ORIGINAL_PLAN_SHA256,
        canonical_plan_sha256=ORIGINAL_SEMANTIC_SHA256,
        synthetic_sha256=ORIGINAL_SYNTHETIC_SHA256,
        original_decision_sha256=ORIGINAL_DECISION_SHA256,
        target=TARGET, model_hits=69, null_hits=42, n=2880,
        fair_p_one_sided="0.00284511217227866453955",
        original_negative_holm12="0.0341413460673439744746",
        status="QUARANTINED_SOURCE_COHORT", scientific_negative_control="FALSIFIED_REPRODUCED_NOT_FIXED",
        cause="UNRESOLVED", reconstruction_pass_is_clearance=False,
        family_namespace="ORIGINAL_SYNTHETIC_NEGATIVE_12_NOT_FORMAL_12",
        scope="This source plan and descendants; not unrelated versions sharing a model name",
        clearance="NO_LOCAL_AUTOMATIC_CLEARANCE")], **BOUNDARY)


def cohort_status(lineage):
    """Assess explicit provenance; absence is unknown, never an exoneration.

    Hash metadata alone is not an authenticated lineage. Even a non-match is
    insufficient for promotion, which still needs independent formal admission.
    """
    if lineage is None:
        return dict(status="BLOCKED_LINEAGE_UNAVAILABLE", quarantined=None, reasons=["MISSING_LINEAGE"], **BOUNDARY)
    expected = {"experiment_plan_sha256", "canonical_plan_sha256", "ancestor_plan_sha256", "synthetic_sha256"}
    if type(lineage) is not dict or set(lineage) != expected:
        raise PromotionBlocked("EXPLICIT_LINEAGE_CONTRACT_REQUIRED")
    plan = _hash(lineage["experiment_plan_sha256"])
    semantic = lineage["canonical_plan_sha256"]
    synthetic = lineage["synthetic_sha256"]
    if semantic is not None:
        _hash(semantic)
    if synthetic is not None:
        _hash(synthetic)
    ancestors = lineage["ancestor_plan_sha256"]
    if (type(ancestors) is not list or len(ancestors) > 128
            or any(_hash(value) != value for value in ancestors)
            or len(set(ancestors)) != len(ancestors)):
        raise PromotionBlocked("INVALID_ANCESTOR_PLAN_CHAIN")
    reasons = []
    if plan == ORIGINAL_PLAN_SHA256:
        reasons.append("ORIGINAL_FAILED_PLAN")
    if semantic == ORIGINAL_SEMANTIC_SHA256:
        reasons.append("SAME_PLAN_WITH_DIFFERENT_SERIALIZATION")
    if ORIGINAL_PLAN_SHA256 in ancestors or ORIGINAL_SEMANTIC_SHA256 in ancestors:
        reasons.append("DESCENDANT_OF_FAILED_PLAN")
    if synthetic == ORIGINAL_SYNTHETIC_SHA256:
        reasons.append("REUSED_EXPOSED_SYNTHETIC_EVIDENCE")
    return dict(status="QUARANTINED_SOURCE_COHORT" if reasons else "NO_KNOWN_QUARANTINE_MATCH_NOT_ADMITTED",
                quarantined=bool(reasons), reasons=reasons,
                model_name_used_for_quarantine=False, **BOUNDARY)


def lineage_from_bytes(raw, *, ancestors=(), synthetic_sha256=None):
    """Bind the actual plan, including a format-independent content identity."""
    if type(raw) is not bytes or len(raw) > 4 * 1024 * 1024:
        raise PromotionBlocked("BOUNDED_PLAN_BYTES_REQUIRED")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PromotionBlocked("DUPLICATE_PLAN_JSON_KEY")
            result[key] = value
        return result
    def constant(_):
        raise PromotionBlocked("NONFINITE_PLAN_JSON")
    try:
        plan = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
        if type(plan) is not dict:
            raise PromotionBlocked("PLAN_OBJECT_REQUIRED")
        semantic = hashlib.sha256(canonical(plan)).hexdigest()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise PromotionBlocked("INVALID_PLAN_JSON") from exc
    result = dict(experiment_plan_sha256=hashlib.sha256(raw).hexdigest(),
                  canonical_plan_sha256=semantic, ancestor_plan_sha256=list(ancestors),
                  synthetic_sha256=synthetic_sha256)
    cohort_status(result)
    return result


def selection_result(proposals):
    """The existing report/selection boundary. Never select an inadmissible row.

    A whole round may propose at most one new primary challenger, across BOTH
    games. This does not activate it or substitute for original formal-12 rules.
    """
    if type(proposals) is not list or len(proposals) > 1:
        raise PromotionBlocked("AT_MOST_ONE_NEW_PRIMARY_CHALLENGER_PER_ROUND")
    decisions = []
    for row in proposals:
        if (type(row) is not dict or set(row) != {"model_id", "version", "lineage"}
                or any(type(row[key]) is not str or not row[key].strip() for key in ("model_id", "version"))):
            raise PromotionBlocked("CANDIDATE_ID_VERSION_AND_LINEAGE_REQUIRED")
        decisions.append(dict(model_id=row["model_id"], version=row["version"],
                              source_gate=cohort_status(row["lineage"])))
    return dict(status="BLOCKED_NO_FORMALLY_ADMITTED_NEW_CHALLENGER", selected_candidate=None,
                proposals=decisions, original_formal_twelve="BLOCKED_ORIGINAL_IDS_AND_SHA_UNAVAILABLE",
                clearance_from_integrity_pass=False, **BOUNDARY)
