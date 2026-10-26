# Locale-independent JSON stdout repair

Scope: one confirmed operational protocol failure in the existing V4.7 CLI. Sole Issue468/DraftPR467; base507f653ab8bc8b2e00ceabb183c93d7eafa9332d/treeb1e9b22484e51026f34add4b21fea6df6c5ce010. Use the existing isolated edit snapshot; verified execution snapshot stays immutable.

## Original evidence and design

Heartbeat2026-10-26T00:02:23.102Z actually completed tickV47T-f0e9230d0c6542508086bd3c1933c862:19attempts/76events, no unfinished journal item. The child returned0 but its3610 stdout bytes were not UTF-8. Diagnostic GBK decoding yields exactly the original canonical SQLite FINISHED.result; that is a root-cause check, not an accepted production fallback. DLT's new national-source Content-Type error contains Chinese. Main CLI printed ensure_ascii=False through locale-dependent Windows stdout, while consumers require strict UTF-8.

Preserve the raw stdout/stderr and failed reader. Recover this attempt's metadata only from the checksum-validated original journal; do not rerun or backfill the same attempt. Source outage and output-encoding defect are separate. Formal_A0/NO_EDGE, unknown formalK/N, and original freeze/score/source/cutoff gates remain.

Choose ASCII-escaped JSON for structured stdout only. ASCII is a UTF-8 subset and JSON decoding preserves every Unicode value, independent of console code page. Change the two closed_loop main print calls and desktop main JSON print; leave actual UTF-8 receipt files, UI text, pinned scientific code, source bodies, requests, model/seed/family and archive identities untouched. Do not soften the consumer with guessed legacy encodings or alter global IO settings.

## Execution checklist

- [ ] Preserve incident bytes and canonical-journal recovery with explicit stdout contract FAIL.
- [ ] RED: actual subprocess public-main paths under cp936/cp1252/ascii plus UTF-8 control, Chinese-only exit0/nonUTF8 and mixed-Unicode encoding failure; strict UTF-8 read and exact value comparison. Mock only business/network boundary.
- [ ] Minimal GREEN: three structured-output ensure_ascii flags only; save focused logs/hashes.
- [ ] Complete V4.7 regression and existing offline SSQ/DLT checks; retain every local script-policy failure by name.
- [ ] Fresh independent increment review and exact-new-head Ubuntu/Windows CI; preserve earlier failure and earlier green CI scopes.
- [ ] Full Git-blob verification, fresh execution snapshot/config/launch artifact and pointer only after proof. Daily-owner GUI failure remains NOT_VERIFIED unless actual owner evidence changes.
- [ ] One bounded real retest through the same original closed_loop, preserve source responses/failures and all old events; no unchanged historical-study rerun. Update soleIssue468 with new evidence and current blockers.

This repair makes output transport reliable; it does not establish source authenticity, qualified future inputs, a certified forecast denominator, or improved lottery odds. Normal-owner startup/install and G00/G01 barriers are unchanged.
