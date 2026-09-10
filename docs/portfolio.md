# 简历项目描述

**OmniAgent Studio｜可配置企业知识与审批 Agent 平台｜个人工程作品**

基于 Vue 3、TypeScript、FastAPI、LangGraph 和 PostgreSQL/pgvector，实现 HR、产品支持和销售运营三套共享 Runtime 的 Agent。演示接入真实 DeepSeek 模型与智谱 embedding，业务系统为本地沙箱。

可按投递篇幅选用以下项目描述：

- 实现配置驱动的 Agent Runtime、PostgreSQL checkpoint 和会话恢复；用有界上下文、预算、RBAC、Profile/KB/Tool 隔离约束模型行为。
- 实现带原文定位的 RAG、HTTP/MCP 连接器、人工审批与参数编辑、幂等回执和 SSE 重连；验证服务重启及响应丢失后不会重复执行业务写入。
- 建立分层测试、独立安全 gate、OpenTelemetry 和评测报告：干净容器 589 个后端测试通过，覆盖率 87.39%；真实模型固定 24 条用例候选及复测均通过，未授权写入和跨知识库命中为 0。

这些是仓库当前可演示、可复核的项目事实。指标来自小型合成数据集，不代表企业生产流量、真实客户数量、通用模型准确率或生产 SLA。模型成本 unknown；不将 Fake 计数冒充付费模型指标。

[项目首页](../README.md) · [实际报告](artifacts/release-real/README.md) · [三分钟演示](demo.md) · [源码与交付范围](delivery-v1.md)
