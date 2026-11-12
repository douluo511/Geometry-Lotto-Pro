# SSQ/DLT formula-compute acceleration: fixed-scope experimental contract

**2026-11-12; Draft research.** Extends V1 PR #479 and V2 PR #480. Must never modify main, formal V4.7, immutable original Random NULL or stored lottery records. This is computation, not a claim that independent lotteries can be predicted.

## Why computing more formulas does not prove an edge

If all valid tickets have equal probability under independent uniform drawing, data mining can select apparently successful historical formulas purely by chance. The scientific requirement is a frozen predeclared search and **genuinely future, timestamped outcome scoring against matched random controls**. A synthetic holdout confirms code isolation, not real predictive validity. Historical replays are exploratory; do not turn an apparent historical gain into a live claim.

## Work package / execution contract

1. **Baseline measurement:** benchmark exactly V1's 72 expressions over 6 synthetic targets per game, plus a smaller cProfile of original Python code. Collect perf_counter wall time, tracemalloc peak Python heap (not process RSS), per-formula throughput, versions, repeated-run caution and correctness hashes. No predictions or actual draws in logs.
2. **Remove repeat computation:** a PrefixMatrix copies the caller's rows into immutable per-instance buffers and caches vectorized raw expression values keyed by (game-bound matrix, area, operation, atoms); windows share the same base tree. Bounded 0–256 entries with LRU eviction. An upstream mutation cannot change a matrix's prediction, and constructing a fresh matrix after the mutation changes the input SHA. No cross-dataset global cache or disk write.
3. **Vectorize:** NumPy residual matrices and bounded rolling cumulative histograms compute the modal modular correction. The same fully specified candidate completion and SHA tie-breaker as V1 is reused so the original 72 formulas have identical outputs. The NumPy histogram has a worst-case estimated temporary memory gate controlled by max_temp_mib.
4. **Optional Numba JIT:** a @njit(cache=True) integer residual-mode kernel enforces only j<t while fitting. First invocation including compilation and subsequent warmed invocations are measured separately. If Numba is not installed, NumPy backend remains fully functional. The JIT cache stores compiled **code**, never source draws or tickets.
5. **CPU multiprocessing:** spawn-context ProcessPoolExecutor with bounded <=8 workers (also <=available CPUs), contiguous formula chunks, executor.map preserving fixed input order; parent receives the same computed tickets as serial version. Spawn overhead and data-copy overhead are measured. CPU parallelism is not automatically faster for small workloads.
6. **Optional PyTorch CPU/GPU probe:** representative int64 formula arithmetic ((x*3+7)%35) on synthetic tensors, numerical result parity, CPU/NumPy and optional CUDA kernel time plus host->device/device->host transfer cost; torch.cuda.synchronize before timing. This is **NOT** end-to-end formula-engine GPU acceleration; no GPU in CI => GPU_UNVERIFIED and do not recommend a GPU purchase. Real GPU verdict requires benchmarking the full kernel and upload on the actual configured machine.
7. **Broader bounded formula grammar:** from the V1 72 expressions to exactly **312** (LAG1–LAG5, ISSUE, ATOM/DOUBLE/ADD/SUB/MUL, windows 8/16/32/64), preserve all old IDs and semantics. Limited CPU-time staged scan with bounded chunks and histogram allocation; record the tested formula roster and its digest. Time-dependent incomplete scans are experimental and **must not** masquerade as preregistered complete selection.
8. **Out-of-sample demonstration:** strictly split (training >=100 issues, validation 20–150, final 20–300 holdout) and freeze eight formula IDs and equal weights based on development-only front/back expected-overlap gains minus predeclared 0.002 complexity penalty. Holdout is read-only for selection. D2 is not directly optimized in development. Use same-issue deterministic V1 **research NULL** (not official V4.7 NULL), and theoretical D2 chance 15/528 (SSQ) and 10/595 (DLT). Aggregate front/back/D2/full matches, exact paired discordance p (exploratory only) and Wilson interval. Do not log actual/anonymous tickets or issue IDs in GitHub.
9–11. Official primary libraries used: NumPy broadcasting, Numba `@njit`, PyTorch `torch.cuda.is_available()` and `torch.cuda.synchronize()`, Python `concurrent.futures.ProcessPoolExecutor` with `multiprocessing.get_context('spawn')`. See primary URLs below.

## Running synthetic tests and benchmark (Windows, Python 3.11+)

    python -m pip install numpy numba
    python -m unittest discover -s research/supercompute/tests -p test_formula_acceleration.py -v
    python -m research.supercompute.formula_benchmark --game both --history 170 --targets 6 --parallel --gpu

PyTorch is optional and is never installed by CI. If absent the GPU probe reports NOT_INSTALLED / UNVERIFIED. No system CUDA availability is presumed. Results are machine/workload dependent and performance improvements cannot be promised in advance.

## Privacy and security

**GitHub is code-only:** source algorithms, synthetic-only tests, and design docs. The CI benchmark never accesses the checked-in official historical seeds or network. It uploads no artifacts, writes no research ledger, and does not print real/synthetic candidate tickets. Do NOT run this study with real draws inside GitHub Actions. Private actual drawing history, candidate forecasts, original HTTP bytes, freeze/score receipts and offsite evidence must be preserved in user-authorized persistent storage outside the repository. Public CI logs may contain timings and synthetic test labels; these do not establish real predictive success.

Preregistered honest states: `FORMAL_A=0`, `PROSPECTIVE_SCORED=0`, `NO_EDGE`, no autonomous ticket purchase, no model promotion. The performance-run status and actual numbers must be appended to the PR *only after* exact HEAD Windows/Ubuntu CI logs are read. Independent reviewer: NOT_VERIFIED.

## Important open limits

- One Python implementation and NumPy/Numba are compared on a modest synthetic batch; real full-workload RAM/CPU/GPU speedup is unknown until measured on the target owner workstation.
- Increased search width raises multiplicity/overfitting risk. No new official-source authentication, sales-cutoff proof, independent RFC3161 timestamp, persistent reboot recovery, or sealed future scoring is implemented by this PR.
- The 312-formula scan plus 8-expert model is a new research hypothesis; only future presealed cohorts could support a predictive edge claim. No automatic promotion.

## Primary technical references

- NumPy broadcasting: https://numpy.org/doc/stable/user/basics.broadcasting.html
- Numba jit and CPU parallel: https://numba.readthedocs.io/en/stable/user/parallel.html
- PyTorch CUDA availability: https://docs.pytorch.org/docs/stable/generated/torch.cuda.is_available.html
- PyTorch CUDA synchronization: https://docs.pytorch.org/docs/stable/generated/torch.cuda.synchronize.html
- Python ProcessPoolExecutor: https://docs.python.org/3/library/concurrent.futures.html#processpoolexecutor
- Python multiprocessing spawn: https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
