# Independent result audit — retained historical recency/Pairwise ablation run

Reviewer: ci_audit independent agent, separate from the implementing/running agent; not an independent human signature. Read-only review of the retained algorithm_run files and their exact source input; no seed, model, outcome, ranking, manifest, report or receipt was changed.

## Result and identity

PASS for the retained exploratory arithmetic and local-record consistency. Full retained files were hashed before and after; all unchanged. Reproducible independent implementation: run_review.py. Structured findings, every reported arm/scope count, independent full-test-scope intervals and hashes: run_review.json.

- Manifest canonical SHA256:5620b85c521b03f67ac9066858a7f739b3e1e4eb82a2beda17fed91f838ce9b1.
- Manifest file SHA256:03d2f8c06980d5a05db2e64b2942cca972f460665d5a164a824ca7fa1268dc0d.
- Input file SHA256:7be1790f9b14cf20c69182813e57cf8f65b7f8d294ca78e86124f9999b57783e.
- Full report file SHA256:22770d539aeb1c3b8d80cc57067e91d5897267ecb0a7aa1efc6cca5069996dfb.
- Evaluation rows canonical SHA256:659a1fff3ec339c2a7b45e7ddb4174185c55f562966d5838cbd93e71899178bc.
- Lab source SHA256:6ddebbeb3c6069588392994f0c111fde8e588c8d7fa31ebfa26707e86d2f68f0, matching the reviewed local code candidate.
- Core/statistics source hashes in the manifest match the retained current source bytes. This run is not itself evidence of remote two-OS CI.

## Complete target and scoring reconstruction

Input source is source_audit/two_game_national_FULL_bundle_EXPLORATORY.json. “FULL” denotes the captured endpoint's available rows, not independently certified official-calendar completeness.

| Game | Captured rows and range | Warmup | Train | Validation | Final retrospective test | All targets |
| --- | --- | --- | --- | --- | --- | --- |
| SSQ |2079;2013001/2013-01-01 through2026121/2026-10-22|120|1175|392|392|1959|
| DLT |2938;07001/2007-05-30 through26120/2026-10-21|120|1690|564|564|2818|

All4777 target rows have exact expected index, raw issue, date, front/back outcomes, training endpoint and reporting scope. All eight arms have five unique legal numbers and preserve the stored first-two pair. Independently recomputed191080 D1–D5 prefix-set success flags, all top-five hit counts and aggregate all-hit totals match the report.

All4777 NULL rankings were independently reconstructed by SHA256 ordering from the fixed seed, game and **original raw issue string** without importing the producer. All matched;280 evaluated DLT targets retain a leading zero. Examples include08028→D2[16,3] and08029→[4,1]. Every prefix fingerprint was independently rebuilt from canonical prior rows and matched. No result target trains its own prediction in these stored identity checks; code-level forecast chronology was separately reviewed.

The full report, statistics_summary (exact report minus rows), frozen manifest unsigned digest, prepared-only row hash, prepared index lists, run receipts and input file identity are mutually consistent. Every supplied post-warmup row remains in the denominator. This does not prove no official historical issue is absent from the captured source.

## Independent statistics and Holm

The audit imports no lab/core/statistics functions. It recomputes all per-game/scope hit counts, paired wins/losses/ties, fair binomial tails and128 hypothesis p-values using independent probability recurrences and combinatorial sums. Holm was independently rebuilt over the complete fixed named family, including deterministic duplicates.

- Maximum difference versus stored128 unadjusted p-values:5.36e-13.
- Maximum Holm difference:8.44e-15.
- Minimum independently recomputed Holm p:0.06503814088626489.
- Minimum belongs to DLT:train:HOT120:joint and DLT:train:P-MARGIN:joint; it is **training-scope**, not final-test evidence.
- For the complete SSQ final-test scope, all eight arms' Clopper-Pearson95% intervals and all paired conservative intervals, plus all nine declared pair-comparison intervals, were independently inverted using direct math.comb binomial sums. Largest CP endpoint difference1.38e-15; paired endpoint difference1.25e-15.

## Validation choice and final test results

| Game | Fixed validation selection | Final test D2 | Same-draw NULL | Paired wins/losses | Nominal paired p | Fair-baseline p | Test Holm joint |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SSQ |EWMA18/392|17/392|6/392|17/6|0.01734483242034912|0.05836630203394531|1.0|
| DLT |HOT60 11/564|11/564|15/564|11/15|0.8365302085876465|0.35152832392380234|1.0|

Validation arm and fixed tie order were independently rederived from every validation D2 bit. No test outcome was used to alter the retained selection in this audit.

SSQ EWMA test rate CP95=[0.0254628572180811,0.0685288975064004]; paired difference CI95=[-0.0123968240367936,0.0675963803151293]. DLT HOT60 retained paired difference CI95=[-0.0373283367929427,0.0233112658682893]. Both difference intervals contain zero. The SSQ nominal paired p alone is not the joint corrected hypothesis and must not be reported as an established advantage.

## Preparation/evaluation local order

Retained local UTC strings are consistent:
- preparation start10:39:52.385734; complete10:40:10.330973;
- evaluation start10:56:44.384242; complete10:57:27.078093;
- same manifest digest in both receipts; recorded file digests match actual bytes.

This establishes consistency of the retained **local records** only. Both receipts explicitly state external_time_proof=NONE. Local timestamps, caller-held hashes and file custody do not establish independently authenticated historical preregistration, unseen data or trusted pre-draw time.

## Limits and scientific ruling

This arithmetic audit does not freshly authenticate national HTTP source custody, upstream independence, true draw/publication semantics, official-calendar completeness, the original2880-draw anomaly protocol, a persistent formal-study ledger, future predictions or outcomes. Existing data-review limitations remain. It does not transform exposed historical labels into a genuinely hidden holdout.

No changed data/seed/model tuning or discarded failure rows were introduced. This run's new protocol/results cannot retroactively explain or replace the historical DLT69/2880 vsNULL42/2880 anomaly.

SCOPED_RETAINED_RUN_ARITHMETIC=PASS.
ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET; D2_EDGE_CONFIRMED=NO; formal_A=0; NO_EDGE.


