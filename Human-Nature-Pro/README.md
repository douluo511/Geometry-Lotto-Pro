# Human Nature Pro — 人性决策系统

第一阶段 Windows 原型：把真实人际/谈判局面结构化为事实、推测、九层状态、竞争假设、信息增益、策略、5 Why 与逆转验证。

## 四个入口
- 分析当前局面
- 一键更新
- 一键修复
- 高级分析

## 原则
- 不把行为线索当成读心证据。
- 永远保留竞争解释和反证条件。
- 高不确定性时优先低成本、可逆、能获取新信息的行动。
- 用于理解、谈判、沟通、合作和边界管理，不提供欺骗、胁迫或针对个人脆弱性的恶意操控。

## 本地运行
```bash
python app.py
python app.py --self-test
python tests/test_core.py
```

## Windows EXE
由仓库 `.github/workflows/human-nature-pro-windows.yml` 在 `windows-latest` 原生构建。只有核心测试、EXE 自检和 SHA-256 生成全部通过，才会上传 artifact。
