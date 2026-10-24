# Version-bound frozen replay, Issue #468

Baseline: PR #467 `861ee53ad172a8ba80bbfb24a2a6597c51c57230`.
Authority: the user's explicit request to execute the two existing blockers;
implementation choices below are the agent's decisions, not a claimed user sign-off.

## Root cause and scope
Both independent-game and legacy dual-game replay validate old predictions with
the currently installed core. A comment edit or CRLF/LF checkout changes its
source hash; normal upgrade therefore prevents immutable old cards being scored.
The independent native reproduction is in the session evidence, not a claim of a
real host outage. Repair these two existing paths, without adding a Harness.

## Approaches and decision
Skipping the source check would accept substituted predictions. Re-running the
current selectors would replace the frozen hypothesis. Use an explicit trusted
source registry: exact, checked-in original LF and CRLF core artifacts, each
selected by its full SHA256, and the pinned date-observed validator dependency.
The artifacts use `-text` so Git cannot silently translate their bytes.
No source path or executable bytes may come from a ledger, outcome or workspace.
Verify every artifact before executing its exact checked-in bytes in an isolated
module namespace. Unknown historical source, missing/tampered artifact, mixed
source roster, changed card/seed/parameter, or incomplete six arms must block.
Current unarchived code can replay itself only while its exact bytes are installed;
it needs a new independently reviewed registry entry before it can be retired.

The original source/parameter/version checks remain: resolve the old core first,
then deterministically regenerate and compare the entire frozen card, including
ticket and NULL identity. Score through the same pinned core. Existing run IDs,
prediction bytes, ledger schema and score receipt schema remain unchanged.
Archive GateError must map to the current public GateError for fail-closed CLI.

## Boundaries
This binds model replay, not official data, independent custody, TSA or deployment.
The registered observed validator is pinned for reproduction; old per-game IDs
did not bind a complete environment/dependency manifest. Do not retroactively
claim such provenance. Retain current snapshot/time/outcome security guards.
Arbitrary future orchestration/scoring-receipt changes and unknown historical
versions remain outside this scoped compatibility promise and must fail closed.

## Acceptance
Native isolated subprocesses freeze A, score A, change installed core bytes to B
and score/retry original A; compare original ledger and receipt bytes throughout.
Cover SSQ, DLT, dual-game legacy, LF/CRLF, observed snapshots, missing/tampered
archive, forged rehashed cards, incomplete/mixed arms and unknown source.
Capture RED before production changes, then GREEN and complete regression; publish
only to existing PR #467 and verify exact-HEAD Ubuntu/Windows Actions raw logs.
Independent agent review is separate from human formal acceptance.
Always formal_A=0, RESEARCH_VALID=NOT_YET, D2_EDGE_CONFIRMED=NO, NO_EDGE.
