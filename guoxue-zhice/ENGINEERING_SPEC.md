# 国学智策系统 v0.2.0 Hard-Gate

冻结主线：需求/目的建模 → 5 Why → 风险边界 → Domain Model → 架构图 → 函数清单 → 接口契约 → 数据源 → NetClient → Storage → Engine → Evidence → Service → UI → Self-Test → Contract Test → Fault Injection → Real Network → Windows Build → Exact EXE → GUI Smoke → Same Hash → Final Gate → 唯一成品。

任何一环非 PASS 都不得交付；WARNING、SKIPPED、PENDING、UNKNOWN、UNAVAILABLE 都按失败处理。

## 需求/目的建模
把传统经典的思想、方法、历史案例和适用边界转为现实判断工具，而不是把古籍包装成万能答案。

## 5 Why
1. 零散阅读难迁移到现实目标。
2. 仅搜索原文缺场景、利益、约束和风险建模。
3. 无复盘无法检验方法是否有用。
4. 无 Evidence 无法证明按钮背后真的执行。
5. 无硬门会出现“UI 显示成功但后台失败”的假 PASS。

## 风险边界
健康、投资、法律等高风险现实问题不得由古籍替代现代专业证据；作者归属与解释争议必须保留；更新失败、Hash/Schema 失败不得覆盖旧库；分析只标 ACTION_HYPOTHESIS。

## Domain Model
KnowledgeBase：经典、场景、方法、来源、边界。
State：推演、复盘、更新时间。
EvidenceEvent：事件、状态、来源、HTTP、payload hash。
UpdateManifest：HTTPS 数据源、版本、SHA256。
AnalysisResult：目标、场景、问题、方法、5 Why、逆转验证。

## 架构图
UI → Service → Domain / Engine / NetClient / Storage / Evidence。UI 不直连底层模块。

## 函数清单
Service: analyze_goal, one_click_update, one_click_repair, save_review, stats。
NetClient: get_json, get_bytes。
Storage: load_knowledge, load_state, replace_knowledge, repair。
Engine: GoalEngine.analyze, ReviewEngine.save。
Evidence: record, recent。

## 接口契约
一键更新仅在 HTTPS、HTTP、Content-Type、JSON、Schema、SHA256、staging、atomic replace 全过后返回 PASS；修复后必须再次加载验证；Final Gate 所有 gate 必须精确 PASS。

## 数据源
主源 GitHub raw main，备用冻结 tag；Real Network 记录最终 source、HTTP、Content-Type、payload hash、字节数。

## NetClient
connect/read timeout 分离；仅 GET 重试；429/5xx 和连接/超时执行有限指数退避+jitter；4xx 非重试；校验 Content-Type 与空 payload。

## Storage
staging → schema validate → backup → atomic replace → reload verify；异常回滚。

## Engine
只负责场景分类、经典选择、5 Why、逆转验证和复盘。

## Evidence
成功与失败都记录，防止只记录 PASS。

## Service
唯一应用编排入口。

## UI
四入口：目标推演｜一键更新｜一键复盘｜高级分析；一键修复收纳在高级分析。全部走 Service。

## Self-Test
验证种子库、分析、5 Why、逆转验证、复盘、修复、Evidence。

## Contract Test
验证 Service/API、Manifest、UI→Service、Final Gate 正反路径。

## Fault Injection
覆盖网络中断、错误 SHA256、非法 payload、损坏 state；失败不得替换旧库。

## Real Network
Windows runner 真实联网验证 HTTPS、HTTP 2xx、Hash、Schema、条目数。

## Windows Build
Windows x64 PyInstaller 自包含构建。

## Exact EXE
对同一个刚构建 EXE 执行自测。

## GUI Smoke
同一个 EXE 执行 tkinter GUI 冒烟，验证四入口与 Service 绑定。

## Same Hash
复制到 final 前后 SHA256 必须一致。

## Final Gate
hard_fail_count == 0 且 final_gate == PASS 才能进入发布。

## 唯一成品
唯一产品 artifact 只含 dist/final/Guoxue_Zhice_Pro.exe；审计证据单独保存。
