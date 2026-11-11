# Psychology Insight Pro

Windows 桌面原型：心理洞察、多假设竞争、证据/反证、个人基线、5 Why、逆转验证。

## 主界面
- 心理分析
- 一键更新
- 一键修复
- 高级分析

## 原则
系统只做概率性推断，不做“读心”、测谎或心理诊断。输出必须保留竞争解释和证据不足状态。

## 本地运行
```powershell
python psychology_insight_pro/app.py
```

## 自检
```powershell
python psychology_insight_pro/app.py --self-test
python -m unittest discover -s psychology_insight_pro/tests -v
```

## Windows EXE
GitHub Actions 工作流 `Psychology Insight Pro - Build Windows EXE` 使用 Windows runner + PyInstaller 构建单文件 GUI EXE，并在上传 artifact 前执行：
1. 单元测试
2. Python 核心自检
3. EXE 本体 `--self-test`
4. SHA256 生成

## 一键更新
原型版的一键更新更新的是知识/规则库 `knowledge.json`，通过 GitHub Raw HTTPS 获取、schema 校验、备份、原子替换，失败保持旧版本。

完整 EXE 自更新应在后续版本采用独立 Updater 进程实现，避免 Windows 文件锁问题。
# Independent software Updater acceptance hardening

Software replacement and knowledge refresh use separate paths. The main EXE hands
off to `Psychology_Insight_Pro_Updater.exe` and closes only after a successful
handoff. `Psychology_Insight_Pro_Update_Config.json` is supplied beside the main
EXE by an accepted independent release, using schema
`psychology-software-update-config-v1`, an HTTPS `manifest_url`, and an explicit
`trusted_hosts` list. No production configuration is fabricated here.

The private Updater validates manifest schema, monotonic version, artifact length
and SHA-256, waits for the main process, stages bytes, keeps a transaction journal,
replaces atomically, and runs the installed EXE's typed self-test. Failed health
checks roll back; interrupted rollback retains recovery evidence for restart.
Thirteen offline fault scenarios exercise this transaction and do not establish
real Release N to N+1 acceptance.

Repair preserves exact damaged knowledge and provenance bytes in hash-named
backups, validates the bundled replacement before writing, clears stale network
receipts after local restoration, and runs the core self-test. Healthy state and
user input are preserved. Medical and behavior inference boundaries remain those
in the frozen business specification.

Windows CI checks the exact product commit, builds both private EXEs, waits for
their self-tests, and records real mouse actions with retained screenshots and
PID/run-bound backend results. The update button's missing-release response is
BLOCKED; it cannot count as real software update PASS. Final acceptance also
requires `ConfiguredRelease` physical update proof and a current independent
Updater transaction with a trusted production manifest receipt; `BlockedRelease`
click diagnostics cannot satisfy the Final GUI gate. It also requires current
independent repository and real release evidence. This shared
recovery repository is not an accepted independent product repository.
