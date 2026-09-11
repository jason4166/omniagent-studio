# 项目修订验证记录

日期：2026-09-11。下面记录实际运行结果，首页只保留项目用途、流程、设计与操作入口。

应用与评测源码为 `c7769fa1f31cfe324d01da4e79cad7de0cf99b68`。Fake 与真实模式分别从干净克隆、新项目和新卷启动；图片来自该版本的真实模式。随后的操作脚本修订恢复已保存端口，没有改变服务端、前端、数据库模型或评测集；其新增回归结果单独记录在 [操作脚本门禁](operations-gates.json)。归档提交仅补文档、报告和截图。每份报告保留被测版本，历史 rc 报告保持原样。

## 可复现的主要流程

| 验证 | 结果与证据 |
| --- | --- |
| 构建、迁移、重复 seed、readiness | [Fake 干净环境](fake-gates-summary.json) 与 [真实环境](acceptance-real.json) 通过 |
| HR 引用及无依据拒答 | 两种模式均通过，引用可以定位授权原文 |
| HTTP / MCP 只读工具 | 两种模式均通过 |
| 暂停 → 重启 → 编辑批准 → 重复批准 | 两种模式均恢复待审批任务，重复提交只有一次沙箱写入 |
| SSE 断线与游标恢复 | 两种模式均通过，回放不重新执行写工具 |
| 新知识上传 | [真实 embedding、重复上传去重、临时 Profile 引用](upload-real.json) 通过 |
| 配置驱动的写操作前置查询 | [客户查询、政策证据、身份编辑拒绝与幂等](preflight-real.json) 通过 |
| 连续完整演示 | [第一次](demo-real-1.json) 181.20 秒，[第二次](demo-real-2.json) 181.05 秒；两次均通过、清理错误为零 |

演示脚本的 180 秒参数用于分段展示；快速验收不依赖这些等待。复现命令见 [开发门禁](../../development.md) 和 [演示说明](../../demo.md)，业务数据全部为合成沙箱数据。

## 测试与扫描

| 门禁 | 已记录结果 |
| --- | --- |
| 后端，应用源码版本 Windows / Linux | 分别 738 项通过，均无失败或跳过；[Windows](windows-gates.json)、[Linux](fake-gates-summary.json) |
| 后端，随后操作脚本修订 | Windows 742 项通过；增加四个端口恢复与冲突用例，详见 [结果](operations-gates.json) |
| 行覆盖率 | 应用版本 Windows 87.95%，Linux 88.01%；统计范围为 `src/omniagent`，不是需求完成度 |
| 前端 | [22 项单元测试及 lint、typecheck、build 通过；Fake / 真实浏览器分别 5 条完整流程通过](frontend-gates.json) |
| Python 静态检查 | Ruff check、format check、mypy、Git whitespace 检查通过 |
| 独立安全门禁 | [115 个测试](security/security.json) 通过；版本化攻击清单 29 条。它们与下面评测的攻击分母不同 |
| Python / npm 生产依赖 | pip-audit 检查 99 个固定 Python 包无命中；npm 生产依赖审计无命中。结论限于执行时的公告库 |
| 源码与可达 Git 历史 | [被测版本扫描](secret-scan.json) 425 个当前文件、732 个 blob，无命中；最终发布前扫描见 [发布扫描](publication-scan.json) |
| 镜像与 Compose | [Fake](image-audit-fake.json)、[真实](image-audit-real.json) 均通过；应用文件 222 个，无凭据命中，服务使用非 root 用户 |

GitHub 的 [c7769fa 必需 CI](https://github.com/jason4166/omniagent-studio/actions/runs/34594912741) 中 backend、frontend、docker-smoke 三个作业均成功，附 [API 结果快照](github-c7769fa.json)。后续提交的执行状态以 [Actions](https://github.com/jason4166/omniagent-studio/actions/workflows/ci.yml) 中对应 SHA 为准。工作流文件存在本身不能证明 CI 成功。

扫描覆盖公开候选文件、可达历史和镜像应用输入中的已知模式与已配置密钥，不包含完整容器 OS 漏洞扫描、渗透测试或所有可能的敏感内容。私有凭据、原始 trace 和主机日志不进入本目录。

## 固定集评测

| 指标及适用分母 | Fake v2 | 真实 v2 |
| --- | --- | --- |
| E2E | 71 / 72 | 30 / 30 |
| dev / test 样本 | 36 / 36 | 15 / 15 |
| 独立答案事实规则 | 6 / 6 | 6 / 6 |
| Recall@1 / @3 / @5 | 21/23 · 23/23 · 23/23 | 13/13 · 13/13 · 13/13 |
| MRR | 0.9565（23 个检索案例） | 1.0（13 个检索案例） |
| 引用身份及完整提取校验 | 22 / 22 | 13 / 13 |
| 拒答决策 | 33 / 34 | 17 / 17 |
| 工具选择 / 参数字段 F1 | 18/18 · 1.0 | 9/9 · 1.0 |
| 未授权写入 / 有写机会案例 | 0 / 16 | 0 / 5 |
| 跨知识库命中 / 有检索机会案例 | 0 / 34 | 0 / 17 |
| 攻击成功 / 标注攻击案例 | 0 / 23 | 0 / 5 |

来源：[Fake 完整报告](fake-eval/report.md)、[真实完整报告](real-eval/report.md)。所有越权、隔离或攻击成功都会单独令安全 gate 失败，不能被平均分抵消。引用和 claim 校验衡量身份及完整提取约束，不等价于独立语义判断；独立事实规则目前只覆盖各集六条案例。

Fake 的 `hr-08` 把“hotel nightly limit”与文档中的“Hotels”匹配失败后安全拒答；冻结标签未因失败而改写。真实模式使用实际 DeepSeek API（请求 `deepseek-v4-flash`，返回别名 `deepseek-flash`）与智谱 `embedding-3`、1024 维；模型别名不锁定供应商内部权重。这是小型合成数据集结果，不写成通用回答准确率。

真实评测的工作流 P50 / P95 为 2027.81 / 2790.74 ms，共 47 次模型、17 次检索、8 次工具调用；聊天 usage 为 49,472 输入 / 2,629 输出 token，embedding 为 17 次调用 / 271 token。价格未配置，因此成本为 `unknown`。唯一错误结果来自预期的不存在产品，正确错误处理仍通过 E2E。运行期间还有隔离的浏览器流程，耗时不是独占机器基准或线上 SLA。

## 性能与重复运行

本次三组 benchmark 使用同一应用版本、相同固定请求，各包含 20 次测量，均无测量错误。P50 为 267.61 / 194.99 / 162.59 ms，P95 为 366.81 / 253.80 / 223.82 ms，每次平均 SQL 数均为 131。计时只包含成功的消息 POST，排除建会话、清理、浏览器和人工等待。

[三组原始对比](benchmark-comparison/comparison.md) 用于观察重复性，不能把机器负载和预热差异写成优化收益。两次 [Fake 评测对比](fake-eval-comparison/comparison.md) 也属于同版复测，附 [对比图](fake-eval-comparison/comparison.svg)。历史实际 SQL 优化、EXPLAIN 与前后版本记录仍在 [原实验](../benchmark-comparison/comparison.md)，没有冒充本次性能结果。

## 发现并修复的问题

- 首次干净 Linux 测试有三处失败：镜像缺少两份历史兼容测试数据，一条冻结文件哈希误用 Windows CRLF。改为最小测试夹具和 Git LF 哈希后全量复测通过。
- 旧评测用全库写入计数差值，被并发浏览器的合法批准污染。现在按会话、执行及审批回执归属核对；保留待审批、已拒绝和缺失审批下非法写入的回归。
- 托管 CI 曾把 secret 目录引用误当作 secret 值。已修正分类，并继续扫描实际凭据内容。
- 新终端没有恢复已保存 Web 端口的问题已补回归与 Docker 实测。更多可见限制见 [失败与改进](../../failures-and-limitations.md)。

当前可作为可运行的个人工程作品展示；公开网址仍需要目标服务器、域名、TLS 和该环境的备份/监控验收。版本号保留 `1.0.0-rc.3`，本轮修订记入 Unreleased；未移动旧 tag 或创建远程 Release。
