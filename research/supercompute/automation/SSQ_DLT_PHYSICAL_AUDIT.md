# SSQ + DLT physical draw evidence — independent research (draft)

Both games use the same **create-only evidence contract**, not the same
physical observation capability. This is a research branch and has no
formal V4.7 influence. It does not predict a future ticket or prove an edge.

| Field | SSQ (Shanghai Welfare Lottery history) | DLT (Guangdong Sports Lottery detail) |
| --- | --- | --- |
| Official source | https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous | https://www.gdlottery.cn/f_html/kjgg/P085_26105.html |
| Issue identifier | 7 digits | 5 digits |
| Draw date | Published in the history row | Explicit 开奖日期 in announcement |
| Sorted winning balls | Verified 6 red + 1 blue | Verified 5 front + 2 back |
| True physical exit order | **UNKNOWN / null** | Parsed when the source explicitly contains it |
| Ball-set identifier | **UNKNOWN / null** | Parsed when source explicitly contains it |
| Original public HTML bytes | SHA-256 keyed and archived | SHA-256 keyed and archived |
| New attempt evidence | Immutable, including non-200 and network failures | Immutable, including non-200 and network failures |
| Formal A / reported predictive edge | 0 / NO_EDGE | 0 / NO_EDGE |

### SSQ verification

From repository root:

\`\`\`bash
python -m unittest discover -s research/supercompute/tests -p test_ssq_physical_source.py -v
python -m research.supercompute.automation.ssq_physical_source --issue 2026130 --ledger ./local_ssq_evidence
python -m research.supercompute.automation.ssq_physical_source --verify --ledger ./local_ssq_evidence
\`\`\`

### DLT verification

\`\`\`bash
python -m unittest discover -s research/supercompute/tests -p test_dlt_physical_source.py -v
python -m research.supercompute.automation.dlt_physical_source --issue 26105 --ledger ./local_dlt_evidence
python -m research.supercompute.automation.dlt_physical_source --verify --ledger ./local_dlt_evidence
\`\`\`

Use separate, excluded local evidence locations. Do not point both collectors
at the same \`--ledger\`. Successful requests produce \`raw/<sha256>.bin\`,
\`draws/<issue>.json\`, and append-only \`attempts/<issue>/*.json\`.
Failed attempts produce receipts without fabricated draws. The official
history table may drop older SSQ issues (50-issue window) and must fail closed.

### CI / operational acceptance

- \`ssq-physical-observation.yml\`: offline synthetic test and a historical
  public-source probe on PR/push, with archived original bytes or blocker;
  manual explicit issue input after the workflow exists on default branch.
- \`dlt-physical-observation.yml\`: same approach for the DLT detail page.
- A CI **failure in the real issuer probe** means source capture has NOT
  passed. Offline tests can still pass; the full gate must remain red.
- GitHub Actions temporary artifacts have finite retention, and their timestamps
  are not trusted independent predraw seals.
- This stage is **NOT** unattended issue discovery, scheduled ingestion,
  immutable durable external publication, independent dual-issuer corroboration,
  group bias modeling or prospective predictive evaluation.
- No changes to existing formal selectors, frozen ledger, fixed Random NULL,
  P0 scheduler, other active draft PRs, or default main branch.

**Methodological constraint:** The sorting of winning red balls does not
reveal the actual exit sequence. Missing physical fields are missing, not zero
and not a random guess. Never use a ball group learned *after* the draw as a
pre-sale prediction feature; marginalize unknown states in prospective testing.

No wagers or paid services are executed. Formal A=0. NO_EDGE.
