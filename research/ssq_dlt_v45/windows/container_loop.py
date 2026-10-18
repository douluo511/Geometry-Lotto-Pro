"""Optional local container supervisor; publication decisions stay in runtime.

Run once immediately, then on each UTC half hour. A nonzero invocation retries
three times, and a successful invocation is not repeated within that slot.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


def next_half_hour(timestamp: float) -> float:
    return (int(timestamp) // 1800 + 1) * 1800


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true", help="Run one check without a loop.")
    args = parser.parse_args()
    if not args.config.is_absolute() or not args.config.is_file():
        parser.error("--config must be an existing absolute JSON file")
    stopped = threading.Event()
    child: subprocess.Popen | None = None

    def stop(_signum, _frame):
        stopped.set()
        if child is not None and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_exit = 0
    while not stopped.is_set():
        for attempt in range(4):
            started = dt.datetime.now(dt.timezone.utc).isoformat()
            child = subprocess.Popen([sys.executable, "-m", "research.ssq_dlt_v45.runtime", "--config", str(args.config)])
            try:
                last_exit = child.wait(timeout=600)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                last_exit = 124
            print(json.dumps({"scope": "container_supervisor", "started_at_utc": started,
                              "attempt": attempt + 1, "exit_code": last_exit}), flush=True)
            child = None
            if last_exit == 0 or stopped.is_set() or attempt == 3:
                break
            if stopped.wait(60):
                break
        if args.once:
            return last_exit
        if stopped.wait(max(1, next_half_hour(time.time()) - time.time())):
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
