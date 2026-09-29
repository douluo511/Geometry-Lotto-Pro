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
            c.execute('CREATE TABLE IF NOT EXISTS source_receipts(id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, ts INTEGER, requested_url TEXT, final_url TEXT, ok INTEGER, status INTEGER, content_type TEXT, sha256 TEXT, size INTEGER, body_b64 TEXT, attempts_json TEXT, error TEXT)')
    def save_evidence(self,text,scores,payload):
        with self._conn() as c: c.execute('INSERT INTO evidence(ts,text,scores,payload) VALUES(?,?,?,?)',(int(time.time()),text,json.dumps(scores,ensure_ascii=False),json.dumps(payload,ensure_ascii=False)))
    def evidence(self,limit=200):
        with self._conn() as c:
            rows=c.execute('SELECT id,ts,text,scores,payload FROM evidence ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return [{'id':r[0],'ts':r[1],'text':r[2],'scores':json.loads(r[3]),'payload':json.loads(r[4])} for r in rows]
    def upsert_source(self,sid,result):
        ts=int(time.time())
        with self._conn() as c:
            c.execute('INSERT INTO source_snapshots(source_id,ts,ok,status,sha256,size,error) VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET ts=excluded.ts,ok=excluded.ok,status=excluded.status,sha256=excluded.sha256,size=excluded.size,error=excluded.error',
                      (sid,ts,int(result.ok),result.status,result.sha256,result.size,result.error))
            c.execute('INSERT INTO source_receipts(source_id,ts,requested_url,final_url,ok,status,content_type,sha256,size,body_b64,attempts_json,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                      (sid,ts,result.requested_url,result.final_url,int(result.ok),result.status,result.content_type,result.sha256,result.size,result.body_b64,json.dumps(result.attempts,ensure_ascii=False),result.error))
    def source_receipts(self,limit=100):
        with self._conn() as c:
            rows=c.execute('SELECT source_id,ts,requested_url,final_url,ok,status,content_type,sha256,size,attempts_json,error FROM source_receipts ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return [{'source_id':r[0],'ts':r[1],'requested_url':r[2],'final_url':r[3],'ok':bool(r[4]),'status':r[5],'content_type':r[6],'sha256':r[7],'size':r[8],'attempts':json.loads(r[9] or '[]'),'error':r[10]} for r in rows]
    def integrity(self):
        with self._conn() as c: return c.execute('PRAGMA integrity_check').fetchone()[0]
