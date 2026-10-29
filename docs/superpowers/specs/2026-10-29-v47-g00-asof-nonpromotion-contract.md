# V4.7 P0: G00/G01 network-history report cannot grant formal status

## Failure surface
On exact PR #467 HEAD `900b2f7...`, DLT `scripts/real_network_check.py` emits `status=PASS` when source transport/history overlap succeed, but does not explicitly bind its result to SHADOW or mark publication as-of, official target, external TSA and result as independently unverified. A consumer could mistake a historical network PASS for formal prospective admission.

## Contract
Retain the legacy network PASS/FAIL and return codes unchanged. For BOTH paths append immutable diagnostic keys:
`gate_scope=LIVE_HISTORY_NETWORK_CROSSCHECK_ONLY`,
`evidence_class=SHADOW`,
`history_asof_authenticity=NOT_VERIFIED`,
`source_origin_authenticity=NOT_CRYPTOGRAPHICALLY_VERIFIED`,
`official_target_admission=BLOCKED`,
`external_predraw_tsa=NOT_VERIFIED`,
`official_outcome_authenticity=NOT_VERIFIED`,
`prospective_verified=false`,
`formal_A=0`,
`decision=NO_EDGE`.
This diagnostic change cannot approve real official source/raw provenance, earliest sale cutoff, historical publication time, trust roots, host scheduling, or an independent prospective study.

## Safety
No source fallback, model identity, Random NULL, freeze history, official draw, schema name, test baseline, or release policy may change. Live G00/G01 failures remain errors and block downstream native build.
