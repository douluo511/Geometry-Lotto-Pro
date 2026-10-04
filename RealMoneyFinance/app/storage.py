from __future__ import annotations

from pathlib import Path
import json
import os
import sqlite3
from contextlib import closing
from typing import Iterable

from .domain import DailyBar, CapitalObservation


class Storage:
    def __init__(self, root: Path):
        self.root = root
        self.db_path = root / "storage" / "finance.sqlite3"
        self.raw_dir = root / "data" / "raw"
        self.evidence_dir = root / "evidence"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    def _init_db(self) -> None:
        with closing(self._connect()) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS daily_bars(
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL NOT NULL,
                close REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                volume REAL NOT NULL,
                amount REAL NOT NULL,
                pct_change REAL NOT NULL,
                turnover_rate REAL,
                provider TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                PRIMARY KEY(symbol, trade_date)
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS observations(
                symbol TEXT NOT NULL,
                asof TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(symbol, asof)
            )""")
            c.commit()

    def persist_raw_metadata(self, meta: dict) -> Path:
        digest = str(meta["payload_sha256"])
        target = self.raw_dir / f"{digest}.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, target)
        return target

    def upsert_bars(self, bars: Iterable[DailyBar]) -> int:
        rows = [b.to_dict() for b in bars]
        with closing(self._connect()) as c:
            c.executemany("""INSERT INTO daily_bars(
                symbol, trade_date, open, close, high, low, volume, amount,
                pct_change, turnover_rate, provider, raw_sha256
            ) VALUES(
                :symbol,:trade_date,:open,:close,:high,:low,:volume,:amount,
                :pct_change,:turnover_rate,:provider,:raw_sha256
            ) ON CONFLICT(symbol, trade_date) DO UPDATE SET
                open=excluded.open, close=excluded.close, high=excluded.high, low=excluded.low,
                volume=excluded.volume, amount=excluded.amount, pct_change=excluded.pct_change,
                turnover_rate=excluded.turnover_rate, provider=excluded.provider,
                raw_sha256=excluded.raw_sha256""", rows)
            c.commit()
        return len(rows)

    def load_bars(self, symbol: str, limit: int = 160) -> list[DailyBar]:
        with closing(self._connect()) as c:
            got = c.execute("""SELECT symbol, trade_date, open, close, high, low, volume, amount,
                pct_change, turnover_rate, provider, raw_sha256
                FROM daily_bars WHERE symbol=? ORDER BY trade_date DESC LIMIT ?""",
                (symbol, int(limit))).fetchall()
        got.reverse()
        return [DailyBar(*r) for r in got]

    def save_observation(self, obs: CapitalObservation) -> None:
        payload = json.dumps(obs.to_dict(), ensure_ascii=False, sort_keys=True)
        with closing(self._connect()) as c:
            c.execute("""INSERT INTO observations(symbol, asof, payload_json)
                VALUES(?,?,?) ON CONFLICT(symbol,asof) DO UPDATE SET payload_json=excluded.payload_json""",
                (obs.symbol, obs.asof, payload))
            c.commit()

    def integrity_check(self) -> str:
        with closing(self._connect()) as c:
            row = c.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"
