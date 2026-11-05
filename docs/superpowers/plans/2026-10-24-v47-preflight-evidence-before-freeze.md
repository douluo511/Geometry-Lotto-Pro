# Superpowers TDD execution: Issue #468 per-game preflight

1. Verify existing Draft PR #467 exact HEAD and prior source/CI; do not use main or create another Harness/PR.
2. Add adversarial test-only RED cases for unknown outcome, unknown receipt, invalid evidence directory, and SSQ/DLT namespace isolation. Preserve original code.
3. Execute GitHub Actions automatically on exact RED SHA; retain Ubuntu and Windows original counts/failure logs.
4. Inside `advance_game_workspace`'s existing SQLite transaction, BEFORE any game card insert, read registered per-game issues and validate the matching game's two evidence folders/JSON names. Reuse existing GateError semantics; keep post-write existing checks. Avoid moving the source admission, freeze timestamp or changing six arms.
5. Run full exact-HEAD CI on both OS, inspect original checkout SHAs, red-to-green cases and entire regression. Compare prior HEAD to final; review against unknown-file injection, per-game isolation and concurrent writer issues.
6. Report original SHA and URLs in Issue #468. Do not promote ENGINEERING_PASS, RESEARCH_VALID, D2_EDGE_CONFIRMED, `formal_A` or NO_EDGE.
