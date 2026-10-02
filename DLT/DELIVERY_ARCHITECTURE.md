# DLT 交付架構與當前缺口

狀態：候選實作，不是最終成品。工程／業務／綜合完成度：未核證。
本文件不擅自縮小原始需求；完整業務分母與發布條件仍需閉合。

## 實際调用鏈

```text
Win32 四入口 GUI
  └─ LottoService
       ├─ update → build_canonical → NetClient → 官方多源 → Store.save_dataset
       ├─ predict → 驗證資料 → Engine → 不可變 Freeze → Evidence
       ├─ repair → 完整性檢查／ledger 恢復／官方資料重建 → 成功或 FAIL ledger
       └─ audit → Evidence Court → 記憶體預覽／ORS → 審计 ledger（不得新建正式 Freeze）

候選 EXE → --acceptance → 實際官方聯網 → 原文保存＋UTC＋SHA-256
                       → predict／repair／audit → 狹義 exact_acceptance_gate
外部 Windows 工作流 → GUI／Same Hash／獨立 Updater／業務／禁止空殼 → Final Gate
```

## 接口邊界

| 接口 | 真實輸入／輸出 | 失敗行為 |
|---|---|---|
| LottoService.update(progress) | 官方原始響應→已驗證 canonical、source receipts | 超時、衝突、解析或落盤失敗向上拋出；不以快取冒充更新 |
| LottoService.predict(progress) | Store 歷史＋合格模型身份→帶 hash 的研究候選／Freeze | 完整性失敗拒絕；最新性及 GUI 負向證據仍需加強 |
| LottoService.audit(progress) | canonical＋prospective replays→Court／ORS | 不調用正式 predict；不新增正式預測；非 PASS 科學執行不可顯示成功 |
| LottoService.repair(progress) | 完整性報告→重建後完整性＋repair ledger | 修復仍失敗必須拋錯；自己的 FAIL ledger；Evidence 寫入失敗也暴露 |
| self_test(root=None) | 新建可清除的測試子目錄→受控回歸結果 | 不得觸及 GLP_DATA_DIR 的使用者帳本；結果不是聯網 PASS |
| preserve_live_evidence(store, result_file, exe_sha256) | 真實 canonical/source JSON、原始 body→保存包＋manifest | hash／bytes／HTTPS／原文／來源時間缺失即失敗 |

## 本批修補與驗收範圍

- 自測資料與使用者資料隔離；GUI 自測去除 StubService，僅測真实視窗／控件。
- Audit 使用本次 Court 產生記憶體分析 trace，不再間接寫入 prediction Freeze。
- Repair 的失敗不再以一般回傳值流入「完成」；失敗證據寫不進去也不能吞錯。
- GUI 結果渲染拋錯會恢復按鈕並顯示失敗；WARNING／UNKNOWN 等不能顯示成功。
- Exact EXE 的聯網原始 bytes 保存於可下載 Evidence 包，不隨臨時 Store 消失。
- source Python 的 hash 不冒充 EXE hash；EXE 內部不得發出整體 Final PASS。

## 尚未閉合的硬門

1. 獨立 DLT Updater EXE、實際 N→N+1 版本更新、原子回滾、Same Hash。
2. GUI 現有截圖變化證據只證明畫面改變；必須追加每個入口的後端效果、實際網絡與 ledger 核對，含失敗路徑。
3. 全部業務／功能／模型／維護入口清單、反例与完整當前證據。
4. 獨立生產倉庫及發布權限；不得把共用倉庫候選包標成最終產品。
5. 種子資料只供冷啟動；預測／審计最新性、來源完整溯源和 Evidence 寫失敗路徑仍需加固。
6. 模型的 NO_EDGE／NULL_DAN 不等於預測優勢；不得承諾中獎率提升。

## 負向 GUI 證據消費加固（2026-10-02）

更新／修復的 Fail-Closed 實體點擊不只由執行腳本自報 PASS。當前 `business_runtime_gate.py` 與
`final_gate.py` 會再次要求同一候選、同一 run、同一 Exact EXE／Updater hash，並驗證：
`physical_hit_test_verified=true`、`updater_failure_count>=1`、UI Fail-Closed、
canonical/evidence 不變，以及對應 FAIL ledger 增量；缺少任何一項均不得通過。
Hosted Windows 的單次 `SetForegroundWindow` 拒絕不是產品後端成功／失敗證據，
所以前景切換只做有界重試與記錄；真正的物理點擊硬證據仍是 topmost child-button
`WindowFromPoint` 命中、`mouse_event`、UI 失敗狀態與 operation-bound backend ledger。

## 不變交付判據

真實聯網 → Windows 原生構建 → 同一 Exact EXE → GUI 實際效果 → Same Hash
→ 完整 Evidence → 工程與業務各 100% → Final Gate PASS → 唯一成品。
任一缺失：Final Gate 非 PASS。受控測試資料、截圖、EXE 檔案存在均不得替代上述證據。


## 真实软件版本更新闭环（当前实现）

独立生产仓库固定为 `douluo511/Geometry-Lotto-Pro-DLT`。共享仓库只能产生候选诊断证据，不能令 `repository_independence`、`release_context` 或 `updater_real_network` 变为 PASS。

独立仓库 `main` 的 Windows 工作流现在按以下顺序执行：

```text
Exact source SHA
  → Live official-data network
  → Native Windows main EXE + reproducible Same Hash
  → Independent Updater EXE + reproducible Same Hash
  → Exact-package acceptance
  → publish hash-bound vN prerelease (EXE + Updater + manifest)
  → updater process / rollback / data-network acceptance
  → release_update_acceptance.ps1:
       download previous vN-1 Exact EXE from GitHub Release over HTTPS
       invoke the current Exact Updater EXE as a separate process
       download current manifest + vN Exact EXE over HTTPS
       verify bytes + SHA-256 + version + process identity
       atomically replace the previous EXE and run installed self-test
       require installed hash == current exact-build hash
       rewrite updater_real_network from PENDING to PASS only on this proof
  → Physical GUI four-entry backend evidence
  → Evidence-derived Final Gate
  → upload Final Actions artifact
  → promote current prerelease to non-prerelease FINAL release
```

`DLT/scripts/release_update_acceptance.ps1` 在非独立仓库／非 `main`／非 `push|workflow_dispatch` 上不得授予软件更新网络 PASS；因此共享仓库的候选仍会 fail closed。

`.github/workflows/dlt-final-production-bootstrap.yml` 负责从经过 manifest/hash 验证的 DLT-only 导出创建或填充独立仓库，先建立 `v2.1.2` 基线 prerelease，再只提升软件版本到 `v2.1.3`，要求该新 SHA 自己完成完整 Windows / Real Network / GUI / Same Hash / N→N+1 / Final Gate 链后才验证正式 Release 和 Final Artifact。

该流程没有删除、跳过或放宽任何原有硬门。独立仓库本身及其账户级写权限仍属于外部发布前置条件；缺失时状态必须保持非 Final。


## Finalization trigger audit

2026-10-02: user explicitly re-authorized continued execution toward the unique Final artifact. This documentation-only commit intentionally retriggers the branch-bound DLT Final Production Bootstrap and Windows acceptance. It does not waive, inherit, or relax any gate and is not evidence by itself.
