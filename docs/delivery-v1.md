# OmniAgent Studio v1.0 交付清单

版本：v1.0.0-rc.3 本地候选。真实 chat + embedding 的个人工程项目，已补齐独立账号和受控公网部署配置。
验收运行时源码：`f82b6053d63410056d2cb4a2c71cf83d2b07a75b`；后续提交只归档正式文档、证据与截图。

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
| 独立账号 / 公网 | UUID 账号、Argon2id、Cookie/CSRF/Origin、服务端撤销、持久化额度、最小数据库权限、TLS、加密备份恢复 | `access.py`、`compose.production.yaml`、`docs/public-deployment.md` |
| 部署 / CI / 发布 | 非 root 镜像、Compose migration/seed/readiness、保留卷的 down、显式危险 reset；Fake 必需门禁、手动真实 workflow、公开 README/ADR/演示/截图/Release 包 | `scripts/ops.py`、`.github/workflows/`、`docs/` |

## 本次实际门禁

| 指标 | 本次实测 |
| --- | --- |
| 后端 Linux / Windows | 618 / 618 通过，0 失败、0 跳过 |
| 前端 unit / 浏览器 E2E | 20；真实 5 + Fake 5，0 重试；lint/typecheck/build 通过 |
| 后端行覆盖率 | 5,808 / 6,742 = 86.15%，门槛 80% |
| 安全 / 故障注入 | 111 项安全专项通过；29 条版本化对抗；14 个故障场景 |
| 真实模型 E2E / route / Recall@1/3/5 / MRR | 24/24 / 100% / 100% / 1.0 |
| 引用有效率 / Claim 支持率 | 100% / 100%（7 处引用、10 条 Claim） |
| 拒答判定 / 工具选择 / 参数 F1 | 100% / 100% / 1.0 |
| 未授权写入 / 跨 KB / 攻击成功率 | 真实、Fake 当前集均为 0，独立 gate 通过 |
| 真实模型 P50 / P95 | 1724.32 / 2534.76 ms |
| 真实调用 / token / 成本 | 模型 35、检索 11、工具 8；chat 36,600 tokens；embedding 11 次 / 154 tokens；成本 unknown |
| Fake E2E / P50 / P95 | 65/66（98.48%）；175.88 / 332.62 ms |
| 独立 Fake runtime benchmark | 20 次：P50 141.70 / P95 162.26 ms，SQL 均值 119，错误率 0 |
| 新增部署验收 | 本地验证 TLS、cookie/CSRF、账号隔离、撤销、备份防篡改/恢复全部通过 |
| 依赖 / secret 扫描 | Python 99 个运行依赖、npm 生产依赖已知漏洞均为 0；源码/可达历史、镜像/配置扫描均为 0 发现 |
| 两轮真实演示 | 182.16 秒、182.19 秒，全部通过 |

完整数据和边界见 [rc.3 证据](artifacts/release-public/README.md)。API/mock 两套镜像的 210 个导出文件分别与 Git 匹配，143 个运行/配置文件在工作区与验收提交一致。Windows 与新 Linux 容器各通过 618 项后端测试，coverage 表使用 Linux 结果；mypy 检查 88 个源文件。

本地 HTTPS 使用受信任 CA 验证，未关闭证书校验。测试证实 Secure cookie、CSRF、跨用户/角色/Profile 隔离和撤销。恢复演练在新库保留待审批任务和 4 个 checkpoint，撤销恢复登录，并在创建数据库之前拒绝篡改密文。首轮 Linux 的唯一失败是测试误假定没有引导管理员；已用回滚事务修正，最终无失败、跳过或浏览器重试。

## 未完成项和真实原因

公网地址尚未部署：没有指定云服务器、域名/DNS、公开证书和外部备份位置。代码与配置已经准备好；目标服务器的防火墙、公开 TLS、异地备份、监控和容量仍须实地验收，不能由本机报告代替。GitHub hosted runner 也未执行，因为没有 push/远程发布授权。

SSO、多组织系统、真实 CRM/ERP/邮件/支付写入、K8s 等是明确排除的范围。当前 managed-account 版本另不包含 MFA、公开注册、邮件找回密码和自动异地备份运输。真实评测是小型合成语料；Fake 仍有一条安全拒答，真实价格 unknown。OTLP 和第二 Provider 适配存在，但没有宣称已连接外部观测平台或实测第二付费模型。

## 演示与部署

1. `python scripts/ops.py bootstrap --mode real`，访问 `http://127.0.0.1:8080`。
2. 从启动提示的私有 `admin.json` 获取随机初始账号，登录后改密；管理员可为不同访客建立独立账号并限定角色/Profile。
3. HR：“今年有多少天带薪年假？”→查看引用；“月球基地停车费是多少”→拒答。
4. 产品：“产品查询 P-100”“MCP 产品 P-200”→只读 HTTP/MCP。
5. 销售：“为客户 C-100 创建回访，备注：确认续约需求”→刷新恢复→编辑/批准→重复决策只有一次效果。

旧 `omniagent-real` 服务已停止，数据库卷保留；当前默认项目是 `omniagent-secure-real`，旧演示身份的会话不会自动转交给新账号。当前 8080 入口通过了独立的真实接口验收。

[公网部署](public-deployment.md) · [三分钟演示](demo.md) · [架构](architecture.md) · [威胁模型](threat-model.md) · [ADR 0011](adr/0011-public-access-and-operational-boundaries.md) · [Release notes](releases/v1.0.0-rc.3.md) · [简历描述](portfolio.md)

## 本地提交和安全发布

本次实现提交：`142e6e7`（独立账号与部署加固）、`f82b605`（测试隔离修正），加上最终文档/证据归档提交。完整列表运行 `git log --oneline 7aef310..HEAD`；之前所有里程碑提交继续保留在历史中。

尚未 push、创建 PR、合并 main 或发布远程 Release。准备发布时先检查本地候选和最新扫描，然后由所有者明确执行：

```sh
git status --short
git log --oneline 7aef310..HEAD
git show --stat v1.0.0-rc.3
git push -u origin codex/public-deployment-hardening
git push origin v1.0.0-rc.3
```

不用 `git add .`。两个受保护未跟踪文件保持原样且未暂存；私人学习文档、密钥、部署账号和数据库不在候选中。这些命令不会创建 PR、合并 main 或创建远程 Release 页面。
