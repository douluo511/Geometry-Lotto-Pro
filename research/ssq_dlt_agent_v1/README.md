# SSQ＋DLT V4.5 研究與交付 Agent 1.0

一個 OpenAI Agents SDK Agent，只有五組封裝工具。資料、固定版本選號、統計、帳本與准入由應用程式管理。所有結果仍為 **A=0、NO_EDGE、下一合法期 BLOCKED**。不自動購彩。

## 邊界與工具

|工具|可以做|停止條件|
|---|---|---|
|discover_sources|固定五組 AnySearch 查詢，原文與 SHA 留本地|權限、來源、傳輸或完整性失敗如實保留；搜尋結果不能指派期號|
|verify_official_sources|核對兩份 SHA 固定歷史及官方白名單來源|未來／當日可用性不明、缺期、重複、來源衝突均 BLOCKED|
|run_frozen_models|只用已核驗帳本快照執行五個原版研究模型|沒有兩彩種完整歷史就停止；只可輸出 UNASSIGNED，不得替換正式八槽|
|audit_experiment|審計、登記一個可反證假說、執行已批准的合成診斷|禁止任意程式／參數／種子／重評歷史鎖定測試集；前瞻實驗尚未開放|
|deliver_report|由帳本重建 JSON／HTML；收尾才建立待發郵件|不採信模型文字的 PASS、SENT、A=1 或 EDGE 宣稱；不提供 SMTP 發送工具|

固定診斷 `synthetic_pair_shrink`：window=60、tau=200、seed=20261018、每彩種20個合成案例。以精確分數核對全部號碼對排序和 D2；沒有使用歷史開獎或評估命中率。相同均勻收縮保持排序，不能宣稱提升。`prospective_d2` 只接受空參數並回傳 BLOCKED_NOT_RUN。其他模型／窗口／參數須先人工修改審查工具實作，不讓 Agent 自行執行程式。

## 安裝及運行

Python 3.11、Windows；安裝 `requirements.txt`。三種模式必須明確區分：

```powershell
python -m research.ssq_dlt_agent_v1 --config C:\GLP\agent-config.json --mode tools-smoke --run-key tools-001
python -m research.ssq_dlt_agent_v1 --config C:\GLP\agent-config.json --mode sdk-fixture --run-key fixture-001
python -m research.ssq_dlt_agent_v1 --config C:\GLP\agent-config.json --mode live
python -m research.ssq_dlt_agent_v1.acceptance --output C:\GLP\new-acceptance
```

`tools-smoke` 實際執行工具但沒有模型；`sdk-fixture` 使用真正 SDK 的工具迴圈搭配固定模擬模型，模型不呼叫 OpenAI HTTP API、付費模型呼叫為0。這兩種模式的工具仍會按配置執行真實 AnySearch／官方資料網路請求；它們都不能算作 live 模型驗收。live 必須明確配置環境 `OPENAI_API_KEY`、`GLP_AGENT_MODEL`，並在 sdk 配置提供已核對的每百萬輸入／輸出 token 價格。缺少任何一項即 BLOCKED，不推測模型與價格。固定官方 Responses API；忽略自定 base URL，拒絕自定標頭，停用代理、重導向、SDK 重試與 tracing。不得把金鑰寫入配置、報告或帳本。

配置只接受 state_dir、history、live_sources、discovery、recipient、limits、sdk；樣例見 config.example.json。state_dir 必須與歷史輸入分開，使用新的專屬 SQLite application_id；不接管原始 SQLite。報告有私人路徑及模型輸出，只留在受信任本地。

預設每輪10 turns、8次模型呼叫、每次最多20,000估算輸入／1,000輸出 tokens、工具12次、時間120秒、本地預估費用上限0.20美元。每次先按完整輸入額度預留費用，預留不因少用而退回。這是保守估算，並非服務商硬性帳單上限。同步工具只在前後檢查時間，HTTP有界；不是可強制中止程序的截止保證。主程式保留一次不經模型工具額度的本地收尾，仍核對程式、配置與時鐘。

## 記憶、故障與重跑

run_key 預設為最近的日本時間週一／三／六16:00 slot；模式、模型名稱、配置 SHA、程式 SHA 綁定 run_key。已完成執行重用原結果。並發以 SQLite BEGIN IMMEDIATE 序列化；先記 claim 再執行，重啟看見未完成 claim 即 UNKNOWN_REQUIRES_RECONCILIATION，不能盲目再呼叫模型或重做外部效果。已保存的失敗／BLOCKED 也不可覆寫；修復後用新 run_key，保留舊失敗期。

AnySearch 與官方 HTTP adapter 自己按有界重試處理傳輸錯誤；Agent 不額外重試已記錄的外部效果。配置 max_attempts_per_tool 是硬上界，當前更嚴格為每個規範化工具請求只執行一次。SQLite UPDATE／DELETE／REPLACE 均拒絕，所有 payload 核對 canonical JSON／SHA。這不能防止檔案擁有者重建 SQLite，更不是外部 TSA。未知付費呼叫的付費次數為 null，並保留 attempted count。

模型中途 deliver 只存檔；完成或停止後，host 必定保存完整用量的最終報告，再按 run_id＋完整 report SHA 去重建立一封 EML／outbox。不會自動發送。HTML 的 QUEUE_PREPARATION_PENDING 是生成時狀態；實際是否排隊請看執行回執 delivery。

## Windows 排程

scripts/Install-V45AgentTask.ps1 預設只匯出 XML 和 deployment manifest，不執行 Agent、不註冊。它固定 live、JST 週一三六16:00（XML UTC07:00）、開機、每30分鐘補跑、IgnoreNew；隱藏執行。manifest 固定 Agent、V45、V44、配置、venv 與基礎 Python SHA。scripts/Run-V45Agent.ps1 驗證後才啟動。缺 key 回傳 BLOCKED，絕不切換測試模型。實際註冊需要管理員及相符的 live 成功回執；匯出 XML 不能算已安裝或已按時運行。

原始正式八槽、01/02/03/04批准、可信外部事前封存與合格前瞻期次未取得；真實冷開機、經過30分鐘、斷網、斷電與外部 TSA 故障未測時必須 NOT_RUN。完整 P0 及正式准入維持 BLOCKED。固定成本比較的 SSQ D2 隨機基準15/528、DLT10/595，尚無獨立前瞻證據證明提升。

官方參考：https://developers.openai.com/api/docs/guides/agents/sdk 與 https://developers.openai.com/api/docs/guides/agents/quickstart。
