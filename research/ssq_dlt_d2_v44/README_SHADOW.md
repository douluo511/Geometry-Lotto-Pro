# Saved-byte SHADOW snapshot import

This is a separate archival component stacked on draft PR #409, related to #408.
It leaves the existing prediction ledger, status runner, SSQ/DLT applications,
historical evidence and original ZIPs unchanged. It never runs archive Python,
BAT or EXE files, contacts a source/TSA, registers candidates, infers a next issue,
or creates formal training samples.

`shadow_snapshot.verify_snapshot_archive` requires independently reviewed SHA256
pins for both the whole ZIP and the exact canonical snapshot manifest. It bounds
archive/member sizes, refuses unsafe Windows paths, duplicate paths/JSON keys,
symlinks and encryption, checks the outer manifest and exact committed copies,
and independently reconstructs every mapped draw from the bound central JSON.
The sealed mapper is inert evidence, not imported code. Recorded absolute source
paths are preserved as metadata and never followed.

The reviewed handoff is `SSQ_DLT_V44_Data_Snapshot_v1.zip`:

- ZIP SHA256: `1eb4242ef88a56e19cc32ecf2f15c0a7c683485830e7bb8baa84d5601ccf1ea9`
- Manifest SHA256: `979969feea1a31e26b9c5b8a54843c08e0be82e9b85211cc35bb5c9f3f182b97`
- 16 bound files: history, row mapping, source manifest, sealed mapper and 12 raw JSON files.
- 1002 reconstructed rows: SSQ 501 (2023071–2026118), DLT 501 (23069–26117).

These ranges describe the saved archive. They are not a current draw schedule or
an expected-issue registration. Additional historical source labels are retained;
only raw IDs explicitly bound in row matches are reconstructed. This does not
establish independent two-source agreement or publisher authentication.

Use an explicit, separate database path and a new receipt path. All paths must be
absolute. Create the receipt's parent directory first, then run from the repository
root with the tested Python interpreter (PowerShell example; replace local paths):

```powershell
python -m research.ssq_dlt_d2_v44.shadow_snapshot `
  --archive 'C:\evidence\SSQ_DLT_V44_Data_Snapshot_v1.zip' `
  --archive-sha256 1eb4242ef88a56e19cc32ecf2f15c0a7c683485830e7bb8baa84d5601ccf1ea9 `
  --manifest-sha256 979969feea1a31e26b9c5b8a54843c08e0be82e9b85211cc35bb5c9f3f182b97 `
  --db 'C:\research\shadow-archive.sqlite3' `
  --output 'C:\research\import-receipt-01.json'
```

Every archive contract passes before opening the database. An exact retry with a
new receipt path returns `appended=false`; a conflicting archive for the same
snapshot identity fails. The SQLite archive has its own application ID/schema,
WAL/FULL transactions and immutable snapshot/artifact/row tables, including SQL
REPLACE guards. Foreign databases are refused before WAL or schema changes.
Initialization publishes a fully checkpointed temporary database with an atomic,
non-replacing hard link; the filesystem must support this operation. Every open
first checks the main-file identity and schema without journal recovery. A
transient concurrent checkpoint view is retried for at most two seconds, then
fails closed. A foreign database never receives a repair or fallback import.
Read APIs require an explicit snapshot SHA, recheck all stored byte/hash/row
bindings, and add `SHADOW_ARCHIVE_ONLY` labels. There is no newest-snapshot fallback.
Triggers protect against accidental SQL writes; an owner replacing the entire
file is outside this integrity boundary. Keep externally pinned originals.

All 1002 `available_at` values and their evidence/upper bounds stay null. Draw
dates, capture clocks, file modification times and the new source timestamp are
never substituted. The importer reports TSA verification as NOT_RUN: the separate
offline handoff review verifies the existing token's CMS/chain/nonce/imprint,
but missing signed Accuracy blocks the strict time upper bound. That token does
not prove historical row publication time or pre-draw candidate sealing.

The fixed outcome is `R2=BLOCKED`, `formal_A=0`, `NO_EDGE`, formal training BLOCKED,
repository independence FAIL and Final Gate FAIL. Actual 01/04 trust authority,
admitted candidate timestamp/deadline policy, genuine eight producers, original
formal twelve definitions and independent prospective validation remain absent.
Boot/Scheduler/reboot acceptance and missing original V4.0 acceptance are not
satisfied by this import. This is a research component, not a FINAL release.

Run the full applicable local suite with:

```powershell
python -m research.ssq_dlt_d2_v44.acceptance --output 'C:\research\new-acceptance-folder'
```

The new snapshot/store tests use independent synthetic fixtures and failure
injection. Producer support-package 40/109 tests are separate scopes and must
not be added to this suite's count. Current-run evidence belongs in a new receipt;
previous PASS files remain historical evidence for their recorded source bytes.
