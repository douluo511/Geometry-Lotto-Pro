# Copy-paste handoff: test2 official data center

Associated RUN_ID: `V46-R1-20261022T015053-0400-7F3A9C`

You are the only official-data verification role. Do not produce lottery predictions. Your job is not complete until both lotteries have machine-readable snapshots and independently reproducible SHA256 values.

## SSQ
- Officially verify the latest published issue, next legal undrawn issue, date, actual sales cutoff, draw time and holiday/exception notices.
- Official Shanghai Welfare Lottery history page currently exposes the latest 100 rows: https://www.swlc.net.cn/lottery/ssq.html?limit=100&view=previous . Latest observed result is 2026120, 2026-10-20, red 13 14 16 18 20 31, blue 03.
- Retrieve at least 120 earlier draws from official source(s), preserve raw bytes, normalize the 6 red + 1 blue values, and cross-check with a second official welfare-lottery source.
- Current tentative next issue is 2026121 on 2026-10-22, draw schedule 21:15 Asia/Shanghai; this is NOT locked until you verify the issue and actual sales cutoff from an authoritative current source.

## DLT
- Official Gansu history page: https://www.gstc.org.cn/wanfa/dlt_history . Latest observed result is 26120, 2026-10-21, front 01 06 10 15 32, back 03 04. This page currently exposes 20 rows.
- Official sales/draw time adjustment notice: https://m.lottery.gov.cn/xxgk/tzggz/20221220/10027143.html ; from 2023-01-01, sales cutoff is 21:00 and draw time 21:25 on draw day.
- Retrieve at least 120 earlier draws from official source(s), preserve raw bytes, normalize 5 front + 2 back values, and cross-check with a second official source.
- Current tentative next issue is 26121 on 2026-10-24 based on the schedule; do NOT lock until an authoritative current source confirms it and any holiday/special schedule is checked.

## Deliverables for EACH lottery
1. Source URLs, capture timestamp with timezone, official publication timestamps if available, and original source bytes/file.
2. Structured JSON/CSV with >=120 earlier draws only; unique issue, strict chronology, valid number ranges, no target-result leakage.
3. Calculate SHA256 over the exact frozen snapshot file bytes. Include the command/method and verify the hash independently.
4. Report duplicate/missing issues, source conflicts, and cutoff/time-lock checks.
5. Explicit G00 and G01 PASS/BLOCKED. Missing authoritative sales cutoff, target confirmation, raw data or hash means BLOCKED.
6. Return actual files/commit IDs and hashes to test1. Do not guess numbers, fabricate timestamps, or issue predictions.
