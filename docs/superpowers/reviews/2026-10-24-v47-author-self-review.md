# Superpowers whole-branch author self-review (not independent)

Review range: parent `b754ec2f9f8b2a76e4358f9a151516f4307fecd8` (#466) to `a367afbaa92295bc15e4a92d6d1dd5cb78944acb` (#467). Spec: `docs/superpowers/specs/2026-10-24-v47-unified-shadow-bot-design.md`; user master goal: Issue #468.

**Reviewer seat**: author self-review because no separate reviewer/subagent execution tool was available. This must NEVER be represented as independent Superpowers code review. `INDEPENDENT_CODE_REVIEW=NOT_VERIFIED`.

## Strengths, supported by code and full CI

- The original fixed six-row model family per game and recorded random NULL remain untouched. The PR462 candidate's historical diagnostic is not promoted to a seventh entry.
- Strict external JSON rejects duplicate nested keys/NaN/oversize, local path ancestry, and many altered outcomes; RED reproductions retained.
- `advance_workspace` checks original pre-draw ledger, makes no new forecast on missing history, and requires complete local roster before statistical summary. Invalid optional challenger now preflights before freeze.
- Real Windows and Ubuntu tests include Python subprocess freeze/score, Windows PowerShell AST and scheduler preview (never installs), and source/clock/alias negative controls.
- Exact-head CI39994939016: Windows 316 OK, Ubuntu 316 OK (skipped=5), SHA matches `a367afbaa92295bc15e4a92d6d1dd5cb78944acb`.

## Important findings / blockers (unresolved; prevent full delivery)

1. **Durable external work is absent.** `research/harness_v46/windows_closed_loop_tasks.ps1`: the scheduler is opt-in and has *not* been installed on an owner-controlled persistent machine. Boot, overlapping ticks, unplugged power and restart evidence are NOT_RUN, not PASS.
2. **G01 and TSA are external.** `closed_loop.py` accepts caller-provided snapshots and outcomes; code validation does not prove independent official source, correct DLT draw-vs-publication date, independent presale bound or signed accuracy. A synthetic SUCCESS must not register A.
3. **Local receipts are not WORM.** `closed_loop.py` uses local SQLite and create-only filesystem receipt. Privileged replacement, TOCTOU linked components, OS-power-loss partial-write and independent clocks remain out of scope, requiring external custody.
4. **Config and operator risk.** PowerShell `ConvertFrom-Json` is not the strict Python duplicate-key decoder; a tampered local scheduler config might be ambiguous, and local `log_path` lacks a trusted append-only policy. Require reviewed operator config/ACL and external archival before real-data claims.
5. **Algorithm improvement is unproven.** `d2_challenger_lab.py` is an already-exposed retrospective fixed recency-pair hypothesis; it does not auto-tune and cannot justify updating the six arms. True future, preregistered paired NULL evidence and DLT69/2880 negative-control resolution are absent.

## Minor / deferred
- Consolidate redundant README and plan references once cross-branch history settles; do not rebase away original source identities.
- Automated log parsing should retain full original PowerShell invocation stdout/stderr with external hash custody after host deployment.

## Declined to judge, with rulings
- Real official next target & source reliability: **not provided by source/cutoff authentication process**, keep G01=BLOCKED; no guessed target.
- Trusted TSA root policy and token accuracy: **requires approved third-party witness**, keep TSA=NOT_VERIFIED, no fabricated certificate trust.
- Actual prospective D2 edge: **cannot be inferred from synthetic/historical tests**, keep `NO_EDGE` and A=0.

## Assessment
**Ready to merge main? NO.** Isolated SHADOW component passes exact-head CI, but the user goal is a deployed, independently audited forward prediction system. Review is self-review only, and external operational/research gates remain unmet.

ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET; D2_EDGE_CONFIRMED=NO; formal_A=0; NO_EDGE.
