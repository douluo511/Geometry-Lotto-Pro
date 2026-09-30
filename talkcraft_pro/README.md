# TalkCraft Pro v1.0 Full Candidate

目标：把“会说话”拆成可训练、可解释、可复盘的闭环，而不是单纯生成段子。

## 四入口
今日训练｜一键更新｜一键修复｜高级分析

## 业务范围（v1.0 冻结范围）
10 个能力域、60 个原创案例骨架、180 个训练任务、7 维可解释评分、Evidence、反例/逆转比较、真实来源网络校验。

## 本地运行
Python 3.11+：`python app.py`

自检：`python app.py --self-test`

真实网络更新：`python app.py --update`

## v1.1 来源恢复状态

当前版本为 **1.1-reauthored-20260929**。它不是把遗失的 legacy JSON 冒充“原件恢复”，而是基于已找回的 TalkCraft 浏览器原型和用户既有训练系统文档，按明确 provenance 重新结构化：

- 10 个原始训练主题
- 6 个训练机制
- 7 个评分维度
- 60 个案例骨架
- 180 个训练任务
- 3 个独立真实网络来源
- 每个案例包含边界、失败模式、逆转问题
- 每个训练任务包含明确验收条件

当前工程已补齐 strict NetClient、raw provenance、SQLite Evidence、Architecture Gate、Business Gate、Unit/Contract/Integration/Fault/Business/Counterexample/Reversal 测试、Real Network、Exact EXE Network、GUI Smoke、Physical GUI、Same Hash 和 evidence-derived Final Gate。

## Windows Final Gate

当前恢复分支已建立 TalkCraft 专用 Windows staging workflow。该 workflow 会完整执行技术硬门，但在本 monorepo 中 **repository_independence 固定为 FAIL**，因此即使其他技术门全部 PASS，也只能产生 staging audit evidence，不能上传 Portfolio Final 成品。

只有迁移到独立仓库后，对同一候选重新完成 Windows Build → Exact EXE → Real Network → Physical GUI → Same Hash → Final Gate，并让 repository_independence=PASS，才允许宣布 Final。
