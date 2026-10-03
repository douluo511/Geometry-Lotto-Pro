# Stock AI Pro recovery — NOT FINAL

Original archive SHA256 `fedbc5378ed5916e487b9cdc70051d5d00f790e4689ba8ff96dc8f2396ac7e10` (225815 bytes). The immutable `recovered_exact/Stock_AI_Pro` contains all 187 original files, including the binary ZIP test fixture. The import manifest records every original byte count, SHA256 and Git blob; remote tree comparison verified 187/187 matching blobs on commit `56e9ce17ad8a4cb03585dc83bee41f9a5b39fd09`.

Original Windows Python 3.11.9 offline acceptance failed 3/30 gates: Windows file URI interpretation and leaked session log file handles. The unmodified original and its failure remain preserved. Separate `staging/Stock_AI_Pro` corrects local URI parsing, rejects unsafe URI hosts and closes owned log handlers on both success and failure. It includes 2 regression gates in addition to the 30 original gates; current local compile and all 32 offline subprocess gates PASS. Package manifests are regenerated for the repaired source, never for the immutable import.

The Windows workflow validates exact checkout identity, all 187 immutable bytes before/after tests, the full 32-test denominator, compile and subprocess exit codes. Its evidence is a current-run diagnostic, not a product acceptance report. New remote execution is NOT VERIFIED until the workflow runs.

Architecture/NetClient migration, real AkShare production network, business validation, dedicated repository, Windows desktop build, Exact EXE, physical desktop GUI, Same Hash and Final are not established by source recovery or offline mocks. The recovered 4.3.0 interface is Streamlit Python. Portfolio Final remains FAIL; there is no accepted final EXE.
