from .scoring import analyze_text

def compare_variants(original:str, variant:str):
    a=analyze_text(original).score.as_dict(); b=analyze_text(variant).score.as_dict()
    delta={k:b[k]-a[k] for k in a}
    improved=[k for k,v in delta.items() if v>=5]
    worsened=[k for k,v in delta.items() if v<=-5]
    verdict='KEEP_VARIANT' if len(improved)>len(worsened) else 'REVIEW_OR_ROLLBACK'
    return {'original':a,'variant':b,'delta':delta,'improved':improved,'worsened':worsened,'verdict':verdict,
            'note':'这是规则型反事实比较；真实表达效果仍需人工听感/听众反馈验证。'}
