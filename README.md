# Geometry Lotto Pro — SSQ + DLT research and automation

This repository contains two lottery applications and an independent research toolkit.

- `SSQ/` and `DLT/`: game-specific implementations and acceptance tests.
- `research/supercompute/`: offline CPU Monte Carlo simulation, historical walk-forward scoring, reproducible evidence receipts, and P0 unattended-schedule verification.
- `.github/workflows/`: GitHub Actions for these two lotteries, their unattended schedule audits, and the manual research calculator.

Validate the consolidated research tools from the repository root:

    python -m unittest discover -s research/supercompute/tests -p 'test_*.py' -v

See `research/supercompute/README.md` and `research/supercompute/automation/README.md` for detailed commands and limitations.

**Research limits:** Snapshots are not live official draws. Neither the Monte Carlo simulator nor historical model scores show a proven predictive advantage. Formal V4.7 selectors and historical forecast evidence remain separate from this research-only code.
