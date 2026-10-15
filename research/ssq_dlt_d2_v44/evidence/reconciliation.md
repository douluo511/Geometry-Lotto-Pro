# SSQ＋DLT V4.4 reconciliation and governance review

Observed: `2026-10-15T11:33:03.936714+00:00`. Source pinned to `c6d4de9aaa49b219e422dace755702b117179fa6`.

## Results

| Check | Result | Evidence and limit |
| --- | --- | --- |
| PR #407 identity | PASS | Connector read confirmed draft/open, head exactly `c6d4de9aaa49b219e422dace755702b117179fa6`; PR was not merged. |
| Governance and Issue #408 reviewed | PASS | Shared migration workspace; independent repository and complete evidence chain required before FINAL. |
| Local ZIP discovery and read-only inventory | PASS | Documents 263, Downloads 0, Desktop 92: 355 central directories scanned; 61 relevant-name/entry candidates inventoried and hashed; 0 ZIP read errors. |
| Related ZIP bytes preserved | PASS | Every candidate SHA-256 was identical before and after the read-only scan. No ZIP was extracted, executed, overwritten, renamed or imported. |
| Original V4.0 identity and byte/interface comparison | BLOCKED | Original SSQ＋DLT V4.0 conversation ZIP not positively located. No original archive SHA or interface was invented, and nearby versions were not substituted. |
| Claimed expected original SHA | BLOCKED | `d9a6decd6c56e39c19e1f8d6786dd5f793792d169ba1815e8faaced7156023e3` was supplied in a cross-chat handoff; no matching candidate bytes were found. This is a claimed expected hash, not verified evidence. |
| Existing Git SSQ/DLT baseline manifest | PASS | 76 canonical Git blobs hashed at the pinned commit; aggregate SHA-256 `241da3e0e77975fd076e38bd938c378b9a5dfeb669e2ca4e1eb2890cf5567c99`. |
| Legacy integration/live network/Windows boot acceptance | NOT_RUN | This report is read-only reconciliation and static code review, not execution acceptance. |
| Repository independence / Final Gate | FAIL / FAIL | Required by PORTFOLIO_GOVERNANCE.md while products remain in this shared repository. |
| Scientific/formal state | BLOCKED | `R2=BLOCKED`, `formal_A=0`, `NO_EDGE`; no synthetic or historic result is promoted to A. |

## Archive identity limitation

The 355 ZIP central directories were read for lottery-related names/entries. For the 61 retained candidates, the scanner read only README, version, manifest, handoff, configuration and constants entries up to 256 KiB to search explicit V4.0 hints. There were no V4.0 entry-name hits. The single 4.0.x text hint belonged to an unrelated Stock_AI_Pro 4.0.1 test fixture and cannot establish this lottery V4.0 identity. Other located software includes SSQ/DLT production candidates, DanLab 1.0.x, MVP v1.2 and the three-version audit. Archive filenames and their release claims are not inherited acceptance evidence.

The full local report preserves scope paths and entry CRC/size inventories. The committed report uses scope labels and candidate IDs, with no user-specific absolute filesystem paths. Neither report can prove absence outside the three searched scopes, inside encrypted/nested archives, or in remote conversation attachments. A byte-for-byte V4.0 diff remains blocked until the actual original is available and its identity is verified.

## Actual existing interface differences at the pinned commit

| Contract | SSQ | DLT | Integration implication |
| --- | --- | --- | --- |
| App version / entry | `8.5.0-verification`; `SSQ/launcher.py` | `2.1.2`; `DLT/src/main.py` | V4.4 research is a distinct layer; product versions are not V4.0 identity proof. |
| Draw identity | Seven-digit issue beginning 20; 6 of 33 front, 1 of 16 back | Five-digit issue; 5 of 35 front, 2 of 12 back | Keys must include game, version and issue; do not normalize away identity. |
| Prediction front/back ranking | `Ranking` object serialized as `numbers`, `scores`, `feature_scores` | Flat `list[int]` rankings | Explicit per-game adapters are required before D1–D5 scoring. |
| Storage / freeze | Immutable freeze UPDATE/DELETE triggers and partial other UPDATE triggers | Unique target issue; existing freeze returned; no immutable table triggers | Existing stores do not by themselves satisfy the new issue/model/slot ledger contract. |
| Replay service | `replay_all(progress) -> dict` with replay and postmortem counts | `replay_all() -> int`; replay `INSERT OR IGNORE` | Neither legacy return value is full expected-issue/eight-slot qualification. |
| Background | No corresponding SSQ background module in the pinned source tree | 1,800-second process loop; startup mode requires manual app launch after login | Legacy background metadata says `autostart_registered=False`; Windows startup registration still requires separate evidence. |
| Boot/check side effects | Explicit service calls only | `background_cycle` creates a prediction if target lacks a freeze | Do not use the old worker as a status-only, no-reprediction boot handler. |
| Official receipt / as-of | Raw-source paths, HTTPS host check, `fetched_at` | National/Jiangsu/Gansu paths, HTTPS final URL check, `fetched_at` | Fetch time and draw date do not prove authenticated publication/as-of time or 01/04 authorization. |
| Eight original identities | No V4.0 identity mapping established | No V4.0 identity mapping established | `M04`, `M05-1..M05-5`, `M06`, `M07` must retain their own identity and admission. |

## Static review findings

1. `DLT/src/glp/background.py:83` calls `predict()` on a missing target freeze; `:178` creates a process polling loop, not proof of a Windows boot task.
2. `DLT/src/glp/storage.py:55` creates freezes/replays without UPDATE/DELETE triggers. SSQ `storage.py:347` has stronger freeze triggers but does not enforce a universal append-only policy on all tables. This is a baseline contract gap, not a claim that the new V4.4 ledger has this gap.
3. `DLT/src/glp/net_client.py:86` permits HTTPS redirects to a different host; `sources.py:61` checks the final scheme but not host identity. SSQ `sources.py:44` requires the original HTTPS host.
4. The domain receipts store `fetched_at` and ordinary draw dates. Independent 01/04 signatures, issue-scoped authorization and external TSA proof cannot be inferred from these fields.
5. The research scorer deliberately emits `RESEARCH_ONLY`, `formal_a_samples=0`, `NO_EDGE`. Its registered research null is not the original M07, and its synthetic test status cannot close any of the nine P0 gates.

Static findings were obtained by reading pinned source and extracting Python AST declarations. They are not represented as executed fault-injection or live-network tests. Current-run implementation/test reports must separately decide the nine P0 results.

## Reproducible evidence

- `reconciliation.json`: exact pinned-source per-file SHA-256/Git blob IDs, interfaces, ZIP candidate hashes, scan counts and status boundaries.
- Manifest aggregate: SHA-256 of UTF-8 compact JSON (`sort_keys=True`, separators comma/colon) for the ordered `source_manifest` array.
- Governance blob SHA-256: `9ad1029485cf98b9ccc17ac5d9bb1a2e5deb0db666d7e5d708461bb550b3d8af`.
- Canonical sources: [PR #407](https://github.com/douluo511/Geometry-Lotto-Pro/pull/407), [Issue #408](https://github.com/douluo511/Geometry-Lotto-Pro/issues/408), [pinned governance](https://github.com/douluo511/Geometry-Lotto-Pro/blob/c6d4de9aaa49b219e422dace755702b117179fa6/PORTFOLIO_GOVERNANCE.md).
