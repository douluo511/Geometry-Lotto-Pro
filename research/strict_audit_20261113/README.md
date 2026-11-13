# Strict SSQ / DLT audit as of 2026-11-13

**NO_EDGE. Genuine untouched test: BLOCKED, n=0. Physics: ABSTAIN.**

This additive research package builds on PR 492 at
`206a4f997a84c53df201180f50809f51fc902d34`, including the PR 491
14 executable models plus 2 physical slots per game. No existing model,
fixed Random NULL, historical prediction or sealed source is changed.

- [All 14 executable forecasts/game plus explicit physical abstentions](results/all_models.md)
- [Historical ranking, confidence intervals and risk report](results/report.md)
- [Complete statistics, correlation matrices and bootstrap diagnostics](results/analysis.json)
- [Structured research candidates](results/candidates.json)
- [Source and input hashes](results/provenance.json)
- [Analysis contract and limitations](PROTOCOL.md)

Latest issuer displays checked in this session: SSQ **2026130**
([Shanghai Welfare Lottery](https://www.swlc.net.cn/)); DLT **26129**
([Shanghai Sports Lottery](https://www.shsportslottery.com/dlt/kjgg.html)).
Research targets at that observation: SSQ **2026131**, 2026-11-15;
DLT **26130**, 2026-11-14 (China draw dates).
Saved official evidence is extracted text, not issuer raw bytes or a trusted
presale seal. Replaying this package does not refresh the latest issue.

## Result and provenance

Original Actions ZIP and every member hash verified. PR 492 omitted validation
events (`details=False`): only those missing 392 SSQ + 564 DLT records were
reconstructed, and every original validation aggregate matched exactly.
The old test events are reused unchanged; 280 model/draw pairs were sampled
for independent replay. The separate reconstruction has a pinned SHA256.

Validation winners: SSQ EWMA 18/392; DLT Recency Pair H45/120 16/564.
Their old test D2 counts: 17/392 and 8/564. Old test post-hoc winners:
SSQ Hot30 19/392, DLT Pair Residual 16/564. None is a proven prospective champion.

The 144 current comparisons have minimum Holm p=1.0.
The 296 labeled known-search comparisons have minimum Holm p=0.1504007008.
Both are exploratory; the latter deliberately includes repeated claims and
does not account for unknown historical searches.
10,000 paired circular-block resamples at each length 5, 20, 60 preserve
same-draw model correlation. They do not create new independent observations.

## Reproduce

Python 3.11, numpy==2.4.6, scipy==1.17.1, requests==2.34.2.

```text
python -m unittest research.strict_audit_20261113.test_audit -v
python -m research.strict_audit_20261113.audit --out NEW_DIRECTORY
python -m research.strict_audit_20261113.run_checks --out NEW_VERIFICATION_DIRECTORY
```

All output directories are create-only. The committed results preserve the local
execution; CI emits its own fresh results and exact source SHA without replacing them.
`reconstruct_validation` is a one-time provenance utility; it refuses to replace
the committed supplement.

## Verification record

Local new suite: **16 tests PASS** after the independent-review corrections.
Original mother/source/rolling suite: **22 tests PASS**.
Supercompute/physical research suite: **53 tests PASS**.
Full historical harness: **593 tests run; 7 failing assertions, 1 skipped**.
All 7 failures came from Windows refusing to execute
`invoke_closed_loop.ps1` under the local script execution policy:
four methods in `test_windows_operational_snapshots.WindowsOperationalSnapshotTests`
(bad SSQ snapshot, explicit snapshot paths, mode/path conflicts, timeout bound).
No system security setting was changed and no failure is counted as PASS.
GitHub Ubuntu/Windows logs and artifacts are the separate full-suite verification.

Independent code review identified two P2 defects: stale candidate wording and
an unpinned prior 128-test input. Both received failing-then-passing regressions.
A training-prefix chronology regression and a validation/test selection integration
regression also pass. No material review finding remains deferred.

Publication is a Draft PR stacked on PR 492; no main merge, production promotion,
automatic scheduling or betting. The 500-future-draw protocol is a design only,
not an activated or already completed experiment.
