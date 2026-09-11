# 项目摘要

OmniAgent Studio 是面向知识查询与审批操作的 Agent 应用，采用 Vue 3、FastAPI、LangGraph 和 PostgreSQL/pgvector。三个 Profile 共用运行时，配置隔离知识库、工具和预算。

- 文档导入后执行全文与向量混合检索；回答引用完整证据片段，检索范围和引用身份由服务端校验。
- HTTP/MCP 工具进入统一 Registry；写操作经人工审批，编辑参数重新验证，重复执行依赖幂等回执。
- PostgreSQL 保存会话、预算、审批和事件，支持重启恢复、运行取消与 SSE 断线回放。
- Docker Compose 可复现；后端、前端、隔离数据库、安全和评测门禁分别记录结果。

[源码](https://github.com/jason4166/omniagent-studio) · [实际界面与实现入口](showcase.md) · [验证记录](delivery-v1.md)

真实模型与 embedding 可选接入，业务工具使用合成数据和本地沙箱。具体限制见 [范围说明](failures-and-limitations.md)。
