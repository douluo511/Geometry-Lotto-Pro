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

## Windows Final Gate
当前恢复分支**尚未包含 TalkCraft 专用 GitHub Actions Windows 工作流**，因此 Windows Build、Exact EXE、自检、GUI 实体按钮点击、Same Hash 与 Final Gate 均未建立当前版本证据。

同时，`TrainingService` 与 `TalkCraftPro.spec` 都依赖 `talkcraft_pro/data/`，但当前恢复分支没有该目录；`sources.json`、`drills.json`、`cases.json` 等内容资产尚未从有来源的历史中恢复。缺失资产不得通过临时生成内容冒充“原始恢复”。

只有在内容资产有明确来源、完整硬门工作流建立，并且当前 Windows 候选的机器可读 `final_gate` 明确 PASS 后，Engineering Final Gate 才能标记为 PASS。

## 一键更新原则
只保存来源状态、HTTP 状态、payload SHA 和大小，不复制外部商业/版权内容。任何来源失败都会使总更新状态 FAIL；旧缓存不能冒充最新成功。
