# SSQ 前瞻 Replay 科學資格硬閘（2026-10-08，獨立修復候選）

狀態：**研究候選／FAIL-CLOSED**，不代表模型已取得可證明的命中優勢，也不代表 Windows 最終 EXE 驗收通過。

## 根因（5 Why）

本地 SQLite `freezes` + `replays` 可以記錄預測及開獎後的回顧，卻**無法單憑自報的時間或 SHA-256 證明該筆預測確實在官方開獎前已對外不可變地公示**。舊版 Evidence Court 僅依 selector 查詢並按 Replay 行數計數；空白 selector／非 dict 可被視作一致。這允許重複、補登或造假的 Replay 污染前瞻樣本數。

## 此修復的硬邊界

- 本機 Replay 繼續保留作為**歷史回顧／故障分析**，不作為已資格確認的前瞻樣本。
- `LottoService._prospective_replays` 現將本機資料全部列為未核實，記錄 `local_replay_rows`、`selector_matched_local_rows`、`qualified_replays=0`，並只向正式 Evidence Court 提供空的已核實清單。
- `run_evidence_court` **獨立保留第二道硬閘**：直接輸入的 Replay JSON 同樣不得自我授權，`qualified_count=0`，必須區分 `historical_edge_candidate` 與經未來期號驗證的 `EDGE_PROVEN`；不滿足前瞻最低數量則為 `NO_EDGE / NULL_DAN`。
- 空白、遺失或類型錯誤的 selector 一律視為不一致；偽造 `provenance_verified: true` 不構成授權。
- 舊 Evidence Court 快取即使原來聲稱 PASS／EDGE_PROVEN／CERTIFIED_DAN，也不能跳過新資格硬閘。
- **不得**把這道保護解釋成「30 期資格已完成」。真正業務阻斷仍未解除。

## 將來允許驗證的證據要求（尚未實施，不是假 PASS）

1. 獨立且可追溯的 GitHub（或具同等證明力）開獎前持久不可變 Freeze，簽定 exact 代碼／模型／selector／源資料摘要、實際預測和當時時間；後補禁止。
2. 每期重取官方來源並核對真實 6 紅 + 1 藍、期號／日期、來源原始資料及驗證雜湊。
3. 按 Freeze 重算 Replay 和隨機基線，拒絕重複及不匹配 cohort，滿足規定的至少 30 筆未來真實樣本後，仍需統計／逆轉驗證及額外生產升格授權。
4. 同步完成 SSQ 自己的獨立 Repository、原生 Windows Build、Exact EXE、實體 GUI、Same Hash、獨立 Updater N→N+1、Final Gate。

SSQ 與 DLT 的代碼、模型、數據、發布仍然完全獨立。這份候選修復不修改 DLT 產品或其研究 Protocol，也不合併獨立成品。
