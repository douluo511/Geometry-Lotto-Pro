"""Separate append-only SQLite identity for Agent claims, results and memory."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from .policy import AgentBlocked,canonical,digest,native,parse

APP_ID=0x47414731

class Ledger:
    def __init__(self,path):
        self.path=Path(path).resolve(); native(self.path.parent).mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            app=db.execute('PRAGMA application_id').fetchone()[0]
            if app not in (0,APP_ID) or tables-{'events'} or (app==0 and tables):
                raise AgentBlocked('FOREIGN_DATABASE')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1): raise AgentBlocked('UNKNOWN_SCHEMA')
            db.execute('PRAGMA journal_mode=WAL'); db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS events(kind TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(kind,key))')
            for op in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op} BEFORE {op} ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS immutable_replace BEFORE INSERT ON events WHEN EXISTS(SELECT 1 FROM events WHERE kind=NEW.kind AND key=NEW.key) BEGIN SELECT RAISE(ABORT,'DUPLICATE_KEY'); END")
            db.execute(f'PRAGMA application_id={APP_ID}'); db.execute('PRAGMA user_version=1'); db.commit()
    @contextmanager
    def connect(self,readonly=False):
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=10) if readonly else sqlite3.connect(str(native(self.path)),isolation_level=None,timeout=10)
        try:
            db.execute('PRAGMA busy_timeout=10000'); db.execute('PRAGMA query_only=ON' if readonly else 'PRAGMA synchronous=FULL')
            yield db
        finally: db.close()
    @staticmethod
    def checked(row):
        if row is None:return None
        value=parse(row[0])
        if canonical(value)!=row[0] or digest(value)!=row[1]:raise AgentBlocked('LEDGER_SHA_MISMATCH')
        return value
    def read(self,kind,key):
        with self.connect(True) as db:return self.checked(db.execute('SELECT payload,sha256 FROM events WHERE kind=? AND key=?',(kind,key)).fetchone())
    def rows(self,kind):
        with self.connect(True) as db:return [self.checked(r) for r in db.execute('SELECT payload,sha256 FROM events WHERE kind=? ORDER BY key',(kind,))]
    def append(self,kind,key,value):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                old=self.checked(db.execute('SELECT payload,sha256 FROM events WHERE kind=? AND key=?',(kind,key)).fetchone())
                if old is not None:
                    if old!=value:raise AgentBlocked('IMMUTABLE_CONFLICT')
                    db.rollback();return False
                db.execute('INSERT INTO events VALUES(?,?,?,?)',(kind,key,canonical(value),digest(value)));db.commit();return True
            except BaseException:db.rollback();raise
    def integrity(self):
        with self.connect(True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise AgentBlocked('SQLITE_INTEGRITY_FAILED')
            for row in db.execute('SELECT payload,sha256 FROM events'):self.checked(row)
        return 'PASS'
