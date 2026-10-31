# DLT application parser — Jiangsu date semantics (2026-10-29)

Scope: the existing Draft PR #467 and DLT application `glp.sources._parse_jiangsu_html`. No separate Harness/PR, model, Random NULL seed, eight official slots, SQLite ledger or preserved freeze changes.

## Original observed P0
The currently deployed application path treats the first date cell of a Jiangsu listing as `Draw.draw_date`, even when the listing labels this column 发布日期. The live native gate at run 40784762821 stopped on independent issue 26123 disagreement. This disagreement is not conclusively attributed to the date alone; the original external source claim remains unauthenticated. The same risk was already identified and mitigated in the research Harness by the date semantics helper; it was not wired to the application parser.

## Contract and bounded fix
Copy the existing, reviewed in-repository `_JiangsuDateTables` / `_verify_jiangsu_draw_date_columns` semantic check from `research/harness_v46/official_intake.py`, only adapting `GateError` to application-local `SourceError`. Check raw decoded HTML *before* HTML entity expansion and existing application parsing. Each candidate must have a prior explicit draw-date / issue / numbers header in its own structurally valid table. Publication, unknown, decoy, hidden, escaped and malformed contexts fail closed. The legacy numeric parser and all post-parse guards remain unchanged.

This is schema authentication only, NOT independent source truth, corroborated date, authoritative target/cutoff, or permission to produce a formal forecast. Known publication-only Jiangsu pages remain blocked, not shifted to prior draw days. No sources are waived to obtain a green native gate.

## Evidence / unverified gates
RED regression source commit `9ef65ce29cf3895e5f544cfafac2a7409f38c6f8`; corrective source commit `d389ead95405dc7b2743feb9f59ba96d412988ff`. Exact-head CI outcome, Windows owner-host two unattended triggers/cold boot, G00/G01, approved predraw TSA, independent review, and prospective paired D2 evidence must all be checked separately before a PASS assertion.

Remain `ENGINEERING_PASS=NOT_YET`, `RESEARCH_VALID=NOT_YET`, `D2_EDGE_CONFIRMED=NO`, `formal_A=0`, `NO_EDGE`.
