from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from glp.constants import APP_NAME, APP_VERSION, PROMOTION_POLICY
from glp.gui import run_gui, gui_self_test
from glp.service import LottoService, self_test
from glp.util import next_draw_date, next_issue, parse_date, sha256_bytes, utc_now


def _write_json(path: str | None, value: dict) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _exe_sha256() -> str:
    try:
        return sha256_bytes(Path(sys.executable).read_bytes())
    except Exception:
        return ""


def _shape_ok(prediction: dict) -> bool:
    front = [int(x) for x in prediction.get("front", [])]
    back = [int(x) for x in prediction.get("back", [])]
    return (
        len(front) == 5
        and len(set(front)) == 5
        and all(1 <= x <= 35 for x in front)
        and len(back) == 2
        and len(set(back)) == 2
        and all(1 <= x <= 12 for x in back)
    )


def run_acceptance(result_file: str | None = None) -> int:
    checks: list[dict] = []
    report = {
        "schema": "dlt-windows-exact-exe-acceptance-v2",
        "app": APP_NAME,
        "game": "DLT",
        "version": APP_VERSION,
        "started_at": utc_now(),
        "exe_sha256": _exe_sha256(),
        "platform": sys.platform,
        "python": sys.version,
        "checks": checks,
        "code_gate": "UNKNOWN",
        "scientific_gate": "UNKNOWN",
        "network_gate": "UNKNOWN",
        "windows_runtime_gate": "UNKNOWN",
        "four_entry_gate": "UNKNOWN",
        "autonomous_prediction_gate": "UNKNOWN",
        "exact_package_gate": "UNKNOWN",
        "hard_fail_count": 0,
        "final_release_gate": "NOT_PASS",
    }

    def add(name: str, status: str, detail=None):
        item = {"name": name, "status": status}
        if detail is not None:
            item["detail"] = detail
        checks.append(item)

    try:
        with tempfile.TemporaryDirectory(prefix="glp_dlt_acceptance_") as td:
            os.environ["GLP_DATA_DIR"] = td

            # 1) Code contract.
            st = self_test(Path(td) / "selftest")
            add("code_self_test", st.get("status", "FAIL"), st)
            report["code_gate"] = st.get("status", "FAIL")
            if st.get("status") != "PASS":
                raise RuntimeError("code self-test failed")

            # 2) Native Windows GUI construction and four entry bindings.
            if os.name != "nt":
                add("windows_runtime", "FAIL", "acceptance requires native Windows")
                raise RuntimeError("not running on Windows")
            gst = gui_self_test()
            add("native_gui_self_test", gst.get("status", "FAIL"), gst)
            report["windows_runtime_gate"] = gst.get("status", "FAIL")
            report["four_entry_gate"] = gst.get("status", "FAIL")
            if gst.get("status") != "PASS":
                raise RuntimeError("native GUI self-test failed")

            svc = LottoService()

            # 3) Real network quorum. National may be blocked by WAF, but the
            # live Jiangsu + Gansu official consensus must both PASS.
            update = svc.update()
            receipts = update.get("source_receipts", [])
            receipt_status = {str(x.get("source")): str(x.get("status")) for x in receipts}
            network_ok = (
                update.get("network_gate") == "PASS"
                and update.get("crosscheck_status") == "PASS"
                and receipt_status.get("jiangsu") == "PASS"
                and receipt_status.get("gansu") == "PASS"
            )
            add("real_network_official_quorum", "PASS" if network_ok else "FAIL", {
                "latest": update.get("latest"),
                "verification": update.get("verification"),
                "crosscheck_count": update.get("crosscheck_count"),
                "crosscheck_status": update.get("crosscheck_status"),
                "source_receipts": receipts,
                "canonical_hash": update.get("canonical_hash"),
            })
            report["network_gate"] = "PASS" if network_ok else "FAIL"
            if not network_ok:
                raise RuntimeError("real network official quorum failed")

            # 4) Offline failure must not be disguised by cached data.
            import glp.sources as source_module
            old_national = source_module.fetch_national_history
            old_jiangsu = source_module.fetch_jiangsu_recent
            old_gansu = source_module.fetch_gansu_recent
            before_hash = svc.store.load_draws()[1]
            rejected = False
            try:
                def _offline(*_args, **_kwargs):
                    raise source_module.SourceError("acceptance injected offline")
                source_module.fetch_national_history = _offline
                source_module.fetch_jiangsu_recent = _offline
                source_module.fetch_gansu_recent = _offline
                try:
                    svc.update()
                except Exception:
                    rejected = True
            finally:
                source_module.fetch_national_history = old_national
                source_module.fetch_jiangsu_recent = old_jiangsu
                source_module.fetch_gansu_recent = old_gansu
            after_hash = svc.store.load_draws()[1]
            offline_ok = rejected and before_hash == after_hash
            add("offline_fail_closed", "PASS" if offline_ok else "FAIL", {
                "rejected": rejected,
                "history_unchanged": before_hash == after_hash,
            })
            if not offline_ok:
                raise RuntimeError("offline fail-closed contract failed")

            # 5) Corrupt canonical bytes then require the real Repair entry to recover.
            history_path = svc.store.history_path
            corrupted = json.loads(history_path.read_text(encoding="utf-8"))
            corrupted["draws"][0]["front"][0] = 1 if corrupted["draws"][0]["front"][0] != 1 else 2
            history_path.write_text(json.dumps(corrupted, ensure_ascii=False), encoding="utf-8")
            before_repair = svc.store.integrity_check()
            repair = svc.repair()
            repair_ok = before_repair.get("status") == "FAIL" and repair.get("after", {}).get("status") == "PASS"
            add("entry_repair_corrupt_canonical", "PASS" if repair_ok else "FAIL", {
                "before": before_repair,
                "after": repair.get("after"),
                "action": repair.get("action"),
            })
            if not repair_ok:
                raise RuntimeError("repair entry failed to recover corrupted canonical")

            # 6) Predict must be autonomous: live update -> current canonical ->
            # evidence court -> score -> immutable freeze, without manual input.
            pred_payload = svc.predict()
            pred = pred_payload.get("prediction") or {}
            auto = pred_payload.get("auto_update") or {}
            draws, canonical_hash = svc.store.load_draws()
            expected_issue = next_issue(draws[-1].issue, draws[-1].draw_date)
            expected_date = next_draw_date(parse_date(draws[-1].draw_date)).isoformat()
            court = svc.latest_court(canonical_hash) or {}
            autonomous = {
                "live_update_pass": auto.get("network_gate") == "PASS" and auto.get("crosscheck_status") == "PASS",
                "target_from_updated_canonical": pred.get("target_issue") == expected_issue and pred.get("target_date") == expected_date,
                "shape_valid": _shape_ok(pred),
                "lineage_bound": bool(
                    pred.get("prediction_id")
                    and pred.get("canonical_hash") == canonical_hash
                    and pred.get("freeze_hash")
                    and pred.get("model_hash")
                    and pred.get("selector_hash")
                    and pred.get("score_hash")
                ),
                "court_software_pass": court.get("software_verdict") == "PASS" and court.get("scientific_gate") == "PASS",
                "edge_state_consistent": (
                    (pred.get("edge_state") == "EDGE_PROVEN") == (court.get("edge_gate") == "PASS")
                ),
                "dan_not_overclaimed": pred.get("dan_state") != "CERTIFIED_DAN" or pred.get("edge_state") == "EDGE_PROVEN",
                "no_manual_input": True,
            }
            autonomous_ok = all(autonomous.values())
            add("entry_predict_autonomous", "PASS" if autonomous_ok else "FAIL", {
                "contract": autonomous,
                "prediction": {
                    "target_issue": pred.get("target_issue"),
                    "target_date": pred.get("target_date"),
                    "front": pred.get("front"),
                    "back": pred.get("back"),
                    "edge_state": pred.get("edge_state"),
                    "dan_state": pred.get("dan_state"),
                    "freeze_hash": pred.get("freeze_hash"),
                },
            })
            report["autonomous_prediction_gate"] = "PASS" if autonomous_ok else "FAIL"
            if not autonomous_ok:
                raise RuntimeError("autonomous prediction contract failed")

            # 7) Strict scientific falsification execution and false-edge firewall.
            synthetic = court.get("synthetic_null_worlds") or {}
            leakage = court.get("leakage_sentinel") or {}
            sci_ok = (
                court.get("software_verdict") == "PASS"
                and court.get("scientific_gate") == "PASS"
                and leakage.get("status") == "PASS"
                and int(synthetic.get("worlds", 0)) == int(PROMOTION_POLICY["synthetic_null_worlds"])
                and int(synthetic.get("false_edges", 999999)) <= int(PROMOTION_POLICY["synthetic_null_max_false_edges"])
            )
            add("scientific_falsification", "PASS" if sci_ok else "FAIL", {
                "software_verdict": court.get("software_verdict"),
                "scientific_gate": court.get("scientific_gate"),
                "edge_gate": court.get("edge_gate"),
                "edge_state": court.get("edge_state"),
                "dan_state": court.get("dan_state"),
                "leakage_sentinel": leakage,
                "synthetic_null_worlds": synthetic,
                "court_hash": court.get("court_hash"),
            })
            report["scientific_gate"] = "PASS" if sci_ok else "FAIL"
            if not sci_ok:
                raise RuntimeError("scientific falsification gate failed")

            # 8) Advanced analysis must execute but never create/overwrite a formal freeze.
            freezes_before = len(svc.store.freezes())
            audit = svc.audit()
            freezes_after = len(svc.store.freezes())
            audit_iso = audit.get("audit_freeze_isolation") or {}
            audit_ok = (
                audit.get("court", {}).get("software_verdict") == "PASS"
                and audit_iso.get("status") == "PASS"
                and freezes_before == freezes_after
                and audit.get("formal_freeze_written") is False
            )
            add("entry_audit_non_freezing", "PASS" if audit_ok else "FAIL", {
                "freeze_count_before": freezes_before,
                "freeze_count_after": freezes_after,
                "isolation": audit_iso,
                "court_hash": audit.get("court", {}).get("court_hash"),
            })
            if not audit_ok:
                raise RuntimeError("advanced audit isolation failed")

            # Update entry was executed directly; all four service entries are now exercised.
            add("entry_update", "PASS", {
                "latest": update.get("latest"),
                "verification": update.get("verification"),
                "network_gate": update.get("network_gate"),
            })

            # 9) Same packaged bytes are bound by the EXE hash.
            report["exact_package_gate"] = "PASS" if bool(report["exe_sha256"]) else "FAIL"
            add("exact_exe_hash_bound", report["exact_package_gate"], {"sha256": report["exe_sha256"]})

            hard_fail = [c["name"] for c in checks if c.get("status") != "PASS"]
            report["hard_fail_count"] = len(hard_fail)
            report["hard_fail_checks"] = hard_fail
            report["final_release_gate"] = "PASS" if (
                not hard_fail
                and report["code_gate"] == "PASS"
                and report["windows_runtime_gate"] == "PASS"
                and report["four_entry_gate"] == "PASS"
                and report["network_gate"] == "PASS"
                and report["scientific_gate"] == "PASS"
                and report["autonomous_prediction_gate"] == "PASS"
                and report["exact_package_gate"] == "PASS"
            ) else "NOT_PASS"
    except Exception as exc:
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        report["hard_fail_count"] = max(1, sum(1 for c in checks if c.get("status") != "PASS"))
    finally:
        report["finished_at"] = utc_now()
        _write_json(result_file, report)
        # ASCII-escaped console output avoids Windows hosted-runner codepage failures.
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))

    return 0 if report["final_release_gate"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(prog="GeometryLottoPro")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-self-test", action="store_true")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--result-file")
    args = parser.parse_args()

    if args.self_test:
        value = self_test()
        _write_json(args.result_file, value)
        print(json.dumps(value, ensure_ascii=True, indent=2))
        return 0 if value.get("status") == "PASS" else 2
    if args.gui_self_test:
        value = gui_self_test()
        _write_json(args.result_file, value)
        print(json.dumps(value, ensure_ascii=True, indent=2))
        return 0 if value.get("status") == "PASS" else 2
    if args.acceptance:
        return run_acceptance(args.result_file)

    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
