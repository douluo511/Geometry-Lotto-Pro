# Strict lottery audit implementation plan

> For agentic workers: use superpowers:executing-plans; perform one fresh final code review.

Goal: extend PR 492's immutable 14-model results without re-running the completed historical sweep.
Architecture: verify and reuse its exact Actions ZIP, compute statistics in a separate research package,
check official current issue evidence, and publish a Draft PR stacked on PR 492.
Tech stack: Python 3.11, NumPy 2.4.6, SciPy 1.17.1, unittest.
Spec: the user's detailed continuation request; research/strict_audit_20261113/PROTOCOL.md.

## Constraints and decisions
- Parent upstream SHA 206a4f997a84c53df201180f50809f51fc902d34 includes PR 491 SHA 79b175d.
- No changes to old source, Random NULL, archives, main or betting operations.
- Ruling: no genuine unobserved historical test can be recovered by re-splitting exposed outcomes.
  Label both prior validation/test descriptive; clean test has n=0 and no winner.
- Ruling: use an isolated codeload snapshot after git transport stalls. Local baseline commit is
  NOT the upstream commit. Publish only additive files through GitHub onto the actual upstream parent.
- Current historical comparisons remain exploratory regardless of adjusted p.
- Ruling: PR 492 omitted validation events. Fill only that missing cache once and require
  exact equality of every original validation aggregate; keep the original ZIP unchanged.
- Preserve null model with its original seed; do not invent kill3 for legacy random.
- Recompute current candidate only after verifying latest official issue; physics abstains.

## Review focus
- Tampered inputs, reordered events, or out-of-bound target dates must be rejected.
- Selection must never depend on historical test scores.
- Exact zero-success intervals must not collapse to zero.
- Bootstrap must preserve simultaneous model outcomes and never masquerade as new evidence.
- Official source retrieval must not masquerade as an externally trusted predraw seal.

## Tasks
- [ ] Add failing behavioral tests for evidence integrity, chronology, selection, statistics and candidate gates.
- [ ] Implement exact/ Wilson intervals, joint fair/paired p, Holm144 and known-history Holm296,
      period blocks, outcome correlation, circular block bootstrap, historical adaptive selection.
- [ ] Replay a small fixed sample of per-draw outputs against the existing cache; retain all old bytes.
- [ ] Emit fresh report, candidates, source hashes and prospective design with clean n=0.
- [ ] Run relevant complete regression suites; have a fresh reviewer inspect and fix major findings.
- [ ] Publish additive research branch and Draft PR; inspect GitHub run logs through completion.
