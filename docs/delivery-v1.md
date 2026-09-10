# OmniAgent Studio v1.0 交付清单

版本：v1.0.0-rc.2 本地候选。可展示、可运行、可从干净环境复现的真实模型个人工程项目。
运行时验证源码为 `8156cb89cdbbe5b8b19cc63ab20877b9512c1f85`；后续提交归档正式文档、报告和截图。

## 已完成功能

| 范围 | 交付内容 | 主要入口 |
| --- | --- | --- |
| Checkpoint / Context | PostgreSQL LangGraph checkpoint，会话创建/查询/恢复/取消/删除，重启恢复，owner/Profile/schema/TTL 隔离，sliding window、摘要、预算 | `src/omniagent/durable_runtime.py`、`session_store.py`、`context.py` |
| HITL / RBAC / 幂等 | approve/edit/reject/expire，interrupt/resume，角色+风险+allowlist，编辑后重校验，乐观版本、并发保护、原决策重放、幂等效果账本和脱敏审计 | `approvals.py`、`execution.py`、`session_api.py` |
| HTTP / MCP / OpenAPI | 管理员固定端点/方法/headers，schema 业务参数、防 SSRF 和重定向，大小/类型/timeout，MCP tools/resources 发现进入 Registry，受控 OpenAPI 导入 | `http_tools.py`、`mcp_tools.py`、`connectors.py` |
| 三套 Profile / 知识 | HR 引用与拒答、产品只读工具、销售审批写入；同 Runtime 配置驱动、隔离知识库、重复 seed、Profile 导入导出 | `presets/`、`presets.py`、`application.py` |
| Vue 管理与聊天 | Vue 3/TS/Element Plus，Profile/KB/Tool/Prompt 管理，上传状态、配置验证，typed client，引用定位、审批编辑、SSE 去重/重连和状态处理 | `apps/web/src/` |
| 安全与可靠性 | 版本化对抗和故障场景，权限/引用/工具返回校验，限流和输入大小，typed errors、退避/jitter/deadline/熔断、受控多 Provider 降级、权限和版本安全的证据缓存 | `security/`、`reliability/`、`providers.py`、`semantic_cache.py` |
| Trace / 评测 / 性能 | OTel ID/span/脱敏、本地指标、可选 OTLP；统一 EvalCase/Run/Result，dev/test 与版本锁定，独立安全 gate，JSON/MD/图，EXPLAIN 和优化实验 | `telemetry.py`、`eval_platform.py`、`benchmark.py` |
| 真实推理 | DeepSeek 实际规划与证据提取，智谱真实 embedding，上传/查询同模型索引，分批和 timeout，secret 文件引用，索引冲突拒绝混用，UI 明示真实模式 | `embedding_config.py`、`credentials.py`、`compose.real.yaml` |
| 部署 / CI / 发布 | 非 root 镜像、Compose migration/seed/readiness、保留卷的 down、显式危险 reset；Fake 必需门禁、手动真实 workflow、公开 README/ADR/演示/截图/Release 包 | `scripts/ops.py`、`.github/workflows/`、`docs/` |

## 真实验收结果

- 干净 Linux 容器：589 个后端测试通过，0 跳过；覆盖率 5,418/6,200 = 87.39%。Ruff、format、mypy 和 diff check 通过。
- 新 npm 安装：lint/typecheck/build 通过，18 个单测通过；真实和 Fake 浏览器分别 4/4，0 重试。
- 74 个安全专项测试通过，16 条版本化对抗、14 个故障场景；当前数据集未授权写入、跨 KB 与攻击成功均为 0。
- 真实基线、候选、完整复测各 24/24；候选 P50/P95 为 1,377.47/2,305.39 ms；复测 1,584.63/2,436.14 ms。
- 候选实际模型 35 次、检索 11 次、工具 8 次；chat 36,617 tokens，embedding 11 次/154 tokens；成本 unknown。
- Fake 固定集 65/66；单独 20 次 benchmark P50/P95 为 134.28/166.16 ms，SQL 均值 119，错误率 0。
- 两套此前不存在的卷完成 build/up/migrate/seed/health；真实引用、无证据拒答、HTTP/MCP、审批编辑/拒绝、重复批准、重启恢复、SSE 回放均通过。
- 新文档上传、重复上传与配置创建新 Profile 的实际问答通过；两轮真实演示 182.17 秒和 182.14 秒均通过。
- 镜像/配置/构建历史扫描 0 发现；源文件和 Git 可达历史扫描 0 发现。运行时 136 个文件与测试源码一致，实际 API/mock 镜像源文件与 Git 一致。

数字与边界完整列在 [可复核证据](artifacts/release-real/README.md)。测试不是真实公网模型的 CI 前提。

## 未完成事项及边界

已承诺的本地工程功能没有待办阻塞。GitHub 托管 runner、push、PR、main 合并和远程 Release 未执行，原因是本次没有远程发布授权。

- 真实业务系统写入、SSO、多组织租户、K8s 等属于明确排除的范围，未实现。
- 当前数据是合成作品集数据，真实评测仅 24 条；别名模型可能变化，不保证一般场景 100% 成功率或生产 SLA。
- Fake 有一条安全拒答的已知词形匹配失败，未修改锁定 test 标签；真实价格未配置，成本显示 unknown。
- 引用采用严格原文片段，SSE 在安全校验后发送答案分片；上下文摘要为有界抽取，缓存使用保守语义归一，均有明确适用边界。
- OTLP/Langfuse 与第二真实 Provider 的适配已实现；本次真实部署只启用主 LLM 和 embedding，未宣称外部观测平台或第二付费模型实测。

## 演示与路径

运行入口：`python scripts/ops.py bootstrap --mode real`，浏览器 `http://127.0.0.1:8080`。
HR 输入“今年有多少天带薪年假？”，点击引用；再询问无关问题查看拒答。
产品输入“产品查询 P-100”和“MCP 查询 P-200”。销售输入“为客户 C-100 创建回访，备注：确认续约需求”，即可查看实际模型生成的审批卡。

[完整三分钟脚本](demo.md) · [架构/状态/审批/数据图](architecture.md) · [威胁模型](threat-model.md) · [Release notes](releases/v1.0.0-rc.2.md) · [简历表述](portfolio.md)

## 本地实现提交

以下是 Day14 之后至最后一次运行时代码修改的完整提交；后续候选提交只归档公开交付材料。

```text
76e27d5 feat: persist bounded sessions and approval execution with replay protection
16716ce feat: integrate fixed HTTP and MCP tools with seeded agent profiles
b0a5425 feat: add Vue workspace and authenticated replay-only event streams
5da5e7c feat: add isolated telemetry reliability security gates and unified evaluation
d02480e perf: reuse freshly authorized profiles and preserve dependency deadlines
17c1b0e docs: record frozen evaluation security and measured performance evidence
d14f6be build: package v1 candidate with verified UI recovery and local operations
ab0ed94 fix: exclude nested development caches from release images
978f044 fix: preserve frozen dataset bytes across clean Windows checkouts
e4b9616 fix: refresh proxy DNS and preserve failed acceptance evidence
a8ce87f fix: persist coverage reports under the non-root CI user
01f427a release: record verified clean v1 candidate and reproducible evidence
0ae6e12 fix: hash release evidence using canonical Git text bytes
ef028e2 feat: deliver live chat and embedding mode with isolated indexes and secret references
3bf5980 fix: provision real-mode secrets with non-root immutable application files
8156cb8 fix: preserve routing intent across live conversations and verify new document ingestion
```

本次未推送。发布前可先检查工作区、差异和扫描报告，再由所有者决定是否运行：

```sh
git status --short
git log --oneline 5c92f945afe92ba09928ddecbffd9fdb5d338918..HEAD
git push -u origin codex/real-provider-delivery
git push origin v1.0.0-rc.2
```

不用 `git add .`；不要暂存受保护文件、本机环境或私人记录。这些命令不创建 PR、不合并 main，也不创建远程 Release 页面。
