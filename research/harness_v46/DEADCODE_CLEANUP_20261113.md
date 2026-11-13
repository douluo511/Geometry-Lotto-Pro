# V4.7 model-adjacent dead-code cleanup — 2026-11-13

Status: isolated **draft** research branch, not a formal production model
promotion or merge into `main`.

## Static inventory

The conservative repository-wide Python AST scan parsed 362 Python files,
finding 232 module-level functions in `research/harness_v46`. Only two
private functions had no Python static read, call, or direct import reference:

- `desktop.py::_bytes`: one-line byte-coercion helper, never called in the
  desktop controller or the checked-in project.
- `statistics.py::_pmf`: unreferenced scalar binomial point-mass helper.
  The actual production-facing exact-tail and confidence-interval calculations
  use `_log_tail_from_boundary` / `exact_binomial_upper_tail` instead.

Both definitions were removed with no change to their callers, model scoring
formulas, selectors, registered seeds or source data.

## Important protected boundaries

The audit is static, not a proof that no external dynamic import references
these private helpers. It inspected Python sources (including tests); external
consumer calls outside the repository may exist. No other method is
automatically eligible for deletion.

**Do not remove** `core.py`, `model_versions`, the pinned Random NULL seed,
data validation, frozen prediction code, source fetch/receipt gates, the
existing historical evidence, `SSQ/` and `DLT/` application code, or the
Windows P0 automation. Low call frequency is not dead code.

`core.py` is byte-for-byte unchanged (original model SHA256
`f780a577d514eb36b4f3bcc4ecdecc92993ffb5fc96d03210cdf61078ff52941`).
Removing a private function from `statistics.py` **does change that file's
SHA256** and therefore the V4.7 orchestration hash, because
`convergence.ORCHESTRATION_SOURCE_FILES` includes `statistics.py`.
The change must receive a new source identity in any future research run.
Do not relabel old manifests or pretend existing immutable seals had the
updated hash. The historical `model_versions/scorecard_*.source` artifacts
remain untouched and should be verified by their frozen-replay tests.

## Review acceptance

1. Audit static references and show no remaining unreferenced functions
   introduced by this cleanup.
2. Run full `research/harness_v46/tests` synthetic suite.
3. Run both `SSQ/tests` and `DLT/tests` offline-source-app suites on
   Ubuntu and Windows for the exact PR head commit where available.
4. Confirm existing frozen-version source replay and fixed Random NULL
   regression tests pass; no live official-source success or winning-number
   advantage should be inferred.
5. Keep PR as draft until independent review of source-hash migration and
   test outcomes. **No mainline merge or model re-registration here.**
