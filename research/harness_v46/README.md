# SSQ + DLT V4.7: canonical evidence contract and isolated SHADOW harness

## V4.7 implementation status: stricter synthetic admission only

**Status: development research only; no formal A, no verified prospective advantage.**
This folder does not alter SSQ/ or DLT/ production applications, historical V4.5
model identities M04/M05-1..5/M06/M07, frozen tests, prior decisions, or seed data.
The current research-core identity is `v47-research-core-0.1`; earlier V4.6
branches and records remain immutable historical evidence.
The multi-product repository itself is NOT a final independent release repository.

## Scope actually implemented

- One strict as-of snapshot schema with draws, issue, timezone-aware time locks,
  sales cutoff, source evidence metadata, and deterministic canonical SHA-256.
- Five *experimental* selectors: Hot60, EWMA(0.08), ShrinkMix(tau=200),
  Pairwise-D2(residual shrinkage), and a single fixed challenger using the
  minimum across preselected 30/60/120 windows.
- One deterministic Random NULL with the preregistered seed ID
  `SSQ-DLT-V47-NULL-SHA256-SORT-v1-20261022`. Its permutation uses SHA256
  ranking, not Python's version-dependent `random.shuffle`; it is a
  negative-control *arm*, NOT another candidate for selecting a champion.
- Parameter SHA256 now covers model parameters, engine version, lottery-rule
  digest, tie-breaking rule, and ticket-back generation/seed contract. Each
  prediction carries the exact installed `core.py` source SHA256.
- Each algorithm produces 5 ordered front candidates, one unique D2 (first
  two), and one valid full ticket. Back numbers never affect D2.
- SQLite local append-only guard triggers, uniqueness, an immutable persisted
  V4.7 manifest preimage/SHA256, immutable RUN_ID + lottery context (target
  issue, snapshot SHA256, as-of and cutoff), and model/source identity checks
  before V47 freeze; cutoff checks, a 120-draw minimum at study manifest,
  CLI and freeze gates,
  Pairwise-D2's registered 120-draw window, parameter/source SHA-256, and a
  read-only score operation. Application writer initialization enables
  `recursive_triggers` and tests reject `INSERT OR REPLACE` against frozen
  rows. This is connection-specific defense-in-depth, not WORM storage or
  protection against privileged file replacement. Existing pre-context ledger
  rows cannot be silently adopted into a new context; resume them under a new
  RUN_ID only.
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
This one-row example deliberately fails the V4.7 study admission gate.
Production batches need at least 120 vetted earlier draws for both games and
all six research arms before a complete study RUN_ID can be admitted. Draws must be sorted by issue and occurrence. Only
prospective, not-yet-drawn and pre-sales-cutoff targets may enter a fresh
forecast attempt.

## Local commands

~~~sh
python -m unittest discover -s research/harness_v46/tests -v
python -m research.harness_v46.cli forecast --snapshot /path/to/01_snapshot.json --database v46.sqlite --run-id V46-UNIQUE-RUN --model all
python -m research.harness_v46.cli score --database v46.sqlite --run-id V46-UNIQUE-RUN --official-result /path/to/01_official_result.json
~~~

The one-lottery CLI above is a legacy SHADOW compatibility path and rejects
caller-supplied `V47-` run IDs. Canonical V4.7 IDs are derived from the
dual-game manifest via `schedule.py`; this does not itself prove official
sources, trusted pre-draw time, or formal admission.

For score, official_result is an externally verified document with keys
lottery, issue, front and back; this program cannot itself verify provenance.
At runtime the CLI obtains its clock from UTC; local metadata alone is **not
an independently trusted TSA**. `snapshot_sha256` is the canonical semantic
JSON digest; `raw_evidence[].sha256` is the SHA256 of the exact source-file
bytes. These are different objects and must never be conflated. Git SHA,
JSON hashes and SQLite triggers do not guarantee tamper-proof or verifiable
pre-draw existence. Store external
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


## V4.7 P0 evidence hardening — 2026-10-22

- The immutable `run_snapshots` table stores the exact canonical normalized snapshot JSON under `(run_id, lottery)`. `register_snapshot` checks it against the persisted manifest; the freeze gate rejects any caller-supplied snapshot that differs from the registered preimage.
- Independent batch checking loads and re-hashes that snapshot, then replays every frozen prediction with the currently registered model source and parameter contract. A database rewrite that updates both prediction JSON and its local SHA but substitutes a legal-looking ranking is rejected by replay.
- The immutable `source_artifacts` table can retain actual raw source bytes as a BLOB, along with the URL claim, allowlisted hostname, raw SHA256, content type, and claimed publication/fetch times. It only accepts HTTPS hostnames on the per-game allowlist and binds each artifact's metadata/SHA to the registered snapshot preimage. Every record remains `source_authenticity=NOT_VERIFIED`: this helper does not fetch the URL, parse HTML/JSON, authenticate page publication times, or establish official-source truth. No real official raw bytes have been admitted by this code change.
- `statistics.py` provides deterministic exact upper-tail binomial arithmetic against the theoretical D2 baseline, exact one-sided paired sign/McNemar arithmetic against same-draw Random NULL, candidate-level intersection-union `max(p_baseline,p_paired_null)`, Holm adjustment over an explicitly supplied exact hypothesis list, exact model-rate intervals, and a conservative paired-rate-difference interval. The family is explicitly marked `CALLER_SUPPLIED_UNVERIFIED`; this module cannot verify the legacy 12 identities, preregistration time, official outcomes or TSA. It always returns `SHADOW_ONLY / formal_A=0 / NO_EDGE`.
- The V4.7 run manifest's orchestration-source hash now includes `statistics.py`, so changes to statistical evaluation code change the canonical RUN_ID.

Exact-head synthetic CI for code HEAD `d1f2ab42f9e170fcae0c5d98101e4321e18ea804`: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39747892642 — Ubuntu and Windows Server 2022 both succeeded with 54 tests; Ubuntu skipped the Windows-only PowerShell parser test, and Windows ran it.

Still BLOCKED/NOT_RUN: live official-source fetch and parser, two-source 120+ issue semantic comparison, official next-target/sales-cutoff admission, external RFC3161/independent witness validation, real Windows task installation/cold boot/offline recovery, verified official-result replay, actual preregistration identity mapping, DLT 69/2880 negative-control root cause, and any prospective D2 advantage.


## V4.7 source-history comparison contract

`source_validation.py` now validates two caller-parsed 120+ draw histories against each other and the immutable normalized snapshot. It checks the per-game HTTPS host allowlist, requires distinct official-domain roots, validates issue/date ordering, number ranges, publication timestamps against as-of, and rejects any row or snapshot disagreement. A matching result is explicitly `semantic_agreement=MATCHED` while `official_G01=BLOCKED`: the module does not fetch or parse the raw bytes and cannot prove that supplied parsed rows came from the named pages. Synthetic test fixtures only; no official history was admitted.


## V4.7 allowlisted raw fetcher

`source_fetch.py` can fetch raw bytes over HTTPS only from the per-game source-host allowlist, validates redirects against the same allowlist, enforces a 25 MB ceiling, records the final URL/content type/HTTP Last-Modified header/raw SHA256 and labels the local fetch time as untrusted. It intentionally returns `published_at=None`: an HTTP Last-Modified header is not treated as official page publication time. The module does not parse results, authenticate the site, or grant G00/G01. Unit tests use mocked HTTP responses; no live official-source request has been executed by this change.


## V4.7 real-source intake adapter

`official_intake.py` is the live collector entry point. It launches the existing SSQ and DLT parsers in separate Python subprocesses because both projects use the package name `glp`. It hashes the exact parser, dependency, and intake-orchestrator source files before and after collection, preserves each raw HTTP response as a SHA256-addressed binary artifact, and reparses every successful nonempty response body before source history can enter cross-source comparison. Non-200 bodies are retained as diagnostic evidence and are never parsed as draws. `audit_intake_bundle.py` then independently rechecks the saved manifest, every referenced raw file's SHA256/size, path safety, and the mandatory blocked-admission guard; its audit receipt records the auditor source SHA256.

Approved source roots in this branch:

- SSQ full history: China Welfare Lottery Center `cwl.gov.cn` plus Shanghai Welfare Lottery Center `swlc.net.cn`. When the CWL endpoint is blocked, Hebei Welfare Lottery `yzfcw.com` may cross-check **one latest issue only**, using its homepage and announcement page together.
- DLT full-history gate: China Sports Lottery `sporttery.cn` plus Jiangsu Sports Lottery `js-lottery.com`, each with at least 120 valid draws and at least 120 matching issue IDs; Gansu Sports Lottery `gstc.org.cn` is a mandatory third corroborator with at least 10 matching recent issue IDs against **each** primary source. Gansu **cannot replace** a missing primary source; any missing source or mismatch keeps DLT blocked.

Run on a network-enabled host with Python and Requests installed:

```powershell
python -m pip install requests
python -m research.harness_v46.official_intake --game ALL --output-dir artifacts/official-intake-<unique-run-id>
python -m research.harness_v46.audit_intake_bundle --bundle-dir artifacts/official-intake-<unique-run-id>
```

The output directory must not already exist. The bundle contains `intake.json`, `raw/<game>/<source>/<sha256>.bin` artifacts, and (after the auditor runs) `intake-audit.json`. An audit `PASS` confirms byte/manifest integrity and blocked-admission guards only; it does **not** authenticate official origin/publication time or admit a target. It is designed to fail closed: SSQ full-history admission requires **at least 120 issue IDs overlapping between CWL and Shanghai**; DLT requires **at least 120 issue IDs overlapping between the national and Jiangsu primary sources plus at least 10 matching recent issue IDs from Gansu against each primary**. All overlaps require exact agreement on issue/date/balls, raw-byte/parser replay, and strict increasing draw dates. SSQ's Hebei latest-only route may return `HISTORY_CROSSCHECK_LIMITED` with one matched issue; DLT's Gansu route is a third corroborator only and cannot replace either primary source. Disagreeing or malformed source dates cause quarantine rather than silent correction. Failed sources preserve their raw diagnostic bodies, even HTTP 403/567, and never count as successful draw pages.

On the verified third live read-only run #39754959885 (2026-10-22), DLT Jiangsu delivered 2,934 primary-history rows with only 20 matching Gansu rows; SSQ Shanghai delivered 2,078 rows while the CWL endpoint returned HTTP 403. These do **not** establish 120+ dual-source consensus. In the Jiangsu DLT historical rows, issues 16003 and 16004 contain dates 2016-01-07 and 2016-01-11 respectively; independent public records instead identify 2016-01-06 and 2016-01-09. The raw-source values are retained unmodified and quarantined pending independent source-backed reconciliation.

On P0-A live intake run #39758924010, the collector retained 64 raw artifacts and a separate SHA audit confirmed all 64 paths, byte sizes, and SHA256 values matched the manifest (artifact ID `12416888557`). SSQ returned `HISTORY_CROSSCHECK_LIMITED`: CWL HTTP 403, Shanghai 2,078 rows, and Hebei independently agreed on one latest issue (`2026120`, 2026-10-20, red 13/14/16/18/20/31, blue 03), which is not full-history admission. DLT remained `SOURCE_FETCH_PARTIAL`: the national endpoint returned two HTTP-567 bodies; 30 Jiangsu HTTP-200 pages were retained but quarantined for date anomalies at issues 16003 and 16005; Gansu's 20 recent rows parsed, latest issue 26120, but could not replace the missing/quarantined primary histories. The run ended with target admission BLOCKED, external TSA NOT_RUN, formal_A=0, and NO_EDGE. ZIP SHA256 `a43f6e1a141bb59b4a4b5ab2f282b260b5616dbfdefbbd05e62384201ca28c85`; manifest SHA256 `f05367ba2099e90e7e97cea88c06e29b43270614e2df5c4bed3439635d588e8e`. This verifies byte preservation only, not the authenticity of failed HTTP responses.
  
This collector is **historical-source intake only**. It does not certify a target issue, actual sales cutoff, publication time, trusted timestamp, or prediction. Local capture times remain untrusted; `official_target_admission=BLOCKED`, `formal_A=0`, and `NO_EDGE` remain mandatory. GitHub's one-shot workflow is limited to the convergence branch and isolated P0-A research branches, and is triggered only by changing `LIVE_INTAKE_TRIGGER.json`; it uploads raw evidence as a temporary Actions artifact and never writes source data to `main`.
