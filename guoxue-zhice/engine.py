from __future__ import annotations
import datetime as dt
from storage import Store

SCENARIO_KEYWORDS = {
"negotiation":["谈判","压价","价格","合作","说服","条件","底线","筹码"],
"competition":["竞争","对手","竞标","胜负","争夺","博弈","市场"],
"organization":["团队","管理","制度","组织","员工","执行","奖惩","领导"],
"relationships":["关系","人情","朋友","沟通","冲突","信任","人心","识人"],
"wealth":["赚钱","投资","商业","生意","财富","成本","利润","现金流"],
"self":["焦虑","自律","成长","选择","坚持","内耗","修身","学习"],
"risk":["风险","不确定","危机","失败","退路","损失","机会"],
"history":["历史","复盘","规律","兴衰","案例","教训"],
"health":["健康","养生","睡眠","饮食","身体"]}
SCENARIO_LABELS={"negotiation":"谈判与合作","competition":"竞争与博弈","organization":"组织与管理","relationships":"人性与关系","wealth":"财富与商业","self":"修身与执行","risk":"风险与不确定性","history":"历史类比与复盘","health":"健康与生活","general":"综合判断"}
DEFAULT_QUESTIONS={
"negotiation":["双方真正想得到什么？","谁的替代方案更强？","哪些条件可交换、哪些必须守住？"],
"competition":["决定胜负的关键资源是什么？","是否能避开对手优势而改变战场？","失败成本与退出条件是什么？"],
"organization":["问题来自人、流程、激励还是权责？","规则是否可执行且可审计？","奖励与惩罚是否真的改变行为？"],
"relationships":["对方的利益、情绪与承诺是否一致？","这是一次性关系还是重复合作？","我看到的是事实还是自己的投射？"],
"wealth":["现金从哪里来、流向哪里？","收益来自能力、周期还是杠杆？","最坏情形下能否活下来？"],
"self":["我能控制什么、不能控制什么？","知道与做到之间卡在哪一环？","如果去掉面子与情绪，我会如何选择？"],
"risk":["最坏结果是什么？","哪些信号出现时必须撤退？","有没有成本更低的试错方式？"],
"history":["当前局面与历史案例真正相似的是机制还是表面？","当时参与者有哪些我们今天没有的约束？","反例在哪里？"],
"health":["这是古代经验、现代证据还是个人感受？","风险是否需要现代医学评估？","哪些生活方式调整低风险且可持续？"],
"general":["目标是什么？","关键约束是什么？","哪条假设最可能错？"]}

class GoalEngine:
    def __init__(self, store: Store): self.store=store
    @property
    def classics(self): return self.store.load_knowledge()["classics"]
    def classify(self, goal):
        scores=[]
        for scenario,words in SCENARIO_KEYWORDS.items():
            score=sum(1 for word in words if word in goal)
            if score: scores.append((scenario,score))
        if not scores: return [("general",1)]
        scores.sort(key=lambda x:(-x[1],x[0])); return scores[:3]
    def _select_classics(self, scenarios):
        scored=[]
        for row in self.classics:
            overlap=sum(1 for s in scenarios if s in row["scenarios"])
            if overlap: scored.append((overlap,int(row.get("priority",0)),row))
        scored.sort(key=lambda x:(-x[0],-x[1],x[2]["title"]))
        return [x[2] for x in scored[:4]] if scored else self.classics[:4]
    def analyze(self, goal):
        goal=goal.strip()
        if len(goal)<4: raise ValueError("请把目标写得更具体一些")
        scenarios=[x[0] for x in self.classify(goal) if x[0]!="general"] or ["general"]
        questions=[]
        for s in scenarios: questions.extend(DEFAULT_QUESTIONS.get(s,DEFAULT_QUESTIONS["general"]))
        selected=self._select_classics(scenarios)
        methods=[]
        for row in selected:
            for method in row["methods"][:2]:
                methods.append({"title":row["title"],"method":method["name"],"prompt":method["prompt"],"source_note":row["source_note"],"boundary":row["boundary"],"authorship_status":row.get("authorship_status","常规传世文本"),"case_prompt":row.get("case_prompt",""),"counterexample_prompt":row.get("counterexample_prompt","")})
        result={"goal":goal,"timestamp":dt.datetime.now().isoformat(timespec="seconds"),"scenarios":[SCENARIO_LABELS.get(s,s) for s in scenarios],"questions":list(dict.fromkeys(questions))[:6],"methods":methods,
        "five_whys":["为什么我认为这条路径能达成目标？","这个判断依赖的关键事实是什么？","这些事实是已验证，还是推测/听说？","如果关键事实相反，我的方案还成立吗？","最小成本验证这条假设的方法是什么？"],
        "reverse_validation":["假设当前结论完全错误，哪些现象仍能被解释？","寻找至少一个能推翻主判断的反例。","把最强反方观点写出来，再决定是否行动。"],
        "status":"ACTION_HYPOTHESIS","note":"经典提供的是分析视角，不是自动正确的答案；先验证事实，再做行动。"}
        self.store.append_analysis({"timestamp":result["timestamp"],"goal":goal,"scenarios":result["scenarios"],"status":result["status"]})
        return result
    def stats(self):
        state=self.store.load_state(); classics=self.classics
        return {"classics":len(classics),"analyses":len(state["analyses"]),"reviews":len(state["reviews"]),"disputed":sum(1 for r in classics if r.get("authorship_status") not in (None,"常规传世文本")),"last_update":state.get("last_update") or "尚未联网更新"}

class ReviewEngine:
    def __init__(self, store: Store): self.store=store
    def save(self, goal, action, result, lesson):
        fields=[goal.strip(),action.strip(),result.strip(),lesson.strip()]
        if any(len(x)<2 for x in fields): raise ValueError("目标、行动、结果、教训都需要填写")
        item={"timestamp":dt.datetime.now().isoformat(timespec="seconds"),"goal":fields[0],"action":fields[1],"result":fields[2],"lesson":fields[3]}
        self.store.append_review(item); return item
    def recent(self, limit=5): return list(reversed(self.store.load_state()["reviews"][-limit:]))
