"""Exercise existing data helpers on labelled fixtures, never lottery history.

Self-pinning a file proves its byte identity, not the prior provenance of its
values.  Accepted artificial taint is reported as that limitation.  This
module does not produce predictions, call a TSA, open a database, or claim
full runtime/P0 validation.  All output is exclusive-create and never retried.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from unittest.mock import patch

from research.ssq_dlt_v45 import sources, workflow


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
CLOCK = datetime(2000, 1, 10, tzinfo=timezone.utc)
GAMES = ("SSQ", "DLT")
CASES = tuple(f"C{i}" for i in range(8))
FIXTURE_SCOPE = "EXPLICIT_SYNTHETIC_ADAPTER_FIXTURE_NOT_REAL_OFFICIAL_SOURCE"
BOUNDARY = dict(formal_A=0, decision="NO_EDGE", qualified_prospective_samples=0,
                asof_qualification="BLOCKED", official_next_legal_issue="BLOCKED",
                new_prediction_candidates=0, new_model_parameters=0,
                new_prediction_seeds=0, existing_sqlite_opened=False,
                lottery_holdout_rows_or_scores_used=False,
                formal_12_family="UNCHANGED_BLOCKED_ORIGINAL_IDENTITY_AND_APPROVAL",
                repository_independence="FAIL", final_gate="FAIL")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def bad(_):
        raise ValueError("NONFINITE_JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write((canonical(value) + "\n").encode("utf-8"))


def _absolute(path, reason):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError(reason)
    return path.resolve()


def validate_protocol(path):
    path = _absolute(path, "ABSOLUTE_PROTOCOL_REQUIRED")
    raw = path.read_bytes()
    value = parse(raw)
    registered = parse((PACKAGE / "diagnostic-protocol.json").read_bytes())
    if value != registered or value.get("schema") != "V45_ASOF_FAULT_AUDIT_1":
        raise ValueError("REGISTERED_PROTOCOL_MISMATCH")
    if (value.get("games") != list(GAMES)
            or [case.get("id") for case in value.get("cases", [])] != list(CASES)):
        raise ValueError("REGISTERED_CASE_RECTANGLE_MISMATCH")
    return path, raw, value


def source_manifest(check_frozen=True):
    frozen = parse((PACKAGE / "frozen-science-sha256.json").read_bytes())
    if type(frozen) is not dict or len(frozen) != 49:
        raise ValueError("EXACT_49_FROZEN_SCIENCE_PINS_REQUIRED")
    result = {}
    for name, expected in frozen.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("INVALID_FROZEN_SCIENCE_PIN")
        actual = file_sha(path)
        if check_frozen and actual != expected:
            raise ValueError("FROZEN_SCIENCE_SOURCE_CHANGED")
        result[name] = actual
    for path in sorted(PACKAGE.rglob("*")):
        if (path.is_file() and "__pycache__" not in path.parts
                and (path.suffix in (".py", ".md", ".json") or path.name == ".gitattributes")):
            result[path.relative_to(ROOT).as_posix()] = file_sha(path)
    ci = ROOT / ".github/workflows/ssq-dlt-asof-audit.yml"
    if not ci.is_file():
        raise ValueError("AUDIT_WORKFLOW_MISSING")
    result[ci.relative_to(ROOT).as_posix()] = file_sha(ci)
    # Explicitly cover the actual helpers even if the historic pin list grows
    # different conventions in a future, separately reviewed diagnostic.
    for module in (sources, workflow):
        path = Path(module.__file__).resolve()
        result[path.relative_to(ROOT).as_posix()] = file_sha(path)
    return dict(sorted(result.items()))


def fixture(game):
    """Four fixed legal rows. These dates/values are entirely invented."""
    count = 6 if game == "SSQ" else 5
    prefix = "2000" if game == "SSQ" else "00"
    rows = [dict(game=game, issue=prefix + f"{index + 1:03d}",
                 draw_date=f"2000-01-{index + 1:02d}",
                 front=list(range(index + 1, index + 1 + count)),
                 back=[index + 1] if game == "SSQ" else [index + 1, index + 2])
            for index in range(4)]
    return dict(game=game, draws=rows,
                fixture_metadata=dict(scope=FIXTURE_SCOPE, synthetic=True,
                                      not_a_prediction=True, external_authenticity=False))


def attack_value(game):
    return dict(front=[11, 12, 13, 14, 15, 16], back=[9]) if game == "SSQ" else dict(
        front=[21, 22, 23, 24, 25], back=[9, 10])


def case_documents(case, game):
    clean = fixture(game)
    attack = copy.deepcopy(clean)
    if case in ("C2", "C3", "C4", "C5", "C7"):
        attack["draws"][0].update(attack_value(game))
    if case == "C1":
        attack["draws"][-1]["draw_date"] = "2000-01-11"
    if case == "C4":
        attack["draws"][0].update(available_at="2000-01-01T00:00:00+00:00", tsa_verified=True)
    if case == "C6":
        attack["untrusted_source_metadata"] = dict(
            captured_at="2000-01-11T00:00:00+00:00",
            sealed_at="2000-01-12T00:00:00+00:00", tsa_verified=True,
            provenance="SELF_ASSERTED_FIXTURE_ONLY_NO_TSA_CALL")
    # C5 exposes an actual same-identity conflict to the unchanged agree().
    # Other accepted taints are copied consistently, illustrating that
    # agreement between two self-supplied files is not external provenance.
    right = clean if case in ("C1", "C3", "C5", "C7") else copy.deepcopy(attack)
    return clean, attack, right


def _call(function, *args):
    try:
        return dict(status="ACCEPTED", value=function(*args))
    except Exception as exc:
        return dict(status="REJECTED", error=type(exc).__name__, reason=str(exc))


def _normalized(document):
    """Independent projection of the fixed fixtures; never call old helpers."""
    return [dict(game=document['game'], issue=r['issue'], draw_date=r['draw_date'],
                 front=sorted(r['front']), back=sorted(r['back']))
            for r in document['draws']]


def _case_config(case, game, directory):
    other = "DLT" if game == "SSQ" else "SSQ"
    spec = dict(path=str(directory / "attack.json"),
                sha256=file_sha(directory / ("clean.json" if case == "C3" else "attack.json")))
    config = dict(history={game:spec,other:dict(path=str(directory/"companion-clean.json"),
        sha256=file_sha(directory/"companion-clean.json"))},live_sources=case=="C7",recipient=None,
        diagnostic_fixture_scope=FIXTURE_SCOPE)
    if case == "C6":
        config.update(case_documents(case,game)[1]["untrusted_source_metadata"])
    return config


def _finding(case, retained_taint):
    if case == "C5":
        return "AGREE_CONFLICT_REJECTED_OFFLINE_STAGE_TAINT_RETAINED_PROVENANCE_LIMITATION"
    if retained_taint:
        return "ACCEPTED_SYNTHETIC_TAINT_PROVENANCE_LIMITATION_NOT_DETECTION_SUCCESS"
    if case == "C6":
        return "SELF_ASSERTED_LATE_METADATA_DOES_NOT_GRANT_ASOF"
    return "SYNTHETIC_HELPER_BOUNDARY_DIAGNOSTIC_ONLY"


def _mock_receipt(game):
    return dict(scope=FIXTURE_SCOPE,synthetic=True,mocked_capture_pair=True,network_calls=0,
                actual_official_source=False,game=game,rows_sha256=digest(_normalized(fixture(game))[-2:]))


def _expected_good_stage(case, selected_game, requested_game):
    document = case_documents(case,selected_game)[1] if requested_game==selected_game else fixture(requested_game)
    rows=_normalized(document)
    return dict(status='HISTORY_CHECKED',rows=rows,
                receipts=[_mock_receipt(requested_game)] if case=='C7' else [],
                sha256=digest(rows),publication_asof_verified=False,target=None)


def _run_case(case, game, directory):
    directory.mkdir(parents=True, exist_ok=False)
    clean, attack, right = case_documents(case, game)
    documents = {"clean.json": clean, "attack.json": attack, "right.json": right,
                 "companion-clean.json": fixture("DLT" if game == "SSQ" else "SSQ")}
    for name, value in documents.items():
        write_new(directory / name, value)
    spec = dict(path=str(directory / "attack.json"),
                sha256=file_sha(directory / ("clean.json" if case == "C3" else "attack.json")))
    other = "DLT" if game == "SSQ" else "SSQ"
    config = _case_config(case,game,directory)
    write_new(directory / "config.json", config)
    write_new(directory / "fixture-attack-value.json", dict(
        game=game, values=attack_value(game), synthetic=True,
        use="FIXED_ATTACK_VALUES_ONLY_NOT_PREDICTION", scope=FIXTURE_SCOPE))
    loader = _call(sources.load_pinned, game, spec, CLOCK)
    right_loader = _call(sources.load_pinned, game,
                         dict(path=str(directory / "right.json"),
                              sha256=file_sha(directory / "right.json")), CLOCK)
    if loader["status"] == "ACCEPTED" and right_loader["status"] == "ACCEPTED":
        left_rows, right_rows = loader["value"], right_loader["value"]
        if case == "C7":
            left_rows, right_rows = left_rows[-2:], right_rows[-2:]
        agreement = _call(sources.agree, game, left_rows, right_rows)
    else:
        agreement = dict(status="NOT_RUN_DEPENDENCY_BLOCKED",
                         reason="LOADER_DID_NOT_ADMIT_BOTH_INPUTS")
    captures = []
    if case == "C7":
        def capture_fixture(requested_game, requested_directory, now):
            # The only replaced helper. No loader/agree/history mock.
            rows = sources.validate_history(requested_game, fixture(requested_game)["draws"][-2:], now)
            receipt = dict(scope=FIXTURE_SCOPE, synthetic=True, mocked_capture_pair=True,
                           network_calls=0, actual_official_source=False,
                           game=requested_game, rows_sha256=digest(rows))
            captures.append(receipt)
            return copy.deepcopy(rows), [receipt]
        with patch.object(sources, "capture_pair", side_effect=capture_fixture):
            stages = workflow.history_stage(config, directory / "stage", CLOCK)
    else:
        stages = workflow.history_stage(config, directory / "stage", CLOCK)
    selected = stages[game]
    retained_taint = (case in ("C2", "C4", "C5", "C7")
                      and selected.get("rows", [{}])[0].get("front") == attack_value(game)["front"]
                      and selected.get("rows", [{}])[0].get("back") == attack_value(game)["back"])
    result = dict(case=case, game=game, synthetic=True, fixture_scope=FIXTURE_SCOPE,
                  clock=CLOCK.isoformat(), loader=loader, right_loader=right_loader,
                  agreement=agreement, history_stage_games=stages,
                  capture_pair_mock_calls=captures, network_calls=0,
                  tainted_old_value_retained=retained_taint,
                  trusted_asof_admission=False,
                  self_asserted_metadata_is_not_time_verification=True,
                  **BOUNDARY)
    result["expectation_met"] = assess(result)
    result["diagnostic_status"] = "EXPECTED_BEHAVIOR" if result["expectation_met"] else "FAIL"
    result["finding"] = _finding(case,retained_taint)
    write_new(directory / "result.json", result)
    return result


def assess(result):
    """Pure assessment of saved observations, never re-execute old helpers."""
    case, game = result.get("case"), result.get("game")
    if case not in CASES or game not in GAMES:
        return False
    if (result.get('synthetic') is not True or result.get('fixture_scope') != FIXTURE_SCOPE
            or result.get('clock') != CLOCK.isoformat() or result.get('network_calls') != 0
            or result.get('trusted_asof_admission') is not False
            or result.get('self_asserted_metadata_is_not_time_verification') is not True
            or any(result.get(k) != v for k,v in BOUNDARY.items())):
        return False
    clean,attack,right = case_documents(case,game)
    other='DLT' if game=='SSQ' else 'SSQ'
    stages=result.get('history_stage_games',{})
    if (set(stages) != set(GAMES) or stages[other] != _expected_good_stage(case,game,other)
            or result.get('capture_pair_mock_calls') != ([_mock_receipt(g) for g in GAMES] if case=='C7' else [])):
        return False
    stage = result.get("history_stage_games", {}).get(game, {})
    if stage.get("target", "MISSING") is not None:
        return False
    if stage.get("publication_asof_verified", False) is not False:
        return False
    loader, agreement = result.get("loader", {}), result.get("agreement", {})
    if case in ("C1", "C3"):
        reason = "F01_FUTURE_OR_INTRADAY_UNPROVEN_DRAW" if case == "C1" else "HISTORY_SHA_MISMATCH"
        return (loader.get("status") == "REJECTED" and loader.get("reason") == reason
                and stage.get("status") == "BLOCKED" and stage.get("reason") == reason
                and result.get('right_loader')==dict(status='ACCEPTED',value=_normalized(right))
                and result.get('tainted_old_value_retained') is False
                and agreement.get("status") == "NOT_RUN_DEPENDENCY_BLOCKED")
    if loader.get("status") != "ACCEPTED" or stage.get("status") != "HISTORY_CHECKED":
        return False
    if (loader.get('value') != _normalized(attack)
            or result.get('right_loader',{}).get('value') != _normalized(right)
            or stage.get('rows') != _normalized(attack)
            or stage.get('sha256') != digest(_normalized(attack))):
        return False
    if stage != _expected_good_stage(case,game,game):
        return False
    if stage.get("publication_asof_verified") is not False:
        return False
    if case == "C5":
        if agreement.get("status") != "REJECTED" or agreement.get("reason") != "OFFICIAL_SOURCE_CONFLICT":
            return False
    elif agreement.get("status") != "ACCEPTED":
        return False
    elif agreement.get('value') != (_normalized(attack)[-2:] if case=='C7' else _normalized(attack)):
        return False
    observed_taint=(case in ('C2','C4','C5','C7') and stage.get('rows',[{}])[0].get('front')==attack_value(game)['front']
                    and stage.get('rows',[{}])[0].get('back')==attack_value(game)['back'])
    if result.get('tainted_old_value_retained') is not observed_taint:
        return False
    if case in ("C2", "C4", "C7") and not result.get("tainted_old_value_retained"):
        return False
    if case == "C7":
        calls = result.get("capture_pair_mock_calls", [])
        if len(calls) != 2 or {call.get("game") for call in calls} != set(GAMES):
            return False
    return result.get("trusted_asof_admission") is False


def _artifact_files(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("ARTIFACT_SYMLINK_REFUSED")
        if path.is_file() and path != root / "SHA256.json":
            files[path.relative_to(root).as_posix()] = file_sha(path)
    return files


def execute(protocol_path, output):
    protocol_path, raw_protocol, protocol = validate_protocol(protocol_path)
    output = _absolute(output, "ABSOLUTE_NEW_OUTPUT_REQUIRED")
    if output.is_relative_to(ROOT) or ROOT.is_relative_to(output):
        raise ValueError("OUTPUT_MUST_BE_SEPARATE_FROM_SOURCE")
    before = source_manifest()
    output.mkdir(parents=True, exist_ok=False)
    started = dict(schema="V45_ASOF_FAULT_EXECUTION_1", protocol_path=str(protocol_path),
                   protocol_sha256=hashlib.sha256(raw_protocol).hexdigest(),
                   local_observed_at=datetime.now(timezone.utc).isoformat(),
                   python=dict(implementation=platform.python_implementation(),version=sys.version),
                   fixture_clock=CLOCK.isoformat(), time_trust="LOCAL_ONLY_NOT_TSA",
                   source_manifest_sha256=digest(before), scope=protocol["scope"], **BOUNDARY)
    write_new(output / "STARTED.json", started)
    write_new(output / "before.json", dict(source_manifest=before, source_manifest_sha256=digest(before)))
    with (output / "PROTOCOL.json").open("xb") as handle:
        handle.write(raw_protocol)
    results, errors = [], []
    try:
        for case in CASES:
            for game in GAMES:
                results.append(_run_case(case, game, output / "cases" / case / game))
    except Exception as exc:
        errors.append(dict(error=type(exc).__name__, reason=str(exc)))
        write_new(output / "EXECUTION_ERROR.json", errors[-1])
    # KeyboardInterrupt/SystemExit/process death intentionally leave STARTED
    # without receipt. The directory remains immutable and cannot be reused.
    after = source_manifest(check_frozen=False)
    write_new(output / "after.json", dict(source_manifest=after,
                                         source_unchanged=before == after,
                                         source_manifest_sha256=digest(after)))
    complete = {(row["case"], row["game"]) for row in results} == {(c, g) for c in CASES for g in GAMES}
    expected = complete and all(row["expectation_met"] for row in results)
    status = "PASS_DIAGNOSTIC_EXPECTATIONS_ONLY" if expected and before == after and not errors else "FAIL"
    receipt = dict(schema="V45_ASOF_FAULT_RECEIPT_1", status=status,
                   scope=protocol["scope"], case_count=len(results), expected_case_count=16,
                   results=[dict(case=row["case"], game=row["game"], expectation_met=row["expectation_met"],
                                 finding=row["finding"], result_sha256=digest(row)) for row in results],
                   errors=errors, source_unchanged=before == after,
                   source_manifest_sha256=digest(before),
                   protocol_sha256=started["protocol_sha256"],
                   accepted_taint_is_detection_success=False,
                   trusted_time_or_source_authenticity_tested=False,
                   complete_runtime_or_physical_p0_tested=False,
                   prediction_effect_improvement_tested=False, **BOUNDARY)
    write_new(output / "receipt.json", receipt)
    write_new(output / "SHA256.json", _artifact_files(output))
    return receipt


def verify(output):
    """Read bytes only: do not run helpers, repair output, or open a database."""
    output = _absolute(output, "ABSOLUTE_OUTPUT_REQUIRED")
    if not (output / "receipt.json").is_file() or not (output / "SHA256.json").is_file():
        raise ValueError("INCOMPLETE_EXECUTION_NO_FINAL_RECEIPT")
    seal = parse((output / "SHA256.json").read_bytes())
    if type(seal) is not dict or seal != _artifact_files(output):
        raise ValueError("ARTIFACT_SHA_OR_FILE_SET_MISMATCH")
    started = parse((output / "STARTED.json").read_bytes())
    protocol_path, current_protocol, _ = validate_protocol(started["protocol_path"])
    copied_protocol = (output / "PROTOCOL.json").read_bytes()
    if (current_protocol != copied_protocol
            or hashlib.sha256(copied_protocol).hexdigest() != started["protocol_sha256"]):
        raise ValueError("PROTOCOL_SHA_MISMATCH")
    if (started.get('schema') != 'V45_ASOF_FAULT_EXECUTION_1'
            or started.get('scope') != parse(copied_protocol)['scope']
            or started.get('fixture_clock') != CLOCK.isoformat()
            or started.get('time_trust') != 'LOCAL_ONLY_NOT_TSA'
            or any(started.get(k) != v for k,v in BOUNDARY.items())):
        raise ValueError('EXECUTION_START_METADATA_CHANGED')
    before = parse((output / "before.json").read_bytes())
    after = parse((output / "after.json").read_bytes())
    current = source_manifest()
    if (before.get("source_manifest") != current or after.get("source_manifest") != current
            or before.get("source_manifest_sha256") != digest(current)
            or after.get("source_manifest_sha256") != digest(current)
            or started.get("source_manifest_sha256") != digest(current)):
        raise ValueError("SOURCE_MANIFEST_DRIFT")
    receipt = parse((output / "receipt.json").read_bytes())
    if (receipt.get('schema') != 'V45_ASOF_FAULT_RECEIPT_1'
            or receipt.get('status') != 'PASS_DIAGNOSTIC_EXPECTATIONS_ONLY'
            or receipt.get('source_unchanged') is not True or receipt.get('errors') != []
            or receipt.get('case_count') != 16 or receipt.get('expected_case_count') != 16
            or receipt.get('protocol_sha256') != started['protocol_sha256']
            or receipt.get('source_manifest_sha256') != digest(current)
            or receipt.get('scope') != parse(copied_protocol)['scope']
            or receipt.get('accepted_taint_is_detection_success') is not False
            or any(receipt.get(k) is not False for k in ('trusted_time_or_source_authenticity_tested',
                'complete_runtime_or_physical_p0_tested','prediction_effect_improvement_tested'))):
        raise ValueError('RECORDED_EXECUTION_NOT_PASS_OR_SUMMARY_CHANGED')
    if started.get('python') != dict(implementation=platform.python_implementation(),version=sys.version):
        raise ValueError('PYTHON_RUNTIME_DRIFT')
    if after.get('source_unchanged') is not True:
        raise ValueError('RECORDED_SOURCE_CHANGED')
    records = receipt.get("results", [])
    keys = [(row.get("case"), row.get("game")) for row in records]
    if len(keys) != 16 or set(keys) != {(c, g) for c in CASES for g in GAMES}:
        raise ValueError("CASE_RECTANGLE_MISMATCH")
    for summary in records:
        directory = output / "cases" / summary["case"] / summary["game"]
        row = parse((directory / "result.json").read_bytes())
        if (row.get("case"), row.get("game")) != (summary["case"], summary["game"]):
            raise ValueError("CASE_RESULT_IDENTITY_MISMATCH")
        if (digest(row) != summary["result_sha256"] or not assess(row)
                or summary.get('expectation_met') is not True or row.get('expectation_met') is not True
                or row.get('diagnostic_status') != 'EXPECTED_BEHAVIOR'
                or row.get('finding') != _finding(row['case'],row['tainted_old_value_retained'])
                or summary.get('finding') != row.get('finding')):
            raise ValueError("CASE_ASSESSMENT_MISMATCH")
        for key, value in BOUNDARY.items():
            if row.get(key) != value or receipt.get(key) != value:
                raise ValueError("RESEARCH_BOUNDARY_CHANGED")
        expected_documents = case_documents(row["case"], row["game"])
        for name, document in zip(("clean.json", "attack.json", "right.json"), expected_documents):
            if parse((directory / name).read_bytes()) != document:
                raise ValueError("FIXED_SYNTHETIC_FIXTURE_CHANGED")
        other = 'DLT' if row['game']=='SSQ' else 'SSQ'
        if (parse((directory/'companion-clean.json').read_bytes()) != fixture(other)
                or parse((directory/'config.json').read_bytes()) != _case_config(row['case'],row['game'],directory)
                or parse((directory/'fixture-attack-value.json').read_bytes()) != dict(game=row['game'],values=attack_value(row['game']),
                    synthetic=True,use='FIXED_ATTACK_VALUES_ONLY_NOT_PREDICTION',scope=FIXTURE_SCOPE)):
            raise ValueError('FIXTURE_CONFIG_OR_COMPANION_CHANGED')
    expected_files={'STARTED.json','before.json','PROTOCOL.json','after.json','receipt.json'}
    for case in CASES:
        for game in GAMES:
            expected_files.update(f'cases/{case}/{game}/{name}' for name in ('clean.json','attack.json','right.json',
                'companion-clean.json','config.json','fixture-attack-value.json','result.json'))
    if set(seal) != expected_files:
        raise ValueError('UNEXPECTED_ARTIFACT_LAYOUT')
    return dict(status="PASS_READ_ONLY_INTEGRITY_VERIFICATION",
                recorded_execution_status=receipt["status"], case_count=16,
                artifact_count=len(seal), protocol_sha256=file_sha(protocol_path),
                source_manifest_sha256=digest(current), helpers_reexecuted=False,
                verification_does_not_prove_external_custody=True, **BOUNDARY)
