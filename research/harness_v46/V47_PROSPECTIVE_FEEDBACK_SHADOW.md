# V4.7 /goal | before-draw forecast -> after-draw scoring -> diagnostic feedback

Research-only prototype, layered on PR #445 HEAD `4ad97e1461166327e94f32a7f40abca3692898c2`. This is **not** an official forward study or a model improvement claim.

## Intended user-facing workflow

1. **Before the actual draw**: acquire vetted as-of history, register manifest and six model outputs, lock one main `primary_d2` per model, persist snapshots and hashes, and obtain a separately verifiable trusted pre-cutoff seal. If independent data or TSA is missing, label SHADOW and do NOT count in formal A.
2. **After the actual draw**: intake authentic independently checked official numbers and proof (not yet implemented). The experimental `replay_shadow_feedback` accepts caller-supplied outcome only, replays exactly six frozen model records, rejects incorrect issue, invented before-target draw time and local post-cutoff freeze, and returns immutable-hash style diagnostic receipt.
3. **Cumulative**: `summarize_shadow_feedback` rejects duplicate (lottery,issue), malformed/mixed-scoring receipts or attempted formal promotion, reports separate game/model D2 numerator/denominator and fair baseline + same-draw fixed Random NULL descriptive delta.
4. **Research improvement**: audit anomalies and propose only a **new pre-registered version**, to test against future unseen draws. Do not backfill target guesses, reselect D2 after draw, choose past winners or change old scores.
5. Do not interpret a hash-controlled diagnostic card as cryptographically authenticated official result or trusted pre-draw proof. A local DB and local timestamp are mutable by privileged owners. This prototype deliberately returns `formal_A=0, NO_EDGE` regardless of hit counts.

## Reproduce

```sh
git checkout --detach <exact-PR-head>
python -m unittest discover -s research/harness_v46/tests -v
```

## Synthetic counterexamples

- Correct issue and legal invented result scores exactly the already-frozen D2; rerunning changes no DB bytes.
- Wrong target issue or alleged result earlier than target draw fails.
- An attempted privileged late-frozen-at modification fails the local predraw consistency guard (still not trusted time).
- Duplicate issue or changed receipt refuses a misleading cumulative count.
- Forged `formal_A=1` refuses promotion even if caller recomputes the receipt checksum.
- Unregistered run and missing ledger are BLOCKED.

## Blockers and status

Official source-origin/time admission remains BLOCKED; independent authenticated result ingestion and witness pre-cutoff seal NOT_RUN; prospective preregistration and sample-size/statistical acceptance NOT_VERIFIED; real Windows P0 NOT_RUN; DLT 69/2880 still unresolved. The V4.5 eight formal slots and `main` are untouched.

`ENGINEERING_PASS=NOT_YET`; `RESEARCH_VALID=NO`; `D2_EDGE_CONFIRMED=NO`; `formal_A=0`; `NO_EDGE`.
