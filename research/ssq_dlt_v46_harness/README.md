# SSQ＋DLT V4.6 REA＋Harness — research prototype

This is a **runnable, synthetic-smoke-tested-by-CI-if-successful, research-only** harness
built beside the existing V4.5 and LangGraph components. It does **not** automatically
control, read, or send messages among ten ChatGPT conversations. Humans can paste
the role handshake; automation requires an independently deployed orchestrator.

## Mapping ten existing chats

| Chat | Role | Scope |
|---|---|---|
| test1 | 00 CONTROL | Authorization, orchestration, final decisions |
| test2 | 01 OFFICIAL DATA | Original issue/timing/source verification |
| test3 | 02 HOT60 | Fixed 60-draw research producer |
| test4 | 03 EWMA | Fixed half-life research producer |
| test5 | 04 SHRINKMIX | Fixed shrinkage research producer |
| test6 | 05 PAIRWISE-D2 | Pairwise research producer |
| test7 | 06 STABILITY CHALLENGER | **Unregistered exploratory mechanism, cannot compete officially** |
| test8 | 07 RANDOM NULL | Fixed seeded random control |
| test9 | 08 INDEPENDENT AUDIT | Read-only scoring and evidentiary review |
| test10 | 09 ENGINEERING | CI, recovery, deployment, P0 tests |

### Common chat handshake to paste before the role assignment

> You are an SSQ＋DLT V4.6 REA＋Harness research participant. Your role is
> defined by your test-chat mapping above. Do not pretend you can read other
> ChatGPT chats or access GitHub without a real connected tool. Use only the
> identical, official-source-reconciled as-of snapshot furnished by role 01.
> Before outcomes, output your version, source SHA256, ordered 1–5 front-zone
> candidates, unique prefix D2, legal full single ticket, seed, and submission
> time. Refuse unknown/future-data input; never replace a prediction after
> an outcome. Your reply is SHADOW unless an independent evidence system proves
> valid prior external TSA and formal admission. Keep V4.5 formal identities
> M04, M05-1..5, M06, M07 untouched. Report missing receipts as BLOCKED.
> Do not claim a higher hit rate or automatic lottery purchase.

### Machine contract

Run at repository root using Python 3.11+ (no new dependency required for these commands):

```sh
python -m research.ssq_dlt_v46_harness roles
python -m research.ssq_dlt_v46_harness smoke
python -m unittest discover -s research/ssq_dlt_v46_harness/tests -v
```

`smoke` generates **fabricated synthetic histories and fabricated outcomes** to
exercise deterministic SSQ and DLT six-stream outputs and research scoring.
These are **not** current draw predictions or evidence for D2.

For a caller-controlled SHADOW file, supply a JSON snapshot:

```json
{
  "asof": "2026-10-21T04:00:00Z",
  "targets": {
    "SSQ": {"issue": "00066", "draw_at": "2026-12-12T12:00:00Z"},
    "DLT": {"issue": "00066", "draw_at": "2026-12-12T12:00:00Z"}
  },
  "history": {
    "SSQ": [{"game": "SSQ", "issue": "00001", "front": [1,2,3,4,5,6], "back": [1], "draw_at": "2026-01-01T12:00:00Z"}],
    "DLT": [{"game": "DLT", "issue": "00001", "front": [1,2,3,4,5], "back": [1,2], "draw_at": "2026-01-01T12:00:00Z"}]
  }
}
```

That skeleton is **intentionally incomplete**: at least 60 distinct valid and
chronologically ordered draw records are required for *each* game. The issue/date
values above are examples, **not approved target periods**. The program rejects
expired targets on `predict` and rejects history at/after as-of.

```sh
python -m research.ssq_dlt_v46_harness predict --snapshot my_checked_snapshot.json --ledger C:/LottoResearch/v46.sqlite3 --output C:/LottoResearch/v46-shadow.json
```

The CLI does not fetch or independently authenticate source originals. **A
caller-provided JSON is not an official as-of snapshot.** No formal candidate
may be enrolled from this prototype; it deliberately emits `SHADOW_ONLY`,
`formal_A=0`, `NO_EDGE`, `external_timestamp_status=NOT_RUN`.

## Research and engineering boundaries

- SSQ front is 6 of 33 and back 1 of 16; DLT front is 5 of 35 and back
  2 of 12. The model ranks and main D2 apply **only to the front zone**.
- Exact baseline D2 probability is SSQ 15/528 and DLT 10/595.
- Every model has one **ordered five-number ranking**. D1–D5 are nested
  prefixes. Its first two numbers define one unchangeable main D2.
- Models 02–05 reuse pinned V4.5 internal scoring functions. Model 06 uses
  two 30-draw halves; it is an exploratory placeholder, **not** the
  previously blocked U/R/C candidate and **not** a registered trial.
- Random NULL is seeded/domain-separated and uses a uniform permutation;
  the same caller input yields the same prediction.
- SQLite insertion is idempotent and UPDATE/DELETE are rejected by triggers.
  An owner with filesystem access can still substitute the entire DB.
- `score_research` accepts caller-provided outcomes and labels them
  **UNVERIFIED_CALLER_INPUT**. There is no certified official outcome
  ingestion and no accepted external freeze-index bridge yet.
- No production 01/04 authorization, external TSA, official next-issue
  confirmation, valid prospective sample, physical reboot acceptance,
  unattended scheduler installation, or full nine P0 suite is claimed.
- Existing DLT 69/2880 negative-control anomaly remains unresolved.
  `A=0`, `NO_EDGE` and original V4.5 8-slot identities remain unchanged.
- Next milestone: independent raw official dual-source ingestion; signed
  freeze receipt/external TSA; end-to-end score process; fault injection;
  Windows task scheduler and operator-visible reporting. **Do not enable
  scheduled predictions until the live target gate is implemented.**
