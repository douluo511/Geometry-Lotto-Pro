# Inverse Formula Discovery: isolated falsification probe (2026-11-11)

## Claim under test
Can a mathematical formula reverse-fit prior full SSQ / DLT draw results perfectly **and** predict disjoint later actual draws better than an independent fair-draw null? Demonstrate distinction between interpolation and forecasting, not claimed predictive edge.

## Input / provenance
- SSQ: issue 2026030..2026129, 100 contiguous draws, parsed from the Shanghai Welfare Lottery regional published history https://www.swlc.net.cn/lottery/ssq.html?view=previous&limit=100 on 2026-11-11. **Not a cryptographic original-source capture.**
- DLT: issue 26039..26128, 90 contiguous draws, parsed from https://www.lyjiayu.top/dlt/ (latest 50) and individual third-party historic https://www.caiyao.net.cn/daletou/draw/<issue>/ (older 40), on 2026-11-11. Third-party data **not** independently authenticated as official records. No formal G00/G01 promotion.
- Fixed fixture bytes are SHA256-logged at runtime. Parser checks legal ranges, sorted distinct numbers, unique contiguous issue IDs.

## Train/test / formula design
For each game's last 90 draws, train on its earliest 60 and hold out the subsequent contiguous 30, untouched in model construction. The basic formula is a unique degree <=59 Newton interpolation polynomial over GF(p) for each sorted ball position (p in {257,65537}). A whole family of different polynomials F(x) + c*product(x-i) agrees exactly at all 60 training nodes, with c in {0,1,2,3,5}. Map residues into legal ball ranges and deterministically resolve duplicate predicted numbers. Ten variants per game are tested with the same untouched holdout.

A separately identified research-only seeded random selector is a sanity-check null, **not the fixed V4.7 Random NULL**. Full ticket exact hits and both-front D2 hits are counted. The next-issue ticket computed with all known history is exploratory only, without authenticated predraw freeze.

## Risks / interpretation
- Train 60/60 is a direct algebraic consequence of constructing the interpolating polynomial, **not a predictive discovery**. Arbitrarily many formulas fit all samples yet disagree on the future.
- The grid was chosen for an overfitting counterexample. **No model selection on the holdout and no statistically valid edge discovery.** Ten correlated tests inflate lucky outcomes. One-shot fixed holdout is not independent external prospective testing, and the fixture may contain source errors.
- This sidecar does not import or alter original harness models, seeds, time gates, frozen ledger, sales cutoffs, CI acceptance, or issue identity. No automatic promotion.

## Acceptance
- Validate contiguous 90+ per game; train 60, test 30. Assert perfect in-sample for all ten variants, show out-of-sample results and theoretical SSQ 15/528 and DLT 10/595 D2 baselines.
- Negative tests: duplicate/invalid balls, holdout non-leakage, and disagreement between equally perfect training fits.
- Research status EXPLORATORY_ONLY_NO_EDGE until independently pre-registered prospective evidence. CI / independent review are not certified by local pytest.
