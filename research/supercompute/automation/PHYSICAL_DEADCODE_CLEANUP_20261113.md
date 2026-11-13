# Physical SSQ/DLT evidence: dead-code cleanup

This document records an isolated cleanup of research data-ingestion modules,
not an algorithmic change to registered V4.7 forecasters.

## Evidence

On 2026-11-13, the first scan of the physical research branch parsed 82
Python sources and found 32 module-level functions in these five research
modules. Excluding import declarations from usage counts identified exactly
one unreferenced function: `dlt_physical_source.fetch_http`. It was the
original single-shot HTTP client, superseded by the bounded official transport
`physical_transport.dlt_fetch`.

Removed:
- `dlt_physical_source.fetch_http()`, plus now-unused `HTTPError`, `Request`,
  and `urlopen` imports.
- The unused `fetch_http` import in `ssq_physical_source.py`.
- Unused `parse_public_table` and `TransportExhausted` imports from
  `physical_tick.py`.

Not removed: the official-source parser, ball-set and true-order fields, raw
SHA256 archive, blocked-receipt handling, immutable SQLite index, tick/scheduler,
cooldown recovery checks or Random NULL/frozen V4.7 contracts.

The renewed audit scans source and checks imports. It must end with exactly
zero unreferenced top-level physical functions and zero unused imports.
`from __future__ import annotations` is language configuration and not an
unused import.

GitHub Actions run [43407341972](https://github.com/douluo511/Geometry-Lotto-Pro/actions/runs/43407341972)
passed all 32 isolated tests: DLT 9, SSQ 8, transport 7, SQLite 4, tick 4.
A passing unit-test suite is **not** proof of real official-source uptime or
of winning-number prediction power.

## Critical boundaries

The physical research branch contains source **collection and auditing**, not
a validated mechanical model of a lottery drawing machine. SSQ physical exit
order and ball-set fields remain unknown in its selected official source.
DLT physical source still has issuer-access blockers; unverified source rows
are not filled by guessing. No reliable prediction improvement is established.

Changes to `dlt_physical_source.py` and `ssq_physical_source.py` alter the
`parser_sha256` that will be stored by **new** attempts. Historical
create-only receipts and their old parser hashes must be retained. Treat the
new code as a new parser revision; do not retroactively rewrite old records
or pretend that GitHub is an external trusted predraw seal.

External importers may in principle have used public `fetch_http`: static
repository checks do not certify external consumers. This deletion is staged
in a draft PR for review, never merged into active collection without review.
Status: formal A=0, NO_EDGE.
