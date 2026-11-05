# V4.7 Windows operational snapshot handoff repair

The authorized continuous loop must consume explicitly supplied per-game snapshots through the same existing Windows caller and Python operational entrypoint. Current f595659 Python flags exist, but the Windows script ignores same-named config fields. This is an integration omission between existing capabilities, not evidence that official input exists.

## Approach and scope

Use optional `ssq_snapshot_path` / `dlt_snapshot_path` only with `operational_tick:true`, forward their exact strings as separate native arguments to existing `--ssq-snapshot-path` / `--dlt-snapshot-path`. Reject these config fields outside operational mode before any tick/log side effect. Preserve legacy `*_snapshot_bundle` modes and existing conflicts. The Python loader, future/cutoff checks, immutable six-arm freeze, fixed NULL, original scoring and formal family remain authoritative. Omitted/invalid SSQ must not prevent independently valid DLT; no automatic target synthesis, JSON conversion, or official promotion.

Reusing legacy bundle fields in operational mode would confuse two distinct modes; generating targets from history would violate existing admission. A new caller/Harness or task is outside scope. Selected minimal approach continues the original entrypoint and task name.

The existing Windows 600-second task limit cannot accommodate the currently accepted 240 seconds per collection/replay: two games each have two budgets, up to960 seconds before other work. Cap the Windows per-worker configuration at120 seconds, leaving120 seconds of the existing task budget after four120-second stages. This is budget headroom, not a proof that the entire tick always finishes; abrupt host termination remains observable as unfinished STARTED. Current actual120-second setting is unchanged.

## Validation and invariants

Real Windows PowerShell subprocess tests, no task installation and no new execution-policy override: both supplied paths freeze12 synthetic cards/two issues and retry reuses them; malformed SSQ still permits DLT six cards while keeping SSQ blocked; new path fields outside mode or mixed with old fields fail before side effects;120.001 timeout fails before Python/log start. Short source timeouts isolate unavailable live dependency; all forecasts remain SYNTHETIC SHADOW, A=0/NO_EDGE.

Record test-only RED first on the existing PR, then minimal GREEN, complete existing451-test regression plus new cases, exact candidate SHA Windows/Ubuntu CI, and independent incremental review. Local constrained PowerShell failure remains visible; remote green cannot certify this host, official sources, trusted presale evidence, or predictive advantage. Keep all old ticks and original snapshots; the current verified runtime is not edited in place.

