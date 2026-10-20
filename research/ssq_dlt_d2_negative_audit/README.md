# 原始69/2880負控制鑑識

只重播已公開的原seed2026101901、DLT/SCRAMBLED_PAIR_STRONG、12條原流、2880個已評分prefix。這不是新seed試驗、新彩票模型、未知測試集或前瞻證據；不改正式主D2及01–04准入。

每流保留原生Random、未使用ring初始化、tilted sampling/rejection及每期完整重標排列的順序與RNG前後狀態摘要。逐期檢查四個凍結模型及固定參照pair、原front、hit與Brier；保留36個prefix界線及target/future擾動檢查。後者不證明真實歷史資料當時已可取得。

獨立Decimal80統計程式重新計算原12項單尾負控家族及Holm校正，不改成雙尾、不改alpha、不刪其他比較。微型全排列枚舉驗證「獨立均勻重標」的數學映射；它不證明有限Mersenne Twister流獨立，也不解釋特定seed為何命中69次。

`PASS_ORIGINAL_SEED_REPLAY_AND_INTEGRITY_ONLY`只表示重建與完整性通過。原負控仍為`FALSIFIED_REPRODUCED_NOT_FIXED`；若沒有找出並反證具體因果缺陷，原因保持`UNRESOLVED`。不能把新的不顯著結果當作已修復，也不能將這個已暴露cell用來選新模型。

輸入僅四份已封存JSON：原plan、synthetic、decision與49來源清單的science plan。原SHA固定在程式中。所有輸出用新目錄、獨占建立及fsync保存；完成後verify只讀雜湊與回執，不重新跑模型；中斷後不自動重跑。全程不開任何SQLite、不讀舊彩票development/validation/test、不連網。

```powershell
python -m research.ssq_dlt_d2_negative_audit prepare --output C:/LottoAudit/new-run --original-plan C:/Original/plan.json --original-synthetic C:/Original/synthetic.json --original-decision C:/Original/decision.json --science-plan C:/Original/forensics-plan.json
python -m research.ssq_dlt_d2_negative_audit execute --output C:/LottoAudit/new-run
python -m research.ssq_dlt_d2_negative_audit verify --output C:/LottoAudit/new-run
```

上述Original路徑是結構範例，必須指向指定原SHA的真實檔案。輸出目錄必須在原件父目錄之外且尚未存在。Python版本及全部審計來源也會鎖定；改碼後須新建審計目錄，舊證據不可覆寫。

新評分S=alpha U+beta R+gamma C尚未新增：原Pairwise已枚舉全pair；CBPAIR可寫為q+[60/(60+200)](h/60−q)；REPLICATED已採兩個不重疊60窗殘差min。新U/R/C必須先定義量綱、固定k基準、與既有模型的非等價性、資料共享及反證條件。未提供完整規格時狀態是BLOCKED_SPEC，不能隨意定權重再重用舊test。

工程審計PASS不等於負控通過，更不等於D2提升。A=0、NO_EDGE、合格前瞻樣本0；官方下一合法期及可信事前封存BLOCKED。倉庫獨立性與Final Gate仍FAIL。
