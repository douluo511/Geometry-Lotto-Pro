# RED→GREEN: G00/G01 evidence-class report

1. On same existing Draft PR #467 add an offline test with both successful synthetic cross-check and forced date-semantic failure, requiring explicit non-promotion fields in both reports. Record exact-head CI RED.
2. Update only existing `DLT/scripts/real_network_check.py` to add fixed unverified fields after assembling the report; do not alter gate decision, exit status, upstream source parser, or any model/freeze/ledger.
3. Confirm exact HEAD Ubuntu+Windows synthetic CI and inspect original failing native DLT live gate. Require RED→GREEN and no false native promotion.
4. Document SHA and failed preconditions in sole Issue #468; external review remains NOT_VERIFIED.
