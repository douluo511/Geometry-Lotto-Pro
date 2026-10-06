# Head Intelligence System

这是“头部信息智能判断系统”的第一版 Windows 原型。

## 当前可见功能

- 信息判断
- 一键更新
- 一键修复
- 高级分析
- Federal Reserve 官方 RSS
- U.S. SEC 官方 RSS
- 原始 XML 留存与 SHA-256
- 失败不覆盖旧快照
- 标题去重
- 新鲜度、来源质量、决策相关度评分
- 本地 Snapshot Freeze
- 本地自检
- GitHub Actions Windows 原生 EXE 构建与 EXE 自检

## 本地运行

    python -m pip install -r head_intelligence/requirements.txt
    python -m head_intelligence.app

## 自检

    python -m head_intelligence.app --self-test

## 真实网络冒烟测试

    python -m head_intelligence.app --network-smoke-test

## 当前边界

这是候选原型，不把“评分”冒充成真实性概率，也不把官方声明中的所有内容自动判定为事实。
下一阶段再加入事件聚类、跨来源独立性、冲突证据、竞争假设、判断账本、5 Why 与逆转验证。

软件更新由独立的 `HeadIntelligence_Updater.exe` 执行，信息源刷新与软件替换分别验证。真实独立仓库和发布配置缺失时，更新按钮明确显示 BLOCKED；这不能算软件更新验收通过。一键修复会保留损坏原件，并从校验通过的原始证据与快照档案恢复数据。

所有当前候选源码改动均需重新通过 Windows 构建、Exact EXE、实体四按钮、Same Hash 和最终 Gate。局部测试通过不代表最终 EXE 完成。
