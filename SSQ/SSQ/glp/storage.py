from __future__ import annotations
import json,sqlite3
from pathlib import Path
from typing import Any
from .domain import CanonicalDataset, Draw
from .util import app_data_dir, atomic_json, sha256_json

class Store:
    def __init__(self, root: Path|None=None):
        self.root=(root or app_data_dir()).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.history_path=self.root/'canonical_history.json'; self.evidence_path=self.root/'source_evidence.json'; self.db_path=self.root/'ledger.sqlite3'
        self._init_db()
    def _connect(self)->sqlite3.Connection:
        db=sqlite3.connect(self.db_path); db.row_factory=sqlite3.Row; db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA foreign_keys=ON'); return db
    def _init_db(self)->None:
        with self._connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS experiments(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,input_hash TEXT NOT NULL,code_hash TEXT NOT NULL,payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS freezes(prediction_id TEXT PRIMARY KEY,target_issue TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,canonical_hash TEXT NOT NULL,model_hash TEXT NOT NULL,selector_hash TEXT NOT NULL,freeze_hash TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS replays(prediction_id TEXT PRIMARY KEY,replayed_at TEXT NOT NULL,actual_issue TEXT NOT NULL,payload_json TEXT NOT NULL,FOREIGN KEY(prediction_id) REFERENCES freezes(prediction_id));
            CREATE TABLE IF NOT EXISTS canonical_contexts(context_hash TEXT PRIMARY KEY,created_at TEXT NOT NULL,payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS final_gate_decisions(gate_hash TEXT PRIMARY KEY,target_issue TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,status TEXT NOT NULL,payload_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS postmortems(prediction_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,payload_json TEXT NOT NULL,FOREIGN KEY(prediction_id) REFERENCES freezes(prediction_id));
            CREATE TRIGGER IF NOT EXISTS freezes_no_update BEFORE UPDATE ON freezes BEGIN SELECT RAISE(ABORT,'immutable freezes'); END;
            CREATE TRIGGER IF NOT EXISTS freezes_no_delete BEFORE DELETE ON freezes BEGIN SELECT RAISE(ABORT,'immutable freezes'); END;
            CREATE TRIGGER IF NOT EXISTS replays_no_update BEFORE UPDATE ON replays BEGIN SELECT RAISE(ABORT,'immutable replays'); END;
            CREATE TRIGGER IF NOT EXISTS contexts_no_update BEFORE UPDATE ON canonical_contexts BEGIN SELECT RAISE(ABORT,'immutable contexts'); END;
            CREATE TRIGGER IF NOT EXISTS final_gate_no_update BEFORE UPDATE ON final_gate_decisions BEGIN SELECT RAISE(ABORT,'immutable final gate'); END;
            ''')
    def save_dataset(self,dataset:CanonicalDataset,evidence:dict[str,Any])->None:
        payload={'schema':3,'game':'SSQ','canonical_hash':dataset.canonical_hash,'draws':[d.to_dict() for d in dataset.draws]}
        atomic_json(self.history_path,payload); atomic_json(self.evidence_path,evidence)
    def load_draws(self)->tuple[list[Draw],str]:
        if not self.history_path.exists(): raise FileNotFoundError('尚无已验证的官方历史数据')
        value=json.loads(self.history_path.read_text(encoding='utf-8'))
        if value.get('game')!='SSQ': raise ValueError('dataset game mismatch')
        draws=[Draw.from_dict(x) for x in value.get('draws',[])]
        if not draws: raise ValueError('empty canonical history')
        expected=str(value.get('canonical_hash') or ''); actual=sha256_json([d.to_dict() for d in draws])
        if actual!=expected: raise ValueError('本地历史数据哈希校验失败，请运行“一键修复”')
        if len({d.issue for d in draws})!=len(draws): raise ValueError('本地历史数据存在重复期号')
        if any(draws[i].draw_date>=draws[i+1].draw_date for i in range(len(draws)-1)): raise ValueError('本地历史开奖日期非严格递增')
        return draws,expected
    def integrity_check(self)->dict[str,Any]:
        checks=[]; draws=None; digest=''
        try:
            with self._connect() as db:
                row=db.execute('PRAGMA integrity_check').fetchone(); ok=bool(row and str(row[0]).lower()=='ok')
            checks.append({'name':'SQLite integrity','status':'PASS' if ok else 'FAIL','detail':str(row[0]) if row else 'no result'})
        except Exception as exc: checks.append({'name':'SQLite integrity','status':'FAIL','detail':str(exc)})
        try:
            draws,digest=self.load_draws(); checks.append({'name':'Canonical hash','status':'PASS','detail':f'{len(draws)} 期 / {digest}'})
        except Exception as exc: checks.append({'name':'Canonical hash','status':'FAIL','detail':str(exc)})
        try:
            if draws is None: raise ValueError('canonical history unavailable')
            ev=json.loads(self.evidence_path.read_text(encoding='utf-8'))
            if str(ev.get('canonical_hash'))!=digest: raise ValueError('source evidence canonical_hash mismatch')
            if str(ev.get('crosscheck_status'))!='PASS': raise ValueError('source crosscheck is not PASS')
            if int(ev.get('draw_count',-1))!=len(draws): raise ValueError('source evidence draw_count mismatch')
            latest=ev.get('latest') or {}
            if str(latest.get('issue'))!=draws[-1].issue: raise ValueError('source evidence latest issue mismatch')
            checks.append({'name':'Source evidence','status':'PASS','detail':f"crosscheck={ev.get('crosscheck_count',0)} / latest={draws[-1].issue}"})
        except Exception as exc: checks.append({'name':'Source evidence','status':'FAIL','detail':str(exc)})
        return {'status':'FAIL' if any(c['status']=='FAIL' for c in checks) else 'PASS','checks':checks}
