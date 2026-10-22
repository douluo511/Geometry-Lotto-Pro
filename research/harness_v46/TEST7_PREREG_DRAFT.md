# V4.7 test7 — one new challenger: CW-Residual-Minimax-v1 (DRAFT ONLY)

> **Status: EXPLORATORY_UNREGISTERED.** This draft and its synthetic tests are NOT an accepted preregistration, not official SSQ/DLT source admission, not trusted predraw freeze, and not evidence of D2 lift. No production core forecast, V4.5 eight-slot identity, original ledger, or main branch is modified.

## Mechanism / falsifiable hypothesis

The incumbent \`core._pair_scores\` and 120-draw Pairwise-D2 use a **sum of observed single-ball marginal frequencies plus a shrunk pair residual**. Existing V4.7 \`challenger\` uses the *minimum across 30/60/120 of that combined score*. Even if it passes tests, marginal dominance makes it difficult to attribute a win to interactions.

**H1 (unproven):** residual-only pair association persisting simultaneously across fixed 30, 60, and 120 previous official draws may improve future top-two D2 success beyond both the incumbent marginal-plus-residual Pairwise-D2 and a same-period frozen Random NULL. **H0:** no genuine prospective gain; observed association reflects chance or pair-selection noise. The mechanism is meaningful only if frozen in advance and independently tested.

Exactly **one** slot-06 proposal, not an additional official model or post-hoc champion. The current production/research \`core.forecast(...,"challenger")\` is intentionally left unchanged until test1 approval and test10 migration.

## Unique deterministic selection (SSQ separately from DLT)

For each window w in (30,60,120) ending at the same locked as-of history draw, compute counts \`c_i\`, \`c_j\`, observed pair co-occurrence \`c_ij\`, and k=6 (SSQ) or k=5 (DLT):

\`\`\`text
E_w(i,j) = c_i * c_j * (k-1) / (w*k)
T_w(i,j) = (c_ij - E_w(i,j))/(w+200)
R(i,j)   = min(T_30(i,j), T_60(i,j), T_120(i,j))
main D2  = argmax_{i<j} R(i,j)
\`\`\`

This is a *heuristic marginal-conditioned residual*, **not** a calibrated hypothesis-test z-statistic or a proof that pair numbers are dependent. The windows overlap; they do not provide three independent samples. The denominator deliberately fixes the same \`tau=200\` shrinkage convention but removes the marginal-addition term. No normalization, learning, changing window weights, hyperparameter tuning, or score-dependent branching is permitted.

**Exact arithmetic:** \`fractions.Fraction((c_ij*w*k-c_i*c_j*(k-1)), w*k*(w+200))\`. Strict ordered-history admission with >=120 draws and core as-of validation. Select the maximum worst-window value; exact ties select numerically smallest ascending pair tuple. Main D2 = selected ordered pair. Positions 3–5 = descending single-number frequencies within the last 120 draws, ties numeric ascending, excluding D2. Legal full ticket = first six ordered red (SSQ) / first five front (DLT), sorted for display. Back balls = unchanged V4.7 SHA256-sort from \`core._stable_permutation\` with fixed parts \`NULL_SEED, lottery, target_issue, "challenger", "back"\`. This back choice does not affect D2.

**Version identity:** draft \`test7_cw_residual_minimax_v1\`, a distinct version from V4.6 \`maximin_pair_score\` and V4.7 incumbent \`challenger\`. Source base is pinned to #432 head \`f12e47106f1d0c325573a48e39a6e2efd5d459ff\`. The module's \`parameter_contract()\` and actual source blob must be hashed from the committed files and independently approved by test10. Changes after accepted preregistration require a new version and future start, not a rewrite.

## Fixed ablations and controls (SHADOW only before registration)

1. **Marginal-only:** set the pair-residual contribution to zero; the canonical comparison is single-number frequency, not a newly selected winning ticket.
2. **Residual 120-only:** same residual formula, only last 120; tests whether cross-window minimum adds information.
3. **Existing 120 Pairwise-D2:** original marginal+residual score with original tau; tests against the incumbent.
4. **Original V4.7 maximin combined:** original min across 30/60/120 combined scores; measures the contribution of removing the marginal term.
5. **Fixed Random NULL:** same target, draw, and frozen seed; independent paired control.
6. **Within-window pair disruption:** a precommitted row/ball-preserving randomized control that preserves each draw's k and, where feasible, observed marginal counts. Its randomization algorithm, fixed seeds, and finite-sample validity must be separately frozen **before** counting it as an inferential negative control. It is diagnostic only until then.

No ablation may silently replace the unique primary D2 after seeing a target's results. Same lottery, history cutoff and draw for all arms.

## Statistical protocol proposal; not yet binding

Two **separate** prospective lottery hypotheses (SSQ and DLT); avoid silently folding them into the historical formal 12-family. For each game require success against **all three** of: exact one-sided binomial fair baseline (SSQ=15/528; DLT=10/595), same-draw exact paired Random NULL comparison, and same-draw exact paired existing Pairwise-D2 comparison. One candidate-level intersection-union p-value is \`max(p_baseline,p_paired_null,p_paired_pairwise)\`. Apply Holm to the two prespecified game-level hypotheses (Holm-2), with family alpha 0.05. Report effect sizes, exact rate CI and paired-difference intervals; do not use a provisional p-value as observed improvement.

Proposed primary fixed analysis at **4,000 admissible future draws per game**, with 200/400/800 draws as completeness/diagnostic checkpoints only. Any fixed horizon must be independently approved before the first eligible target; reaching 4,000 can take many years. No early success declaration based on repeatedly viewed p-values. If a future audit invalidates evidence (future leakage, forged cutoff, model identity change, old snapshots, TSA failure, outcome tamper), exclude it according to locked rules and preserve the reason. If primary comparisons fail, status is \`D2_EDGE_NOT_CONFIRMED\` (or \`INCONCLUSIVE\` if power assumptions fail), not proof of equivalence or absence of any possible edge. Operational historical scientific verdict remains NO_EDGE until convincing new evidence.

## Historical exposure, admission and release gates

All data/results already visible by the trusted acceptance timestamp (including V4.5/V4.6/V4.7 backtests and historic DLT 69/2880 negative-control anomaly) are **development or contamination-exposed**, never independent prospective evidence. The DLT anomaly is \`ROOT_CAUSE_UNRESOLVED\` and must remain visible.

The first countable target per game must be explicitly named in the test1 receipt *before that game's cutoff*, using the test2 independently checked >=120 official histories, normalized as-of, full original source raw bytes and source SHA, legal future issue and cutoff, and test10-approved source+parameter SHA. Freeze one ordered prefix and one unique main D2. The trusted external TSA/witness receipt and independent read-only test9 audit are required before formal promotion. Forecasts from this module before these conditions are **synthetic/SHADOW only** and may not be backfilled or retroactively promoted.

**Next independent decisions required:** test10 reviews algorithm/source/parameter identity and V4.7 core integration diff; test1 approves or rejects this preregistration version and starts eligible future targets; test2 supplies a verified as-of snapshot; test9 independently verifies statistics and freeze. No auto-buy, no chat-to-chat synchronization claims.
