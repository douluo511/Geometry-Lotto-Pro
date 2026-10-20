# Old-value provenance and as-of admission diagnostic

This component executes the eight registered faults for SSQ and DLT using
four invented legal rows per game, January 1–4, 2000, and a fixed January 10
fixture clock. It reads source code and its registered protocol, not lottery
history, holdouts, SQLite, or previous model scores. It creates no prediction.

`sources.load_pinned`, `sources.agree`, and `workflow.history_stage` remain
unchanged. C7 replaces only `capture_pair` with two recent, explicitly
synthetic rows per game. There are no network or TSA calls. C1/C3 agreement is
`NOT_RUN_DEPENDENCY_BLOCKED` after the real loader rejects its prerequisite.

The old helper can accept a changed old value whose legal identity/date and
file SHA have been preserved/re-pinned. That is an unresolved provenance
limitation, **not successful taint detection and not evidence that real
historical leakage occurred**. Self-asserted `available_at`, `captured_at`,
`sealed_at`, or `tsa_verified` fields do not establish trusted availability.
Successful history-stage output must retain `target=None` and
`publication_asof_verified=False`. C5 separately exercises the real conflict
check; offline history loading does not itself run two-source agreement.

Run with absolute paths and a fresh output directory:

```powershell
python -m research.ssq_dlt_asof_audit execute --protocol ABS_PROTOCOL --output NEW_ABS_OUTPUT
python -m research.ssq_dlt_asof_audit verify --output ABS_OUTPUT
```

Execution exclusively creates STARTED, source snapshots, reproducible input
JSON, each observation, a receipt, and a file SHA inventory. Existing output
is never reused, overwritten, or retried. Unknown interruption leaves STARTED
and all existing bytes; a new explicit output directory is required. SHA is
local integrity evidence, not a trusted external seal.

Verification reads and hashes all files, checks the protocol/source pins and
the full 8×2 case rectangle, and evaluates saved observations without
re-running old helpers or opening a database. It does not repair evidence.

`PASS_DIAGNOSTIC_EXPECTATIONS_ONLY` applies solely to the predeclared helper
behavior. As-of qualification remains BLOCKED, A=0, NO_EDGE, prospective=0.
This diagnostic does not establish official-source authenticity, live TSA
failure handling, complete runtime/physical P0, or improved prediction effect.

The original formal twelve-comparison family is unchanged. Its identities and
approvals are not supplied by this component; missing originals stay BLOCKED.
The diagnostic does not replace it with any existing research family.
