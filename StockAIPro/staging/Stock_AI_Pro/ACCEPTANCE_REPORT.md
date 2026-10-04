# Stock AI Pro 4.3 — Acceptance Report

## Delivery rule

Only one user-facing ZIP is allowed. Source regression must pass; an internal candidate is then built and extracted to a new empty directory for complete re-testing. Only after candidate acceptance is the final ZIP built. The final ZIP itself is then extracted to a second new empty directory and exact-package tested without any later mutation.

## Source/engineering acceptance — PASS

- Production model stack: Ridge + HistGradientBoosting + ExtraTrees.
- Past-only validation Rank-IC weighting with 20% shrinkage toward equal weights.
- Production/backtest model parity: walk-forward uses the same three-model training, horizon embargo and prior validation weighting logic.
- Dynamic cost, PIT valuation, Net Alpha, TRADE/WATCH/NO_TRADE, capacity, feature drift, prediction freeze/hash chain and R&D evidence remain enforced.
- R&D adds `extra_trees_only`; `auto_promote=false` remains mandatory.
- Config Schema deliberately remains 6. New 4.3 model parameters are backward-compatible defaults; a dedicated gate proves 4.3 and rollback 4.2 use the same schema, avoiding a rollback dead-end.
- Updater 1.2 adds anti-downgrade/reinstall, download cap, disk-space preflight, final HTTPS redirect validation and Schema-2 internal file-manifest verification, in addition to Ed25519, SHA-256, staging, ZIP traversal/symlink/bomb defenses, journal and rollback.
- Launcher pending-version UI failure is fault-injected and verified to roll back to the prior version and blacklist the failed release id.
- Deterministic release-build test proves identical source trees produce byte-identical ZIP archives.
- Distribution and active-version manifests are bidirectional: listed files must match hashes, and every immutable shipped file must also be listed.

## Candidate history

The first internal 4.3 candidate **FAILED** fresh-unzip acceptance because the deterministic builder excluded every nested `.zip`, including the Updater security fixture. That candidate was rejected and not delivered. The builder and manifest completeness rules were fixed so legitimate nested fixture archives are included and controlled.

A new internal candidate was then built. From its freshly extracted copy, all root acceptance tests, all active 4.3 tests, both distribution/core manifests, Updater security/rollback, launcher rollback, schema rollback compatibility, 4.3 Health Check, and 4.2 rollback-version manifest/Health Check passed. Candidate verdict: **PASS**.

## Evidence boundary

Engineering acceptance proves defined software contracts and failure handling; it does not prove future A-share alpha. Scores are not objective probabilities. Historical ST/suspension reconstruction, limit-order queueing and real execution impact remain constrained by available public data.

## Target-environment boundary

The build environment is Linux. It cannot truthfully execute the user's Windows `cmd.exe`, PowerShell/Task Scheduler, fresh Windows online dependency installation, or the user's live AkShare network path. `WINDOWS_FIRST_RUN_ACCEPTANCE.bat` performs those target-machine checks. They are not marked PASS here.

## Exact final package rule

After this report and the top-level Manifest are frozen, the final archive is built. Its exact bytes are then CRC-tested, extracted into a new empty directory, and the complete root + 4.3 + rollback health suite is run again. The final archive is never mutated after that check; its final SHA-256 is reported alongside the download link.
