# P0: Gansu DLT history duplicate draw-date quarantine

## Observed live counterexample (2026-10-29)
- Jiangsu DLT 26123 official announcement identifies draw date 2026-10-28: https://api.js-lottery.com/cms/post-148153.html
- Gansu official history https://www.gstc.org.cn/wanfa/dlt_history lists both 26123 and 26122 as draw date 2026-10-26, despite distinct issues. This is an official-source contradiction, not a correction authority.

## Contract
Reject any two distinct DLT issues parsed from the same Gansu HTML history response if they claim the same draw date. Check original candidate rows before sorting and before generating a source PASS receipt. Fail closed with `GANSU_DUPLICATE_DRAW_DATE`, preserving source URL and issue identifiers in failure diagnostics. Do not reinterpret either date, edit old rows, bypass independent quorum, or promote SHADOW evidence.

## Boundary
This is a local structural source guard, not a resolution of the true date, national 403/567, 120+ authenticated histories, authorized cutoff, TSA, or Windows host. A malformed official source remains blocked; future correction requires original authenticated source evidence.