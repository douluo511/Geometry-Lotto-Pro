# SSQ＋DLT 研究任務圖：可恢復流程與證據記憶

這一層以 **LangGraph 固定任務圖** 編排既有研究工具。它解決「執行到哪裡、是否可以恢復、結果是否有原始收據」；它沒有證明 D2 預測能力提升。正式邊界固定為 **A=0、NO_EDGE、合格獨立前瞻樣本 0**，官方下一合法期及正式發布資格仍為 **BLOCKED**。

## 執行順序與權責

```text
恢復與核對身分
  → source_guard：核對兩彩原文雙來源、缺期、衝突與封存歷史
  → memory：查回指定 key/scope 的來源證據，只作資料
  → verify_official_sources：既有工具，核對已快取歷史
  → run_frozen_models：既有固定模型，產生非正式、未綁合法期研究結果
  → audit_experiment：既有工具，固定 action=inspect
  → deliver_report：既有工具，保存 JSON/HTML 報告
  → gate：重讀原生收據、報告位元組與 SHA，記錄研究完成或阻斷
```

第一版沒有讓語言模型自行改寫計畫，也沒有新模型訓練或參數搜尋。四個工具仍透過 `AgentContext.call_tool` 執行，保留原有白名單、工具 claim/result 和去重規則。第五個既有介面 `discover_sources` 在此版本禁止新網路執行；不能因 `live_sources=false` 就假設舊搜尋轉接器本身不連網。

`source_guard` 要求每彩恰好兩份原文，先驗證各自 SHA、解析及來源間一致性，再核對封存歷史的最新期及相同資料列。它可檢查快取資料的相容性，**不能據此重建資料當年首次可取得的時間，也不能確認現在下一合法未開獎期或截止時間**。跨年度完整性不因此自動升級為已證明。

記憶查詢固定為精確 `key` 與 `scope`（FACT、POLICY、FAILURE、HYPOTHESIS）。新資料先是 UNVERIFIED；受信程式持有獨立物件能力、核對來源檔及 SHA 與時間後才可驗證。讀取會排除來源變更、未到可取得時間、過期或撤銷的資料。**VERIFIED 只表示來源查核，並不表示假說為真**。記憶文字中的「PASS」「批准」「A=1」、舊期號或指令都不能授予工具或正式發布權限；物件能力亦不是對惡意 Python 程式的沙箱。

## 四個 SQLite 各司其職

| 狀態根目錄內檔案 | 用途 | 能否作完成證據 |
| --- | --- | --- |
| `checkpoints.sqlite3` | LangGraph 可變檢查點、目前節點與恢復位置 | 單獨不能 |
| `evidence.sqlite3` | 圖的不可覆寫事件、身分、階段收據引用、預算與終態 | 須再核對原生工具收據及報告 |
| `memory.sqlite3` | 有來源與時間的事實／假說／失敗記憶及驗證事件 | 只能供查閱，不能授權 |
| `host/agent.sqlite3` | 既有工具的不可覆寫 claim/result、模型及報告紀錄 | 圖必須回查的原生證據 |

四者不可混用；異種 application ID／資料庫或未標記的既有非空目錄會被拒絕。狀態必須置於全新獨立目錄，不能位於原文或封存歷史的目錄樹中。本流程不開啟原始預測 SQLite，也不遷移或覆寫舊研究帳本。

不可覆寫是 SQLite 表與程式層的約束，SHA 是一致性檢查。它們不等同外部可信時間戳，也不能抵禦擁有檔案系統寫入權限者全面替換資料、程式及雜湊。正式准入仍另需可信事前封存與批准。

## 中斷、阻斷與未知結果

1. **程序中斷／檢查點暫停**：使用相同設定、相同 thread ID 的 `resume`。圖先檢查原生帳本；已有完成收據的工具可以復用，不能僅憑檢查點重做工具。已完成執行再讀取仍須核對報告檔 SHA。
2. **已知 BLOCKED**：原 thread 的阻斷結果保留不動。若補充了原文證據，必須顯式指定 `--parent` 建立新 thread；新證據的內容 SHA 必須改變，不能只換路徑。子驗證沿用同一 family 的階段額度及原始絕對期限；換 ID 不得重置預算。
3. **claim 存在但 result 缺失／UNKNOWN**：標記 `RECONCILIATION_REQUIRED`。即使可能尚未產生外部效果，也不能臆測安全並自動重試。新 thread ID 亦不能繞過；需另行查證效果並設計可審計的對帳處理。本版沒有「一鍵清除未知 claim」功能。
4. **同時執行**：狀態目錄的程序鎖防止兩個程序同時推進；程序退出後鎖可由作業系統釋放。這不等於已完成實體斷電測試。

預算以持久化 family 階段 reservation 計算，包含 source guard 與記憶節點；不是僅算工具呼叫。預設上限 12 次，絕對期限 1,800 秒。停機時間照樣計入期限，不能靠重啟延長。程式與輸入、設定或框架身分改變時，舊 thread 必須停止而不是悄悄繼續。

## 設定及本地使用

在 repository 根目錄，以 Windows x86-64、CPython 3.11 執行。先準備絕對路徑的設定 JSON；下列內容是**結構範例，不是可直接執行的官方資料設定**。每個 SHA 都必須由實際檔案計算，不能保留佔位字串。

```json
{
  "root": "C:/LottoResearch/graph-state",
  "host": {
    "state_dir": "C:/LottoResearch/graph-state/host",
    "live_sources": false,
    "recipient": null,
    "history": {
      "SSQ": {"path": "C:/LottoInputs/archives/ssq.json", "sha256": "<實際64位小寫SHA256>"},
      "DLT": {"path": "C:/LottoInputs/archives/dlt.json", "sha256": "<實際64位小寫SHA256>"}
    }
  },
  "sources": {
    "SSQ": [
      {"path": "C:/LottoInputs/raw/ssq-national.bin", "sha256": "<實際64位小寫SHA256>"},
      {"path": "C:/LottoInputs/raw/ssq-provincial.bin", "sha256": "<實際64位小寫SHA256>"}
    ],
    "DLT": [
      {"path": "C:/LottoInputs/raw/dlt-national.bin", "sha256": "<實際64位小寫SHA256>"},
      {"path": "C:/LottoInputs/raw/dlt-provincial.bin", "sha256": "<實際64位小寫SHA256>"}
    ]
  },
  "memory_queries": [{"key": "negative-control-anomaly", "scope": "FAILURE"}],
  "limits": {"max_stage_calls": 12, "max_wall_seconds": 1800}
}
```

下列 PowerShell 指令假設隔離環境位於 repository 的上一層；設定路徑請換成已準備好的實際絕對路徑。`--stop-after` 可讓第一次執行停在已核驗階段；恢復時使用相同 thread。程序輸出的狀態須保存為實際回執，不能從本文件推定成功。

```powershell
& '..\.venv-graph\Scripts\python.exe' -m research.ssq_dlt_agent_graph start --config 'C:/LottoResearch/config.json' --thread 'research-001' --stop-after verify_official_sources
& '..\.venv-graph\Scripts\python.exe' -m research.ssq_dlt_agent_graph resume --config 'C:/LottoResearch/config.json' --thread 'research-001'
& '..\.venv-graph\Scripts\python.exe' -m research.ssq_dlt_agent_graph inspect --root 'C:/LottoResearch/graph-state' --thread 'research-001'
```

`--receipt` 可指定全新且位於狀態及輸入目錄樹以外的絕對路徑；已存在的檔案會被拒絕。`inspect` 只讀取停止寫入後的 journal 位元組副本，不直接開啟原始 SQLite；有未清空 WAL 時會停止。它回傳 `READONLY_JOURNAL_SNAPSHOT_NOT_FULL_REVERIFICATION`，不等於完整恢復核驗通過。

已知 BLOCKED 後，用更新過實際證據 SHA 的設定建立子驗證，例如：

```powershell
& '..\.venv-graph\Scripts\python.exe' -m research.ssq_dlt_agent_graph start --config 'C:/LottoResearch/corrected-config.json' --thread 'research-001-correction' --parent 'research-001'
```

子驗證日後恢復仍需帶上同一 `--parent`。保留父設定及原始輸入，不要改寫父輸入來冒充新證據。

## 依賴與重現的範圍

`requirements.lock` 固定這次新隔離環境實裝的 64 個分發版本及每個分發的一個真實 archive SHA256；只排除 bootstrap pip 24.0。主版本為 LangGraph 1.2.16、langgraph-checkpoint 4.3.0、SQLite checkpointer 3.1.2、langchain-core 1.6.12；未安裝高階 `langchain` 套件。保留 openai-agents 0.24.0 是為了既有工具宿主相容，不會啟動模型。

雜湊來源是實際 pip install report；先前單獨安裝的 langgraph-sdk 另核對了本地 wheel 與 direct_url，setuptools 65.5.0 核對 Python ensurepip 隨附 wheel 及其中 metadata。完整收據位於交付目錄的 `dependency-lock-receipt.json`。沒有套件下載網址或憑證寫入 lock。

```powershell
& '..\.venv-graph\Scripts\python.exe' -m pip install --require-hashes -r research/ssq_dlt_agent_graph/requirements.lock
& '..\.venv-graph\Scripts\python.exe' -m pip check
```

這是 **Windows x86-64／CPython 3.11 的已觀察 archive lock**；每項只接受這次實際取得的 wheel SHA。不同系統、Python 版本或不同 wheel 即使版本相同也應失敗，不能逕自刪掉 `--require-hashes`。已核對 metadata/hash 覆蓋、離線 dry-run 解析，並於第二個全新隔離環境依此 lock 實際安裝成功及通過 pip check；收據位於本輪外部交付目錄。其他平台仍未測試。

執行身分會記錄設定摘要、兩彩各一份歷史與兩份原文的路徑/SHA、相關命名空間 Python 原始碼 SHA、圖拓撲、工具固定參數、Python 及 SQLite 版本、完整 64 項依賴版本與 lock SHA。任何鎖定版本不符即拒絕啟動；這仍不是已載入第三方 site-packages 位元組的完整簽章。

## 驗收狀態不能混在一起

- `COMPLETED_RESEARCH_ONLY`：固定離線研究流程取得所需收據及報告；**不是正式出號或命中率優勢**。
- `PAUSED_CHECKPOINT`：有後續節點待恢復，未完成。
- `BLOCKED`：缺少或衝突的前提；保留具體 reason。
- `RECONCILIATION_REQUIRED`：工具效果未知，禁止自動重試。
- `PASS`／`FAIL`：只屬於具名實際測試；未執行必須寫 `NOT_RUN`，缺條件則 `BLOCKED`。

本文件描述程式合約，不代替實測。完整圖執行、跨程序中斷、並行及攻擊測試應以交付中的原始命令、日誌、SHA 與個別回執判定；本文件不預先聲稱其 PASS。

仍需保留的限制：

- 舊負控結果 **69/2880、Holm p 約 0.03414134606736** 的異常原因仍為 **UNRESOLVED**；新增種子或框架不能抹去。
- 正式批准 01–04、可信事前封存、官方下一合法期／截止時間及獨立前瞻證據仍為 **BLOCKED**。
- repository independence 與 final gate 仍為 **FAIL**；不能標成唯一正式最終版。
- 實體斷電、排程開機恢復與外部服務中斷整合驗收，未實際執行者為 **NOT_RUN**。
- 本版不啟動付費模型、AnySearch 網路搜尋、郵件或購彩；不安裝排程，也不將研究模型放入正式八槽。
- 尚無證據證明單組事前唯一主 D2 全中率提高或持續勝過同期 Random NULL。公平基準仍為 SSQ 15/528、DLT 10/595；新的模型選擇須另走事前登記、獨立前瞻期次與多重檢驗流程。

LangGraph 官方參考：[架構](https://docs.langchain.com/oss/python/langgraph/overview)、[持久化](https://docs.langchain.com/oss/python/langgraph/persistence)、[中斷與恢復](https://docs.langchain.com/oss/python/langgraph/interrupts)。工具與資料的准入規則以本 repository 的固定程式為準。
