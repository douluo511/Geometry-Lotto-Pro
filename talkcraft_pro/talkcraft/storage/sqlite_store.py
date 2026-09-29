import sqlite3, json, time
from pathlib import Path

class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def _conn(self): return sqlite3.connect(self.path)
    def _init(self):
        with self._conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, text TEXT, scores TEXT, payload TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS source_snapshots(source_id TEXT PRIMARY KEY, ts INTEGER, ok INTEGER, status INTEGER, sha256 TEXT, size INTEGER, error TEXT)')
    def save_evidence(self,text,scores,payload):
        with self._conn() as c: c.execute('INSERT INTO evidence(ts,text,scores,payload) VALUES(?,?,?,?)',(int(time.time()),text,json.dumps(scores,ensure_ascii=False),json.dumps(payload,ensure_ascii=False)))
    def evidence(self,limit=200):
        with self._conn() as c:
            rows=c.execute('SELECT id,ts,text,scores,payload FROM evidence ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return [{'id':r[0],'ts':r[1],'text':r[2],'scores':json.loads(r[3]),'payload':json.loads(r[4])} for r in rows]
    def upsert_source(self,sid,result):
        with self._conn() as c:
            c.execute('INSERT INTO source_snapshots(source_id,ts,ok,status,sha256,size,error) VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET ts=excluded.ts,ok=excluded.ok,status=excluded.status,sha256=excluded.sha256,size=excluded.size,error=excluded.error',
                      (sid,int(time.time()),int(result.ok),result.status,result.sha256,result.size,result.error))
    def integrity(self):
        with self._conn() as c: return c.execute('PRAGMA integrity_check').fetchone()[0]
