# G01 SSQ+DLT official-source quarantine — raw-source forensics, 2026-10-23

**Evidence class: SHADOW diagnostics, not official-history admission.**
No source row, frozen prediction, seed, schedule or model was rewritten.

## Immutable observed inputs

- Live one-shot run: https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/39930599493
- GitHub Actions artifact ID: `12491542007`, archived name `v47-official-intake-39930599493`.
- Intake audit: `status=PASS`, 64/64 referenced raw records SHA-256/size/path validated; 3 diagnostic non-HTTP-200 bodies. This is **byte preservation only**, not authenticated official origin.
- SHA-256 of audit's intake manifest: `91f49b273e74f713f2f6f3da90052768df93d56062da841053cb4eba9608a729`.
- Source page: `https://api.js-lottery.com/Lottery/_ListData?itemType=lo&pageIndex=17&pageSize=100`
- Preserved raw exact page path: `raw/DLT/jiangsu/30ab3938992ba14cd15b340d7f684ea9cc1331462eaf00125b559597aca17442.bin`
- Raw page SHA-256: `30ab3938992ba14cd15b340d7f684ea9cc1331462eaf00125b559597aca17442`.
- Source response: HTTP 200, `text/html; charset=utf-8`, decoded by the pinned parser. The rows below are copied from preserved raw HTML (not corrected data).

| Issue | Original source date cell | Original balls | Independent historical date evidence |
|---|---|---|---|
| DLT 16003 | 2016-01-07 | 04 12 17 22 26 + 06 07 | 2016-01-06 |
| DLT 16004 | 2016-01-11 | 10 20 23 32 35 + 09 10 | 2016-01-09 |
| DLT 16005 | 2016-01-11 | 06 09 12 15 20 + 08 11 | 2016-01-11 |

Independent cross-references (public pages are not themselves archived into the SHA-verified intake bundle):

1. Jiangsu Sports Lottery's own 2016 provincial jackpot table: https://www.js-lottery.com/djfb/cms/post-70227.html lists DLT 16003 on Jan 6 and 16005 on Jan 11.
2. China General Administration of Sport historical DLT 16004 news: https://www.sport.gov.cn/n20001280/n20745751/n20767297/c21206580/content.html states the draw occurred Jan 9.
3. Inner Mongolia Sports Lottery reprint from China Sports Lottery Center: https://www.nmtc.com.cn/zjgs/16592.html states 16003 occurred Jan 6, with same balls.

**Finding:** The date cells for 16003 and 16004 in the preserved Jiangsu API HTML are inconsistent with separately published historical draw dates. 16004 and 16005 share a source date even though distinct draws took place on two different dates. There is no basis to silently map the first date to its previous calendar day or to automatically treat every HTML date as a publication timestamp. The cause (legacy backend data entry versus column semantics) has **not** been independently established. The current strict date-calendar gate correctly quarantines these rows. No model may train on this unapproved history.

## National Sports Lottery: HTTP 567, not valid history

- Both official-site request header variants targeted:
  `https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry?gameNo=85&provinceId=0&pageSize=100&isVerify=1&pageNo=1`.
- Both returned HTTP **567**, with HTML bodies of **7,351 bytes** rather than valid accepted history JSON.
- Preserved body SHA-256:
  - `840db80ca72f3c14c4a5f1208afca06333dc821e18423d70a5d91a13b737c199`
  - `06f47587f581fc92204eee525910804ae27cc0c138d3d60570a9e5003fd08e9d`
- Plain rendered text includes "567" and a numeric request identifier; the exact bodies remain archived for diagnostics. A WAF or anti-automation restriction is plausible, **not proven** from these bytes. Never treat an HTML error body as draw data, and do not bypass access controls.

## Audit boundary and next permitted actions

1. Escalate exact issue/date conflict to official-source maintainers; request an authenticated, machine-readable history with explicit distinction between draw date and publication date. Retain original response bytes unchanged.
2. Independently acquire a second national/provincial full history with >120 matching issues, signed/archived provenance and verified official target calendar. The two existing Jiangsu/Gansu sources cannot substitute for the missing national primary under the present V4.7 contract.
3. On the national 567 response, use official documented access channels or permissioned access only. Investigate endpoint policy; do not rotate fingerprints to circumvent site restrictions or inject guessed records.
4. Repeat source intake into a NEW evidence bundle; audit raw SHA, parser identity, every issue/date/balls disagreement and 120+ overlaps before raising any gate.

**Result:** G00/G01=BLOCKED, official target admission BLOCKED, independent pre-sale cutoff BLOCKED, formal_A=0, RESEARCH_VALID=NOT_YET, D2_EDGE_CONFIRMED=NO, NO_EDGE.
