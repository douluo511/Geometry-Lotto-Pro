"""Fail-closed local evidence consistency preflight; NEVER a release certification."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
from typing import Any

SCHEMA_VERSION = "acceptance-evidence/1"
MODES = {"OBSERVED", "CONTROLLED_FAULT", "UNIT_FIXTURE"}
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
FINGERPRINT_FIELDS = ("commit_sha", "tree_sha", "config_sha256", "dependencies_sha256",
                      "data_sha256", "model_sha256", "tested_exe_sha256")
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|MOCK|PLACEHOLDER|DEMO)\b|����д|ռλ", re.I)


class InvalidInput(ValueError):
    pass


def strict_json(raw: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidInput("duplicate JSON key: " + key)
            result[key] = value
        return result

    def reject(value):
        raise InvalidInput("non-finite JSON number: " + value)

    def finite_float(value):
        parsed = float(value)
        if not __import__("math").isfinite(parsed):
            raise InvalidInput("non-finite JSON number")
        return parsed

    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                          parse_constant=reject, parse_float=finite_float)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidInput("invalid UTF-8 JSON") from exc


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def candidate_fingerprint(candidate):
    return digest(json.dumps({key: candidate[key] for key in FINGERPRINT_FIELDS},
                             sort_keys=True, separators=(",", ":")).encode("utf-8"))


def instant(value: Any) -> datetime:
    if not isinstance(value, str) or not UTC.fullmatch(value):
        raise InvalidInput("timestamp must be an actual UTC date with Z suffix")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidInput("invalid calendar timestamp") from exc


def result(errors=None, blockers=None, computed=None):
    errors, blockers = errors or [], blockers or []
    status = "FAIL" if errors else "BLOCKED" if blockers else "PASS"
    return {"check": "evidence_preflight", "status": status,
            "final_gate": "NOT_CERTIFIED", "release_authorized": False,
            "limitations": ["Hashes establish integrity, not authenticity or real execution.",
                            "An independent reviewer must verify baseline approval, production behavior, "
                            "Windows GUI execution, business fitness and release authority."],
            "errors": errors, "blockers": blockers, "computed_scores": computed,
            "reportable_scores": computed if status == "PASS" else None}


class Audit:
    def __init__(self, root: Path, now: datetime):
        self.root = root.resolve(strict=True)
        self.now = now
        self.errors: list[str] = []
        self.blockers: list[str] = []

    def fail(self, context, message):
        self.errors.append(context + ": " + message)

    def block(self, context, message):
        self.blockers.append(context + ": " + message)

    def local_bytes(self, uri, expected, context):
        try:
            # No URL decoding, drives, UNC, ADS, hidden alternate roots or traversal.
            if (not isinstance(uri, str) or not uri or ":" in uri or "\\" in uri
                    or PurePosixPath(uri).is_absolute() or PureWindowsPath(uri).is_absolute()
                    or any(part in (".", "..", "") for part in uri.split("/"))):
                raise InvalidInput("artifact must be a clean evidence-root-relative path")
            if not isinstance(expected, str) or not SHA256.fullmatch(expected):
                raise InvalidInput("missing or invalid SHA-256")
            candidate = self.root / uri
            current = self.root
            for part in uri.split("/"):
                current = current / part
                if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                    raise InvalidInput("symlink/junction evidence paths are forbidden")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(self.root) or not resolved.is_file():
                raise InvalidInput("artifact escapes evidence root or is not a regular file")
            raw = resolved.read_bytes()
            if digest(raw) != expected.lower():
                raise InvalidInput("artifact SHA-256 mismatch")
            return raw
        except (OSError, ValueError) as exc:
            self.fail(context, str(exc))
            return None

    def at(self, value, context, lower=None, max_age=None):
        try:
            stamp = instant(value)
            if stamp > self.now:
                raise InvalidInput("timestamp is in the future")
            if lower is not None and stamp < lower:
                raise InvalidInput("timestamp predates frozen baseline")
            if max_age is not None and (self.now - stamp).total_seconds() > max_age:
                raise InvalidInput("timestamp is expired under frozen freshness policy")
            return stamp
        except InvalidInput as exc:
            self.fail(context, str(exc))
            return None


def indexed(rows, key, audit, context):
    data = {}
    for row in rows:
        value = row[key]
        if value in data:
            audit.fail(context, "duplicate " + key + ": " + value)
        data[value] = row
    return data


def same_inventory(actual, expected, audit, context):
    for key in sorted(set(expected) - set(actual)):
        audit.block(context, "missing frozen inventory item: " + key)
    for key in sorted(set(actual) - set(expected)):
        audit.fail(context, "unapproved inventory item: " + key)


def _audit(report, baseline, schema, root, expected_candidate, expected_commit, now):
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(schema)
    violations = sorted(Draft202012Validator(schema).iter_errors(report), key=lambda e: str(e.path))
    if violations:
        return result(errors=["report schema: " + "/".join(map(str, e.path)) + ": " + e.message
                              for e in violations])
    audit = Audit(root, now)
    frozen = audit.at(baseline["frozen_at_utc"], "baseline.frozen_at_utc")
    if report["project_id"] != baseline["project_id"]:
        audit.fail("project", "report does not match approved baseline")
    for key, expected in (("id", baseline["baseline_id"]), ("frozen_at_utc", baseline["frozen_at_utc"])):
        if report["baseline"][key] != expected:
            audit.fail("baseline." + key, "report disagrees with approved baseline")
    candidate = report["candidate"]
    if not expected_candidate or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", expected_commit):
        audit.fail("expected candidate", "independent candidate ID and exact Git commit are required")
    if candidate["id"] != expected_candidate or candidate["commit_sha"] != expected_commit:
        audit.fail("candidate", "report does not match independently supplied candidate/commit")
    for field in ("tree_sha", "config_sha256", "dependencies_sha256", "data_sha256", "model_sha256",
                  "build_run_url", "windows_environment", "release_manifest_sha256"):
        if not candidate[field]:
            audit.block("candidate." + field, "candidate identity or build context is incomplete")
    if report["updated_at_utc"] is None:
        audit.block("report", "updated_at_utc is missing")
        updated = None
    else:
        updated = audit.at(report["updated_at_utc"], "report.updated_at_utc", frozen,
                           baseline["max_report_age_seconds"])
    criteria = indexed(baseline["criteria"], "criterion_id", audit, "baseline.criteria")
    entries = indexed(baseline["entry_points"], "entry_id", audit, "baseline.entry_points")
    sources = indexed(baseline["network_sources"], "source_id", audit, "baseline.network_sources")
    evidence = indexed(report["evidence"], "evidence_id", audit, "evidence")
    checks = indexed(report["checks"], "criterion_id", audit, "checks")
    indexed(report["checks"], "check_id", audit, "checks")
    actual_entries = indexed(report["entry_points"], "entry_id", audit, "entry_points")
    indexed(report["network_attempts"], "attempt_id", audit, "network_attempts")
    same_inventory(checks, criteria, audit, "checks")
    same_inventory(actual_entries, entries, audit, "entry_points")
    valid_evidence = {}
    for eid, ev in evidence.items():
        before = len(audit.errors)
        if ev["candidate_id"] != expected_candidate:
            audit.fail(eid, "wrong candidate binding")
        stamp = audit.at(ev["collected_at_utc"], eid, frozen, baseline["max_evidence_age_seconds"])
        if stamp and updated and stamp > updated:
            audit.fail(eid, "evidence is newer than report")
        if not ev["assertions"] or not all(item.strip() for item in ev["assertions"]):
            audit.fail(eid, "empty assertions")
        raw = audit.local_bytes(ev["artifact_uri"], ev["artifact_sha256"], eid)
        receipt = None
        if raw is not None:
            try:
                receipt = strict_json(raw)
                if not isinstance(receipt, dict) or receipt.get("format") != SCHEMA_VERSION:
                    raise InvalidInput("a candidate-bound acceptance-evidence/1 JSON receipt is required")
                for key in ("evidence_id", "candidate_id", "kind", "collected_at_utc", "environment", "status", "assertions"):
                    if receipt.get(key) != ev[key]:
                        raise InvalidInput("receipt/report mismatch: " + key)
                if receipt.get("commit_sha") != expected_commit:
                    raise InvalidInput("receipt commit differs from independently supplied commit")
                if receipt.get("candidate_fingerprint") != candidate_fingerprint(candidate):
                    raise InvalidInput("receipt configuration/data/model/EXE fingerprint differs from candidate")
                if receipt.get("mode") not in MODES:
                    raise InvalidInput("receipt must classify observed, controlled fault or unit fixture")
                if receipt.get("kind") in {"real_network", "exact_exe", "gui_effect", "business_result"} and receipt["mode"] != "OBSERVED":
                    raise InvalidInput("production evidence cannot use fixture/fault mode")
                if not isinstance(receipt.get("payload"), dict):
                    raise InvalidInput("receipt requires a payload object")
                assets = receipt.get("assets")
                if not isinstance(assets, list) or not assets:
                    raise InvalidInput("receipt requires retained input/output/log assets")
                seen_assets = set()
                for asset in assets:
                    if not isinstance(asset, dict) or set(asset) != {"path", "sha256"}:
                        raise InvalidInput("asset must contain path and sha256")
                    if asset["path"] in seen_assets:
                        raise InvalidInput("duplicate receipt asset")
                    seen_assets.add(asset["path"])
                    audit.local_bytes(asset["path"], asset["sha256"], eid + ".asset")
            except (InvalidInput, TypeError) as exc:
                audit.fail(eid, str(exc))
        if before == len(audit.errors) and receipt is not None:
            valid_evidence[eid] = receipt

    def references(ids, modes, kinds, context):
        valid = bool(ids)
        if not ids:
            audit.fail(context, "PASS requires evidence references")
        found_kinds = set()
        for eid in ids:
            ev = valid_evidence.get(eid)
            if ev is None:
                audit.fail(context, "unresolved or invalid evidence: " + eid)
                valid = False
            elif ev["status"] != "PASS" or ev["mode"] not in modes:
                audit.fail(context, "evidence has non-PASS status or disallowed test mode: " + eid)
                valid = False
            else:
                found_kinds.add(ev["kind"])
        if not set(kinds).issubset(found_kinds):
            audit.fail(context, "required evidence kinds missing")
            valid = False
        return valid

    accepted = {"engineering": Decimal(0), "business": Decimal(0)}
    totals = {"engineering": Decimal(0), "business": Decimal(0)}
    for cid, criterion in criteria.items():
        stream = criterion["stream"]
        weight = Decimal(str(criterion["weight"]))
        totals[stream] += weight
        check = checks.get(cid)
        if check is None:
            continue
        before = len(audit.errors)
        if check["stream"] != stream or check["mandatory"] != criterion["mandatory"]:
            audit.fail(cid, "report changes frozen stream/mandatory flag")
        if check["candidate_id"] != expected_candidate:
            audit.fail(cid, "wrong candidate binding")
        # Even failing/pending checks must not contain dangling links.
        if any(eid not in evidence for eid in check["evidence_ids"]):
            audit.fail(cid, "unresolvable evidence ID")
        if check["status"] != "PASS":
            audit.block(cid, "criterion is " + check["status"] + "; counted as zero")
            continue
        try:
            until = instant(check["valid_until_utc"])
            if until <= now:
                raise InvalidInput("PASS criterion expired")
            if (until - now).total_seconds() > baseline["max_evidence_age_seconds"]:
                raise InvalidInput("validity exceeds frozen maximum evidence lifetime")
        except InvalidInput as exc:
            audit.fail(cid, str(exc))
        references(check["evidence_ids"], criterion["allowed_evidence_modes"],
                   criterion["required_evidence_kinds"], cid)
        if before == len(audit.errors):
            accepted[stream] += weight
    for stream in totals:
        if totals[stream] != 100:
            audit.fail("baseline", stream + " weights must total exactly 100")
        if report["baseline"][stream + "_total_weight"] != float(totals[stream]):
            audit.fail("baseline", "report changes " + stream + " denominator")
    for entry_id, frozen_entry in entries.items():
        entry = actual_entries.get(entry_id)
        if entry is None:
            continue
        for key in ("kind", "requirement_id"):
            if entry[key] != frozen_entry[key]:
                audit.fail(entry_id, "entry changes frozen " + key)
        if entry["candidate_id"] != expected_candidate:
            audit.fail(entry_id, "wrong candidate binding")
        for name in ("test_evidence_ids", "effect_evidence_ids"):
            if any(eid not in evidence for eid in entry[name]):
                audit.fail(entry_id, "unresolvable " + name)
        if entry["status"] != "PASS":
            audit.block(entry_id, "entry not PASS")
            continue
        for name in ("implementation_ref", "production_call_path", "real_input_or_data_ref"):
            if (not isinstance(entry[name], str) or not entry[name].strip()
                    or PLACEHOLDER.search(entry[name])):
                audit.fail(entry_id, "missing or placeholder " + name)
        references(entry["test_evidence_ids"], MODES, frozen_entry["required_test_kinds"], entry_id)
        references(entry["effect_evidence_ids"], {"OBSERVED"},
                   frozen_entry["required_effect_kinds"], entry_id)
        # An effect from another entry must not be reused as proof of this one.
        bound_effects = []
        for eid in entry["effect_evidence_ids"]:
            ev = valid_evidence.get(eid)
            if ev is None or ev["status"] != "PASS" or ev["mode"] != "OBSERVED":
                continue
            bindings = ev["payload"].get("entry_bindings")
            if not isinstance(bindings, list):
                continue
            for binding in bindings:
                if not isinstance(binding, dict) or binding.get("entry_id") != entry_id:
                    continue
                fields = ("requirement_id", "implementation_ref", "production_call_path", "real_input_or_data_ref")
                if (any(binding.get(key) != entry[key] for key in fields)
                        or binding.get("exe_sha256") != candidate["tested_exe_sha256"]):
                    audit.fail(entry_id, "effect is not bound to the entry and Exact EXE")
                    continue
                input_bytes = audit.local_bytes(entry["real_input_or_data_ref"],
                                               binding.get("input_sha256"), entry_id + ".input")
                implementation = binding.get("implementation_asset", {})
                output = binding.get("output_asset", {})
                if not isinstance(implementation, dict) or not isinstance(output, dict):
                    audit.fail(entry_id, "implementation/output asset binding is malformed")
                    continue
                source_bytes = audit.local_bytes(implementation.get("path"), implementation.get("sha256"), entry_id + ".implementation")
                output_bytes = audit.local_bytes(output.get("path"), output.get("sha256"), entry_id + ".output")
                if input_bytes and source_bytes and output_bytes:
                    bound_effects.append(eid)
        if not bound_effects:
            audit.fail(entry_id, "missing entry-specific observed input/implementation/output/EXE binding")

    attempted, successful = set(), set()
    for attempt in report["network_attempts"]:
        aid, sid = attempt["attempt_id"], attempt["source_id"]
        attempted.add(sid)
        if sid not in sources:
            audit.fail(aid, "unapproved network source")
        elif attempt["source_role"] != sources[sid]["source_role"]:
            audit.fail(aid, "source role differs from baseline")
        if attempt["candidate_id"] != expected_candidate:
            audit.fail(aid, "wrong candidate binding")
        audit.at(attempt["observed_at_utc"], aid, frozen, baseline["max_evidence_age_seconds"])
        if attempt["raw_response_uri"] is not None:
            audit.local_bytes(attempt["raw_response_uri"], attempt["raw_response_sha256"], aid)
        elif attempt["raw_response_sha256"] is not None:
            audit.fail(aid, "raw hash without retained response path")
        if attempt["status"] == "PASS":
            successful.add(sid)
            matching = [ev for ev in valid_evidence.values() if ev["kind"] == "real_network"
                        and ev["status"] == "PASS" and ev["mode"] == "OBSERVED"
                        and ev["payload"].get("attempt_id") == aid
                        and ev["payload"].get("source_id") == sid
                        and ev["payload"].get("raw_response_sha256") == attempt["raw_response_sha256"]
                        and ev["payload"].get("source_uri") == sources.get(sid, {}).get("source_uri")]
            if not matching:
                audit.fail(aid, "PASS requires matching observed real_network receipt and approved source URI")
        elif not attempt["failure_detail"]:
            audit.fail(aid, "non-PASS attempt must preserve failure detail")
    for sid, source in sources.items():
        if sid not in attempted:
            audit.block(sid, "approved source was not attempted")
        if source["required_success"] and sid not in successful:
            audit.block(sid, "required source has no PASS attempt")
    if not successful:
        audit.block("real_network", "no observed successful network attempt")

    tested, released = candidate["tested_exe_sha256"], candidate["release_exe_sha256"]
    if not candidate["same_hash_verified"] or not tested or not released:
        audit.block("same_hash", "tested/released EXE binding is incomplete")
    elif tested.lower() != released.lower():
        audit.fail("same_hash", "tested EXE differs from released EXE")
    else:
        audit.local_bytes(candidate["release_artifact_uri"], released, "release EXE")
        exact = [ev for ev in valid_evidence.values() if ev["kind"] == "exact_exe"
                 and ev["status"] == "PASS" and ev["mode"] == "OBSERVED"
                 and ev["payload"].get("exe_sha256") == tested]
        if not exact:
            audit.fail("same_hash", "no observed exact_exe receipt bound to tested hash")
        for ev in exact:
            audit.local_bytes(ev["payload"].get("exe_path"), tested, "tested EXE")
    computed = {stream + "_accepted_weight": float(accepted[stream]) for stream in accepted}
    for stream in accepted:
        computed[stream + "_pct"] = float((accepted[stream] / totals[stream] * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)) if totals[stream] else 0.0
    computed["overall_pct"] = min(computed["engineering_pct"], computed["business_pct"])
    for key, value in computed.items():
        claimed = report["scores"][key]
        if claimed is None:
            audit.block("scores." + key, "completion is unverified")
        elif Decimal(str(claimed)) != Decimal(str(value)):
            audit.fail("scores." + key, "claimed value does not equal independently recomputed value")
    if computed["overall_pct"] < 100:
        audit.block("coverage", "not all frozen criteria have current PASS evidence")
    if audit.errors or audit.blockers:
        if any(report["gates"][g] == "PASS" for g in ("no_shell", "engineering", "business", "project_final")):
            # A stream PASS is not inherently a lie because another stream is blocked.
            for stream in ("engineering", "business"):
                if report["gates"][stream] == "PASS" and computed[stream + "_pct"] < 100:
                    audit.fail(stream, "gate claims PASS with incomplete accepted coverage")
            if report["gates"]["project_final"] == "PASS" or report["gates"]["release"] == "YES":
                audit.fail("final claim", "unresolved evidence preflight problems contradict release claim")
        if report["gates"]["no_shell"] == "PASS" and (set(actual_entries) != set(entries)
                or any(e["status"] != "PASS" for e in actual_entries.values())):
            audit.fail("no_shell", "PASS contradicts incomplete frozen entry inventory")
    return result(audit.errors, audit.blockers, computed)


def preflight(report_raw, baseline_raw, approved_baseline_sha256, schema_raw, root,
              expected_candidate, expected_commit, now=None):
    """All failures are represented in output; callers must enforce the nonzero CLI exit."""
    try:
        if not isinstance(approved_baseline_sha256, str) or not SHA256.fullmatch(approved_baseline_sha256):
            return result(blockers=["an independently approved baseline SHA-256 is required"])
        if digest(baseline_raw) != approved_baseline_sha256.lower():
            return result(errors=["baseline digest differs from independent approval"])
        baseline = strict_json(baseline_raw)
        from jsonschema import Draft202012Validator
        baseline_schema = strict_json(Path(__file__).with_name("baseline.schema.json").read_bytes())
        Draft202012Validator.check_schema(baseline_schema)
        issues = list(Draft202012Validator(baseline_schema).iter_errors(baseline))
        if issues:
            return result(blockers=["frozen baseline is incomplete or invalid: " + e.message for e in issues])
        return _audit(strict_json(report_raw), baseline, strict_json(schema_raw), Path(root),
                      expected_candidate, expected_commit, now or datetime.now(timezone.utc))
    except ImportError:
        return result(blockers=["required dependency unavailable: jsonschema==4.26.0"])
    except Exception as exc:
        # CLI input may include an invalid schema, unreadable paths or excessive nesting.
        # No input-dependent exception is allowed to become an unstructured traceback.
        return result(errors=["input validation failed: " + str(exc)])


class MachineParser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidInput(message)


def main(argv=None):
    parser = MachineParser(description=__doc__)
    for name in ("status", "baseline", "approved-baseline-sha256", "status-schema",
                 "evidence-root", "expected-candidate-id", "expected-commit-sha"):
        parser.add_argument("--" + name, required=True)
    try:
        args = parser.parse_args(argv)
        outcome = preflight(Path(args.status).read_bytes(), Path(args.baseline).read_bytes(),
                            args.approved_baseline_sha256, Path(args.status_schema).read_bytes(),
                            args.evidence_root, args.expected_candidate_id, args.expected_commit_sha)
    except (OSError, ValueError) as exc:
        outcome = result(errors=["input validation failed: " + str(exc)])
    print(json.dumps(outcome, ensure_ascii=True, allow_nan=False, sort_keys=True))
    return 0 if outcome["status"] == "PASS" else 1 if outcome["status"] == "FAIL" else 2


if __name__ == "__main__":
    sys.exit(main())
