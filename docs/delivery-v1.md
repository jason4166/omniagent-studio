# 交付与验证记录

当前源码包含独立公开访客、管理只读配置、日常知识扩展及预构建镜像部署支持，也保留了真实多轮对话中发现的结构化输出、失败重放和工具结果呈现修复。以下记录分别标明其应用、测试和部署版本。

## 查看证据

- [云端内部部署验收](cloud-deployment-2026-09-12.md)：运行应用提交 `3254c97`，浏览器测试提交 `558e63d`；新数据库卷启动、真实 API、管理只读与用户隔离、两次整机重启及加密备份恢复。公开域名尚未上线。
- [公开访客与知识扩展验证](artifacts/knowledge-expansion/README.md)：应用提交 `68b23aa`、`9e46785`，测试脚本 `77ad5d1`；包含扩展资料、自然问法和固定数据集结果。
- [工作台文案修订截图](screenshots/product-workspace.png)：应用提交 `db70389` 的产品文案调整；默认助手介绍与知识库名称按旧值精确更新，自定义配置保留。旧截图和评测保留为对应版本记录。
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

云端内部部署已经验收；域名 `omniagentstudio.top` 已提交 ICP 备案申请，目前正在审核中，公开 DNS/TLS 与外部监控仍未完成验收。当前不包含组织多租户、SSO、真实 CRM/邮件/支付写入、MFA 或邮件找回密码。更多边界见 [限制与改进](failures-and-limitations.md)。

## 发布状态

GitHub 源码以当前分支与提交为准，CI 状态查看该提交的 GitHub Checks；云端运行镜像的应用版本单独记录，文档或测试提交不自动改变运行服务。此前版本的记录保持原样，每条 CI 结论仅适用于其记录的提交。

本地提交、远端分支和远程 Release 是不同状态。仓库未因本轮文档整理自动创建远程 Release 页面。历史 tag 与报告不会被移动或覆盖。
