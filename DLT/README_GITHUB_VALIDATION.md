# Geometry Lotto Pro DLT — Windows native validation repo

This repository is intentionally build-first and evidence-first. It rebuilds the EXE natively on GitHub's `windows-latest` runner from the extracted v2.1.2 source instead of patching a previous PyInstaller archive.

The workflow blocks release unless the **same EXE bytes** pass:

- deterministic code self-test;
- native Win32 GUI creation and four-entry binding;
- real dual-source network update;
- predict / update / repair / audit execution;
- complete scientific protocol execution;
- SHA-256 equality between the built artifact and the acceptance report;
- default GUI process smoke test.

`NO_EDGE / NULL_DAN` is not a release failure. A network failure, GUI failure, missing check, exception, or non-zero process exit is a hard failure.

The workflow is **Windows build and exact-package acceptance**. The executable's
`acceptance.json` describes narrow service checks only: `exact_acceptance_gate`
may be PASS while `final_release_gate` must remain PENDING. Only the external,
evidence-derived `final_gate.json` can judge the complete release.

The diagnostic artifact is explicitly **CANDIDATE / NOT FINAL**. Its existence,
window liveness, or screenshot changes do not establish backend completion.
Independent updater, complete business/no-shell evidence, exact GUI backend
effects, and independent repository remain required. Missing evidence blocks
delivery; no percentages or full-product PASS are inferred from test counts.

See `DELIVERY_ARCHITECTURE.md` for the current interfaces and remaining gaps.
