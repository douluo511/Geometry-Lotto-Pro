# Minimal execution plan for SSQ/DLT D2 validation & coverage (2026-11-12)

1. Review current `research/supercompute/engine.py`, `exhaustive.py`, P0 research workflows and existing V4.7 PR #467/#472; preserve all frozen records, no additional Harness.
2. Create isolated branch from verified main `241684ed`. Commit this scope and tests first. Collect actual RED GitHub Actions job.
3. Add `research/supercompute/d2_lab.py`: exact D2 coverage counts (inclusion-exclusion), deterministic greedy coverage, same-sized overlapping comparison; historical full-roster paired research against fixed RANDOM_NULL, exact two-sided discordant test with Holm across four comparisons.
4. Add `ssqdlt-d2-lab.yml`: read-only permission; tests, generate dual-game report, independent SHA/eligibility gate, artifact (no privileged repository writes). Run at exact HEAD.
5. Review evidence; report real historical counts/p-values and provenance. If source or timestamp gates missing mark blocked, not PASS. Draft PR only; next real P0 task remains verified-source, trustworthy pre-cutoff sealing, authentic post-draw scoring and actual two schedule events on a durable host.

**No unverified claim that more CPU work changes independent fair-draw probabilities.**
