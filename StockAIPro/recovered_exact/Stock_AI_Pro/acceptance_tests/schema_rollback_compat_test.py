import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cur=json.loads((ROOT/'current.json').read_text(encoding='utf-8'))
a=ROOT/'versions'/cur['active_version'];p=ROOT/'versions'/cur['previous_version']
ac=json.loads((a/'config.default.json').read_text(encoding='utf-8'));pc=json.loads((p/'config.default.json').read_text(encoding='utf-8'))
assert int(ac['schema_version'])==int(pc['schema_version']), 'active release changed config schema and would make code rollback unsafe'
assert int(ac['schema_version'])==6
# New 4.3 model controls are additive defaults, not an incompatible schema mutation.
for k in ['extra_trees_n_estimators','extra_trees_min_samples_leaf','ensemble_shrinkage']:
    assert k in ac['model']
print('ACTIVE/PREVIOUS CONFIG ROLLBACK COMPATIBILITY TEST PASS')
