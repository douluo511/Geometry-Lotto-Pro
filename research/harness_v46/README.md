# SSQ + DLT V4.6: isolated multi-agent SHADOW bootstrap

**Status: development research only; no formal A, no verified prospective advantage.**
This folder does not alter SSQ/ or DLT/ production applications, historical V4.5
model identities M04/M05-1..5/M06/M07, frozen tests, prior decisions, or seed data.
The multi-product repository itself is NOT a final independent release repository.

## Scope actually implemented

- One strict as-of snapshot schema with draws, issue, timezone-aware time locks,
  sales cutoff, source evidence metadata, and deterministic canonical SHA-256.
- Five *experimental* selectors: Hot60, EWMA(0.08), ShrinkMix(tau=200),
  Pairwise-D2(residual shrinkage), and a single fixed challenger using the
  minimum across preselected 30/60/120 windows.
- One deterministic Random NULL with a fixed, committed seed. It is a
  negative-control *arm*, NOT another candidate for selecting a champion.
- Each algorithm produces 5 ordered front candidates, one unique D2 (first
  two), and one valid full ticket. Back numbers never affect D2.
- SQLite local append-only guard triggers, uniqueness, same-data identity,
  cutoff checks, an atomic single-lottery CLI batch, parameter SHA-256,
  and a read-only score operation.
- Synthetic reproducibility, cross-lottery, tamper, and gate tests.
- No live ingestion, isolated LLM processes, unattended scheduler, external
  trusted timestamps, official draw verification, multi-day statistical trial,
  or official A gate. CLI always emits SHADOW.

## Roles: chat instructions are not execution permissions

00 controller; 01 independent official data verifier; 02 Hot60; 03 EWMA;
04 ShrinkMix; 05 Pairwise-D2; 06 challenger; 07 Random NULL; 08 read-only
auditor; 09 engineering. The numbers 02-07 are researcher role IDs, NOT the
legacy formal ticket identities. Chat runs do not share a mutable memory.

## Input snapshot

The 01 agent must independently verify issue schedules, official links,
timestamp evidence and each record before real forward use. This core checks
internal consistency **only**; fields such as provenance are *not* proof of an
official source. Example structure (illustrative, not genuine lottery data):

~~~json
{
  "lottery": "SSQ",
  "as_of": "2026-10-21T08:00:00+08:00",
  "sales_cutoff": "2026-10-23T19:00:00+08:00",
  "target_draw_at": "2026-10-23T21:15:00+08:00",
  "target_issue": "29999",
  "provenance": {"status": "SYNTHETIC_FIXTURE_NOT_OFFICIAL"},
  "draws": [
    {
      "issue": "29998",
      "front": [1, 2, 3, 4, 5, 6],
      "back": [7],
      "drawn_at": "2026-10-20T21:15:00+08:00",
      "published_at": "2026-10-20T22:00:00+08:00"
    }
  ]
}
~~~

**The dates, issue and numbers in this example are invented fixtures.**
Production batches need at least 120 vetted earlier draws for all five
experimental models. Draws must be sorted by issue and occurrence. Only
prospective, not-yet-drawn and pre-sales-cutoff targets may enter a fresh
forecast attempt.

## Local commands

~~~sh
python -m unittest discover -s research/harness_v46/tests -v
python -m research.harness_v46.cli forecast --snapshot /path/to/01_snapshot.json --database v46.sqlite --run-id V46-UNIQUE-RUN --model all
python -m research.harness_v46.cli score --database v46.sqlite --run-id V46-UNIQUE-RUN --official-result /path/to/01_official_result.json
~~~

For score, official_result is an externally verified document with keys
lottery, issue, front and back; this program cannot itself verify provenance.
At runtime the CLI obtains its clock from UTC; local metadata alone is **not
an independently trusted TSA**. Git SHA, JSON hashes and SQLite triggers do
not guarantee tamper-proof or verifiable pre-draw existence. Store external
TSA token, independent witness, and source snapshots before any claim to A.

## Statistical contract

Main indicator = one preregistered D2 pair per model/draw, with binary success
when both designated front numbers occur; SSQ fair rate = 15/528,
DLT = 10/595. D1/D3/D4/D5, ticket-back matches and hit_count_5 are diagnostic.
Do not swap D2 post-result or claim extra significance from 5 tickets or
selection across agents. Only use prospective same-draw paired comparisons to
NULL, preregister family-12 Holm corrections, uncertainty reporting and
independent audit. The 69/2880 DLT negative-control anomaly remains
UNRESOLVED; this bootstrap must not mark it fixed.

## Open gates and limitations

1. G00-G01: official two-channel discovery, independent 01 proof, true target
   calendar including holidays, cutoff and authoritative source bytes — BLOCKED.
2. G02: model implementations available for synthetic SHADOW research, not
   shown to beat random chance. Params are fixed in code, not tuned.
3. G03-G04: machine-validated SHA + local append-only SQLite; external
   witnessed timestamp and role-based authorization — NOT_RUN.
4. G05-G06: read-only scoring code exists; verified official intake,
   complete prior immutable record validation and paired statistical
   evaluation — NOT_RUN.
5. G07: A admission, V4.5 formal eight-slot upgrade, real schedules,
   real Windows restart / physical P0, security hardening — BLOCKED.
6. Local SQLite triggers prevent normal row modification but not DBA-level
   edits or file replacement; they are defense-in-depth, NOT WORM storage.
7. The CLI wraps each one-lottery six-model batch in one SQLite transaction:
   duplicate/fault aborts that batch without partial rows. An SSQ run and a
   separate DLT run do NOT yet form one atomic dual-lottery batch; partial
   cross-lottery execution remains BLOCKED from formal release.

**Interpretation:** code/test success validates software contracts only.
It does not establish improved odds, official data correctness, automated
publication, credible time sealing, or eligibility for gambling purchases.
