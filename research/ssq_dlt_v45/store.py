"""Append-only research event ledger; SQLite is not external timestamp custody."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

APP_ID = 0x47565035


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('NONFINITE_JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            app_id = db.execute('PRAGMA application_id').fetchone()[0]
            if app_id not in (0, APP_ID) or tables - {'events'} or (app_id == 0 and tables):
                raise ValueError('FOREIGN_DATABASE')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                raise ValueError('UNKNOWN_SCHEMA')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS events (kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(kind,key))')
            for op in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op} BEFORE {op} ON events BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS immutable_replace BEFORE INSERT ON events WHEN EXISTS(SELECT 1 FROM events WHERE kind=NEW.kind AND key=NEW.key) BEGIN SELECT RAISE(ABORT, 'DUPLICATE_KEY'); END")
            db.execute(f'PRAGMA application_id={APP_ID}')
            db.execute('PRAGMA user_version=1')
            db.commit()

    @contextmanager
    def connect(self, readonly=False):
        db = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True, timeout=10) if readonly else sqlite3.connect(self.path, isolation_level=None, timeout=10)
        try:
            db.execute('PRAGMA busy_timeout=10000')
            db.execute('PRAGMA query_only=ON' if readonly else 'PRAGMA synchronous=FULL')
            yield db
        finally:
            db.close()

    @staticmethod
    def checked(row):
        if row is None:
            return None
        payload, sha = row
        value = parse(payload)
        if canonical(value) != payload or digest(value) != sha:
            raise ValueError('LEDGER_SHA_MISMATCH')
        return value

    def read(self, kind, key):
        with self.connect(True) as db:
            return self.checked(db.execute('SELECT payload,sha256 FROM events WHERE kind=? AND key=?', (kind,key)).fetchone())

    def rows(self, kind):
        with self.connect(True) as db:
            return [self.checked(row) for row in db.execute('SELECT payload,sha256 FROM events WHERE kind=? ORDER BY key', (kind,))]

    def append(self, kind, key, payload):
        if not all(type(x) is str and x and len(x) <= 256 for x in (kind,key)):
            raise ValueError('INVALID_IDENTITY')
        body, sha = canonical(payload), digest(payload)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                old = self.checked(db.execute('SELECT payload,sha256 FROM events WHERE kind=? AND key=?', (kind,key)).fetchone())
                if old is not None:
                    if canonical(old) != body:
                        raise ValueError('IMMUTABLE_CONFLICT')
                    db.rollback()
                    return False
                db.execute('INSERT INTO events VALUES(?,?,?,?)', (kind,key,body,sha))
                db.commit()
                return True
            except BaseException:
                db.rollback()
                raise
