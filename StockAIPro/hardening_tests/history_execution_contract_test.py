from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(VERSION))
from stock_ai.netclient import AkShareProxy, NetClientError
from stock_ai import data_source


class Response:
    status_code = 200
    content = b'{"ok":true}'
    headers = {"content-type": "application/json"}

    def __init__(self, url):
        self.url = url

    def raise_for_status(self):
        pass


def test_parallel_transport(folder):
    barrier = threading.Barrier(5)
    requests_seen = []
    lock = threading.Lock()

    class Provider:
        def fetch(self, symbol):
            requests.get("https://example.invalid/" + symbol, timeout=None)
            return {"symbol": symbol}

    def transport(session, method, url, **kwargs):
        with lock:
            requests_seen.append((url, kwargs.get("timeout")))
        barrier.wait(timeout=5)
        return Response(url)

    cfg = {"retry_attempts": 3, "connect_timeout_seconds": 1, "read_timeout_seconds": 2}
    receipt_path = folder / "parallel.jsonl"
    proxy = AkShareProxy(Provider(), cfg, receipt_path)
    with patch.object(requests.sessions.Session, "request", new=transport):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(proxy.fetch, str(i)) for i in range(4)]
            # The unrelated caller has no proxy guard, so its original timeout
            # must survive while four guarded provider requests are active.
            requests.get("https://example.invalid/unrelated")
            assert [future.result()["symbol"] for future in futures] == [str(i) for i in range(4)]
        assert requests.sessions.Session.request is transport
    rows = [json.loads(line) for line in receipt_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert {row["raw_responses"][0]["request"]["path"] for row in rows} == {"/" + str(i) for i in range(4)}
    assert all(len(row["raw_responses"]) == 1 and row["status"] == "PASS" for row in rows)
    assert dict(requests_seen)["https://example.invalid/unrelated"] is None
    assert all(timeout == (1.0, 2.0) for url, timeout in requests_seen if not url.endswith("unrelated"))


def test_retry_classification(folder):
    class Provider:
        def fetch(self):
            requests.get("https://example.invalid/data", timeout=999)
            return {"ok": True}

        def parser_failure(self):
            raise ValueError("invalid provider schema")

    cfg = {"retry_attempts": 3, "connect_timeout_seconds": 1, "read_timeout_seconds": 2,
           "retry_backoff_seconds": 0, "retry_jitter_seconds": 0}
    proxy = AkShareProxy(Provider(), cfg, folder / "retry.jsonl")
    counter = []

    def transient(session, method, url, **kwargs):
        counter.append(kwargs["timeout"])
        raise requests.ConnectionError("production source unavailable")

    with patch.object(requests.sessions.Session, "request", new=transient):
        try:
            proxy.fetch()
            raise AssertionError("unavailable source must fail closed")
        except NetClientError:
            pass
    assert counter == [(1.0, 2.0)] * 3
    try:
        proxy.parser_failure()
        raise AssertionError("schema error must fail closed")
    except NetClientError:
        pass
    rows = [json.loads(line) for line in (folder / "retry.jsonl").read_text().splitlines()]
    assert rows[0]["attempts_used"] == 3 and rows[0]["retryable"] is True
    assert rows[1]["attempts_used"] == 1 and rows[1]["retryable"] is False
    for exception in (requests.HTTPError("HTTP 403"), requests.exceptions.SSLError("invalid certificate")):
        counter.clear()
        def permanent(session, method, url, **kwargs):
            counter.append(kwargs["timeout"])
            raise exception
        with patch.object(requests.sessions.Session, "request", new=permanent):
            try:
                proxy.fetch()
                raise AssertionError("permanent error must fail")
            except NetClientError:
                pass
        assert len(counter) == 1


def test_full_history_workload(folder):
    cfg = json.loads((VERSION / "config.default.json").read_text(encoding="utf-8"))
    assert cfg["universe"]["live_top_n"] == 300
    assert cfg["universe"]["bootstrap_batch"] == 60
    assert cfg["universe"]["history_start"] == "20180101"
    assert cfg["model"]["extra_trees_n_estimators"] == 320
    cfg["network"].update({"retry_backoff_seconds": 0, "retry_jitter_seconds": 0, "request_delay_seconds": 0})
    primary, fallback = [], []
    active, peak = 0, 0
    lock = threading.Lock()

    class Provider:
        def stock_zh_a_hist(self, symbol, start_date, end_date, **kwargs):
            with lock:
                primary.append((symbol, start_date, end_date))
            requests.get("https://example.invalid/primary")

        def stock_zh_a_hist_tx(self, symbol, start_date, end_date, **kwargs):
            nonlocal active, peak
            with lock:
                fallback.append((symbol, start_date, end_date))
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.002)
                requests.get("https://example.invalid/fallback")
                return pd.DataFrame({"date": pd.date_range("2026-09-21", periods=4),
                                     "close": [9, 10, 11, 12], "open": [9, 10, 11, 12],
                                     "high": [10, 11, 12, 13], "low": [8, 9, 10, 11],
                                     "volume": [100] * 4, "amount": [1000] * 4,
                                     "turnover": [0.01] * 4})
            finally:
                with lock:
                    active -= 1

    def transport(session, method, url, **kwargs):
        if url.endswith("primary"):
            raise requests.ConnectionError("primary unavailable")
        return Response(url)

    data = folder / "workload"
    (data / "data" / "history").mkdir(parents=True)
    proxy = AkShareProxy(Provider(), cfg["network"], data / "evidence" / "requests.jsonl")
    live = [str(i).zfill(6) for i in range(1, 301)]
    extra = [str(i).zfill(6) for i in range(301, 361)]
    master = pd.DataFrame({"code": live + extra, "status": ["current"] * 300 + ["delisted"] * 15 + ["current"] * 45})
    with patch.object(data_source, "ROOT", data), patch.object(data_source, "_ak", return_value=proxy), \
            patch.object(requests.sessions.Session, "request", new=transport):
        update = data_source.update_live_histories(pd.DataFrame({"code": live}), cfg)
        bootstrap = data_source.bootstrap_research_pool(master, cfg, live)
    assert update["total"] == 300 and update["ok"] == 300
    assert update["provider_counts"] == {"tencent": 300}
    assert bootstrap["downloaded"] == 60 and not bootstrap["failed"]
    assert len(primary) == 3 * 360, "proxy must be the only retry owner"
    assert len(fallback) == 360
    assert {symbol[-6:] for symbol, _, _ in fallback} == set(live + extra)
    assert all(start == "20180101" for _, start, _ in primary + fallback)
    assert 1 < peak <= 4
    assert len(list((data / "data" / "history").glob("*.csv"))) == 360
    for phase, total in (("live_history", 300), ("bootstrap_history", 60)):
        state = json.loads((data / "state" / f"{phase}_progress.json").read_text(encoding="utf-8"))
        assert state["status"] == "COMPLETE" and state["completed"] == state["total"] == total
        assert state["failed_count"] == 0
    # Same target submitted twice cannot race on the atomic CSV temporary file.
    with patch.object(data_source, "ROOT", data), patch.object(data_source, "_ak", return_value=proxy), \
            patch.object(requests.sessions.Session, "request", new=transport):
        assert len(list(data_source._run_history_batch([live[0], live[0]], cfg, "dedup"))) == 1


def test_unavailable_sources_fail_closed(folder):
    from stock_ai import pipeline
    cfg = json.loads((VERSION / "config.default.json").read_text(encoding="utf-8"))
    cfg["network"].update({"retry_backoff_seconds": 0, "retry_jitter_seconds": 0, "request_delay_seconds": 0})
    class Provider:
        def stock_zh_a_hist(self, **kwargs):
            requests.get("https://example.invalid/primary")
        def stock_zh_a_hist_tx(self, **kwargs):
            requests.get("https://example.invalid/fallback")
    data = folder / "unavailable"
    (data / "data" / "history").mkdir(parents=True)
    (data / "cache").mkdir()
    cached = data / "data" / "history" / "000001.csv"
    cached.write_text("date,close,adjust_mode,schema_version\n2026-09-30,10,hfq,3\n", encoding="utf-8")
    cache_before = cached.read_bytes()
    proxy = AkShareProxy(Provider(), cfg["network"], data / "evidence" / "requests.jsonl")
    snapshot = pd.DataFrame({"code": ["000001", "000002", "000003"]})
    def unavailable(session, method, url, **kwargs):
        raise requests.ConnectionError("both production sources unavailable")
    with patch.object(data_source, "ROOT", data), patch.object(pipeline, "ROOT", data), \
            patch.object(data_source, "_ak", return_value=proxy), \
            patch.object(requests.sessions.Session, "request", new=unavailable), \
            patch.object(pipeline, "fetch_full_universe", return_value=snapshot), \
            patch.object(pipeline, "fetch_market_snapshot", return_value=snapshot), \
            patch.object(pipeline, "fetch_expected_trade_date", return_value=None):
        try:
            pipeline._run_locked(cfg, logging.getLogger("test"), False, True)
            raise AssertionError("failed sources must stop before prediction freeze")
        except RuntimeError as exc:
            assert "有效行情更新比例过低" in str(exc)
    update = json.loads((data / "cache" / "last_update_status.json").read_text(encoding="utf-8"))
    assert update["ok"] == 0 and len(update["failed"]) == 3
    assert cached.read_bytes() == cache_before
    assert not (data / "predictions").exists()


def test_timeout_retains_log(folder):
    spec = importlib.util.spec_from_file_location("full_daily_business_gate", ROOT / "hardening_tests" / "full_daily_business_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    log = folder / "timeout.log"
    try:
        gate.run_logged([sys.executable, "-u", "-c", "import time; print('checkpoint-before-timeout', flush=True); time.sleep(2)"],
                        log, cwd=folder, env=None, timeout=0.3)
        raise AssertionError("timeout must still fail")
    except subprocess.TimeoutExpired:
        pass
    assert "checkpoint-before-timeout" in log.read_text(encoding="utf-8")


def test_prediction_freeze_fail_closed(folder):
    spec = importlib.util.spec_from_file_location("full_daily_freeze", ROOT / "hardening_tests" / "full_daily_business_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    latest = folder / "latest"
    latest.mkdir()
    required = [name for name in gate.REQUIRED_FROZEN_FILES if name != "manifest.json"]
    for name in required:
        (latest / name).write_bytes((name + ": frozen fixture\n").encode("utf-8"))
    files = {name: gate.sha256(latest / name) for name in required}
    manifest_path = latest / "manifest.json"

    def verify(manifest, error=None):
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        if error is None:
            assert gate.verify_prediction_freeze(latest) == manifest
            return
        try:
            gate.verify_prediction_freeze(latest)
            raise AssertionError("malformed prediction freeze must fail closed")
        except RuntimeError as exc:
            assert error in str(exc), str(exc)

    verify({"files": files})
    for invalid in ({}, {"files": None}, {"files": {}}, {"files": []}, {"files": "malformed"}):
        verify(invalid, "nonempty object")
    verify([], "must be an object")
    incomplete = dict(files)
    incomplete.pop("predictions.csv")
    verify({"files": incomplete}, "required files are uncontrolled")
    for digest in (None, 123, "", "a" * 63, "g" * 64):
        verify({"files": dict(files, **{"predictions.csv": digest})}, "invalid SHA-256")
    outside = folder / "outside.csv"
    outside.write_bytes(b"existing outside payload with a matching hash")
    for name in ("../outside.csv", str(outside.resolve())):
        verify({"files": dict(files, **{name: gate.sha256(outside)})}, "path outside latest")
    # Every required file can exist while its frozen hash is wrong.
    verify({"files": dict(files, **{"predictions.csv": "0" * 64})}, "hash mismatch")
    (latest / "predictions.csv").unlink()
    verify({"files": files}, "missing files")


def main():
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        test_parallel_transport(folder)
        test_retry_classification(folder)
        test_full_history_workload(folder)
        test_unavailable_sources_fail_closed(folder)
        test_timeout_retains_log(folder)
        test_prediction_freeze_fail_closed(folder)
    report = {"schema": "stock-ai-history-execution-contract-v1", "status": "PASS",
              "scope": "simulated transport regression; does not certify real network, EXE or Final",
              "checks": ["four_requests_overlap_without_receipt_leakage", "unrelated_requests_use_original_transport",
                         "transport_restored_after_last_context", "none_and_oversized_timeout_bounded",
                         "only_transient_failures_retry", "single_retry_owner_three_attempts",
                         "300_live_plus_60_bootstrap_preserved", "eight_year_range_preserved", "models_unchanged",
                         "atomic_history_target_deduplicated", "progress_checkpoints_persisted",
                         "both_sources_unavailable_stop_prediction", "preserved_cache_not_counted_as_live_refresh", "timeout_retains_stdout",
                         "prediction_freeze_rejects_missing_empty_malformed_map", "prediction_freeze_requires_all_frozen_files",
                         "prediction_freeze_requires_sha256_hex", "prediction_freeze_rejects_outside_paths",
                         "prediction_freeze_rejects_hash_mismatch_and_missing_payload"]}
    (ROOT / "history_execution_contract_evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
