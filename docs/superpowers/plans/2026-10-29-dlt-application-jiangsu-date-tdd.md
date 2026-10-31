# Original #467 / Issue #468 execution record — DLT app semantic TDD

1. Read real PR #467 at `5b09cee0fcbca034393d105dc85bd0fe441efea6`, exact native SSQ 40784762861 and DLT 40784762821 failures, and existing research date-guard code. Main remains untouched.
2. RED tests first: commit `9ef65ce29cf3895e5f544cfafac2a7409f38c6f8` adds application-level invented examples for publication-date, headerless, decoy header and explicit draw-date controls. RED exact-head run: 40815587436. Test output must be checked; no assumed RED outcome.
3. GREEN candidate: commit `d389ead95405dc7b2743feb9f59ba96d412988ff` wires the existing research structural guard into the DLT app intake, changing only local exception type. Run exact-head cross-platform core+SSQ+DLT, scrutinize actual failures, and retain raw logs.
4. Negative controls: publication date must not silently become draw date; no source fallback, date shifting, row dropping or source threshold reduction. Record any new native run's actual fail reason, never call source quorum PASS without original independent evidence.
5. Independent nonauthor review: no approval inferred from author's own inspection or CI. Check parent SHAs, diff and any regression separately.

Open operational gates: trusted official future issue/cutoff/TSA, complete prospective ledger and postdraw independent results, real Windows owned scheduler 30m/boot/restart recovery, DLT 69/2880 anomaly, external acceptance. SHADOW/NO_EDGE until independently proven.
