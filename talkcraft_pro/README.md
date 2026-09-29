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
GitHub Actions 工作流会执行：单元/契约/故障注入 → 源码自检 → PyInstaller Windows EXE → Exact EXE 自检 → GUI 实体按钮点击 → artifact hash → same-hash → final gate。

注意：当前生成环境不是 Windows，也无法在这里执行 GitHub Actions，因此包内的 Windows Final Gate 是“可执行验收工程”，不是已经通过的证据。只有 `reports/final_gate.json` 明确 `ok=true` 才能把 Engineering Final Gate 标记为 PASS。

## 一键更新原则
只保存来源状态、HTTP 状态、payload SHA 和大小，不复制外部商业/版权内容。任何来源失败都会使总更新状态 FAIL；旧缓存不能冒充最新成功。
