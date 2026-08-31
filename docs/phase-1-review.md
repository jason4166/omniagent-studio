# Phase 1 Review

## 阶段结论

Phase 1 已建立一个完全离线、配置驱动的 Agent 最小闭环：同一个 `AgentRuntime` 可以加载不同 `AgentProfile`，读取固定版本 Prompt，调用 `LLMProvider` 做结构化路由，并按配置选择直接回答、检索或受控工具调用。

当前实现只使用合成数据、in-memory Repository、FakeLLM、FakeRetriever 和本地 mock 工具，不连接真实 LLM、数据库、知识库、CRM、邮件或支付系统。

## 已建立的能力

- Python 类型、异常、pytest、同步与异步基础。
- Pydantic 严格领域模型与 JSON Schema 边界。
- FastAPI 单资源 CRUD、Repository、Service 和稳定错误响应。
- `LLMProvider`、`LLMRequest`、`LLMResponse`、typed errors 与 `RouteDecision`。
- 固定版本 `PromptVersion`、安全渲染、离线路由评测及原始证据留存。
- `ToolRegistry`、`ToolAdapter`、AST calculator，以及工具、Profile、角色、Schema、审批和预算门禁。
- 配置驱动 `AgentRuntime`、最多一次工具调用、无隐式循环和 FakeRetriever 接缝。

## 配置与运行时依赖方向

```text
runtime_config ──> AgentRuntime
                     ├──> AgentProfileRepository ──> AgentProfile
                     ├──> PromptVersionRepository ──> PromptVersion
                     ├──> LLMProvider
                     ├──> Retriever
                     └──> ToolRegistry ──> ToolAdapter
```

配置负责装配依赖；Runtime 负责通用控制流。Runtime 可以判断 `direct`、`retrieve`、`tool`、`clarify` 这些通用运行状态，但不按 `profile_id` 写场景分支。

## 两个 Profile 的行为差异

| Profile | 知识库 | 允许工具 | 可产生的行为 |
|---|---|---|---|
| `general-kb` | `general-kb-v1` | 无 | `direct`、`retrieve`；工具提案会被拒绝 |
| `product-support` | 无 | `lookup_product`、`check_warranty` | `direct`、获准的只读工具调用；检索会被拒绝 |
| `warranty-support` | 无 | `check_warranty` | 保修查询工具可用；产品查询工具提案会被拒绝 |

这两个 Profile 由同一个 Runtime 执行。差异来自配置中的 Prompt、知识库和工具 allowlist，不来自 Runtime 中的场景名称判断。

## Day 9 演示

运行：

```powershell
uv --cache-dir .uv-cache run python day09_runtime_demo.py
```

演示使用一个按顺序返回合成响应的 Provider 和一个 Runtime 实例：第一次让 `general-kb` 直接回答，第二次让 `product-support` 调用 `lookup_product`。预期结果是两个调用均成功、模型调用两次、Retriever 未被调用。

## 60～90 秒演示词

这是 OmniAgent Studio 第一阶段的配置驱动 Runtime。入口脚本只装配一次 Runtime，但加载了两个不同 Profile。`general-kb` 配置了知识库、没有业务工具；`product-support` 没有知识库，只允许查询产品和保修。用户消息先与 Profile 指定的系统 Prompt 一起交给 Provider，模型返回结构化路由提案。Runtime 不信任模型给出的权限信息，而是使用已加载的 Profile、预算和系统角色进行判断。直接回答会返回统一的 `RuntimeResult`；检索只会读取 Profile 允许的知识库；工具调用还必须经过 Registry 的工具存在性、Profile allowlist、角色、Schema、审批和预算门禁。整个流程最多调用一次工具，没有隐式循环。当前演示全部使用 Fake 和合成数据，所以它证明的是控制流和安全边界可复跑，不证明真实模型效果，也不代表已经完成正式 RAG 或生产集成。

## 证据边界

- 固定 FakeLLM 的旧路由准确率为 26.67%，只证明评测管线可复跑，不能证明 Prompt 质量。
- FakeRetriever 只建立检索接口和调用位置，不包含切分、embedding、向量检索、重排、引用或召回评估，因此不是正式 RAG。
- 当前没有真实 Provider、数据库、Retriever 或外部工具，也没有 LangGraph。
- 工具超时目前只映射 `TimeoutError`，不会主动取消阻塞 adapter。
- Runtime 最多执行一次工具，不包含规划循环、重试循环或多步 Agent graph。

## 已知技术债

- `ToolRegistry` 重复注册同名工具会静默覆盖。
- `ToolResult` 模型只约束了部分状态组合不变量。
- `approval_policy_id` 尚未解析为生产审批策略；当前 Runtime 以 `approval_granted=False` 的安全默认值调用 Registry。
- 默认 Runtime 配置仍是代码内的合成装配，尚未接入配置文件、环境分层或持久化配置。
- Runtime 测试存在较多重复装配代码；当前保留既有测试，不在 Day 9 为重构而扩大范围。

## Day 9 P0 状态

1. 同一 Runtime 运行两个 Profile，并覆盖 direct/tool：完成。
2. 预算、禁用 Profile、越权工具、坏模型输出有测试：完成。
3. 学习者独立完成一个小功能和测试：新增 Profile 配置由学习者独立完成，但测试经逐块提示完成，尚不能按完整“独立”标准确认。
4. 能说明配置、Runtime 与各依赖的方向：完成。
5. 全部门禁和演示脚本：完成；全量 pytest 为 143 passed，Ruff、mypy、Day 9 演示和 `git diff --check` 通过。
6. 薄弱项显式记录：完成；独立编码证据不足及后续补强动作已写入本地学习日志。

当前为 5/6 P0。唯一未完成项是第 3 项，不能把分步提示下完成的代码记作独立编码证据。
