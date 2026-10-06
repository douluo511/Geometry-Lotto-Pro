# DLT Prospective-Only Qualification Protocol

Status: **RESEARCH / FAIL-CLOSED / NOT A PRODUCTION PROMOTION PATH BY ITSELF**

## Why this exists

Historical V2 Ridge research was closed as **NO EDGE**. Repeatedly adapting models to the
same 2,927 historical draws would increase selection bias. Any future predictive claim must
therefore be evaluated on predictions frozen **before** the corresponding official draw exists.

## Cohort identity

A prospective cohort is bound to all of the following:

- exact source commit;
- model hash;
- selector hash;
- complete model specification;
- complete promotion policy / hyperparameters;
- protocol version.

The cohort id is derived from these identities. If any identity changes, the active cohort
changes and the qualifying replay count restarts from zero. Old cohorts remain preserved as
evidence and are never merged into the new count.

## Immutable evidence

For each target issue, the ledger writes one immutable Freeze record containing:

- exact cohort / protocol / source commit identities;
- canonical history hash and latest observed official issue;
- target issue and target date;
- exact prediction id;
- complete front/back rankings;
- one research-only 5+2 combination;
- research-only dan candidates;
- model / selector / score hashes;
- freeze hash and record hash;
- explicit `NO_EDGE / NULL_DAN / rho=0` boundaries.

A second write for the same target must byte-match the first record. A changed record fails
closed. A target that already exists in official history cannot be registered as prospective.

When the official target draw later exists, one immutable replay is written and bound back to
the exact Freeze hash. Missing predictions and targets without a pre-draw Freeze do not add to
the qualifying count.

## Qualification threshold

The hard minimum is **30 valid selector/model/source-matched prospective replays**.

At 30 or more valid replays, both front and back must independently show:

- positive mean recall gain versus same-target deterministic random rankings;
- bootstrap 95% lower bound > 0;
- permutation p < configured alpha;
- the same conditions in both chronological halves.

Failure is `NO_EDGE`. Passing this stage yields only
`PROSPECTIVE_EDGE_CANDIDATE`, never production promotion.

The production boundary remains:

- `EDGE_STATE=NO_EDGE`
- `DAN_STATE=NULL_DAN`
- `production_rho=0`
- `promotion_authorized=false`

until the existing Evidence Court and all frozen release gates independently pass.

## Git evidence branch

The persistent ledger is stored separately on:

`evidence/dlt-prospective-ledger`

Model/protocol source remains on its research exact head. Evidence commits append Freeze /
Replay records without modifying the model source commit, allowing later runs to accumulate
prospective evidence without silently resetting the cohort.

## Release boundary

This protocol does **not** clear:

- repository independence;
- independent software Release N→N+1;
- updater real-network release proof;
- release context;
- Final Gate.

A successful prospective workflow means the protocol executed correctly. It does not mean
predictive edge exists.

## Single-writer CI governance

The persistent `evidence/dlt-prospective-ledger` branch has exactly one CI writer:
`.github/workflows/dlt-prospective-only.yml`.

Windows acceptance may validate the same DLT product bytes, but it must not embed a second
`prospective-cycle` ledger writer. Duplicate writers sharing one concurrency group can cancel
pending exact-head runs and make evidence state ambiguous. The standalone prospective workflow
therefore owns live Freeze/Replay mutation and also executes the 1.0.3 background-compatibility
regression before writing evidence.

