# English Root Intelligence

Windows desktop prototype for learning English through **morphemes → semantic bridges → word families → spoken chunks → active practice**.

## UI

Main screen keeps four primary actions:

- 今日学习
- 一键更新
- 一键修复
- 高级分析

The home panel also provides an interactive word analyzer.

## Data and safety model

Knowledge data and user progress are separated. The software update button validates a trusted release configuration beside the main EXE and hands the replacement transaction to `English_Root_Intelligence_Updater.exe`. The main process closes after the separate updater starts. Missing independent release configuration is BLOCKED and preserves the installed software and learning data. Corpus refresh remains the separate audited `Service.refresh_knowledge()` operation; it verifies the matching manifest/database receipts and commits storage/evidence with rollback.

One-click repair validates both the knowledge database and user progress. Corrupted original bytes are archived under a content hash before recovery. Healthy learning progress remains unchanged. The post-repair data must validate before the UI reports PASS.

## Local source test

```powershell
python app.py --self-test
python -m unittest discover -s tests -v
```

## Windows build

GitHub Actions builds the main EXE and independent Updater on Windows with Python 3.11.9. It waits for the windowed Updater process and checks its actual exit code and typed self-test JSON. Physical GUI acceptance requires real foreground mouse clicks, screenshot bytes, the correct process and completed Service results. A blocked update click proves only that the UI handles the missing release configuration; it cannot satisfy final software-update acceptance. Final publication requires a dedicated repository, current-run real N to N+1 release evidence and matching main/Updater hashes. This shared recovery repository does not satisfy independence, so it cannot publish a final product.
