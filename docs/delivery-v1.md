# 交付与验证记录

当前源码包含公开项目审查后的修订：完整证据单元校验、保留语序的证据缓存、运行取消、事务审计、可选有界前置查询，以及评测口径和首页整理。

## 查看证据

- [本次修订验收](artifacts/portfolio-review/README.md)：本轮源码版本、实际执行的门禁、复现结果和限制。
- [rc.3 原始记录](artifacts/release-public/README.md)：之前的真实模型、账号与 TLS/恢复验收，保持原样；其中的测试数量和模型结果属于该历史版本。
- [更早的实验记录](artifacts/benchmark-comparison/comparison.md)：固定负载 SQL 往返优化与 EXPLAIN。延迟依赖环境，不能作为生产 SLA。
- [当前评测口径](../evals/measurement-methods.md)：工作流耗时、适用分母、独立安全 gate 和比较条件。

本次源码修改后应使用本次报告，不能把历史真实模型结果直接移作当前版本结果。Fake 回归与真实 API 评测分别记录。测试覆盖率表示执行过的代码行范围。

## 运行和检查

[快速启动](../README.md#快速启动) · [开发门禁](development.md) · [演示脚本](demo.md) · [公网部署](public-deployment.md)

默认部署支持独立账号、服务端授权、审批、checkpoint、事件回放、迁移和可重复 seed。模型密钥通过服务端私有文件引用传入，业务写入仅进入本地合成账本。

公开网址仍需要目标服务器、域名/DNS 和公开 TLS 的实地部署验收。当前不包含组织多租户、SSO、真实 CRM/邮件/支付写入、MFA 或邮件找回密码。更多边界见 [限制与改进](failures-and-limitations.md)。

## 发布状态

GitHub 默认分支已更新为本次修订。`c7769fa` 的三个必需 CI 作业均已通过，原始运行链接和后续操作脚本修订见 [本次验证记录](artifacts/portfolio-review/README.md)。每条 CI 结论仅适用于其记录的提交。

本地提交、远端分支和远程 Release 是不同状态。仓库未因本轮文档整理自动创建远程 Release 页面。历史 tag 与报告不会被移动或覆盖。
