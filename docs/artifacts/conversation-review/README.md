# 对话路由修订验证

应用版本：[`8bcd6e3`](https://github.com/jason4166/omniagent-studio/commit/8bcd6e35a7e626c60ec78a0bca0387a2abd5bb07)，2026-09-11。后续证据归档提交不改变应用代码。

问候与能力问题原先可能进入知识检索，出现英文澄清或整段制度原文。现在真实模型按语义选择对话类型，服务端从当前 Profile、工具和权限生成公开能力说明；生产路由没有用户句子白名单。缺少业务参数时明确追问，补充信息后继续原请求。设计与边界见 [ADR 0013](../../adr/0013-model-routed-public-conversation.md)。

## 已执行的验证

| 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| Windows 后端全量 | 779 通过，0 跳过；行覆盖率 88.84% | [门禁汇总](verification.json) |
| 静态与前端 | Ruff、格式、mypy、diff；前端 lint、typecheck、22 项单测、build 通过 | [门禁汇总](verification.json) |
| Fake v3 | 业务 70/71，对话 7/7；总计 77/78 | [完整报告](fake-eval.json) |
| 真实 API v3 | 原业务 30/30，对话 7/7 | [完整报告](real-eval.json) |
| 真实 HTTP 连续对话 | 隔离实例及日常 8080 实例各 9 次消息；同键重放无额外工作 | [对话记录](conversation-live.json) |
| 实际 Chromium 页面 | 销售问候、能力说明正常；无英文兜底、引用或审批卡 | [页面记录](browser.json) · [截图](sales-conversation.png) |
| 安全 | 119 项安全测试通过；两个评测集的越权写入、跨库命中、攻击成功均为 0 | [门禁汇总](verification.json)及两份评测报告 |
| 镜像与密钥扫描 | 默认真实部署镜像审计通过；工作树与 Git 可达历史扫描未发现匹配项 | [镜像汇总](verification.json) · [源码扫描](secret-scan.json) |
| GitHub CI | 应用提交的 backend、frontend、docker-smoke 三项通过 | [实际运行](https://github.com/jason4166/omniagent-studio/actions/runs/34600920878) · [归档状态](ci.json) |

真实模型请求 `deepseek-v4-flash`，本次响应模型标识为 `deepseek-flash`；检索使用真实 `embedding-3`。真实评测记录 54 次模型调用、17 次 embedding API 调用；价格未配置，成本保留 `unknown`。评测里的业务工具操作只涉及合成数据。

9 次连续对话覆盖三套 Profile 的不同问候和能力问法、缺少客户资料时追问、补充后生成待审批提案，以及带问候的客户查询。提案随后被拒绝，本场景未执行写操作。两个实例的测试会话均已清理，原有账号和会话保留。

## 结果边界

Fake 的 `hr-08` 仍因检索不到适合的证据而拒答，是已有的业务失败，未修改标签将其算作通过。新增对话用例和业务用例分开统计；37/37 是这组固定工作流通过，不能解释为一般问答准确率或语言理解全覆盖。v1/v2 数据和历史报告保持原样。

真实 v3 工作流 P50/P95 为 1.68/2.83 秒，使用串行进程内 TestClient，包含该评测协议定义的工作流步骤。独立 [Fake benchmark](benchmark.json) 的成功消息 POST P50/P95 为 250.87/302.55 毫秒；它不包含浏览器、真实模型网络和人工等待。二者不是同一种负载，不能相互比较或作为生产 SLA。报告中的 `error_rate` 包含预期的权限拒绝等终态，不等于评测失败率。

能力介绍仍采用受控文案；模型负责理解用户意图。业务知识回答继续使用经过校验的证据原文，复杂指代、任务切换和非业务闲聊仍可能需要澄清。固定回归用例、真实变体与多轮验收共同发现问题，不能替代上线后的反馈与持续评测。

## 复验

在独立 Fake 数据库配置下执行 `uv run omniagent eval --output .pytest-tmp-eval-v3`。已配置真实密钥的独立真实部署可执行 `python scripts/ops.py eval-real --mode real --project <已有独立测试项目>`，保留输出目录中的原始报告。

对话回归：`python scripts/conversation_smoke.py --project <已有真实项目> --base-url http://127.0.0.1:<该项目端口> --output .pytest-tmp-conversation-check`。该命令调用真实模型，在目标实例创建并清理自己的测试会话。原始报告文件的 SHA-256 见 [manifest](manifest.json)。
