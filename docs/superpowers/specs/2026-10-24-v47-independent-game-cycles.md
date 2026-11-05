# V4.7 unified Harness — per-game freeze/score execution (Issue #468)

Only one `closed_loop` CLI and durable workspace, with two independently
scheduled SSQ and DLT issue tracks. This is **not a new Harness**; existing
paired RUN_ID rows remain preserved and independent-game V47G rows go into
two additive tables `game_runs` and `game_predictions` within the **same**
SQLite ledger. Do NOT promote old 12-card runs or migrate their identities.

## Operational commands (SHADOW ONLY)

For a vetted single game snapshot available **before that game's sales cutoff**:

```sh
python -m research.harness_v46.closed_loop --workspace ./workspace \
  --game-snapshot ./ssq_verified_asof.json

python -m research.harness_v46.closed_loop --workspace ./workspace \
  --game-snapshot ./dlt_verified_asof.json
```

After a game's results are available, add its original result JSON at
`workspace/outcomes_by_game/SSQ/<canonical_issue>.json` or
`workspace/outcomes_by_game/DLT/<canonical_issue>.json` with EXACT
`lottery`, `issue`, `front`, `back`, `drawn_at` fields.
Then poll either game separately:

```sh
python -m research.harness_v46.closed_loop --workspace ./workspace --game SSQ
python -m research.harness_v46.closed_loop --workspace ./workspace --game DLT
```

**WARNING:** these are caller-unverified result files. The CLI does NOT
fetch sources, cross-check official draw results, issue external TSA time
stamps, or grant trusted prospective research eligibility. A host scheduler
must NOT supply invented issue IDs, unverified cutoffs or synthetic fixtures
as qualified runs. Do not interpret `LOCAL_ROSTER_SHADOW_SCORED` as
scientifically admitted evidence.

## Precise invariants

- One normalized ASCII-decimal `(lottery, issue)` key. Each game can
  freeze its own six **unchanged** model forecasts including fixed
  `random_null`, without requiring the other game's current snapshot.
- For an existing game/issue, a byte-identical snapshot is replayable even
  after the cutoff; a different snapshot is rejected permanently.
  Missing issue after cutoff is NOT backdated.
- Model version, input SHA, model code SHA, parameter SHA, frozen candidate
  D1–D5 and unique primary D2 are inside each core prediction's SHA-locked
  canonical payload. All six rows are transactionally inserted before commit.
- Every read checks six rows and recomputes the frozen predictions against
  the stored original snapshot; model source version mismatches fail closed.
- Two game result folders and receipt folders permit independent
  post-draw scoring. True outcome authenticity remains unverified.
  All local frozen issues of a game, including pending, appear in its
  local roster; partial or selected issues must not claim complete cohort.
- Source release, official calendar completeness, authoritative cutoff,
  trusted RFC3161 signer/cert/accuracy and independent outcome custody
  remain external blocked gates. Nothing here verifies a future edge.
- Existing dual snapshot CLI `--snapshot-bundle` is **still** available
  for legacy SHADOW regression. Do not feed both legacy and new runners the
  same issue as separate qualifying samples.

## TDD proof requested

Follow Superpowers test-driven-development, systematic-debugging and
verification-before-completion. RED introduced Saturday DLT, Sunday SSQ,
Monday DLT issue alternation, retry overwrite, cutoff, forged/early score,
concurrent tick, original dual-run preservation and CLI subprocess.
GREEN implements only this issue-level state path in existing
`closed_loop.py`. Exact Ubuntu+Windows GitHub CI and raw logs required.
Independent second reviewer and owner-authorized physical scheduler
deployment remain `NOT_VERIFIED`.

Formal verdict remains `ENGINEERING_PASS=NOT_YET`,
`RESEARCH_VALID=NOT_YET`, `D2_EDGE_CONFIRMED=NO`,
`formal_A=0`, `NO_EDGE`. No tickets purchased.
