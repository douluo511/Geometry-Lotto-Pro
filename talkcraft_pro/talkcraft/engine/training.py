import json, random
from pathlib import Path

class TrainingEngine:
    def __init__(self, data_dir:Path):
        self.data_dir=Path(data_dir)
        self.drills=json.loads((self.data_dir/'drills.json').read_text(encoding='utf-8'))
        self.cases=json.loads((self.data_dir/'cases.json').read_text(encoding='utf-8'))
    def daily(self, weakness=None):
        pool=self.drills
        if weakness:
            keys={'observation':['事实','具体'],'pov':['观点'],'concise':['压缩'],'humor':['反差','类比','夸张','三段式','回扣'],
                  'story':['背景-欲望'],'rhythm':['压缩'],'interaction':['接话','问题']}
            terms=keys.get(weakness,[])
            cand=[d for d in pool if any(x in d['task'] for x in terms)]
            if cand: pool=cand
        return random.choice(pool)
    def case_for(self, mechanism=None):
        pool=[c for c in self.cases if not mechanism or c['mechanism']==mechanism]
        return random.choice(pool or self.cases)
