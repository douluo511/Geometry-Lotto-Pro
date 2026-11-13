# Analysis contract recorded before this extension's computations

This is a **retrospective extension**, not a preregistration for already published outcomes.
Prior PR 492 chose EWMA (SSQ) and Recency Pair H45/120 (DLT) from its validation block.
Those choices stay fixed. All ties use the existing registry order. Test-window leaders
are explicitly post hoc. Both historical blocks and the nine later transcribed rows were
already exposed. A genuinely untouched test has **n=0, winner=null, status=BLOCKED**.

Reuse the exact ZIP of Actions run 43422587316; verify ZIP SHA256 and every enclosed
file hash, observation canonical digest, event labels/order/counts and model counts.
Correction after inspection: PR 492 used details=False for validation, so its validation
event arrays are empty. Reconstruct ONLY those missing 392+564 validation records once
using unchanged scoring code, compare every aggregate exactly, and store a separate
pinned supplement. Test events and original ZIP are reused byte for byte.
Check the scoring adapter against fixed sample offsets 0, n/4, n/2, 3n/4, n-1 in each
game/block; no repeated full sweep. All metrics refer to one ticket per model per draw.

Primary endpoint: both registered D2 front numbers hit. Full-ticket hit means **all
front AND back balls**, not any prize. Kill3 error means **at least one** excluded
front ball is actually drawn. Legacy random has no registered kill3; leave missing.

Report Wilson and two-sided 95% Clopper-Pearson intervals; these are marginal,
descriptive intervals, not simultaneous or selection-adjusted guarantees.
Fair D2=C(k,2)/C(N,2); exact ticket=1/[C(N,k) C(M,l)];
kill3 error=1-C(N-k,3)/C(N,3). Fair-draw independence is an assumption.

Nominal D2 p=max(one-sided binomial vs fair, one-sided paired discordance test vs
the unchanged fixed NULL). Paired sign testing assumes suitable exchangeability;
adaptive rolling dependence and retrospective model development limit calibration.
Kill3 and full-ticket p compare to fair only; paired kill3 event data is unavailable
in the cached artifact and will NOT be manufactured.
Primary comparable historical family: 24 D2 tests from PR 492, reproduced unchanged.
Expanded family: 12 nonrandom models x 2 games x 2 windows x 3 metrics = 144.
Known-search sensitivity: append 128 prior recency-ablation p values and the 24
previous PR 492 tests, giving 296 labeled comparisons (intentional conservative
double counting of repeated claims). Unknown earlier searches remain unknown;
Holm correction cannot make historical test exposure disappear.

Stability: four contiguous equal blocks per window, rank changes, validation-to-test
changes, one exploratory expanding-history policy selecting from earlier hit records
only. Correlation: pairwise phi of aligned D2 outcomes, exact matching hit streams,
spectral effective rank as a descriptive correlation measure, not reduced multiplicity.
Bootstrap: 10,000 paired circular-block resamples for lengths 5,20,60, fixed seed
20261113. Preserve common draw indices across all arms. Show selected-minus-NULL
intervals and selection frequencies. These fixed forecast outcome resamples do not
retrain models and are sensitivity diagnostics, never a fresh holdout.

Future design proposal: fixed selected model per game, first 500 eligible future draws
after a public GitHub commit timestamp and a strict per-draw presale publication gate;
two D2 hypotheses across games, Holm at .05, no early significance stopping or switching.
Missed publications, source failures, cancelled draws and all losses must be retained;
invalid/missing publication is not a scored success and blocks complete-case promotion.
This change does not schedule, purchase, or certify a trusted seal.

Candidate publication must compare latest issuer issue/numbers to the history tail,
require target=latest+1 within the year, and require observation time before the future
draw date (conservative day-level cutoff). Historical input beyond that target is rejected.
Dates are China draw dates, timestamps UTC. Current source snapshots were retrieved
via Firecrawl maxAge=0; saved JSON is tool-extracted text, **not official raw response bytes**.
Authenticity of the full historical corpus, independent TSA/WORM, and future mechanical
features remain UNVERIFIED. Physical models ABSTAIN. Decision remains NO_EDGE.
