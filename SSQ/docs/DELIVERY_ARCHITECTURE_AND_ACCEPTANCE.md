# SSQ 交接架構、接口與驗收邊界

狀態：候選版本；不是 Final。工程、業務、綜合完成度均未核證。
本文是可執行的交接說明與待確認的業務範圍，不冒充使用者已批准的完整驗收分母。

## 1. 架構與責任

```text
Windows GUI / launcher
    ├─ 預測、分析 → LottoService → Engine + Evidence Court
    └─ 更新、修復 → UpdaterClient → 獨立 Updater.exe → LottoService
                                                ↓
                                  OfficialSource → NetClient → 官方 HTTPS
                                                ↓
              RAW → VALIDATED → CANONICAL → FEATURE → RESULT → EVIDENCE
                                                ↓
                          Store：原始響應、JSON、SQLite ledger、freeze

獨立驗收程式：重新讀取文件和原文 → 重算 hash／解析／檢查 → Final Gate
```

GUI 不直接計算模型或把請求失敗轉換成成功。Service 協調用途、資料與證據；
Store 保護原子寫入與完整性；模型層不能自行提升成正式合格模型；
更新器先驗身份和 hash，再執行更新／失敗回滾。發佈驗收器與業務輸出分開。

## 2. 實際接口

| 接口 | 輸入與輸出 | 失敗與必要證據 |
|---|---|---|
| `NetClient.get(url, params, headers, timeout, allow_redirects)` | 官方 HTTPS；獨立連線／讀取時間；已限量讀取的 Response | 有限次重試、429／5xx、同主機 HTTPS redirect；exception 帶 `glp_attempts`；UTC、URL、HTTP status、原文 hash |
| `Draw.from_dict(value)`／`validate()` | 期號、ISO 日期、6 個紅球、1 個藍球；標準 Draw | 禁止 bool、字串／小數悄悄轉整數，禁止期號年份與日期不一致 |
| `Store.save_dataset(dataset, evidence)` | 驗證後資料及來源 manifest | 原始響應及各階段 hash；原子提交／回復；不能只保存最終結果 |
| `Store.load_draws()` | 持久資料 | 回傳 Draw 清單與 canonical hash；破損不能靜默修正 |
| `Store.validate_raw_evidence(evidence, artifact_root)` | manifest 與實際原文檔案 | 重讀全部 bytes／hash／來源；驗證失敗阻斷 |
| `LottoService.update(progress)` | 即時官方資料 | 回傳官方來源 receipts、最新期、筆數、crosscheck、canonical hash；來源不足或衝突不 PASS |
| `LottoService.predict(progress)` | 已驗證當前資料、模型政策 | 預測＋trace＋freeze；科學無穩定增益時必須維持 NO_EDGE／NULL_DAN，不承諾中奖 |
| `LottoService.audit(progress)` | 當前資料、Evidence Court | 審計結果、對照與隔離檢查；不得寫入正式 prediction freeze |
| `LottoService.repair(progress)` | 損壞資料／當前官方來源 | 修復結果及前後身份；失敗保留證據，不顯示修復成功 |
| `UpdaterClient.update/repair(progress)` | 真實獨立程序及資料目錄 | 子程序 PID、EXE hash、結果／ledger 綁定；不得用父程序重算冒充子程序效果 |
| `derive(evidence_dir, exact_exe)` | 當前 run、實際 EXE、原文與測試檔案 | 重算門檻；不接受呼叫者提供的 PASS 清單替代執行 |

接口目前主要是 Python 方法與 JSON／SQLite，不是已上線的 REST API。
不能把本文件或新增 type/schema 當作功能實際執行證明。

## 3. 網絡時間與資源約束

每次 GET 有 connect/read timeout、有限重試、指數退避、jitter、Retry-After 上限、
redirect 上限及解碼後響應 bytes 上限。Retry-After 日期用 UTC wall clock；
耗時預算用 monotonic clock，不受系統校時回撥影響。成功、拒絕、超限、
中斷及重試路徑均釋放響應資源；等待失敗必須保存完整 attempt ledger。

重要剩餘限制：目前 Requests 的 deadline 是分階段協作檢查，不是可強制終止
OS DNS／單次 slow-drip read 的硬牆鐘期限。不得宣稱已證明任意網絡下的硬即時上限；
如要此保證，需要受控可取消 I/O 或隔離 worker 與進程級監督，並以真實慢速 socket 測試。

官方来源回退不等於所有來源成功：某來源 403 必須保留 FAIL。
跨源法定數量、相同期號內容和新鮮度符合當前政策後，才可判定這次資料更新成功。
快取只能明示為歷史／研究輸入，不能充當這次 Real Network 的成功響應。

## 4. 禁止空殼與業務分母

現有 `BUSINESS_GATE.json` 檢查常數和源碼文字，只證明靜態結構。
因此即使全部為 true，`business_content` 仍為 PENDING；另設強制 `no_shell` 門。
未有完整、批准的需求／入口分母及逐入口證據前，Final Gate 不得通過。
這是阻止錯誤放行，不是把缺少的產品功能做成佔位介面。

建議待凍結的 SSQ 業務驗收集合：

| ID | 真實使用任務 | 正向與反向條件 |
|---|---|---|
| B01 | 更新歷史、查看來源及最新期 | 官方多源一致／來源衝突、空資料、過期、429、5xx、斷網 |
| B02 | 生成有追溯資訊的研究結果 | 輸入、模型、baseline、freeze 可還原／未合格模型不能入生產 |
| B03 | 獨立科學與事後審計 | OOS／holdout／ablation／多重比較／無洩漏／錯結論反證 |
| B04 | 損壞檢測與修復 | 真實修復、原子性、回滾／證據缺失與來源失效 |
| B05 | 獨立更新器 | 真實版本 N→N+1；簽識／hash／程序身份／失敗回滾／不更新自身假成功 |
| B06 | 所有 GUI 入口 | 實際點擊→真實後端→顯示＋ledger；按鈕失敗不顯示 PASS |
| B07 | 長期維護 | 备份恢復、資料遷移、證據導出、來源失效告警、普通帳戶／中文路徑 |

以上只是待凍結的最低討論集合，不能刪除原始需求，也不能替其他 17 專案定義業務100%。
每條需要具體資料量、情境、成功／失敗標準、負責人、測试與 Evidence ID，
並由使用者確認完整範圍；未確認時百分比保持 null／未核證。

## 5. 新候選的唯一驗收鏈

1. 固定 source commit、依賴、配置、模型／資料身份及需求分母。
2. Unit／Contract／Fault Injection 通過；測試夾具標示 TEST_ONLY，不計作 Real Network。
3. 同候選源碼對官方來源真實請求；保存所有原文、UTC、來源、hash、解析與衝突結果。
4. Windows 原生構建，固定主 EXE／Updater EXE 身份；可重現構建另行記錄。
5. 對同一 Exact EXE 執行 CLI 與 GUI 真實點擊，包括正向、斷網／失敗路径、ledger 與後端效果。
6. 獨立生產倉庫實際 Release N→N+1 更新；驗證下載 bytes 與實測 EXE、manifest、tag commit。
7. 工程／業務／no-shell 全部門檻重新計算；每項 PASS 綁定本候選，不拼接其他分支／舊候選。
8. 先成功保存審計包和 EXE artifact，最後才允許正式 Release 提升與唯一成品交接。

實質變更後，上述候選最終驗收失效；未變更的調查結果不需反覆重做。
不得為了降低失敗數刪除 hard gate、修改資料真實性或忽略 PENDING。

## 6. 已發現的部署缺陷與修復範圍

- 遠端重克隆只排除已核實、根目錄內真正的 `.git`；普通 export 與巢狀 `.git` 仍拒絕。
- 盤點先檢查 reparse directory，不沿連結讀取外部檔案；額外 payload 仍阻斷。
- Git 單行輸出保留為陣列，避免 commit SHA 被當作最後一個字元。
- 匯出必須包含正向和負向 GUI 腳本；否則獨立倉庫即使完整上傳仍無法驗收。
- `gh release create --target` 綁定實測 commit；審計／EXE artifact 保存成功後才能提升 Release。
- 本機 PowerShell 受限語言模式會阻止 bootstrap 測試載入。這是 UNAVAILABLE，不是測試 PASS；
  用 GitHub CI 的真實 Git 克隆反例執行，沒有關閉本機安全限制。

## 7. 當前交接界線

既有 PR #76 基線 `984a7f...` 的 run `36831958527` 已於 2026-10-01 08:00 UTC 結束，
Windows、Exact EXE、正負 GUI、Same Hash 的當次機器證據通過；Final Gate 仍 FAIL。
其 EXE SHA-256 是 `6750075bb0f5d1c4e3c57e64ed410c7d97fdada91a572d1e615212523368f2a3`。
這只是修復前候選，不能充當本次修改後版本的驗收。

外部阻斷：`douluo511/Geometry-Lotto-Pro-SSQ` 尚需使用者建立並授權；404 不能區分未建立或無權。
使用者已選擇自行建立，不以此授權重新建立其他倉庫、覆蓋已有 main、公開私有內容或合併 PR。

全18項保留：11項已有源碼／原型線索，7項（#17–#23）缺精確應用源碼與構建鏈。
SSQ 第一項完整閉環後才逐項處理下一個。任何專案「有 EXE」都不等於有成品。

Final Gate：BLOCKED。唯一最終成品：NO。
