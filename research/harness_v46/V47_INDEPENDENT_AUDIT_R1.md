# V4.7 independent audit round 1 — SHADOW ONLY

Base: PR #446 at `28ac1b6ee8a597a574f8a3f12f4cdf6f5e38b596`.
Canonical integration target remains Draft PR #432; this isolated follow-on does not merge any PR.

## Reproduced defects and fixes

- A PARTIAL worker payload could retain a successful source without second-process replay. Any successful nonempty source now requires replay, including a partially failed collection.
- Replay timeout/launch failures previously escaped to collect_both and discarded captured source bytes. They now return a blocked quarantine with raw artifacts retained. Complete semantic receipt fields, per-source row hashes, NO_EDGE and unverified origin/time claims are checked; source hashes are checked again after replay.
- Worker/replay pipes now explicitly use UTF-8 at both ends. Actual child-process tests reproduce the Windows cp1252 locale failure with Chinese error messages and verify UTF-8 stdout/stderr transport.
- Binomial right-tail seeds underflowed: k=1,n=2500,p=.5 returned 0 instead of 1; at SSQ n=30000 one win versus 29999 NULL wins could produce baseline/paired/joint/Holm p=0. Mode-side log-scaled recurrence and complements now match an independent Decimal oracle; confidence intervals remain ordered.
- The run identity omitted raw_semantic_replay.py and audit_intake_bundle.py. Both now affect the manifest and RUN_ID.
- #438/#444/#446 lineage was missing #432's final alternate-HTTPS-port guards. The four affected source/test files were copied exactly from #432 `f12e47106f1d0c325573a48e39a6e2efd5d459ff`.
- Previous PR CI checked out synthetic merge commits. Their source trees matched their PR heads, but commit identities differed. CI now explicitly checks out and asserts the candidate head SHA before tests. Offline child-parser tests install requests==2.34.2.

## Validation

Windows 10, Python 3.11.9: full unittest discovery ran 159 tests, all passed.
Includes real offline second-interpreter replay positive/negative cases, timeout/launch errors, forged complete receipts, source mutation, large-sample Decimal arithmetic, confidence-interval inversion, model minimums, SQLite rollback and schedule retries.
Fresh remote Ubuntu/Windows CI is required for the final candidate SHA; no remote result is claimed in this document in advance.

Reproduce:

```sh
python -m pip install requests==2.34.2
python -m unittest discover -s research/harness_v46/tests -v
```

## Live historical evidence collected at the base SHA

A detached, unchanged checkout of the base performed actual read-only network collection. 110 raw HTTP artifacts were preserved; all sizes and SHA256s matched the independent bundle audit.

- SSQ: national and Shanghai responses each contained 2079 rows through issue 2026121; complete row agreement and second-process replay matched. Canonical rows SHA256: `7b7cdb90998dc78fda7a83a13452945267ca800d308499b6d4382d81ce707902`. SHADOW historical agreement only.
- DLT: national 2938 rows and Gansu 20 rows; Jiangsu 2934 rows quarantined. Independent standard-library reads of original bodies located date conflicts at 16003 (Jiangsu 2016-01-07 vs national 2016-01-06) and 16004 (2016-01-11 vs 2016-01-09). Both sources date 16005 as 2016-01-11; its monotonicity alarm is caused by the preceding Jiangsu row. No manual correction is authorized.
- Two responding domains do not establish independent upstream collection; Shanghai links to CWL details. Source-origin and publication-time authenticity are not authenticated. These already-drawn historical records cannot become prospective samples.

The immutable local output evidence is delivered separately with raw bodies, manifests, per-file hashes, original CI logs and counterexample receipts; it is not a trusted predraw seal.

## Remaining blockers

| Item | Status / required evidence |
| --- | --- |
| Parent/worker validation failure custody | OPEN: source conflict or malformed worker validation before replay can still be replaced by collect_both's generic error and lose captured bytes. Needs an untrusted worker-output capture protocol, without admitting failed rows. |
| Stored freeze-time audit | OPEN: check_complete_batch does not inspect frozen_at after a privileged file-level rewrite. This is not a freeze_shadow API bypass; local DB remains non-WORM. |
| Official G00/G01 | BLOCKED: target issue/cutoff and source-origin/publication/upstream independence not authenticated; DLT source-content conflict unresolved. |
| External predraw seal | NOT_RUN: no cryptographically verified RFC3161/witness response before sales cutoff. Local hashes/Git/SQLite times are insufficient. |
| Postdraw qualification | NOT_RUN: no authenticated official outcome intake and verified end-to-end REPLAY/SCORE/AUDIT/REPORT/NEXT. |
| Windows physical acceptance | NOT_RUN: no installed scheduler/cold boot/offline/30-minute recovery original logs and complete nine-P0 real-host evidence. DST hosts are explicitly blocked by the existing installer. |
| Confirmatory research | NOT_VERIFIED: exact historical 12-hypothesis registration; #443 remains exploratory/unregistered; DLT 69/2880 cause unresolved. |
| Prospective D2 edge | NO_EVIDENCE: no formal A samples or valid prospective superiority comparison. |

Independent verdicts remain ENGINEERING_PASS=NOT_YET, RESEARCH_VALID=NO, D2_EDGE_CONFIRMED=NO, formal_A=0, NO_EDGE.
No edits to main, V4.5 M04/M05-1..5/M06/M07, prior ledgers or source parsers. No lottery purchase.
