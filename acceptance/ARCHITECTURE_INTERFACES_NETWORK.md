# 可落地的工程架構、接口與聯網驗收規格

版本：1.0；日期：2026-09-30；性質：母版 V2.2 的執行補充，不是完成證明。

目標：工程 100% + 業務內容 100% + 整體 Final Gate PASS。當前三項完成度均未核證。沒有已批准、凍結的完整範圍、權重及當前版本證據，不產生百分比。

## 1. 先把「完整」定義成可驗收的內容

保留全部 18 專案與既有硬門，不把缺源碼項目移除。詳細目錄見 [EXECUTION_CONTROL.md](EXECUTION_CONTROL.md)。本輪可直接核對的實作基線是 SSQ PR #55，head `a2455a44c5c9b0c57687567efcfd26609f256221`；後續 SSQ 更新器／遷移分支不是同一候選，不能繼承它的 PASS。

每個專案先交付四份可追溯清單：

1. 原始需求與業務驗收基線：使用者、目的、5 Why、風險、範圍、成功／失敗閾值、批准記錄。
2. 入口清單：每個按鈕、菜单、模型、更新器、網絡接口、分析入口，以及它的實際生產調用鏈。
3. 工程／業務準則清單：每項都有正權重、反例、證據要求；兩條線各自總重 100；硬門仍一票否決。
4. 當前候選發布清單：源码 commit/tree、配置／依賴／數據／模型 hash、Windows 環境、構建與執行記錄、成品 hash。

完成度 = 當前有效 PASS 的凍結權重 / 全部凍結權重；綜合取兩者較低值。任何一條線未核證，綜合也未核證。批准範圍不能在測試失敗後自行縮小；來源缺失、業務不完整、測試未跑都保留在分母。

## 2. 架構：先做模組清楚的桌面程式，不堆分散式服務

每個產品獨立交付，內部採分層模組；不為湊架構而增加 REST 伺服器、消息中間件或多個資料庫。Updater 因替換運行中 EXE 的需要作為獨立進程；驗收控制程式不與業務程式共用「自行宣布成功」的權限。

```text
使用者 → Windows UI → Application Service → Domain / Engine
                            │                   │
                            ├→ Source Adapter → NetClient → 已批准官方來源
                            ├→ Storage（canonical + SQLite ledger）
                            └→ Evidence（成功與失敗的可復核事實）

獨立 Updater → 可信發布清單 → 下載／驗簽／hash → 暫存 → 原子替換 → 健康檢查／回滾

獨立驗收控制 → 冻結基線 + 當前源码／EXE + retained evidence → Final Gate
```

| 層 | 必須負責 | 禁止事項 | SSQ 已有落點 |
|---|---|---|---|
| Domain | 數據實體、類型、不變量 | 容忍非法資料、隱式截斷 | `SSQ/SSQ/glp/domain.py` |
| NetClient | HTTPS、超時、重試、退避、redirect、attempt ledger | 判斷業務正確、把 HTTP 200 等同 PASS | `glp/net_client.py` |
| Source Adapter | 各源解析、完整性、時效、交叉比對、原文收集 | 默認值／快取替代實時成功 | `glp/sources.py` |
| Storage | 原文持久化、canonical、ledger、一致性及恢復 | 失敗覆蓋最後有效資料、只存 hash 不存可復查原文 | `glp/storage.py` |
| Engine | 純計算、模型候選、確定性輸入輸出 | 直接操作 UI、隱式聯網、宣稱未驗證優勢 | `glp/engine.py` |
| Validation | 契約、科學驗證、反例／逆轉驗證 | 根據當次結果修改閾值 | `glp/evidence.py`、`tests/`、`tools/` |
| Service | 編排更新／分析／修復／審計、狀態傳播 | 捕獲錯誤後返回成功 | `glp/service.py` |
| UI | 真實入口、進度、取消、錯誤／結果呈現 | 自行計算 PASS、只展示成功彈窗 | `glp/gui.py` |
| Evidence / Gate | 綁定版本、檢查原始證據、拒絕缺失／衝突 | 信任頂層 PASS 字串、信任自報百分比 | `tools/derive_gate_status.py`、`acceptance/validate_status.py` |

表中落點表示代碼存在及本輪可檢查，不表示整層已驗收。其他 17 個專案須逐項映射實際模組，不能複製 SSQ 表格作完成證明。

## 3. 現有接口及必須保證的契約

| 接口 | 輸入／輸出 | 成功後必須成立 | 失敗處理 |
|---|---|---|---|
| `Draw.from_dict(value)` / `Draw.validate()` | canonical 開獎資料 → `Draw` | 七位 ASCII 期號、真實 ISO 日期、期號年份一致、整數球號、合法範圍與不重複 | `ValueError`；禁止 bool、小數或非法日期被轉成有效開獎 |
| `NetClient.get(url, *, params, headers, timeout, allow_redirects)` | HTTPS request → Response + attempts | connect/read 各自有效；每次請求可追溯；未離開配置來源主機 | 有限重試後拋異常，攜带 attempt ledger；TLS／redirect 違規不放行 |
| `build_canonical(..., failure_sink)` | 已核驗基線及真實來源 → `(CanonicalDataset, evidence)` | schema、內容、時效、來源一致；raw 與 canonical 可重建 | 無 quorum／衝突／缺頁等拋錯，先保留失敗證據；證據寫入也失敗則連同原因上拋 |
| `Store.save_dataset(dataset, evidence)` | dataset + raw 證據 → 持久化 | 校驗原文 hash、canonical hash、ledger；提交後能重新讀取驗證 | 不完整提交不得被當作新有效版本；恢復／回滾失敗明確阻斷 |
| `Store.integrity_check()` | 持久化目錄 → 結構化報告 | 內容與原文／來源／hash 的一致性 | `ok=false` 不能被 Service 或 UI 改成成功 |
| `LottoService.update(progress=None)` | 無人工開獎輸入 → 更新回執 | 官方交叉驗證、持久化校驗及 `official_update` ledger 綁定同一 canonical | 原始錯誤可見；不得因舊資料可用而顯示「更新成功」 |
| `LottoService.predict(progress=None)` | 當前可信資料 → prediction + gate | 輸入／模型／selector／輸出血緣完整；未知優勢輸出 `NO_EDGE` | 不完整／失效輸入阻斷；不得編造預測準確率 |
| `LottoService.repair(progress=None)` | 待恢復狀態 → 修復報告 | 修復後再驗證資料一致性，不僅刪錯誤提示 | 保留損壞與恢復證據；未恢復不能 PASS |
| `LottoService.audit(progress=None)` | 既有資料／預測 → 審計報告 | 可復盤，不暗中新增正式預測凍結 | 審計失敗可見；不能更改歷史使結果變好 |
| `derive_gate_status` | 當前驗收目錄 + Exact EXE → gates | 逐項檢查原文、數值、範圍、hash、實際後端效果 | 缺項／假陽性／混版本一律非 PASS |
| `validate_status` | 狀態報告 + 外部批准基線指紋 → consistency preflight | 格式、清單、文件、引用、身份、權重一致 | 即使預檢 PASS，也固定 `release_authorized=false`，不簽發 FINAL |

輸入邊界原則：來源適配器可以按來源契約解析數字字串，但進入 canonical Domain 後只接受規範型別。不能在 Domain 中用 `int(1.9)` 等方式洗掉錯誤。

## 4. 統一結果契約：設計目標，不冒稱全專案已接入

現有 SSQ 多處返回 dict／異常；跨專案整合時逐接口遷移，不一次性把未實作層換成空包裝。

```text
OperationResult
  schema_version, project_id, operation_id, entry_id, candidate_id
  status: PASS | FAIL | BLOCKED | PENDING
  started_at_utc, finished_at_utc, environment
  input_hash, output_hash, data_version, model_version
  evidence_ids[]
  data: 只有通過該操作後置條件才有有效業務結果
  error: code, stage, safe_message, retryable, cause_evidence_id
```

建議錯誤族：`NET_CONNECT_TIMEOUT`、`NET_READ_TIMEOUT`、`NET_RATE_LIMIT`、`NET_TLS`、`SOURCE_SCHEMA`、`SOURCE_STALE`、`SOURCE_CONFLICT`、`SOURCE_INCOMPLETE`、`STORAGE_INTEGRITY`、`EVIDENCE_WRITE`、`MODEL_UNQUALIFIED`、`UPDATER_VERIFY`、`UPDATER_ROLLBACK`。這是待實作／測試的接口規格，不是新增 PASS。

每個入口都必須記錄操作 ID；UI 與後台、ledger、raw、候選 EXE 一一對應。進度回调不是成功事件；只有持久化後置條件成立才可返回成功。

## 5. 聯網策略與已知邊界

SSQ 可核查配置：CWL 主源、上海／河北官方輔源；production `connect=20s`、`read=30s`、`max_attempts=3`（包括首次）、exponential backoff + jitter；408／429／5xx 有界重試，遵守可接受的 Retry-After；HTTPS 同主機 redirect 有界，拒絕降級。這些只是現有設定，不是 18 專案的共同性能 SLA。

本輪需要保留的改進缺口：

- connect/read timeout 不是整個操作的總截止時間；慢速持續回應、分頁總耗時、取消與同時更新仍須專項驗收。
- 目前來源層的 8 MiB 檢查是在讀取 body 之後；不能聲稱已具備串流過程記憶體上限。
- 最新資料年齡目前是固定 7 日窗口；不是逐期「應開獎時間／節假日／官方延遲」時效模型。
- transport attempts 有記錄，不代表所有中間重試的原始 response 都已完整保留；必須逐失敗模式核對。
- 程式自己寫出的回執只能證明一致性，不能單獨證明執行真實性；需要受控 runner／EXE／GUI／原始響應的相互佐證。

不要為了讓網站可達而關閉 TLS 校驗、把 https 改成 http、繞過網站保護或更換未批准來源。官方來源持續不可用應標記 UNAVAILABLE／BLOCKED，保留有限重試證據。

### 聯網驗收矩陣

| 情境 | 測試方式 | 必須觀察的結果 | 必須保留 |
|---|---|---|---|
| 官方實時成功 | 生產 Source → NetClient → Store | schema／內容／時效／quorum 全過；落盤與回讀一致 | requested/final URL、UTC、status、raw bytes、SHA-256、parser版本、canonical、ledger |
| 主源403，批准備源有效 | 官方實網 + 受控契約反例 | 主源保留 FAIL；備源只按原批准策略接管，不改寫主源結果 | 每源獨立狀態與交叉比對 |
| 全部不可用 | 受控斷網；另有真實故障則獨立保存 | 操作失敗；原有效資料不被覆蓋；UI 不顯示更新成功 | attempts、原異常、前後資料hash、UI錯誤 |
| 429／5xx／連線與讀取超時 | 可控 transport 故障注入 | 次數／延遲有界，指數退避和 jitter 合約正確 | 每次嘗試、delay、最終錯誤；不能標成真實來源成功 |
| 200但HTML錯頁／空資料／schema漂移 | 保存的fixture反例 + live原文解析 | 200也拒絕；不產生正常分析結果 | 原文、解析錯誤、schema版本 |
| 過期／未來資料／缺頁／來源衝突 | 可控反例 | 不拼接出假一致資料；Fail-Closed | 衝突明細與拒絕原因 |
| SSL錯誤／跨域／HTTPS降級 | 可控 transport 反例 | 拒絕；未向未批准主機傳送後續請求 | redirect鏈／異常與請求次數 |
| 中途崩潰／磁碟滿／證據寫入失败 | 獨立測試目錄故障注入 | 不出現半成功；重新啟動能辨識待恢復交易 | 前後hash、交易標记、恢復／回滾結果 |
| 同一成品GUI聯網 | Windows Exact EXE 實體點擊更新 | 同一操作到真實來源；UI、後端、ledger、raw一致 | EXE hash、PID、控件ID／點擊、畫面、回執、後端效果 |
| 同一成品GUI失敗 | 同一Exact EXE受控斷網／資料錯誤 | 真實錯誤呈現，無成功提示，既有資料不被冒充新資料 | 錯誤畫面、後端拒絕、故障注入條件 |
| Updater真發布 | 已批准發布端點 + 實際候選安裝包 | 可信清單、hash／身份、替換、健康檢查／回滾 | 清單原文、下載原文／檔案、前後hash、獨立進程證據 |

Source-level live PASS、Exact-EXE CLI live PASS、GUI-triggered live PASS 是三種不同證據，不互相替代。測試使用 fixture 是允許的，但其證據分類必须是 UNIT／CONTRACT／CONTROLLED_FAULT，絕不可混成 REAL_NETWORK。

## 6. 減少 Bug 的實際方法

1. 在 Domain 與輸入解析處用嚴格型別／不變量；拒絕 bool 假冒 int、小數截斷、NaN／Infinity、非真實日期、未知 schema。
2. 生產端與驗收端用同一版本化契約，但驗收端仍獨立重算關鍵結果。未知 schema 不猜測兼容；升級時生產者／消費者／反例測試同步變更。
3. 先寫會失敗的回歸反例，再做最小修復；不為保留某個結果修改業務閾值。
4. CI 分層：快速 deterministic Unit／Contract → Integration／Fault → 真實網絡 → Windows Build → Exact EXE → GUI成功與失敗 → Same Hash → Final。
5. 同一 active candidate 只維持一條明確集成路徑；並行任務按文件／模組分工，明確 SHA；不把不同分支各自的綠燈拼成一次驗收。
6. 測試 Gate 本身：缺檢查項、重複項、假 PASS 字串、NaN、錯 seed、混 EXE、偽造 hash、錯誤原文、舊版本回執，都要有拒絕測試。
7. 模型採樣本外／walk-forward、baseline、bootstrap、ablation、多種子／窗口、reality check、多重比較；沒有穩定優勢就淘汰／降級，不保證彩票或投資收益。
8. Windows 實測中文／空格路徑、普通帳號、只讀／磁碟滿、重入操作、網路恢復、關閉中任務、重新啟動、Updater中斷；測試清單未全跑完不能聲稱少 Bug 已驗收。

不承諾零 Bug。承諾的是：可定位、可復現、有反例防回歸、有失敗閉鎖、可回滾，並且不隱藏剩餘風險。

## 7. 科學驗收與禁止空殼

一個 `status=PASS` 的 JSON 不足以通過。驗收需核對全部命名檢查項、有限實數及整數型別、当前模型／selector／policy 的指紋、court hash、隨機世界的指定 seed、`NO_EDGE / NULL_DAN`、零資料洩漏，以及實際對應的原始測試輸出。

即使科學流水線正常執行，也不能把「算法程序正常」說成「模型已證明能預測」。這兩個結論分欄記錄。業務 100% 仍需逐一滿足原始用戶目的、內容範圍、案例與實際使用價值。

本輪獨立審查另復現：只改正向升格旗標並重算 hash，不能證明其統計前提。當前驗收器因此明確阻斷 `EDGE_PROVEN / CERTIFIED_DAN`，直到獨立重算全部升格前提的驗證器完成；正常 `NO_EDGE / NULL_DAN` 必須仍以 uniform baseline 作 Champion，research 權重為零。這是尚未完成的正向升格驗收能力，不得宣稱全部科學驗收已閉環。現有逆轉檢查的 audit court hash 獨立重算仍須補齊。

每個交付入口必須對上：`requirement_id → entry_id → implementation → production_call_path → real_input → output/effect → positive_test + negative_test → candidate-bound Evidence`。少一項就非 PASS。沒有用途的空模組不能用文件描述來補齊。

## 8. 長期可用不是一次構建成功

逐專案批准並測試：資料備份／恢復、schema遷移、來源變更偵測、操作錯誤支援、依賴鎖定與安全維護、更新信任根、回滾／降版攻擊防護、原文隱私與保存期、敏感憑證保護、維護責任與退出／資料匯出。尚未確認的保存期／性能／恢復時間不能自行填成合格。

Same Hash 指測試、展示和交付是同一位元組成品；不能據此宣稱另一台機器重建必然得到相同 hash。可重現構建需另外核證工具鏈、環境、依賴與非確定性輸入。

唯一成品指每個產品在同一發布範圍內有唯一獲批准版本與清單；不刪除可回滾歷史或失敗審計證據。

## 9. 本轮推进顺序与退出条件

1. 完成實際架構／入口／接口對照，確定一條候選集成路徑。
2. 修復已復現的 Domain 輸入漏洞與 Gate 假陽性；跑全量回歸並保存輸出。
3. 直接使用生產來源和存儲流程執行新的 Real Network；失敗也完整保留，無網絡權限時標記 BLOCKED。
4. 將變更送審，不自動合併或發布；當前候選重新執行 Windows／Exact EXE／GUI／Same Hash，不繼承舊驗收。
5. 補齊其餘專案各自的業務／來源／入口驗收；缺源碼專案維持 BLOCKED 並繼續恢復，不能假裝已有完整實作。

階段報告必填：工程／業務／綜合完成度、已完成、真實 PASS（限定證據範圍）、未完成、BLOCKED、FAIL、最大風險、下一個可驗收產物、Final Gate、唯一成品 YES／NO。

**只有当前完整候选的工程100%、业务100%、全部强制硬门PASS，才允许整体 Final Gate PASS。**
