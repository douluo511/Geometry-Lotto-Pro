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

Knowledge data and user progress are separated. One-click update downloads the public GitHub manifest and roots database, verifies SHA256, validates schema, stages the file, keeps a backup, and atomically replaces the production data only after validation. Failure keeps the previous database.

One-click repair validates both the knowledge database and user progress. A damaged knowledge database is restored from the bundled verified seed. A damaged progress file is rebuilt without touching the knowledge database.

## Local source test

```powershell
python app.py --self-test
python -m unittest discover -s tests -v
```

## Windows build

GitHub Actions builds a standalone x64 EXE with PyInstaller. The final workflow runs source tests, packaged-EXE self-test, SHA256 generation, and a live GUI-process smoke gate before publishing the artifact.
