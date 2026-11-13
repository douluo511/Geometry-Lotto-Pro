# SSQ + DLT: CPU Parallel Research Calculator v1

This is a genuine CPU batch calculator, not a supercomputer cluster or GPU setup. It does not promise improved lottery odds, nor does it change formal V4.7, frozen random NULL records, or official sealed forecasts.

Windows / PowerShell (Python 3.11 or newer; repository root):

    python -m unittest discover -s research/supercompute/tests -p "test_supercompute.py" -v
    python -m research.supercompute.engine --game both --backtest 200 --simulate 50000 --workers 2 --out supercompute-output

The separate GitHub Actions workflow provides a manually runnable button with bounded compute inputs; the workflow is initially offered through a feature branch and has to be merged to main for a durable Actions launcher.

## Verified algorithms and interpretation

* SSQ: six front balls from 1..33 and one back ball from 1..16.
* DLT: five front balls from 1..35 and two back balls from 1..12.
* Models: HOT60 frequency and EWMA30 (30-draw half-life). M2 uses the exact combinatorial fair-D2 probability; uniform Monte Carlo remains a simulation utility, not a candidate selector.
* Time-ordered, strictly past-only backtest with a 120-draw minimum training prefix; reports exact full-ticket hits and D2.
* D2 means both of two preselected front numbers appear in the next observed front draw (not a prize level). The theoretical fair-draw chance is k(k-1)/[N(N-1)].
* Exact full-ticket fair-draw probability is 1/[C(N,k)*C(M,b)].
* Monte Carlo checks D2 against uniform simulated draws. Its 5,000-trial block assignment and deterministic SHA256 seeds produce the same hit count independent of worker count (1 through 8 CPU workers); maximum two million simulations per game.
* Report includes raw snapshot SHA256, source, historical as-of issue and date, backtest measures, 95% Wilson intervals, baseline, local CPU runtime, models and trial seed. JSON reports are created without replacing previous reports; GitHub Actions archives a copy for 90 days.
* Data is checked-in historical snapshot, not live verified issuer data. The hypothetical post-snapshot ticket is NOT a confirmed next-issue forecast. Current local snapshot last draws: SSQ 2026-09-20, DLT 2026-09-21.
* Edge is always NO_EDGE, formal_A=0, paid_api_calls=0. Increased trial count does not make random lottery outcomes predictable.

To build a true longitudinal validation loop later, source verification, pre-draw sealing, independent append-only evidence, subsequent official draw checks and out-of-sample statistical tests must all be established. This tool does not claim those tasks are complete.

P0 unattended heartbeat code and tests were consolidated under `research/supercompute/automation/` and `research/supercompute/tests/` without changing the separate P0 ledger branch. Run their tests using:

    python -m unittest discover -s research/supercompute/tests -p 'test_p0_*.py' -v
