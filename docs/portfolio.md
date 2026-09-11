# OmniAgent Studio 项目介绍

**OmniAgent Studio｜可配置知识问答与审批 Agent 平台**

面向 HR 制度查询、产品支持和销售运营场景，基于 Vue 3、TypeScript、FastAPI、LangGraph 和 PostgreSQL/pgvector，提供从知识检索、引用回答到工具提案、人工审批和执行恢复的完整流程。三套 Agent 共享同一个 Runtime，通过配置隔离知识库、工具、权限与预算。

源码地址：<https://github.com/jason4166/omniagent-studio>。截图和验证报告对应 `v1.0.0-rc.3`；后续展示文档整理未改变已验证的运行逻辑。

## 项目能力

- **知识问答**：支持 PDF、Markdown、TXT 导入及切块，结合全文检索、向量检索与 RRF 融合；回答提供原文引用，无充分证据时拒答，检索前按 Profile 限定知识库。
- **工具与审批**：HTTP/MCP 工具统一进入 Registry；只读操作按策略执行，写操作先生成审批卡。参数编辑后重新校验权限与 Schema，通过版本校验和下游幂等回执处理重复批准、并发及响应丢失。
- **持久化与交互**：LangGraph 和 PostgreSQL 保存会话、checkpoint、待审批任务与事件；Vue 工作台支持会话恢复、引用定位、审批操作及 SSE 断线重连，事件回放不重新执行写操作。
- **运行与验证**：Docker Compose 集成 API、Web、PostgreSQL、迁移、seed 和本地业务服务；自动化测试与回归评测覆盖知识库隔离、引用、审批重放和故障恢复。真实模型与 Fake 离线门禁独立验证。

项目摘要保留具体功能、约束和可演示的验证场景；测试数量、覆盖率和固定评测集结果可从 [验证报告](artifacts/release-public/README.md) 复核。

## 可展示范围

演示调用真实 DeepSeek 模型与智谱 embedding-3；知识文档、产品、客户与业务写入均为合成数据和本地沙箱。已验证本地干净部署、账号隔离、TLS 与备份恢复，并提供公网部署配置；尚未完成真实服务器和公开域名部署，不宣称生产用户量、商业落地或 SLA。

当前小型评测集不能代表通用模型准确率。缓存只复用经权限及版本校验的检索证据；业务幂等依赖本地 mock 的事务回执，不能推广成任意外部系统的 exactly-once 保证。已知失败与改进保留在 [限制说明](failures-and-limitations.md)。

[项目首页](../README.md) · [实际界面与源码导览](showcase.md) · [演示脚本](demo.md) · [源码与交付范围](delivery-v1.md)
