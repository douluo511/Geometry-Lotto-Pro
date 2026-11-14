# V4.7 four-area dynamic interval research

## Meaning of mathematical intervals

SSQ and DLT each have TWO independent number areas. Draws are unordered sets:

| Game | Area | Universe | Balls per draw | Display zones |
| --- | --- | --- | --- | --- |
| SSQ | front (red) | 01..33 | 6 | 01..11 / 12..22 / 23..33 |
| SSQ | back (blue) | 01..16 | 1 | 01..05 / 06..10 / 11..16 |
| DLT | front | 01..35 | 5 | 01..12 / 13..24 / 25..35 |
| DLT | back | 01..12 | 2 | 01..04 / 05..08 / 09..12 |

For every area independently, A is a selected **required subset** and E is a selected **fully excluded subset**. A condition passes if and only if A is a subset of the published draw and E is disjoint from the published draw. A and E cannot overlap. A draw cannot be selected out of thin air by grouping numbers in a zone: the zones are report partitions, not special lottery probabilities.

Let N be the size of the area's universe and k the number of winning balls. If the required set has a elements and the excluded set has e elements, with all constraints valid, there are precisely C(N-a-e,k-a) legal area combinations. The complete legal lottery ticket space is the product of both areas' retained counts. The original size is C(N_front,k_front) * C(N_back,k_back). For uniformly random independent areas, the chance that a fixed complete winning draw survives **all** constraints is exactly the fraction of the full space retained. Merely reducing search space DOES NOT create a proven unconditional jackpot advantage.

## Dynamic profile and chronological selection

The new V4.7 research grid considers front required counts 0..3, front excluded counts 0..4, back required counts 0..k_back and back excluded counts 0..4. These are intentionally bounded computational research settings, not mathematically enforced maxima for exclusion in general. All four counts can be **zero**. Training selects the narrowest profile that kept the actual result in **all earlier** training folds; the last fold is withheld from profile selection and evaluated separately. The standard 3 folds provide 2 selection folds and 1 held-out fold, which is far too small to demonstrate a predictive edge. Because many profiles are evaluated, the profile can overfit by chance: the report explicitly says INSUFFICIENT_FOLDS_NO_RELIABLE_EDGE, multiple_comparisons_adjusted=false, and NO_EDGE.

The existing 11 positive M+ and 11 strict fully-disjoint M- model records remain unchanged in their own objective. Front M- exclusions are separately selected pairs from the negative models. The back-area negative votes are derived from **low-ranked back marginal candidate scores**, not separately trained back M- exclusion models; the report MUST continue identifying these as UNVERIFIED_PROXY_NOT_INDEPENDENT_M_MINUS. They must not be described as equivalent to front negative training without an independent fitted target and validation.

For each game prediction, inspect the new field games.<game>.interval_search:
- profile: front_include, front_exclude, back_include, back_exclude
- areas.front and areas.back: selected required and excluded numbers; numeric vote support and three disjoint display zones; exact retained and original combination counts
- retained_full_ticket_combinations, original_full_ticket_combinations, retained_fraction
- calibration: first folds' training fit, independent held-out event (each area included / excluded / retained), and the explicit insufficient-evidence status
- tickets: 8 top-ranked fully legal combinations for both areas, using exact top-K best-first search over additive heuristic scores. This is not an exhaustive enumeration of every retained full combination; only the count is computed exactly.

The old V2 joint_search is retained as a comparison and for compatible pre-existing frozen files. It is still only a front-area 2-required/2-excluded research baseline. The new output is **additive** to V2 frozen reports and does not rewrite old hashes. When scoring a previous V2 document without interval_search, the scorer records NOT_AVAILABLE_IN_OLD_V2_FREEZE rather than claiming new tests were performed on past predictions.

## Commands and evidence

From the repository root, after preparing independently audited merged past-only inputs:

    python -m unittest discover -s research/supercompute/tests -p "test_v47_interval_search.py" -v
    python -m research.supercompute.v47_hedge generate --ssq-data INPUT_SSQ.json --dlt-data INPUT_DLT.json --ssq-target NEXT_SSQ --dlt-target NEXT_DLT --output OUTPUT_44.json --freeze-dir FROZEN_DIR

Each generated report includes 22 models per game plus the four-area interval output. The commit-specific GitHub Actions workflow runs these assertions and publishes report artifacts. Only an actual subsequent scheduled event, source publication and independently verified draw can establish automated predraw forecasting and postdraw results. No historical selection or simulation alone supports a claim of improved prize odds.
