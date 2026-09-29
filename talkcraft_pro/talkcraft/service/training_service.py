import json, time
from pathlib import Path
from ..engine.scoring import analyze_text
from ..engine.reversal import compare_variants
from ..engine.training import TrainingEngine
from ..net.client import NetClient
from ..storage.sqlite_store import Store

class TrainingService:
    def __init__(self, base_dir:Path):
        self.base=Path(base_dir); self.data=self.base/'data'; self.store=Store(self.base/'runtime'/'talkcraft.db')
        self.engine=TrainingEngine(self.data); self.net=NetClient()
        self.sources=json.loads((self.data/'sources.json').read_text(encoding='utf-8'))
    def analyze(self,text):
        r=analyze_text(text); self.store.save_evidence(text,r.score.as_dict(),r.evidence); return r
    def daily(self,weakness=None): return self.engine.daily(weakness)
    def case(self,mechanism=None): return self.engine.case_for(mechanism)
    def compare(self,a,b): return compare_variants(a,b)
    def update_all_sources(self):
        out=[]
        for s in self.sources:
            r=self.net.get(s['url']); self.store.upsert_source(s['id'],r)
            out.append({'source':s['id'],'name':s['name'],'ok':r.ok,'status':r.status,'sha256':r.sha256,'size':r.size,'error':r.error})
        return {'ok':all(x['ok'] for x in out),'sources':out,'policy':'Any failed source keeps overall update FAIL; cache is not reported as fresh.'}
    def repair(self):
        checks={'db_integrity':self.store.integrity()=='ok','knowledge':(self.data/'knowledge.json').exists(),'drills':(self.data/'drills.json').exists(),'cases':(self.data/'cases.json').exists(),'sources':(self.data/'sources.json').exists()}
        return {'ok':all(checks.values()),'checks':checks}
    def analytics(self):
        ev=self.store.evidence();
        if not ev:return {'count':0,'averages':{},'weakest':None,'strongest':None}
        keys=ev[0]['scores'].keys(); avg={k:round(sum(x['scores'][k] for x in ev)/len(ev),1) for k in keys}
        return {'count':len(ev),'averages':avg,'weakest':min(avg,key=avg.get),'strongest':max(avg,key=avg.get)}
