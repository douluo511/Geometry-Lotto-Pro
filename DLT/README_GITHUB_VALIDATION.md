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

The workflow to run is **Windows build and exact-package acceptance**. Download the single Actions artifact only when the job is green and `acceptance.json` contains `final_release_gate: PASS`.
