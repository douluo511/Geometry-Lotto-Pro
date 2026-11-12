# GPU full-formula computation and private SSQ/DLT D2 evidence verification

**2026-11-12.** Research extension stacked on PR #483 (which stacks #480 and #479). No modifications to formal V4.7, original Random NULL, main or sealed research ledger.

## Decision being tested

1. Does GPU computation accelerate the **whole formula-to-ticket pipeline** over vectorized NumPy and warm Numba, including source transfer, residual estimation, host return and stable de-duplication?
2. Does an expanded formula system (312 candidates, eight frozen experts) **actually improve D2 on same-draw future outcomes** compared with both the original frozen 72-candidate V2 and a fixed research random NULL, after multiple-test correction?

These are independent hypotheses. GPU speed cannot make fair independent lottery numbers more predictable. Every draw ticket has the same theoretical probability if draws are truly uniform and independent.

## Implemented GPU algorithm

The optional PyTorch module performs entire formula evaluation over batched expressions, issues and positions, computes modular residuals with strictly prior draws (j<t), creates prefix histograms, chooses smallest tie-winning residual index, and uses the identical SHA-based ticket de-duplication / D2 pair process as the original Python implementation. Its return value must exactly match CPU NumPy for every formula and target.

- Supports torch.device("cpu") and torch.device("cuda"); CUDA is rejected if torch.cuda.is_available() is false.
- Bounds batch count and estimated peak memory; checks available VRAM to fail closed before allocating.
- The benchmark measures the **full end-to-end function**, including device transfer and CPU-side ticket completion, with several repetitions and device synchronization. The CSV/receipt inputs are never read by this synthetic benchmark.
- CI has read-only standard hosted runners, no real GPU, no authoritative GPU speedup. A true GPU result requires a real CUDA-equipped host and a separate owner-approved local execution. GitHub GPU larger runners are not automatically enabled or paid for.
- The CPU-only PyTorch path is also tested against 72/312 expression semantics, independently of CUDA hardware.

## Strict read-only research scoring

The private evaluator accepts two separate, properly ordered owner-controlled draw-history JSON files with the exact SSQ/DLT fields and validates every issue, date and ball combination. It refuses inputs from inside the Git checkout; no network calls or file writes are performed. Existing source raw bytes, official identity and independent trusted timestamps must be validated in a separate process; a supplied JSON file is not proof of official authenticity.

Selection rules:
1. Training oldest >=180 draws, 60-issue development validation, 120-issue final **historical holdout** per lottery (window sizes explicitly selectable within 20..150 and 20..300).
2. Select V2 and V3 rosters ONLY from the training/development prefix. Freeze roster identities and equal weights before scoring any held-out draw.
3. V3 expands to exactly 312 candidates. Its validation fitness is front/back normalized above uniform expected overlap plus a predeclared complexity penalty, without direct D2 optimization. V2 freezes original 72-candidate algorithm separately.
4. For each held-out draw, create three predictions from pretarget history: V3, V2 and the same-issue fixed deterministic **research** NULL. This research NULL is NOT the untouched formal V4.7 NULL.
5. Evaluate full-ticket exact matches, front/back overlaps, D2 (two preselected front numbers), Wilson 95% CI and exact paired discordance tests; Holm-correct the four comparisons (SSQ and DLT, V3 vs NULL and V3 vs V2).
6. Retain every eligible test issue, including losses. The CLI prints **aggregate counts only** on the owner-controlled terminal and never writes results. Even nominal positive historical findings **cannot** be promoted as a proven future edge because model design could have seen this history.
7. Independent pre-sale target/cutoff authentication, trusted predraw seal, durable user-owned private ledger, prospective scoring and independent audit are STILL NOT VERIFIED. Always mark formal_A=0 and edge=NO_EDGE.

## Private Windows execution commands

Keep live sources and original authoritative evidence OUTSIDE the Git repository, in owner-controlled durable encrypted storage. Replace the example paths with actual files only when independently acquired and checked. **Do not upload these files to GitHub Actions or attach them to the PR.**

    python -m pip install numpy numba torch
    python -m research.supercompute.formula_torch_full --game both --history 190 --targets 8 --formulas 72 --repeats 3
    python -m research.supercompute.private_hit_validation --ssq-private C:\PrivateLotto\ssq.json --dlt-private C:\PrivateLotto\dlt.json --validation 60 --holdout 120 --backend numba

The first command is a synthetic computation benchmark. The second is a historical research test from private input, **not** a formally preregistered prospective forecast. Actual SHA of input histories is printed privately to the operator, not saved to GitHub.

## Threat model / tests

- Require separate CPU/NumPy/PyTorch parity including full completed tickets and chosen D2 front pairs.
- Mutating the exact target and all later outcomes cannot affect that target's predraw ticket.
- Reject absent CUDA rather than substituting CPU, unknown operations, duplicate formulas, memory overflow, unknown issues, malformed balls, untrusted inputs from Git repository, duplicate JSON keys and mislabelled game.
- Tests use deterministic SYNTHETIC histories only, never actual source histories in public CI. Uploads and data artifacts must remain **zero**.
- A GPU speedup claim requires a measured CUDA=PASS **full-pipeline** comparison with CPU on the same machine and workload; a small Torch tensor microbenchmark does not count.
- Hit-rate improvement claim requires future official independently verified prospectively frozen outcomes with corrected statistics; sample-historical gains are only exploratory.

## Official references

- NumPy: https://numpy.org/doc/stable/
- PyTorch CUDA availability: https://docs.pytorch.org/docs/stable/generated/torch.cuda.is_available.html
- PyTorch CUDA synchronization: https://docs.pytorch.org/docs/stable/generated/torch.cuda.synchronize.html
- PyTorch GPU memory info: https://docs.pytorch.org/docs/stable/generated/torch.cuda.mem_get_info.html
- Numba: https://numba.readthedocs.io/en/stable/
- Python futures: https://docs.python.org/3/library/concurrent.futures.html
- GitHub GPU runner eligibility: https://docs.github.com/en/actions/concepts/runners/larger-runners
- Fair SSQ D2 chance: 15/528 = 2.841%. Fair DLT D2: 10/595 = 1.681%.

**Conservative outcomes until proven otherwise:** GPU_ACCELERATION=UNVERIFIED; OFFICIAL_SOURCE_AUTHENTICATION=UNVERIFIED; FORWARD_EDGE=NO_EDGE; FORMAL_A=0.
