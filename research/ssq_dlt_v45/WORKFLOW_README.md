# AnySearch discovery and five-stage local research delivery

This change follows draft #412 without rerunning its locked historical outcomes.
It does not promote a model, replace the original primary, or enroll guessed
future issues. `formal_A=0`, `NO_EDGE`; shared-repository Final Gate remains FAIL.

Use Python 3.11+ directly; Docker remains optional. Create a separate state
directory and use the absolute input paths/SHA pins in `config.example.json`.
Add `"discovery":{"transport":"rest","attempts":2,"timeout_seconds":8}`.
Credentials, if supplied, come only from `ANYSEARCH_API_KEY`; no registration,
automatic key creation or plaintext credential persistence occurs.

```powershell
python -m research.ssq_dlt_v45.workflow --config C:\GLP\V45\config.json
python -m research.ssq_dlt_v45.discovery probe --transport mcp --output C:\GLP\V45\mcp-probe
python -m research.ssq_dlt_v45.acceptance --output C:\GLP\V45\new-acceptance
```

The five Monday/Wednesday/Saturday JST stages are discovery15:10,
official-history20, prediction30, local hash check45, publication16:00. Exact
UTC triggers are06:10/06:20/06:30/06:45/07:00. Boot and30-minute catch-up
call the same coordinator. The optional container supervisor still implements
the original single-cycle runtime; it does not claim these five exact triggers.

Each stage is admitted at its actual local observation time and preserved in a
separate `workflow.sqlite3`. A catch-up invocation never backdates to its due
slot. An atomic clock observation survives process interruption; config/code
drift requires a new reviewed state. All non-test V44/V45 Python modules and
Windows scripts/templates are SHA-pinned per cycle. Local wall-clock controls
are not trusted external timestamp custody or protection from a file owner.

Search output supplies untrusted URLs only. Existing independently configured
official national/provincial byte fetchers run even when discovery fails;
every shared row and latest issue must agree. Search text cannot update
canonical histories, define a target, or supply a ball. Generic official URLs
are fallback fetch candidates, not proof of a legal next issue or deadline.
S05 cannot modify current numbers or register/promote a model automatically.

A failed history attempt is retained and retried. At16:00 an incomplete run
still creates a BLOCKED status report with actual reasons. A later recovered
report is an additional late artifact. Completed predictions and reports are
fixed; retries verify their SHA. Stable outbox IDs prevent duplicate unchanged
alerts. SMTP credential/connection failure retries; ambiguous post-DATA state
requires reconciliation and never causes a blind resend. Gmail's earlier
one-off success is not unattended SMTP configuration or inbox-delivery proof.

There is no verified official next-target adapter. Hence all generated numbers
remain **UNASSIGNED research previews**; even Random NULL cannot be labeled
for a legal future issue. Formal eight producers, actual01–04 approval,
qualified pre-draw seal and independent prospective enrollment remain blocked.
Replay is invoked every tick but cannot score forecasts that were never
admitted. No physical reboot/power loss/network disconnect is implied by
synthetic clock/fault tests or a direct Python invocation.

Metrics distinguish local on-time research output, SMTP-accepted cycles,
qualified pre-draw freezes and Replay completion. Denominators cover only
observed local cycles; missing unobserved scheduled dates and inbox delivery
cannot be inferred. The HTML has a clearly labeled pre-dispatch metric
snapshot; the tick receipt has updated post-dispatch counts. Zero admitted
Replay forecasts produce an undefined rate, not100%.

The pasted plan's5/65 figure has no matching source in this study. Frozen #412
test slices remain SSQ392/DLT564, all10 Holm comparisons nonsignificant,
qualified prospective n=0. Common uniform pair shrinkage
`(h_ij+tau*p0)/(n+tau)` preserves every pair ranking and tie; with the same
tie rule it yields exactly the original Pairwise-D2. Changing only tau is not
a new D2 improvement. New features/windows/tie rules/seeds require new
registered hypotheses and independent future tests; no weekly optional
winner selection or reuse of the observed historical test slice is allowed.

Windows: export with `Install-Tasks.ps1 -StagedWorkflow` and review the XML.
Actual installation additionally requires current code/config-bound integration
acceptance, administrator access and a successful LocalSystem action smoke.
Missing permission stays BLOCKED. No durable task is claimed by an XML export.

Primary API reference: https://github.com/anysearch-ai/anysearch-mcp-server
and https://github.com/anysearch-ai/anysearch-skill .
