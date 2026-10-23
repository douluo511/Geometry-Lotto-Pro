# V4.7 source-date semantics and pre-draw freeze integration

Pinned parent: PR #452 at `d66677936347d39cc490699f9983790d2ca4dc57`.
Independent research child; never main. Keep #451/#452's canonical cumulative
entrypoint and RFC3161 component. Port only the scheduler protection from #453;
do not add the parallel cumulative_shadow reducer from its divergent stack.

## Actual retained-byte finding

GitHub live intake run 39876744148 artifact 12468094967 was downloaded and
independently byte-audited: ZIP SHA256
`fec59aa2cb99022d58b53947931781d019c277f7a35753fc8b8e80b1b0d9d2c5`,
412823 bytes; 64/64 retained raw files match their byte receipts.

All 30 Jiangsu history responses label their first date column `发布日期`
(publication date), while the reused application parser assigns it to
`Draw.draw_date`. Independent HTMLParser extraction matches all 2934 source
rows and confirms incorrect field meaning, not shifted numeric cells.
Page 17 raw SHA256
`30ab3938992ba14cd15b340d7f684ea9cc1331462eaf00125b559597aca17442`
contains issue16003 published2016-01-07 and issues16004/16005 published2016-01-11.
Those bytes cannot supply replacement actual draw dates or precise publication
timestamps. A calendar-clean recent slice cannot repair their field meaning.

The research raw replay now requires an explicit draw-date/time column header
bound to the same candidate data table and its first column. Missing or
ambiguous labels, publication labels, misplaced/decoy headers, conflicting
tables and unsafe malformed structures fail closed before replay can treat
the date as a draw date. It does not infer dates, ignore old rows, relax full
history requirements, modify raw evidence or claim independent source origin.
The shared DLT application parser remains untouched and must not be treated as
semantically corrected by this research admission guard.

## Live recovery-path probe

The observed latest-detail link
https://api.js-lottery.com/cms/post-148104.html returned HTTP200, 65715 bytes,
SHA256 `bd2ece301dacd40e1102ee674044195023454bbd25d805a23cedfcf79e0d433c`.
It explicitly separates publication time from draw date for issue26120.
This is one preserved source page, not admitted 120-draw history or a qualified
prospective observation. A future adapter must bind explicit issue-detail draw
dates and numbers to every retained record before the full cross-source gates
can be rerun. Five observed Gansu pagination-script requests returned HTTP403;
no extra independent history was recovered and no access restriction bypassed.

## Freeze consistency

The parent still guarded raw issue strings. Numeric aliases could create
multiple freezes with alternative NULL streams for one issue. The scheduler
now compares numeric issue identities inside its existing transaction while
preserving raw historical strings. Newly frozen targets must also be ASCII,
matching the parent's outcome-feedback contract. A conflicting alias is rejected
before insertion; partial records for the other game roll back together.

Existing Unicode frozen records remain available through read-only `show` with
their original run identity and bytes. This does not expand #452's ASCII-only
outcome-scoring contract for old Unicode records. Exact write retries remain
same-harness-version only; upgrading source bytes changes run identity.

## Verification and scope

The exact parent baseline ran 222 local Windows tests, OK. A first setup attempt
could not hydrate missing Git promisor blobs; the passing baseline was taken
only after all 56 required files matched their declared Git blob hashes.

Scheduler TDD: two new tests failed across eight expected rejection subcases,
then passed after the numeric/ASCII guard. Both games, aliases in both directions,
rollback of every ledger table, and unchanged legacy Unicode replay are covered.
An initial test-placement error was corrected before recording the valid RED
run. Semantic replay uses actual DLT-parser subprocesses on explicitly synthetic
fixtures; its RED/GREEN and real retained-page replay logs are supplied in the
Draft PR evidence. These tests are not official forecasts, source-origin proof,
publication-time proof or external TSA evidence.

Final commit, full-suite counts, independent review findings and exact-candidate
Windows/Ubuntu run URLs must be taken from the final Draft PR and original job
logs. Local success alone does not establish remote dual-platform CI.

Independent review of the initial candidate found three important bypasses:
ignored inert containers could forge headers, unknown replacement headers could
inherit an earlier safe schema, and document-wide entity decoding could create
structural tags from escaped text. All were reproduced through actual legacy
raw replay. Eleven regression methods ran RED with 37 failing subcases and no
errors, then GREEN (34 semantic methods total). The guard now parses original
markup, decodes cell text once, verifies literal/legacy candidate agreement,
rejects hidden/inert contexts and malformed table sections, and requires every
non-candidate row in a data table to be an explicit verified header. This
deliberately rejects unknown footer/schema rows instead of inferring meaning.
Balanced thead/tbody/tfoot and supported inline/entity labels remain covered by
positive controls. Original review findings remain in the evidence; a fresh
independent re-review is required before calling this patch reviewed.

Re-review exposed two further context-release paths: mismatched ancestor closes
and non-void self-closing syntax. Four more regression methods produced 22 RED
subcases; a separate plaintext pseudo-close regression also failed. Unsafe
descendants can no longer be released by ancestor matching, HTML non-void '/>'
does not terminate a container, and plaintext cannot be ended by an explicit
closing tag. Normal explicitly closed containers remain positive controls.

Another re-review found that HTMLParser normalizes `</ textarea>` into an end
callback although it is not a closing HTML token. Six more methods ran RED with
44 failing subcases (42 unsafe accepts and two mixed-line-ending false rejects).
The guard now verifies original `</tag[ASCII whitespace]*>` syntax before any
context release and maps getpos() using LF boundaries. Attributes and a solidus
suffix on end tags are conservatively unsupported; this is a restricted data
admission grammar, not a complete HTML5 parser. HTML token semantics were checked
against https://html.spec.whatwg.org/multipage/parsing.html#rcdata-end-tag-open-state.

Model core, parameters, NULL seed, V4.5 formal slots, datasets and historical
records are unchanged. There is no main write/merge or purchase operation.
Official history/target/cutoff authentication, an approved independent external
TSA, qualified future outcomes, cohort completeness, preregistration, physical
Windows recovery and the historical DLT69/2880 investigation remain unresolved.

Separate global verdicts remain ENGINEERING_PASS=NOT_YET, RESEARCH_VALID=NO,
D2_EDGE_CONFIRMED=NO, formal_A=0, NO_EDGE. A passing bounded patch cannot
promote these verdicts or create a forward observation retrospectively.
