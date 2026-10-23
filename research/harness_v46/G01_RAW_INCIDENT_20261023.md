# V4.7 G01 source-incident replay — archived raw HTTP evidence

**Purpose:** diagnose exactly why a previously collected intake is blocked.
This is **not** source admission, date correction, backtesting approval or
evidence of higher SSQ/DLT D2 hit rate.

## Reproduce from the original Actions archive

1. Open GitHub Actions
   [#39930599493](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39930599493).
2. Obtain artifact ID `12491542007`,
   `v47-official-intake-39930599493`, without rewriting its ZIP.
3. Verify the downloaded archive SHA256 equals
   `79fad042d50657e6cfeeaf93ddfa5354a1073433e5378fa8afe6a09358c5f715`.
4. Execute from the repository root:

```sh
python -m research.harness_v46.g01_raw_incident \
  --intake-zip ./v47-official-intake-39930599493.zip \
  > g01-raw-incident-report.json
```

The tool checks the ZIP manifest SHA, uniqueness of all archive member paths,
all declared original raw HTTP file paths and individual SHA256/byte size,
and matching audited evidence counts. It never extracts ZIP members to disk,
never modifies the original raw files and never makes a network request.
A self-consistent archived manifest is **not** independent HTTP origin proof.

## Observations from separately reading the same archived ZIP bytes

- Archive ZIP SHA256: `79fad042d50657e6cfeeaf93ddfa5354a1073433e5378fa8afe6a09358c5f715`
- `intake.json` SHA256: `91f49b273e74f713f2f6f3da90052768df93d56062da841053cb4eba9608a729`
- `intake-audit.json` reports `PASS` on the narrow
  `BYTE_INTEGRITY_ONLY_NOT_SOURCE_AUTHENTICITY` claim:
  **64 declared and saved raw file objects, 64/64 byte hashes and lengths
  matched**, with no undeclared raw member in that original ZIP.
- National DLT `webapi.sporttery.cn` returned **HTTP 567 twice**.
  National SSQ `www.cwl.gov.cn` returned **HTTP 403 once**.
  The response bodies are archived for diagnosis, **not** counted as draws.
- The archived Jiangsu HTML reproduces **2934 distinct issue rows** by
  regex-based diagnostic extraction, not trusted G01 canonical admission.
  All three rows below are in the **same original raw file** SHA256
  `30ab3938992ba14cd15b340d7f684ea9cc1331462eaf00125b559597aca17442`:

| DLT issue | Raw Jiangsu HTML date | Original front numbers | Diagnostic |
| --- | --- | --- | --- |
| 16003 | 2016-01-07 | 04 12 17 22 26 | Not a regular Mon/Wed/Sat draw weekday |
| 16004 | 2016-01-11 | 10 20 23 32 35 | Predecessor of duplicate-date issue |
| 16005 | 2016-01-11 | 06 09 12 15 20 | Repeated date with issue 16004 |

There are **two** observed calendar anomaly events in this preserved source:
`16003/NON_REGULAR_DRAW_WEEKDAY` and
`16005/DRAW_DATE_REPEATED_ACROSS_ISSUES`. No conflicting issue/date was
found *between different archived Jiangsu pagination bodies*, but that is
not cross-publisher verification.

**Do not silently infer or rewrite 16003, 16004, 16005 dates.**
A later resolution needs independent primary-source raw evidence tied to
the exact issue and date, independent historical cross-check, and an
explicit versioned exception protocol with provenance. Replacing a date
in this saved archive would destroy the forensic evidence.

SSQ remains `HISTORY_CROSSCHECK_LIMITED`; DLT remains
`SOURCE_FETCH_PARTIAL`. The bundle states
`official_target_admission=BLOCKED`; local timestamps are not trusted;
a full verified official issue calendar and cutoff are not established.
The DLT 69/2880 negative-control anomaly and all future D2 testing gates
remain independent.

## Admission verdict

`ENGINEERING_PASS=NOT_YET` at whole-system level;
`RESEARCH_VALID=NOT_YET`; `D2_EDGE_CONFIRMED=NO`;
`formal_A=0`; `NO_EDGE`. Even a successful rerun of this ZIP verifier
cannot resolve G01 by itself.
