import re, hashlib
from ..domain import ScoreCard, AnalysisResult

FILLERS=("然后","就是","其实","那个","这个","嗯","啊","怎么说","就是说")
DETAIL_PATTERNS=(r"\d+",r"分钟|小时|点|次|米|块|岁|今天|昨天|朋友|老板|同事|外卖|会议|地铁|排队")

def _clamp(n): return max(0,min(100,int(round(n))))

def analyze_text(text:str)->AnalysisResult:
    t=(text or '').strip()
    if not t: raise ValueError('text_required')
    length=len(t); sentences=max(1,len(re.findall(r'[。！？!?]',t))+1)
    fillers=sum(t.count(x) for x in FILLERS)
    contrast=bool(re.search(r'但是|结果|没想到|原来|却|反而|后来才发现|偏偏|本来以为',t))
    pov=bool(re.search(r'我觉得|我发现|我认为|在我看来|最奇怪|最荒谬|本质上|真正',t))
    detail=any(re.search(p,t) for p in DETAIL_PATTERNS)
    analogy=bool(re.search(r'像|仿佛|简直|好比|就像',t))
    escalation=bool(re.search(r'永远|从来|全世界|一辈子|宇宙|人生|越来越',t))
    selfref=bool(re.search(r'我自己|我也|我这个人|我的问题|我最大的|我以为',t))
    question=len(re.findall(r'[？?]',t))
    scores=ScoreCard(
        observation=_clamp(42+(18 if detail else 0)+min(24,length/5)),
        pov=_clamp(36+(30 if pov else 0)+(14 if contrast else 0)),
        concise=_clamp(92-max(0,length-100)*0.25-fillers*6),
        humor=_clamp(32+(20 if contrast else 0)+(14 if analogy else 0)+(10 if escalation else 0)+(8 if selfref else 0)),
        story=_clamp(36+(14 if detail else 0)+(18 if contrast else 0)+min(18,sentences*3)),
        rhythm=_clamp(52+min(20,sentences*3)-fillers*4),
        interaction=_clamp(46+min(24,question*8)+(6 if '你' in t else 0))
    )
    imp=[]
    if not detail: imp.append('补一个可被看见或听见的具体细节。')
    if not pov: imp.append('补一句明确观点：你真正想说的是什么？')
    if not contrast: imp.append('尝试建立预期后再打破，但只改这一处。')
    if fillers>1: imp.append('删除一部分口头填充词，再读一遍。')
    if length>120: imp.append('压缩30%，保留冲突、细节和结尾。')
    if not imp: imp.append('结构较完整；下一轮只练停顿和重音，不继续加技巧。')
    weakest=scores.weakest()[0]
    next_map={
      'observation':'再讲一次，必须加入1个具体动作或数字。','pov':'用一句话补上“所以我真正想说的是…”。',
      'concise':'把原文缩短30%，不能丢掉冲突。','humor':'做A/B：原版 vs 只增加一次预期反转。',
      'story':'补齐背景→欲望→障碍→转折→结果。','rhythm':'拆成3个短句，每句只承担一个信息点。',
      'interaction':'结尾加一个自然问题，让对方有可接话空间。'}
    evidence={'text_sha256':hashlib.sha256(t.encode('utf-8')).hexdigest(),'chars':length,'sentences':sentences,'fillers':fillers,
              'features':{'contrast':contrast,'pov':pov,'detail':detail,'analogy':analogy,'escalation':escalation,'selfref':selfref}}
    return AnalysisResult(scores,[f'当前强项：{scores.strongest()[0]}'],imp,next_map[weakest],evidence)
