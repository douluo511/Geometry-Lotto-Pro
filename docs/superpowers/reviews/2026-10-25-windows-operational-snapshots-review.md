# Independent incremental review: Windows operational snapshots

Base: f59565905fe758d00f78ac3bbac91125247a3116. Scope: existing invoke_closed_loop.ps1, new Windows caller tests, README and this increment's spec/plan; no new Harness or PR. Separate agent host_forward_review used fresh context, read-only files, and pure in-memory PowerShell expressions. This is agent code review, not human formal acceptance or real-host certification.

## Findings and disposition

1. Important: candidate used the truthiness of new snapshot values, silently ignoring empty/null declarations outside operational mode. Final script tests PSObject.Properties existence, rejecting every declared new field in non-operational mode before log/Python. Actual pure-expression checks found false-mode empty SSQ and null DLT reject; absent fields do not reject; operational null remains omitted when forwarding. No security policy was changed and the complete handler was not executed through another route.
2. Important: retry originally compared prediction counts and old operational-event prefix only. Final test compares full original game_runs/game_predictions SQL rows (including frozen snapshot/card payloads, hashes and times), and second tick must add0 issues. Each bad-mode subcase has its own workspace/log. These two issues are resolved; final incremental review found no remaining Critical/Important in the reviewed scope.

Final reviewed SHA256: invoke_closed_loop.ps1 `9f22505c36c406b1b35609d1ff7b380615ebbbdf563d30cd5a97e37b2c9db333`; test_windows_operational_snapshots.py `e189f801a15e449a4e1c90d1e9b6b87d0300dceedf6618bcd2a9b7c02968ca1a`. Python closed_loop.py, official_intake.py, core.py and windows_closed_loop_tasks.ps1 are byte-identical to base. New paths are forwarded as separate native arguments to the existing strict CLI. Per-worker120-second bound allocates four source/replay budgets under the existing600-second task setting with headroom, not a guaranteed whole-tick hard deadline.

## TDD and test limits

Test-only9a018bd1aff5a9cfe5d5c5fdaa33a9dee0d6b5a5 CI40173412048: exact checkout/expected SHA matched; Windows455 tests,5 failures/254.551s; Ubuntu455,skip12,OK/121.677s. The initial helper incorrectly queried a lottery column directly from game_predictions and has been corrected to its actual game_runs join before any successful test claim. The initial bad-mode subcases shared paths, so one RED assertion was cascading side-effect evidence; stronger cases now isolate paths.

Strengthened test-onlyd746bca9a542787bdc922f6380cb85743b1599c9 CI40188611942: exact SHA matched; Windows455,6 failures/252.115s, including genuine empty/null non-operational cases; Ubuntu455,skip12,OK/115.664s. These are product RED results from the real Windows caller, distinct from this tool host's disabled default script entrypoint.

A local pre-review-fix full candidate ran455/397.624s and FAILED5, all new default-PowerShell script-policy failures; the old451 reported no failure/error in that run. Original prior local5fail+2error is retained as a historical environment checkpoint, not silently overwritten or presented as this run. Final focused local call also remains policy-blocked; no execution-policy override was added to new tests, no security policy changed, and no successful local-host claim follows. Final exact-SHA complete Windows/Ubuntu CI must be collected separately after this reviewed increment is committed.

The reviewer did not run complete Windows -File→Python→ledger, independently retrieve remote CI, authenticate sources/target/cutoff/TSA, install a task or prove cold boot. Existing actual ticks and old forecasts remain untouched. ENGINEERING_PASS=NOT_YET; RESEARCH_VALID=NOT_YET; D2_EDGE_CONFIRMED=NO; formal_A=0; NO_EDGE.

