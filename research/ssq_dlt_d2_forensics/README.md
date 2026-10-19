# D2異常追查與概率機制分解

本模組延續R46，但不修改其候選、參數、種子、歷史研究或正式號碼。它不出號、不讀彩票開獎檔、不購彩、不寄信、不調參，不會因新合成控制未拒絕而洗掉原FAIL。

## 三個可被推翻的問題

1. 原REPLICATED負控制異常是否在全新固定seed、直接均勻抽樣／SHA256拒絕抽樣／分開RNG的打散／忠實原共享RNG打散四條路徑中再出現？24個雙尾檢定固定Holm；未拒絕只表示本輪未偵測偏離。另以simultaneous CP區間檢查事前固定±1pp容許帶，不涵蓋則INCONCLUSIVE，不能宣稱完全公平。
2. 將概率以alpha=.5向公平概率收縮，能否在公平控制精確把**條件期望**excess Brier變成四分之一，卻不提高D2？直接攜帶原D2、不重新round或排序；這是概率診斷，不新增選號候選，也不承諾每一條有限樣本的realized Brier都改善。
3. marginal surrogate、最近60期pair噪聲與真正interaction分別付出甚麼誤差？使用已知人工生成律的真q，將mixture MSE精確拆成empirical/prior/cross三項；200次固定迭代上限、tol1e-9的moment fit只在固定快照上消融。另使用生成器真marginals做population structural fit，區分樣本估計與CB族本身不足。快照改善不能證明任何一項是原失敗的唯一原因。

## 固定試驗

完整實驗seed2026101931，與先前合成seed及unit fixture域分開。四負控制×兩遊戲×24rep×240期＝46080；三正控制(MARGINAL_STRONG,PAIR_STRONG,RING_PERSISTENT)×兩遊戲×8rep×240期＝11520，總57600期。每流warmup240。每期每個候選只一組D2，固定R46-CBPAIR-SHRINK、R46-REPLICATED-PAIR及同期seed20261018 NULL，沒有增加覆蓋注數。

四負控制的known-p0雙尾binomial family共24項，Holm alpha .05。在conditional uniform與past-only pair下，即使pair自適應，個別hit序列仍有固定Bernoulli(p0)定律；不同模型相依不影響Holm。這不證明真實彩票的來源／時間／分布假設成立。配對差值及CI另附IID未證實限制。正控制的優勢不能作彩票證據。

固定n5760/cell，+1pp只是功效規劃alternative；prepare用Bonferroni雙尾臨界值精確計算power，不把計算當模型技能。未設可選停止或重抽seed。新模型／窗口／seed一律需新protocol，不重用舊test。原負控制69/2880、Holm .03414永久保留，原因仍UNRESOLVED。

## 運行

```powershell
python -m research.ssq_dlt_d2_forensics prepare --output C:\GLP\new-forensics --prior-decision C:\GLP\V45-D2-next\decision.json
python -m research.ssq_dlt_d2_forensics execute --output C:\GLP\new-forensics
python -m research.ssq_dlt_d2_forensics verify --output C:\GLP\new-forensics
python -m research.ssq_dlt_d2_forensics.acceptance --output C:\GLP\new-acceptance
```

prepare封存全部方法source SHA、Python實作版本、參數、stream rectangle與原FAIL；只屬本地plan/SQLite，不是外部TSA。execute先記claim，逐stream先持久保存全部predictable pairs再評分／保存outcomes；模型只接收prefix。生成器先產生整個合成資料流，這不是聲稱真實事前預測。未知中斷claim停止，不能覆蓋半成品。已完成execute以只讀verify返回，不再初始化SQLite或改DB header。

verify重建生成資料與metadata、完整模型期次集合、全部hit與CSV欄位、summary/檢定/Holm/CI/均值及固定快照集合，抽查每流首中末的模型與概率hash。它不是所有57600期模型的完整二次重播；完整與抽查範圍必須區別。原時間封存、下一期合法性、01–04批准、八槽、前瞻樣本仍未准入。A=0、NO_EDGE、Final Gate FAIL。

原理參考：[conditional Poisson/maximum entropy sampling](https://pmc.ncbi.nlm.nih.gov/articles/PMC12830118/)、[R Holm](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)、[NIST intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)。這些方法文獻不構成彩票存在偏差的證據。
