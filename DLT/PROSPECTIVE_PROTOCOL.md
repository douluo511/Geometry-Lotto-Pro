## Official actual-draw qualification firewall — 2026-10-08

Replay score verification now requires **two separate evidence layers**:

1. The immutable Freeze and Replay must be internally consistent: predicted rankings, actual intersections, seeded random baseline, reported effect and record hashes are recalculated.
2. Before `qualification` or `status` can count a Replay, the replayed winning draw must **exactly match the current freshly verified official canonical draw** for the same issue, including issue, date, five front numbers and two back numbers.

When no official canonical draws are supplied, the decision is `NOT_READY` with `OFFICIAL_ACTUALS_NOT_BOUND`, **zero qualified Replay count** and a separate unverified-record count, even if 30 self-reported scores appear positive. Missing official actuals, duplicate official issue IDs and mismatched draw bytes fail closed. The live official-source workflow passes the canonical draws to this gate and checks `official_actuals_bound=true`.

This closes an important loophole: an attacker could previously forge a statistically flattering but internally consistent result, recompute all hashes and scores against the *forged* actual numbers, and have it counted. A hash certifies bytes only; an independently retrieved official draw certifies the outcome. The remaining gate still requires independent Git-committed pre-draw timestamps, cohort stability and sufficient future draws. No production promotion follows from this repair.

## Prospective time and replay-score firewall — 2026-10-08

A canonical source report showing a still-unseen target issue is **not** proof that its draw has not already happened. A new immutable Freeze is eligible only when its UTC registration and creation timestamps are valid, the prediction existed before registration, and registration occurred **before the Chinese civil date of the target draw** (UTC+08). Because no independently verified same-day lottery cutoff-time contract has been established, same-day predictions are conservatively rejected from the qualified prospective cohort even when a ticket might still be purchasable. This is intentional fail-closed behavior; a future cutoff policy change must reset the behavior-bound cohort.

Replays are never qualified using self-reported `front_gain_vs_random` or `back_gain_vs_random` alone. Every stored actual draw is validated, the exact prediction's winning intersection/ranks are recomputed, and the same frozen random seeds and score formula are re-evaluated before the 30-valid-replay threshold. Rehashing a tampered score or actual after the draw does not turn it into a valid replay.

These checks are **necessary, not sufficient**: archived JSON digests do not independently prove pre-draw GitHub persistence. Durable qualification also requires timestamped, immutable GitHub ledger commits and separate authorized writer/release governance. PR CI artifacts remain `VALIDATION ONLY` and never count toward the production cohort.

## Current-main staging authority — 2026-10-08

This port is based on actual monorepo main `c2b0db6876d2aae874f8cf4d08f52455c8eaf152` after DLT background restoration PR #326. It supersedes the stale product-code basis in draft PR #293. The new exact source/behavior fingerprint must start an independent prospective cohort; no historical replay can be inherited.

**STAGING / VALIDATION ONLY:** CI has read-only GitHub contents permissions, cannot push to the persistent prospective ledger, and only uploads temporary research evidence. Neither a CI SUCCESS nor an artifact is a qualified 30-replay cohort or a Final/independent release. An explicitly governed, fixed-source writer and persistent ledger must be separately reviewed before prospective collection counts. Production remains NO_EDGE / NULL_DAN / rho=0.

# DLT Prospective-Only Qualification Protocol

Status: **RESEARCH / FAIL-CLOSED / NOT A PRODUCTION PROMOTION PATH BY ITSELF**

## Why this exists

Historical V2 Ridge research was closed as **NO EDGE**. Repeatedly adapting models to the
same 2,927 historical draws would increase selection bias. Any future predictive claim must
therefore be evaluated on predictions frozen **before** the corresponding official draw exists.

## Cohort identity

A prospective cohort is bound to all of the following:

- byte-level behavior fingerprint over the DLT data/model/evidence/prospective/background code;
- model hash;
- selector hash;
- complete model specification;
- complete promotion policy / hyperparameters;
- protocol version.

The exact Git source commit is still recorded on every immutable Freeze as provenance, but a
documentation-only or CI-governance-only commit does **not** reset the scientific cohort when
the behavior fingerprint is unchanged. If the behavior fingerprint, model, selector, promotion
policy or protocol changes, the active cohort changes and the qualifying replay count restarts
from zero. Old cohorts remain preserved as evidence and are never merged into the new count.

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



## Behavior identity rule

The behavior fingerprint is computed from exact bytes of the DLT modules that can change
canonical data, prediction, qualification, replay, or 1.0.3 background lifecycle behavior.
This prevents two opposite false outcomes:

- **false reset**: docs-only commits must not erase accumulated prospective evidence;
- **false carry-forward**: any behavior-affecting code change must create a new zero-replay cohort.

The Freeze itself still records the exact source commit used to create that prediction. Thus
provenance remains exact even when multiple documentation-only commits share one scientific
cohort.


## Evidence-branch no-op rule

Issue #296 freezes the persistence rule: a cycle that adds no cohort identity, immutable Freeze,
immutable Replay, or qualification-relevant state must not create a Git evidence commit merely
because generated summary timestamps changed. CI artifacts may still contain refreshed summaries.
