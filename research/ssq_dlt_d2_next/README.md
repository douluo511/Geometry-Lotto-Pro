# SSQ＋DLT D2 機制研究 R46

此模組是隔離研究執行器，不是正式出號器。目標固定：每彩種、每期、每模型僅一組兩膽，檢查兩個號碼是否全部出現。正式八槽、原主D2、原種子及舊封存結果不變。沒有自動購彩或寄信。

## 為什麼做這兩個改進

公平且獨立的 k-of-N 開獎下，任何只用過去資訊選出的兩膽，下一期全中機率必為 k(k−1)/(N(N−1))：SSQ15/528，DLT10/595。更複雜的提示詞或排序無法繞過此條件。要提高命中率，必須找到能在未來重現的非均勻性或交互作用；本輪只測這些機制能否被方法辨識。

純 conditional-Bernoulli 聯合機率本身不改top-two權重排序。交換公式為 q_aj−q_bj = w_j(w_a−w_b)e_(k−2)(w_without_a_b_j)/e_k(w)，正權重時符號由w_a−w_b決定。因此不把精確joint公式包裝成新選號優勢。

1. **R46-CBPAIR-SHRINK 1.0.0**：最近240期單號計數加200期均勻pseudo-draws，再轉odds，形成固定k product-weight分布；其pair q與最近60期經驗分布按200:60混合。非均勻prior可改D2，混合分布仍合法。這是surrogate odds，條件化後邊際未必等於輸入收縮邊際，不是精確MLE；重疊資料不能稱獨立Bayesian prior。
2. **R46-REPLICATED-PAIR 1.0.0**：最近兩個不重疊60期區塊，各計 `(h−60q)/sqrt(60q(1−q)+1)`，取兩分數較小者，再選最大pair；最大分數不正則回到固定top-two長期odds。兩塊共享240期估計的q，因此不是獨立驗證；z不是常態p值。

所有參數、12位小數tie rule與fallback都在registry及執行前plan內固定，沒有參數搜尋。公開CB機率及sampler以完整小子集／Decimal核對，極小normalizer直接使用log DP。

## 實驗界線

舊plan SHA必須等於 `ce4545aa00941cda7fe2868d63d5900432779a50ec1d7a4f3f8edff8ff9c0720`；只允許原SSQ前1293行（截止2021088）、DLT前1809行（截止19027），物理匯出成兩個開發檔。統一warmup240後，SSQ1053期、DLT1569期。日期嚴格遞增、期序完整，train_date必小於target_date。

舊validation/test不能重新評分，所有新模型的歷史數字都只算**已暴露開發資料探索**。完整比較包含Hot60、EWMA、ShrinkMix、Pairwise-D2、Pair-Residual、固定seed20261018 Random NULL及兩個新候選。14項非NULL比較做Holm，但不得從開發結果選正式模型。

合成控制在方案封存後才執行：seed2026101901，每格12replications、240warmup＋240評分期；FAIR、強marginal、弱pair、強pair、pair反轉、逐期label打散、固定隱藏環、逐期重排環。環混合ρ=.25保持每個單號真邊際k/N，只有pair交互作用；每期重排回到公平可觀測分布。生成器參考pair不進入預測函式。

每個完整開獎才是一個Brier觀測，不把528/595個相依pair當成獨立樣本。三個負控制×兩模型×兩彩種的12個公平null p固定Holm；正控制只做預先規定的point diagnostic，不能轉稱彩票證據。弱訊號和反轉結果不刪。

## 事前登記、執行與核驗

```powershell
python -m research.ssq_dlt_d2_next prepare --legacy-plan C:\GLP\old-study\plan.json --history-config C:\GLP\old-config.json --output C:\GLP\new-study
python -m research.ssq_dlt_d2_next execute --output C:\GLP\new-study
python -m research.ssq_dlt_d2_next verify --output C:\GLP\new-study
python -m research.ssq_dlt_d2_next.acceptance --output C:\GLP\new-acceptance
```

prepare固定程式SHA、模型、種子、資料前綴、功效與停止規則；SQLite登記後不可覆寫。execute先記claim，每期先留預測再評分。結果完整才可cache重用；未知中斷保留claim並停止，不能重抽種子。verify核對全部期、每組D2、評分、CSV／JSON與SHA。這是本地一致性紀錄，不是外部TSA。

## 未來驗證仍未啟動

固定兩候選×兩遊戲，Holm家族4；IUT取對公平p0與同期NULL兩個p的較大值。+1pp只是規劃alternative，不能稱已證明至少提升1pp。固定n按analytic與worst-discordance兩分量90%規劃取較大、向上round100：SSQ8300、DLT5500。2000rep/cell、seed2026101903、3種joint law×4個效果配置只驗統計設計，不是檢驗實際候選能力，也非全部16種配置。

確認gate不另加CI下界或observed delta>=.01，否則原規劃功效失效。配對McNemar／CI需可辯護IID；滾動訓練未證明此條件，故確認仍BLOCKED。可信事前封存、官方下一合法期與截止時間、正式批准及全新獨立期次均缺失。A=0、NO_EDGE、前瞻樣本0，共享儲存庫獨立性與Final Gate FAIL。

Agent v1尚未獲准自動執行這些新模型；本輪由隔離CLI受控執行，沒有偷偷擴張其五組工具權限或改正式主D2。

原始參考：
- 官方SSQ規則：https://www.scflcp.com.cn/yxgz/823145252.jhtml
- 官方DLT規則：https://m.lottery.gov.cn/ksjz/m/yxgz_dlt/
- Aubry, conditional Poisson算法與joint inclusion：https://pmc.ncbi.nlm.nih.gov/articles/PMC12830118/
- NIST比例區間：https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm
- R Holm校正：https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html

上述理論不構成任何彩票存在偏差的證據。
