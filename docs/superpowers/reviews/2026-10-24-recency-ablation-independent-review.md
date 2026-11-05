# Independent agent review — local recency/Pairwise ablation candidate

Review time: 2026-10-24 10:43 UTC. Reviewer is the separately invoked ci_audit agent, not the implementation agent and not an independent human signatory. No production file, frozen ledger, model, seed, remote branch or GitHub record was edited by this reviewer.

## Exact scope and identity

Baseline Git HEAD: 5d52161efb9115ee41be8e6e8a7428229e434be6.
Object reviewed: local uncommitted candidate on that HEAD, not a claimed remote GREEN or final remote commit. Final candidate SHA and exact remote CI are still to be provided by root for a separate scope confirmation.

Stable during both final adversarial probe and final24-test run:
- d2_challenger_lab.py SHA256 6ddebbeb3c6069588392994f0c111fde8e588c8d7fa31ebfa26707e86d2f68f0.
- tests/test_recency_ablation.py SHA256 1454fae30f481ca71778e11fb7e2feb749275ce613333d2b8c6212e5a37b9433.
- design SHA256 30f2b4c74ebd95a8ade9318c4bd9f150e6553fec53e2b807ae8c670f8cc2a96a.
- plan SHA256 2ce2498f73353693d843f121df677178e4ca4bb494a6cb907040d6cda916b526.
- existing core.py SHA256 f780a577d514eb36b4f3bcc4ecdecc92993ffb5fc96d03210cdf61078ff52941.
- existing statistics.py SHA256 bfcee7a56f20f139de5bff3eba1736bbc9536b10dcfd7c4b72a97661a2d9c037.

The initial reading saw transitional lab/test hashes9c84f766…/e212b995… while implementation normalized files. The conclusions below refer to the final6dde…/1454… hashes only. File hashes before and after the adversarial probe are recorded in recency_review_probes.json. Git diff --ignore-space-at-eol for core/statistics was empty; their index/worktree status reflects line-ending handling. No core/statistics behavior changes were part of this candidate review.

## Result

No actionable P0/P1 defect found in the reviewed new interfaces under the declared trusted installed Python/package and caller-unverified historical data boundary. The scoped local candidate meets the recency/ablation design's observable behavior. This is not full-branch human acceptance, official source admission, prospective validation, or remote exact-HEAD CI approval.

## Code and scientific reasoning checked

1. Input schema is exactly two game lists with exact date-only row fields; legal sorted complete front/back balls, ASCII decimal issue strings, numeric issue uniqueness/order, canonical strictly increasing ISO dates and at least125 observations are required. Raw issue spelling is preserved for NULL, while numeric ordering rejects duplicate aliases. It claims observed-row contiguity and explicitly leaves official calendar completeness/publication availability unverified.
2. Integer60/20/20 boundaries preserve at least one row per scope at the minimum125 rows. Initial120 are warmup. Each forecast receives only its preceding120 rows; HOT30/60/120 slice those as intended; EWMA/P-COMBINED/NULL delegate to unchanged incumbent rankers.
3. Marginal/residual-only pair winners use integer numerators with the same fixed120/tau200 mathematical component ordering; full ranking filler is Hot60 excluding that pair. P-COMBINED remains exactly the incumbent floating implementation. Synthetic independent Fraction tests cover the components, winners and filler. A separate4000 randomized legal-history check of integer exact combined winners versus incumbent winners found no discrepancy; it is a finite synthetic check, not a proof of universal numerical equivalence.
4. Preparation scores only train/validation rows; validation D2 count selects a fixed non-NULL arm with fixed order tie-break. Full input hashing and validation can read test records but do not use test scores for selection. Test labels were public already; the design correctly does not call them genuinely hidden.
5. Evaluation requires an expected manifest digest and recreates the whole preparation manifest before calling include_test=True. Canonical JSON comparison rejects extra keys and bool/int aliases, not merely stale hashes.
6. Complete hypothesis family is128=(seven joint tests+nine directed paired comparisons)×two games×four reporting scopes. Joint=max(fair-upper-tail,paired-NULL-upper-tail), an intersection-union hypothesis. All generated family/pvalue/adjusted-p keys exactly match; selected arm references an existing test ID and creates no additional “independent” result.
7. All supplied target indices enter the appropriate scope and the all scope. D1-D5 are nested prefix-all-hit flags, top5_hits is separate, D2 is the original first pair. Prefix fingerprints exactly equal core.digest(original full prior prefix); streaming avoids quadratic repeated full-prefix hashing.
8. Pair statistics use same-draw discordant wins/losses and exact conditional binomial tail; conservative paired CI combines97.5% marginal Clopper-Pearson intervals. Zero-variance phi returns None. Pair agreement is separate from success. These are explicit model-based exploratory calculations; the report does not promote an arm or assert calibrated inference under arbitrary adaptive real processes.

## Independently executed evidence

Command:
python -B -m unittest research.harness_v46.tests.test_recency_ablation research.harness_v46.tests.test_d2_challenger_lab -v

Final recorded result:24 tests in3.900s, OK. Full command/output/exit status is independent-24tests.json. This covers16 new behavioral tests plus8 old lab tests; it does not replace root's complete regression.

Independent executable: recency_review_probes.py.
Persisted raw result: recency_review_probes.json.

Actual counterexamples and controls:
-15 edited manifests, each with its checksum recomputed and attacker-supplied matching new expected digest: chosen arm, validation hit count, validation_n, bool/int alias, split, missing/extra/renamed family ID, seed, core source hash, input hash, prepared-row hash, extra approval field, decision and formal_A. All were rejected. Instrumented _ablation_rows observed only include_test=False in every attack, so no final test scoring occurred before rejection.
- Changed test suffix produced unchanged prepared selection and prepared rows. Rankings and full prefix fingerprints remained unchanged through the changed target's prediction; data fingerprint correctly changed.
- Dataset/manifest replacement with the old external expected digest was rejected. Replacement with a newly supplied valid digest was accepted as a *separate* study, demonstrating the declared caller-custody limitation rather than independent sealing.
- Every emitted prefix hash was independently compared with core.digest(bundle[game][:i]); all matched. For140 input rows/game, each game's train/validation/test/all denominators were12/4/4/20 and40 total per-draw rows.
- Independent paired-tail enumeration over13,908 small binary-vector pairs (all combinations throughn5 plus deterministic coveragen6–8) differed from rational combinatorial probabilities by at most8.881784197001252e-16.
- Real subprocess: python -B -m research.harness_v46.d2_challenger_lab --snapshot-bundle <temporary invented legacy fixture>. Exit0, stderr empty, original walkforward schema,10 rows, NO_EDGE.
- Loaded baseline HEAD lab code as a separate temporary trusted module and compared old audit_walk_forward output: exact equality after removing the expected whole-lab-source-bound challenger_contract_sha256 field. The source-bound identity changes because the lab source file changes, even though the legacy algorithm/output behavior remains.
- Full synthetic1000 observations/game study: preparation6.8697s, evaluation16.4266s,1760 emitted prediction rows,128 hypotheses, NO_EDGE. This is feasible local research execution; it is not a benchmark guarantee for all larger cohorts or slower CI hosts.
- Core producer/NULL seeding and old CLI behavior were not changed by this reviewer. All six recorded file hashes stayed unchanged across the final probe.

## Remaining limits and nonblocking documentation note

- The plan's signature sketch omits the required expected_manifest_sha256 keyword. The actual implementation/tests and updated design require it; callers must use the explicit keyword. Updating the plan sketch would avoid ambiguity but is not a runtime blocker.
- Pure caller-supplied data+manifest+new expected digest can describe a fresh study. The digest is operational local custody, not RFC3161, trusted historical publication availability, a human signature, or proof against a host/interpreter owner.
- No raw official input dataset, original2880-draw anomaly cohort, persistent original formal study ledger or real prospective prediction was authenticated by this code review. No claim is made that the tests or synthetic results prove data truth.
- Old V46 NULL seed/MT19937 and current V47 seed/SHA256-sort are distinct protocols. Raw numeric aliases can change NULL seed preimages. New code preserves raw strings; historical69/2880 vs42/2880 remains unresolved without exact original cohort/protocol.
- Local roster and supplied observed rows cannot prove missing official calendar draws did not exist. No synthetic publication dates, cutoffs or pre-draw timestamps were invented by the new date-only interface.
- No compromised Python-memory/stdlib defense, TOCTOU source mutation defense, external WORM custody, cold boot/power loss or persistent scheduler deployment was tested.
- Exact arithmetic labels refer to binomial model definitions evaluated using numerical recurrence. Extreme machine tails may underflow to0; this does not establish impossibility or scientific edge.
- Root must independently record final full regression, exact remote commit and two-OS CI raw logs. If production/test source hashes change, this review requires targeted reinspection; it must not silently transfer to a different candidate.

Disposition: SCOPED_LOCAL_AGENT_REVIEW=PASS_WITH_DECLARED_LIMITS, final remote scope confirmation pending.
ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET; D2_EDGE_CONFIRMED=NO; formal_A=0; NO_EDGE.

