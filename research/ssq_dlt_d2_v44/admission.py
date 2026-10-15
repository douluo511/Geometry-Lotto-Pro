"""Fail-closed V4.4 research contracts, never formal admission.

Contract checks and synthetic cryptographic verification are not official-source,
external publication-time, RFC3161, preregistration, or prospective evidence.
The report deliberately cannot promote R2, formal A, or a scientific edge.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from math import comb
from urllib.parse import urlsplit

from .scoring import AdmissionBlocked, RULES, paired_exact_one_sided, validate_numbers


FORMAL_SLOTS = ("M04", "M05-1", "M05-2", "M05-3", "M05-4", "M05-5", "M06", "M07")
# Exact hosts from the existing product adapters; this is no live availability claim.
OFFICIAL_HOSTS = {
    "SSQ": frozenset(("www.cwl.gov.cn", "www.swlc.net.cn", "www.yzfcw.com")),
    "DLT": frozenset(("webapi.sporttery.cn", "api.js-lottery.com")),
}


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AdmissionBlocked("NON_CANONICAL_JSON") from exc


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _digest(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _time(value: object) -> datetime:
    if type(value) is not str:
        raise AdmissionBlocked("MISSING_OR_INVALID_TIME")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone required")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise AdmissionBlocked("TIMEZONE_AWARE_TIME_REQUIRED") from exc


def _https_host(url: object, game: str) -> str:
    if type(url) is not str or any(c.isspace() for c in url):
        raise AdmissionBlocked("INVALID_SOURCE_URL")
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS[game]
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError("not an allowed exact official host")
    except (KeyError, ValueError) as exc:
        raise AdmissionBlocked("NON_OFFICIAL_HTTPS_SOURCE") from exc
    return parsed.hostname


def _json_pointer(document: object, pointer: object) -> object:
    """Read only an explicitly recorded RFC6901 path in the original JSON bytes."""
    if type(pointer) is not str or not pointer.startswith("/"):
        raise AdmissionBlocked("RAW_FIELD_PATH_REQUIRED")
    current = document
    try:
        for token in pointer[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            current = current[int(token)] if type(current) is list else current[token]
        return current
    except (TypeError, KeyError, IndexError, ValueError) as exc:
        raise AdmissionBlocked("PUBLICATION_OR_DRAW_NOT_IN_RAW_BYTES") from exc


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict:
    document = {}
    for key, value in pairs:
        if key in document:
            raise AdmissionBlocked("DUPLICATE_RAW_JSON_KEY")
        document[key] = value
    return document


def validate_source_pair(game: str, issue: str, sources: list[dict], *,
                         as_of: str, cutoff: str, now: str) -> dict:
    """Check a two-source original-byte/chronology contract without certifying it.

    A source has requested_url, final_url, redirect_chain, origin, raw_bytes,
    raw_sha256, publication_time, observed_time and RFC6901 publication_path,
    issue_path, draw_path.  Its parser must record these paths into the original
    JSON. HTML/XML adapters are intentionally unsupported until separately audited.
    A raw publication field is a source statement, not external proof that these
    bytes were public at that time. No caller boolean changes that distinction.
    """
    if type(game) is not str or game not in RULES or type(issue) is not str or not issue:
        raise AdmissionBlocked("INVALID_GAME_OR_ISSUE")
    boundary, deadline, current = _time(as_of), _time(cutoff), _time(now)
    if not boundary <= deadline <= current:
        raise AdmissionBlocked("INVALID_AS_OF_CUTOFF_CHRONOLOGY")
    if type(sources) is not list or len(sources) != 2:
        raise AdmissionBlocked("TWO_OFFICIAL_ORIGINALS_REQUIRED")
    hosts, receipts, results = [], [], []
    upper, drawn = RULES[game]
    for source in sources:
        if type(source) is not dict or source.get("origin") != "official_original":
            raise AdmissionBlocked("DISCOVERY_IS_NOT_EVIDENCE")
        host = _https_host(source.get("requested_url"), game)
        redirects = source.get("redirect_chain")
        if type(redirects) is not list:
            raise AdmissionBlocked("REDIRECT_CHAIN_REQUIRED")
        for url in [*redirects, source.get("final_url")]:
            if _https_host(url, game) != host:
                raise AdmissionBlocked("CROSS_HOST_REDIRECT_REJECTED")
        raw = source.get("raw_bytes")
        if type(raw) is not bytes or not raw:
            raise AdmissionBlocked("ORIGINAL_BYTES_REQUIRED")
        digest = hashlib.sha256(raw).hexdigest()
        if source.get("raw_sha256") != digest:
            raise AdmissionBlocked("RAW_HASH_MISMATCH")
        try:
            document = json.loads(raw, object_pairs_hook=_unique_json_pairs)
        except AdmissionBlocked:
            raise
        except (UnicodeError, ValueError) as exc:
            raise AdmissionBlocked("UNSUPPORTED_RAW_SOURCE_FORMAT") from exc
        publication_value = _json_pointer(document, source.get("publication_path"))
        if publication_value != source.get("publication_time"):
            raise AdmissionBlocked("PUBLICATION_NOT_BOUND_TO_RAW_BYTES")
        published, observed = _time(publication_value), _time(source.get("observed_time"))
        if not published <= observed <= boundary <= deadline <= current:
            raise AdmissionBlocked("FUTURE_OR_LATE_SOURCE_RECORD")
        if _json_pointer(document, source.get("issue_path")) != issue:
            raise AdmissionBlocked("SOURCE_ISSUE_MISMATCH")
        draw = _json_pointer(document, source.get("draw_path"))
        validate_numbers(draw, drawn, upper)
        hosts.append(host)
        results.append(sorted(draw))
        receipts.append({"host": host, "raw_sha256": digest,
                         "publication_time": publication_value,
                         "observed_time": source["observed_time"]})
    if len(set(hosts)) != 2:
        raise AdmissionBlocked("INDEPENDENT_OFFICIAL_HOSTS_REQUIRED")
    if results[0] != results[1]:
        raise AdmissionBlocked("OFFICIAL_SOURCE_CONFLICT")
    return {"contract_status": "PASS", "game": game, "issue": issue,
            "draw_front": results[0], "receipts": receipts,
            "external_publication_proof": "BLOCKED", "official_network": "NOT_RUN",
            "formal_a_samples": 0}


def validate_registry(registry: dict, expected_sha256: str) -> dict:
    """Bind the local registry to a separately supplied hash; no external seal claim."""
    if (type(registry) is not dict or not _digest(expected_sha256)
            or fingerprint(registry) != expected_sha256):
        raise AdmissionBlocked("REGISTRY_HASH_MISMATCH")
    if (type(registry.get("game")) is not str or registry["game"] not in RULES
            or registry.get("family") != "FORMAL-12"
            or type(registry.get("versions")) is not dict
            or set(registry["versions"]) != set(FORMAL_SLOTS)
            or any(type(v) is not str or not v for v in registry["versions"].values())):
        raise AdmissionBlocked("ORIGINAL_EIGHT_SLOT_REGISTRY_REQUIRED")
    if registry.get("primary_m05_slot") not in FORMAL_SLOTS[1:6]:
        raise AdmissionBlocked("M05_PRIMARY_D2_REQUIRED")
    tests = registry.get("test_ids")
    if (type(tests) is not list or len(tests) != 12
            or any(type(t) is not str or not t for t in tests) or len(set(tests)) != 12
            or type(registry.get("sequential_plan")) is not dict
            or not registry["sequential_plan"]):
        raise AdmissionBlocked("PREREGISTERED_12_TESTS_AND_SEQUENTIAL_PLAN_REQUIRED")
    if not _time(registry.get("registered_at")) < _time(registry.get("cutoff")):
        raise AdmissionBlocked("REGISTRY_NOT_BEFORE_CUTOFF")
    return {"contract_status": "PASS", "sha256": expected_sha256,
            "external_registration": "BLOCKED", "formal_family_semantics": "BLOCKED",
            "formal_test_ids_verified": False,
            "limitation": "Twelve local IDs do not establish the original frozen formal family"}


def validate_candidate_slots(game: str, slots: dict, versions: dict,
                             primary_m05_slot: str) -> str:
    """Each identity has independent D1..D5 lists; nesting is not required."""
    if (type(game) is not str or game not in RULES or type(versions) is not dict
            or set(versions) != set(FORMAL_SLOTS)
            or any(type(v) is not str or not v for v in versions.values())
            or type(slots) is not dict or set(slots) != set(FORMAL_SLOTS)):
        raise AdmissionBlocked("ORIGINAL_EIGHT_SLOTS_REQUIRED")
    if primary_m05_slot not in FORMAL_SLOTS[1:6]:
        raise AdmissionBlocked("M05_PRIMARY_D2_REQUIRED")
    for slot in FORMAL_SLOTS:
        prediction = slots[slot]
        if (type(prediction) is not dict
                or set(prediction) != {"version", "D1", "D2", "D3", "D4", "D5"}
                or prediction["version"] != versions[slot]):
            raise AdmissionBlocked("SLOT_VERSION_OR_D1_D5_MISMATCH")
        for k in range(1, 6):
            validate_numbers(prediction[f"D{k}"], k, RULES[game][0])
    return fingerprint({"game": game, "slots": slots, "versions": versions,
                        "primary_m05_slot": primary_m05_slot})


def validate_challengers(challengers: list[dict], formal_registry: dict) -> str:
    """New trials remain in a separate namespace, with separately frozen versions."""
    if (type(challengers) is not list or type(formal_registry) is not dict
            or formal_registry.get("family") != "FORMAL-12"):
        raise AdmissionBlocked("INVALID_CHALLENGER_REGISTRY")
    seen = set()
    for trial in challengers:
        if type(trial) is not dict:
            raise AdmissionBlocked("INVALID_CHALLENGER_TRIAL")
        trial_id = trial.get("trial_id")
        if (type(trial_id) is not str or not trial_id.startswith("CHALLENGER/")
                or not trial_id.removeprefix("CHALLENGER/") or trial_id in seen
                or type(trial.get("family")) is not str or not trial["family"]
                or trial.get("family") == formal_registry.get("family")
                or type(trial.get("version")) is not str or not trial["version"]):
            raise AdmissionBlocked("CHALLENGER_FORMAL_IDENTITY_COLLISION")
        if not _time(trial.get("registered_at")) < _time(trial.get("cutoff")):
            raise AdmissionBlocked("CHALLENGER_NOT_PREREGISTERED")
        seen.add(trial_id)
    return fingerprint(challengers)


def prediction_commitment(row: dict) -> str:
    """Hash the pre-draw payload alone; the observed draw must never enter a seal."""
    if type(row) is not dict:
        raise AdmissionBlocked("INVALID_PREDICTION_PAYLOAD")
    return fingerprint({key: row.get(key) for key in ("game", "issue", "slots")})


def replay_dual_holdout(game: str, rows: list[dict], *, expected_issues: list[str],
                        versions: dict, primary_m05_slot: str,
                        holdouts: dict[str, list[str]], expected_holdouts_sha256: str,
                        prediction_commitments: dict[str, str],
                        claimed: dict | None = None) -> dict:
    """Independently recompute every issue, D1..D5 and same-issue D2 against M07.

    This reads predictions; it never calls a model or updates a prediction. A
    submitted aggregate is checked against recomputed integer counts, not trusted.
    Holdout and prediction hashes must be supplied from separate registration;
    their presence does not prove an external seal or its pre-draw timestamp.
    """
    if (type(game) is not str or game not in RULES
            or type(expected_issues) is not list or not expected_issues
            or any(type(i) is not str or not i for i in expected_issues)
            or len(set(expected_issues)) != len(expected_issues)
            or type(rows) is not list or len(rows) != len(expected_issues)):
        raise AdmissionBlocked("INVALID_REPLAY_ISSUE_RECTANGLE")
    if type(holdouts) is not dict or set(holdouts) != {"holdout_a", "holdout_b"}:
        raise AdmissionBlocked("TWO_FROZEN_HOLDOUTS_REQUIRED")
    if (not _digest(expected_holdouts_sha256)
            or fingerprint(holdouts) != expected_holdouts_sha256):
        raise AdmissionBlocked("HOLDOUT_REGISTRY_HASH_MISMATCH")
    if (type(prediction_commitments) is not dict
            or set(prediction_commitments) != set(expected_issues)
            or not all(_digest(h) for h in prediction_commitments.values())):
        raise AdmissionBlocked("PREDICTION_COMMITMENT_RECTANGLE_REQUIRED")
    all_holdout_ids = []
    for ids in holdouts.values():
        if (type(ids) is not list or not ids
                or any(type(i) is not str or not i for i in ids)):
            raise AdmissionBlocked("INVALID_HOLDOUT_ISSUES")
        all_holdout_ids.extend(ids)
    if (len(set(all_holdout_ids)) != len(all_holdout_ids)
            or set(all_holdout_ids) != set(expected_issues)):
        raise AdmissionBlocked("OVERLAPPING_OR_CHANGED_HOLDOUTS")
    by_issue = {}
    for row in rows:
        if (type(row) is not dict or row.get("game") != game
                or type(row.get("issue")) is not str
                or row["issue"] not in expected_issues or row["issue"] in by_issue):
            raise AdmissionBlocked("WRONG_OR_DUPLICATE_REPLAY_ISSUE")
        validate_numbers(row.get("draw_front"), RULES[game][1], RULES[game][0])
        validate_candidate_slots(game, row.get("slots"), versions, primary_m05_slot)
        if prediction_commitment(row) != prediction_commitments[row["issue"]]:
            raise AdmissionBlocked("PRE_DRAW_PREDICTION_HASH_MISMATCH")
        winning = set(row["draw_front"])
        # Deliberately independent from scoring.score_d1_d5 and rank prefixes.
        by_issue[row["issue"]] = {
            slot: {f"D{k}": {
                "hits": sum(number in winning for number in row["slots"][slot][f"D{k}"]),
                "full": int(all(number in winning
                                for number in row["slots"][slot][f"D{k}"]))}
                for k in range(1, 6)} for slot in FORMAL_SLOTS}
    summary = {}
    for holdout, ids in holdouts.items():
        models = {}
        for slot in FORMAL_SLOTS:
            wins = sum(by_issue[i][slot]["D2"]["full"] == 1
                       and by_issue[i]["M07"]["D2"]["full"] == 0 for i in ids)
            losses = sum(by_issue[i][slot]["D2"]["full"] == 0
                         and by_issue[i]["M07"]["D2"]["full"] == 1 for i in ids)
            models[slot] = {
                "n": len(ids), "version": versions[slot],
                "D1_D5_full": {f"D{k}": sum(by_issue[i][slot][f"D{k}"]["full"] for i in ids)
                               for k in range(1, 6)},
                "D1_D5_hits": {f"D{k}": sum(by_issue[i][slot][f"D{k}"]["hits"] for i in ids)
                               for k in range(1, 6)},
                "D2_vs_M07": {"wins": wins, "losses": losses,
                              "ties": len(ids) - wins - losses,
                              "paired_delta": (wins - losses) / len(ids),
                              "p_one_sided_exploratory": paired_exact_one_sided(wins, losses)}}
        summary[holdout] = models
    if claimed is not None and canonical_bytes(claimed) != canonical_bytes(summary):
        raise AdmissionBlocked("HOLDOUT_CLAIM_MISMATCH")
    upper, drawn = RULES[game]
    return {"contract_status": "PASS", "summary": summary, "per_issue": by_issue,
            "input_sha256": fingerprint(rows), "holdouts_sha256": fingerprint(holdouts),
            "D2_random_p0": comb(drawn, 2) / comb(upper, 2),
            "formal_a_samples": 0, "decision": "NO_EDGE"}


def verify_ed25519_authorization(envelope: dict, *, expected_role: str,
                                  payload_sha256: str, trusted_keys: dict,
                                  now: str, cutoff: str, consumed_nonces: set[str]) -> dict:
    """Verify bytes using cryptography; never accept a supplied 'verified' flag.

    trusted_keys is independently provisioned {role: {key_id: raw_public_key}}.
    The caller must atomically persist returned nonce with the authorized action.
    This pure verifier does not claim durable replay protection or formal trust.
    """
    if (type(expected_role) is not str or expected_role not in {"01", "04"}
            or not _digest(payload_sha256)):
        raise AdmissionBlocked("INVALID_AUTHORIZATION_SCOPE")
    if (type(envelope) is not dict or set(envelope) != {"claims", "signature"}
            or type(envelope.get("claims")) is not dict):
        raise AdmissionBlocked("SIGNED_AUTHORIZATION_REQUIRED")
    claims = envelope["claims"]
    if (set(claims) != {"schema", "role", "key_id", "payload_sha256", "nonce",
                       "issued_at", "expires_at", "cutoff"}
            or claims["schema"] != "ssq-dlt-auth-v1" or claims["role"] != expected_role
            or claims["payload_sha256"] != payload_sha256
            or claims["cutoff"] != cutoff
            or type(claims["nonce"]) is not str or len(claims["nonce"]) < 16
            or type(claims["key_id"]) is not str):
        raise AdmissionBlocked("AUTHORIZATION_SCOPE_MISMATCH")
    nonce = claims["nonce"]
    if type(consumed_nonces) is not set or nonce in consumed_nonces:
        raise AdmissionBlocked("AUTHORIZATION_REPLAY")
    issued, expires, current, deadline = (_time(claims["issued_at"]),
                                         _time(claims["expires_at"]),
                                         _time(now), _time(cutoff))
    if not issued <= current < expires <= deadline:
        raise AdmissionBlocked("AUTHORIZATION_EXPIRED_OR_FUTURE")
    try:
        key = trusted_keys[expected_role][claims["key_id"]]
        if type(key) is not bytes or len(key) != 32:
            raise KeyError("invalid Ed25519 public key")
    except (KeyError, TypeError) as exc:
        raise AdmissionBlocked("UNTRUSTED_AUTHORITY_KEY") from exc
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
        if len(signature) != 64:
            raise ValueError("signature length")
    except (TypeError, ValueError) as exc:
        raise AdmissionBlocked("INVALID_SIGNATURE_ENCODING") from exc
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:
        raise AdmissionBlocked("CRYPTOGRAPHIC_VERIFIER_UNAVAILABLE") from exc
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, canonical_bytes(claims))
    except (InvalidSignature, ValueError) as exc:
        raise AdmissionBlocked("INVALID_AUTHORITY_SIGNATURE") from exc
    return {"cryptographic_signature": "PASS", "role": expected_role,
            "key_id": claims["key_id"], "consume_nonce": nonce,
            "claims_sha256": fingerprint(claims), "formal_admission": "BLOCKED"}


def admission_report() -> dict:
    """Unconditionally fail closed; callers cannot inject statuses or booleans."""
    return {"R2": "BLOCKED", "formal_A": 0, "formal_a_samples": 0,
            "decision": "NO_EDGE", "repository_independence": "FAIL",
            "final_gate": "FAIL", "p0": {
                "P0-01": "BLOCKED", "P0-02": "BLOCKED", "P0-03": "BLOCKED",
                "P0-04": "BLOCKED", "P0-05": "BLOCKED", "P0-06": "BLOCKED",
                "P0-07": "BLOCKED", "P0-08": "BLOCKED", "P0-09": "NOT_RUN"},
            "limitations": ["Synthetic contracts are not formal prospective evidence",
                            "No independently provisioned 01/04 authority keys",
                            "No external RFC3161 TSA or publication-time proof",
                            "Original frozen formal twelve test definitions were not supplied",
                            "No externally frozen registry or independent prospective statistics",
                            "No physical Windows 10/11 boot acceptance in this module"]}
