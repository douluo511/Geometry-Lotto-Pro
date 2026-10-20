"""Independent append-only graph evidence and a process-scoped run lock."""
from contextlib import contextmanager
from pathlib import Path
import hashlib,json,os,sqlite3

APP_ID=0x474A4731


class GraphBlocked(ValueError):pass


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()
def checked(row):
    if row is None:return None
    try:value=json.loads(row[0])
    except (ValueError,TypeError) as exc:raise GraphBlocked('GRAPH_JOURNAL_INVALID_JSON') from exc
    if canonical(value)!=row[0] or digest(value)!=row[1]:raise GraphBlocked('GRAPH_JOURNAL_SHA_MISMATCH')
    return value


class Journal:
    def __init__(self,path):
        self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            app=db.execute('PRAGMA application_id').fetchone()[0]
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if app not in (0,APP_ID) or tables-{'events'} or (app==0 and tables) or version not in (0,1):raise GraphBlocked('FOREIGN_GRAPH_JOURNAL')
            db.execute('PRAGMA journal_mode=WAL');db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS events(kind TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(kind,key))')
            for op in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{op} BEFORE {op} ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS immutable_replace BEFORE INSERT ON events WHEN EXISTS(SELECT 1 FROM events WHERE kind=NEW.kind AND key=NEW.key) BEGIN SELECT RAISE(ABORT,'DUPLICATE_KEY'); END")
            db.execute(f'PRAGMA application_id={APP_ID}');db.execute('PRAGMA user_version=1');db.commit()

    @contextmanager
    def connect(self,readonly=False):
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=5) if readonly else sqlite3.connect(str(self.path),isolation_level=None,timeout=5)
        try:
            db.execute('PRAGMA busy_timeout=5000');db.execute('PRAGMA query_only=ON' if readonly else 'PRAGMA synchronous=FULL')
            yield db
        finally:db.close()

    def read(self,kind,key):
        with self.connect(True) as db:return checked(db.execute('SELECT payload,sha256 FROM events WHERE kind=? AND key=?',(kind,key)).fetchone())

    def rows(self,kind):
        with self.connect(True) as db:return [checked(row) for row in db.execute('SELECT payload,sha256 FROM events WHERE kind=? ORDER BY key',(kind,))]

    def append(self,kind,key,value):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                old=checked(db.execute('SELECT payload,sha256 FROM events WHERE kind=? AND key=?',(kind,key)).fetchone())
                if old is not None:
                    if old!=value:raise GraphBlocked('GRAPH_IMMUTABLE_CONFLICT')
                    db.rollback();return False
                db.execute('INSERT INTO events VALUES(?,?,?,?)',(kind,key,canonical(value),digest(value)));db.commit();return True
            except BaseException:db.rollback();raise

    def integrity(self):
        with self.connect(True) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise GraphBlocked('GRAPH_SQLITE_INTEGRITY_FAILED')
            for row in db.execute('SELECT payload,sha256 FROM events'):checked(row)
        return 'PASS'


@contextmanager
def process_lock(path):
    """OS releases the byte lock after process exit; no stale lease takeover."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b')
    try:
        if handle.seek(0,os.SEEK_END)==0:handle.write(b'0');handle.flush();os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:raise GraphBlocked('CONCURRENT_GRAPH_EXECUTION') from exc
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
    finally:handle.close()
