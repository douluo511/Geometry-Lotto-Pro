# Gansu same-source POST history repair Implementation Plan
> For agentic workers: REQUIRED SUB-SKILL superpowers:subagent-driven-development or superpowers:executing-plans.
Goal: preserve exact POST request/response evidence while allowing current Gansu corroborator to use its existing publicJSON history.
Architecture: extend existing source parser/fetcher and original intake/replay/auditor; no new runner. One integrated task owns data shape and every evidence boundary.
Tech Stack: existingPython3.11+requests2.34.2, unittest, no dependency changes.
Spec: docs/superpowers/specs/2026-10-27-gansu-post-history.md

Global constraints: solePR467/Issue468; same Gansu identity/root and role; national+Jiangsu120 plus Gansu10/latest rules unchanged; oldHTML20 path preserved. No formalpromotion, arbitraryPOSTURL, forwardingredirectbody, sourceauthclaim, model/NULL/seed/family/stoprule change, mainmerge, purchase, extraHarness or oldrecordoverwrite. Exactcurrentbaseline602d542files. Userdelegatedexecution, preserveevidence.

Review focus: requests leaking/relabelled across redirects; invalid200/partialpages masquerading as complete source; same-response retries or method/bodytampering doublecounted/unbound; duplicateJSONkeys/schema coercion/publicationdates; old GET/HTML artifacts and their rawreplay compatibility.

Task1 integrated source→request capture→canonicalrawreplay:
Files: DLT/src/glp/sources.py; research/harness_v46/official_intake.py and existing raw/audit helpers only as required; new focused tests underresearch/harness_v46/tests and TEST_ONLY captured fixtures. Do not touch core/statistics/models/Windows scheduling.
Interfaces: parse_gansu_json_page(raw:bytes) -> draws and strictpagination metadata; fetch_gansu_history_json(limit:int=140) -> existing(draws,SourceReceipt,list[manifest]), rejectinganyotherlimitincluding10/21; GansuApiUnavailable(SourceError) only first-request transport/non200 for narrowHTMLfallback. Use request_method/request_body_base64/request_body_sha256 consistently; exact request_json may be derived/readable, not substitute for bytes. Originalfixtureshavehistoricalresponsebytesbutonlylogicalrequest_json; fixtureencodedrequestbytesmustbeexplicitTEST_ONLY_RECONSTRUCTED.
- [ ] Copy7rawfixtures only after originalSHAverification; include historicalcapture metadata marked TEST_ONLY/untrustedtime.
- [ ] Write tests for literal140rows and body/method-bound response preservation; verify genuine missing-feature/POSTcaptureRED before production.
- [ ] Add strictfixedschema JSONparser/boundedpaginatedfetch preservingHTML/native interface.
- [ ] Add GET-compatible POSTguard/persist/bind/replay/auditor plumbing. POST redirects refused after capture. Counterexamples: wrongmethod/bodySHA/JSONschema/type_id, duplicateissue/page/totals, invalid200, partiallaterfailure, stale/latestmismatch sourcequorum unchanged, sourcebodymissing, legacyartifact.
- [ ] MinimalGREEN focusedsuite, full oldsource/intake/replay/audit suites; independently replay original7fixturepages with existingnational audit rows, no algorithmstudy.
- [ ] Fresh independentreview; Important fixes one pass with RED→GREEN; record minors/rulings.
- [ ] Fullregression +542baseline-diff/source/actualledger hashes; prepare exactsamebranch commit byexpected-parentCAS, exactUbuntu/WindowsCI. Never hide known local7policyfailures.
- [ ] Verifyall deliveredGitblobs/trees/CIlogs independently, promoteimmutablecopy/config/ownedentries onlyafterchecks, actualoriginaltick+scopednewinputaudit. UpdateonlyIssue468 andoldPR; preserveoldfailures and returnformalstatsNOTVERIFIED/A0NOEDGE.
