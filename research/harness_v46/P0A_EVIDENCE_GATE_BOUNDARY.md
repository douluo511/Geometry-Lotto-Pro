# V4.7 P0-A — verified gate boundary vs SHADOW execution trace

**Scope:** isolated fail-closed contract correction. This is not proof of official-source
authenticity, signed 01/04 authorization, an external RFC 3161 timestamp, authenticated outcomes,
a production Windows scheduler, or improved D2 hit rate.

## Finding

The previous scheduler wrote unverified labels for SYNC/VERIFY/AUTHORIZE/PREDICT/FREEZE/WAIT
into one workflow table. Ordered stage names and local hashes could be mistaken for verified
gate passage.

## Corrected contract

- `workflow_events` is a gate journal. The scheduler writes only a nonpassing SYNC event marked
  `gate_status=BLOCKED`, `evidence_class=SHADOW`, `formal_A=0`.
- Caller-supplied `PASS` is refused with `INDEPENDENT_GATE_VERIFIER_REQUIRED`. No later gate
  event can be appended after blocked SYNC. Future PASS requires an independent verifier and
  auditable receipt contract, not a boolean or free-text claim.
- Research execution steps are stored separately in `shadow_trace_events` as
  `SHADOW_UNVERIFIED`. They cannot promote official gate state. FREEZE trace still checks the
  complete six-model batch digest.
- Both journals are append-only with update/delete guards and recursive triggers.
- Scheduler output explicitly reports `gate_status=BLOCKED`,
  `shadow_trace_status=UNVERIFIED_EXECUTION_ONLY`, `formal_A=0`, and `NO_EDGE`.
- The official intake orchestrator is included in the before/after SHA256 lock so the worker
  cannot silently change its own validation logic during collection.

Historical databases and the V4.5 eight formal-slot identities are not modified. Older workflow
rows must not be reinterpreted as verified gate receipts.

## DLT source contract

DLT history admission requires all three source identities to be present in the intake record:
national and Jiangsu primary histories, each with at least 120 valid draws and at least 120 matching
issues between the two primaries, plus Gansu's recent official history with at least 10 matching
overlapping issue IDs against EACH primary source. Gansu is a third corroborator only; it cannot
substitute for either missing primary history. Latest issue, date, and balls must agree; any issue
mismatch blocks cross-check admission.

Even when this history check passes, the result is `SHADOW_HISTORY_ONLY`; publication-time
authenticity, target/cutoff admission, external TSA verification and formal-A eligibility remain
blocked.

## Synthetic verification

GitHub Actions run `39760961219` passed the deterministic harness suite on both
`ubuntu-latest` and `windows-2022`: 108 tests per platform, one platform-specific PowerShell
parser test skipped on Ubuntu. The run tested head `425b4865804e25a53d53f611c5ac9db832cd7051`,
including gate/trace separation, the source self-hash lock, DLT primary 120+ overlap, Gansu 10+
exact overlap against BOTH primary histories, chronology quarantine, SSQ Hebei latest-only
fallback, duplicate raw-receipt handling, and the independent bundle auditor.

## Independent raw-bundle auditor

`audit_intake_bundle.py` verifies the saved manifest, safe relative artifact paths, raw-file SHA256
and byte sizes, the explicit blocked-admission guards, and records the auditor source SHA256. It
permits a valid audit PASS when source fetching failed, because it audits byte integrity rather than
source authenticity. The one-shot workflow now runs this audit before upload and includes
`intake-audit.json` in the retained Actions artifact; the final report fails if the audit is missing
or fails.

## Live read-only intake evidence

Run `39758924010` (code SHA `c6500dcfb3213c4a9e84947f092a576f2f22a698`) completed with the
expected fail-closed result. It predates the final explicit code check that Gansu must overlap each
primary separately; the live sources failed before that final cross-source check could be reached.
The run still provides real source-access and preserved-raw evidence:

- **SSQ — `HISTORY_CROSSCHECK_LIMITED`**: CWL national endpoint HTTP 403; Shanghai returned 2,078
  parsed rows; Hebei homepage plus announcement independently agreed on only issue `2026120`,
  dated 2026-10-20, red `13,14,16,18,20,31`, blue `03`. Independent overlap=1, so full 120+ dual-source
  admission remains blocked.
- **DLT — `SOURCE_FETCH_PARTIAL`**: national Sports Lottery returned two HTTP-567 responses;
  Jiangsu returned 30 HTTP-200 raw pages but its parsed history was quarantined for issue `16003`
  dated 2016-01-07 (outside the regular Mon/Wed/Sat draw calendar) and issue `16005` dated
  2016-01-11 (not strictly increasing). Gansu returned 20 raw-reparsed recent rows, latest issue
  `26120`, but cannot substitute for either failed/quarantined primary history.
- Overall `official_target_admission=BLOCKED`, `external_tsa=NOT_RUN`, `formal_A=0`,
  `decision=NO_EDGE`. The red workflow exit means source admission was not achieved, not that the
  evidence was silently accepted.

Raw evidence artifact: `12416888557`
(`v47-official-intake-39758924010`). An independent archive audit verified all 64/64 listed raw
artifact paths exist and each file's SHA256 and byte size match its manifest; zero integrity errors.
ZIP SHA256: `a43f6e1a141bb59b4a4b5ab2f282b260b5616dbfdefbbd05e62384201ca28c85`.
Manifest SHA256: `f05367ba2099e90e7e97cea88c06e29b43270614e2df5c4bed3439635d588e8e`.
This confirms byte preservation, not that failed HTTP bodies are official draw data. The new
automated auditor will be exercised by the next one-shot intake.

DLT 69/2880 negative-control anomaly remains unresolved. Formal A=0; NO_EDGE.

## Follow-on P0-A: raw provenance and write-once audit receipt — 2026-10-22

An independent review found that checking an artifact's bytes against a declared SHA256 was
insufficient to bind the file to the declared game and official source. The auditor now requires
`raw/<game>/<source_id>/<sha256>.bin` exactly, with source IDs restricted to the audited game's
allowlist. Cross-game, cross-source, wrong-hash-named, symlink, and unlisted raw files are refused.
The auditor also rejects oversized/unpreserved evidence instead of certifying incomplete raw
preservation, and writes `intake-audit.json` once using exclusive file creation so an older audit
receipt cannot be overwritten on rerun.

GitHub Actions [run 39765806469](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39765806469)
validated the canonical-path and orphan-file checks on both Ubuntu and Windows: 112 tests per
platform; the Ubuntu suite skipped one Windows-only PowerShell syntax test. Following the
write-once receipt and unlisted-sidecar tests, [run 39765963248](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39765963248)
passed 114 tests per platform on exact code commit
`a7085051d74518499fb1d73a2f905b075662efc3` (Ubuntu skipped one Windows-only test).
An offline recheck against preserved live artifact `12416888557` at issue time again found 64
manifest records, 64 canonical paths, 64 SHA/size matches and no unreferenced raw file.
This offline check is NOT a new live full-history source admission and does not establish an
external trusted timestamp or prediction edge.

The full source/cutoff gates and independent V4.5 formal-slot authorization remain blocked;
formal A=0, NO_EDGE, and DLT 69/2880 negative-control anomaly remains open.
