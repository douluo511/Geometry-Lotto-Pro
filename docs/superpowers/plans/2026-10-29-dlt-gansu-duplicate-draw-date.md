# RED→GREEN execution plan: existing DLT application parser

1. On exact existing Draft PR #467 HEAD add a focused synthetic two-issue same-date fixture and assert fail-closed source error. Capture exact-head RED CI or local failure.
2. Make a minimal change in `DLT/src/glp/sources.py::_parse_gansu_history`: reject same draw date across different DLT issues before `Draw` sorting and source receipt creation. Do not change any forecasts, seed, formal arms, historical ledgers, or source quorum.
3. Verify the focused regression and original DLT suite on Windows+Ubuntu exact-HEAD Actions. Keep real-network gate blocked if live source remains contradictory.
4. Report original SHA, RED and GREEN jobs, remaining native failures, and external-review status. Do not merge or release.