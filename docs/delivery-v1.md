# 交付与验证记录

当前源码包含公开项目审查后的修订、模型语义路由，以及真实多轮对话中发现的结构化输出、失败重放和工具结果呈现修复。业务证据、审批和权限校验保持有效。

## 查看证据

- [当前工作台截图](screenshots/product-workspace.png)：应用提交 `db70389` 的产品文案调整；默认助手介绍与知识库名称按旧值精确更新，自定义配置保留。前端与完整容器流程以对应提交的 GitHub Checks 为准，之前的截图和评测保留为历史记录。
- [引用与业务表单界面验收](artifacts/ui-polish/README.md)：应用提交 `054c1e0` 的引用阅读、审批字段表单、真实试聊及回归记录；输入框旁保留 token/成本统计。
- [真实对话修复验收](artifacts/conversation-recovery/README.md)：应用提交 `0a798ce` 的真实多轮对话、页面复测、评测和门禁记录。
- [此前对话路由修订验证](artifacts/conversation-review/README.md)：应用提交 `8bcd6e3` 的历史记录，保留当时的结果和页面截图。
- [公开项目审查验收](artifacts/portfolio-review/README.md)：此前证据校验、缓存、审计和操作脚本的修订记录。
- [rc.3 原始记录](artifacts/release-public/README.md)：之前的真实模型、账号与 TLS/恢复验收，保持原样；其中的测试数量和模型结果属于该历史版本。
- [更早的实验记录](artifacts/benchmark-comparison/comparison.md)：固定负载 SQL 往返优化与 EXPLAIN。延迟依赖环境，不能作为生产 SLA。
- [当前评测口径](../evals/measurement-methods.md)：工作流耗时、适用分母、独立安全 gate 和比较条件。

本次源码修改后应使用本次报告，不能把历史真实模型结果直接移作当前版本结果。Fake 回归与真实 API 评测分别记录。测试覆盖率表示执行过的代码行范围。

## 运行和检查

[快速启动](../README.md#快速启动) · [开发门禁](development.md) · [演示脚本](demo.md) · [公网部署](public-deployment.md)

默认部署支持独立账号、服务端授权、审批、checkpoint、事件回放、迁移和可重复 seed。模型密钥通过服务端私有文件引用传入，业务写入仅进入本地合成账本。

公开网址仍需要目标服务器、域名/DNS 和公开 TLS 的实地部署验收。当前不包含组织多租户、SSO、真实 CRM/邮件/支付写入、MFA 或邮件找回密码。更多边界见 [限制与改进](failures-and-limitations.md)。

## 发布状态

GitHub 默认分支已包含应用提交 `db70389` 的界面文案与预置介绍修订。源码与截图归档提交的 CI 以对应 GitHub Checks 为准，应用构建版本单独标明。此前版本的记录保持原样；每条 CI 结论仅适用于其记录的提交。

本地提交、远端分支和远程 Release 是不同状态。仓库未因本轮文档整理自动创建远程 Release 页面。历史 tag 与报告不会被移动或覆盖。
