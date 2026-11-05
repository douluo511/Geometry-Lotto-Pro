# V4.7 retrospective research artifacts

These are deterministic gzip files (`mtime=0`), not prospective forecasts. Decompress with any gzip reader. `observations.json.gz` contains the exact national API observations used (SSQ2079/DLT2938); `frozen_manifest.json.gz` contains the preparation contract; `statistics_summary.json.gz` contains all per-game/per-scope statistics and128 explicit exploratory hypotheses. The full4777 per-draw results and original HTTP entities/headers/request parameters, failed attempts, tests, and independent reviews are preserved in the downloadable evidence package delivered in the originating chat.

Manifest canonical SHA256: `5620b85c521b03f67ac9066858a7f739b3e1e4eb82a2beda17fed91f838ce9b1`.

Input canonical SHA256: `3d4399da45529ab458ae926dad682cf01a6a2c4af3e4780bd8bbee6df1c0792c` (use the manifest's exact input_bundle_sha256 as authority; the following reproduction verifies it rather than trusting this prose).

Run from repository root using Python3.11 after checking out the final audited commit:

```python
import gzip, json
from pathlib import Path
from research.harness_v46.d2_challenger_lab import evaluate_ablation_study
p = Path('research/harness_v46/evidence/recency_ablation_20261024')
bundle = json.loads(gzip.decompress((p / 'observations.json.gz').read_bytes()))
manifest = json.loads(gzip.decompress((p / 'frozen_manifest.json.gz').read_bytes()))
result = evaluate_ablation_study(bundle, manifest,
    expected_manifest_sha256='5620b85c521b03f67ac9066858a7f739b3e1e4eb82a2beda17fed91f838ce9b1')
assert result['evaluation_rows_sha256'] == '659a1fff3ec339c2a7b45e7ddb4174185c55f562966d5838cbd93e71899178bc'
Path('reproduced_research.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
```

This replays already public historical labels. It is not an external trusted freeze, real preregistration, official G00/G01 admission, deployment, or external human certification. No registered model/family/NULL seed or previous ledger was replaced. All original failures and blocked gates remain. See the parent research report and sole Issue #468.

`ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET; D2_EDGE_CONFIRMED=NO; formal_A=0; NO_EDGE`.
