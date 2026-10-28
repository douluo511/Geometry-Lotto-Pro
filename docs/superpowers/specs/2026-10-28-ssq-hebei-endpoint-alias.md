# V4.7 SSQ 河北首页/公告响应字节别名审计 (2026-10-28)

Original native SSQ run 40668838185, job 122750147731, failure artifact 12807012956, manifest failure ID 53f47da999cc49f983a61e11. Distinct requested official paths `https://www.yzfcw.com/` and `https://www.yzfcw.com/game/ssqAnnounce` both returned HTTP 200 with **identical 50,237 bytes**, SHA256 `759b69033cbd3fdee6212b6db6fdb1ef65a0456063d0ea32c2f77f7d54b4098a`. Hashes were independently recomputed on the exported raw bytes. Existing parser rejected a missing draw panel; national official URL returned HTTP 403, Shanghai history provided 2081 rows through 2026123, leaving quorum BLOCKED.

## Minimal hardening contract
`SSQ/SSQ/glp/sources.py::parse_hebei_latest` must reject two **identical raw bodies** with `HEBEI_ENDPOINT_BODY_ALIAS` before parsing or considering them internal home+announcement consensus. No URL/redirect inference is made; equal-body detection is not sufficient to authenticate distinct bodies. All existing strict issue/date/balls/source freshness/cross-source/ledger gates remain. Do not relax official quorum, backdate old observations, or treat SHADOW as formal A. No model, Random NULL, seed, eight slots, freeze or formal ledger modifications.

Acceptance: negative fixture RED on original code, GREEN after minimum guard; existing SSQ and full V4.7 synthetic regressions; native source success still unproven and must remain BLOCKED while external sources fail. Independent external review remains NOT_VERIFIED.
