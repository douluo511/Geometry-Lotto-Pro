# TDD execution: 河北同字节两个“官方”端点 (2026-10-28)

1. Pin original PR HEAD c1ff2664 and download/re-hash native SSQ failing artifact 12807012956. Confirm distinct request paths, identical raw bodies, and existing parser symptom.
2. Add failing SSQ regression requiring explicit HEBEI_ENDPOINT_BODY_ALIAS for identical homepage+announcement bytes. Preserve raw responses and failure manifests.
3. Add the smallest early guard inside parse_hebei_latest, no parser fallback, no new source approval.
4. Verify against exact-head GitHub Actions on both OS; separately preserve SSQ live-source failure and DLT external release non-admission. Do not claim physical owner-host or outside review.
5. Record RED/GREEN SHA, raw CI links and remaining P0 blockers in sole Issue #468; keep PR #467 Draft and main unmerged.
