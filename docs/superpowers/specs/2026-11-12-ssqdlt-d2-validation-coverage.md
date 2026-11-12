# SSQ/DLT exact D2 coverage and paired future-test readiness — research-only

2026-11-12. Parent main at `241684ed09f348b845d7150b92b01b3d6171b828`.

## Goal

Enhance the **existing** `research/supercompute` project, not create another V4.7 Harness:
- Exact fair-draw D2 multi-pair coverage for a **fixed number of distinct pairs**, with a reproducible greedily selected portfolio and a predeclared overlapping baseline, reporting total front draws (not a ticket-profit forecast).
- Historical **past-only** EWMA30/HOT60 versus same-issue seeded RANDOM_NULL D2 performance, with a full per-draw roster, exact two-sided McNemar tests for discordant pairs and Holm correction over SSQ/DLT × two active arms.
- JSON + SHA256 + human-readable Markdown report from one manual or push GitHub Action. Source bytes SHA, target history cutoff, limitations are required.
- Explicit stop-gate: no authenticated live official source, independently trusted predraw freeze, prospective scores or formal V4.7 promotion. This module NEVER writes to V4.7 ledger.

## Definitions

For one pair `e={a,b}`, D2 hits if the drawn front subset `W` contains both. For a set `S` of m distinct pairs, coverage event is union of pair events. Exact count among `C(N,k)` equiprobable front draws is
`sum_{nonempty T subset S} (-1)^(|T|+1) C(N-|union(T)|, k-|union(T)|)`.
Compare greedy deterministic max-marginal coverage at every step with a fixed overlapping star `(1,2),(1,3),...` with **same m**. Greedy is not a claim of global optimality. Each additional pair is a separate prediction selection, potentially a cost; do not call increased coverage a per-ticket advantage. Fully matching any fixed full ticket remains `1/[C(N,k)C(B,b)]`.

Strict historical walk forward: for each issue, compute all arms **before** reading its outcome, score all arms on identical issues, preserve failures and all losses; static models HOT60 (60 recent draws) and EWMA30 (half-life 30, last 240) are separate from V4.7 incumbents and were selected after earlier exploratory analyses. Therefore Holm-adjusted historical p-values remain exploratory and do not certify registered or independent future success.

## Controls / stop gates

Reject invalid pair/rule arrays, missing output path, partial or out-of-order historical issue roster, duplicate JSON keys, nonfinite JSON values, source identity mismatch; fail whole experiment instead of silently shrinking sample. No API/network, no bets, no dynamic model selection using the evaluated target period, no editing historical forecasts, no formal promise. All results `formal_A=0`, `NO_EDGE`, `RESEARCH_VALID=NOT_YET`, `ENGINEERING_PASS=NOT_YET`.

## Acceptance

Write adversarial tests before implementation (RED log); then implement; exact-head branch CI (GREEN), 1- and 4-worker-independent reproducible coverage, independent small-universe brute force, fixed historical per-issue cohort, all sources and methods recorded. Create single Draft PR, retain main until independent review. Do not treat passing offline tests as a physical Windows cold boot, two genuine schedule events, authenticated sales cutoff, or future sample.
