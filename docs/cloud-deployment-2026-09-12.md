# 云端内部验收记录 · 2026-09-12

应用已部署到独立 Linux ECS 和新数据库卷，使用真实对话与 embedding API；当前只监听服务器回环地址，由已核验主机身份的 SSH 隧道访问。**这份记录证明云端内部部署，不代表公网网站已经上线。** 域名尚未办理 ICP 备案，公开 DNS、证书签发和外网 HTTPS 验收未完成。

运行源码为 `3254c97dbe4fb56ed935314069fafe9c6dd52f4f`；浏览器测试使用 `558e63d2b74c057d65a9dc8a6f2082e3f6475738`。两者之间仅修改 E2E 断言，应用代码和镜像未变。镜像内容 ID 与传输归档校验和见 [镜像清单](artifacts/cloud-preview/image-manifest.json)，结果汇总见 [summary.json](artifacts/cloud-preview/summary.json)。

## 部署方式

- 使用已提交源码的 Git bundle，单独传输已构建镜像，逐项核对 SHA-256 与 Image ID。目标机不接收整个开发目录、旧数据库或个人文件。
- PostgreSQL、API、mock、Web 从新卷执行 migration、seed 和 readiness；重复 seed 不新增文档。三套知识库共 29 份合成资料、57 个块。
- 对话配置为 `deepseek-v4-flash`，供应商实际响应中的模型标识为 `deepseek-flash`；embedding 为 `embedding-3`、1024 维。业务 HTTP/MCP 仍连接受控合成数据服务。
- 使用 `--skip-build` 防止目标机隐式构建或拉取。Docker 25 的 `load` 未恢复 PostgreSQL registry digest，因此校验内容 ID 后通过 `OMNIAGENT_POSTGRES_IMAGE` 引用完整本地 SHA-256；没有改成浮动版本。
- 宿主机保留系统 Python，部署脚本使用并存的 Python 3.11；应用容器仍为锁定的 Python 3.12。备份工具使用独立 venv。
- 初始管理员与数据库凭据在目标机生成。模型凭据单独安全传入，均保存在私有目录；网页不显示密钥。公开登录入口给每位访客建立独立身份，后台配置只读。

## 验证结果

| 检查 | 本次结果与范围 |
| --- | --- |
| 后端全套 | 936 passed，0 failed / error / skipped；执行行覆盖 6693 / 7454（89.79%） |
| 静态检查 | Ruff check、format check、mypy `src`、`git diff --check` 通过；ops 脚本另按 Linux 平台检查通过 |
| Vue | lint、typecheck、68 项单元测试、build 通过 |
| 浏览器 E2E | Fake 4 项、云端真实模式 4 项均通过；管理只读、访客隔离、引用、HTTP/MCP、审批编辑和重放 |
| 自然对话 | 18 条检查的断言与清理均通过；包括问候、能力介绍、日常知识、多轮澄清和审批延续。不是一般语言准确率 |
| 业务验收 | 云端完整流程通过，114.06 秒；重复 seed、引用与拒答、HTTP/MCP、容器重启恢复、审批幂等、SSE 重连 |
| 整机重启 | 两次实际重启；第二次恢复了 2 条已完成历史消息及待审批任务，原预算与审批版本不变，重复批准只产生 1 条对应业务回执 |
| 备份恢复 | 加密归档恢复到新库；原库 24 张表内容不变，恢复库 23 张非登录表及 schema 一致，登录记录撤销；篡改密文在建库前被拒绝 |
| 运行镜像检查 | 271 个应用文件，0 项秘密扫描发现；4 个运行容器均以非 root 用户运行 |
| 源码秘密扫描 | 当前发布候选文件和所有本地 Git 引用可达历史中，0 项发现；私有部署文件不进入 Git 或构建上下文 |
| 重启后端口 | 在工作站实测的 11 个端口中，仅 SSH 可达；Web、数据库、内部 API 和出厂面板端口不可从公网连接 |

原始业务结果：[acceptance.json](artifacts/cloud-preview/acceptance.json)；整机恢复：[第一次](artifacts/cloud-preview/host-reboot.json)、[第二次](artifacts/cloud-preview/host-reboot-2.json)；[端口检查](artifacts/cloud-preview/public-ports.json)；[镜像检查](artifacts/cloud-preview/image-audit.json)；[提交前源码扫描](artifacts/cloud-preview/secret-scan.json)。账号、主机地址、SSH 私钥和完整运维日志保留在受限文件中，不进入公开报告。

自然对话脚本在保存成功报告并清理会话后，因 Windows GBK 终端无法输出模型返回的 `U+2022` 字符而退出 1。报告明确保留这个进程结果，没有把它写成整个命令退出成功。后续验收命令使用 `python -X utf8`，退出码为 0。

浏览器首轮的两项失败来自写死 `fake-v1` 和“总共只有一条引用”的测试假设。修正后按当前 Profile 的 Provider/模型验证，并定位具体年假资料；权限、原文校验和幂等断言保留，两个模式复测通过。首次整机探针也修正了“第一条待审批消息已经属于已完成历史”的错误假设，第二次使用真实的已完成对话加待审批任务验证。

## 重启、网络和数据恢复

启动顺序已验证为 `nftables → 自有访问限制 → Docker / 出厂宿主管理服务 → 应用`。只增加自有链和服务依赖，不重载或清空 Docker 防火墙规则；原有出厂服务与数据保留，公网入口受限。交换空间与应用服务均已开机启用。

重启后的单次资源快照：宿主机可用内存 766 MiB，交换空间使用 43 MiB，磁盘剩余约 23 GiB；应用容器未发生 OOM。该快照说明当前小型验收可以运行，**不构成并发容量、延迟或可用性承诺**。本次没有重新运行负载 benchmark。

备份在清理验收会话之后生成，因此其中会话与待审批表为空；不能据此声称完成了非空待审批备份的灾难恢复。非空历史及待审批任务的恢复由两次整机重启单独验证。已将一份密文复制到服务器外的所有者工作站，解密 key 保存在另一受限目录，并验证了校验和及 AES-GCM 认证。尚未配置自动异地备份、流量切换或外部可用性监控。

## 公网入口的剩余工作

1. 完成所有者的 ICP 备案，再配置域名 DNS、公开 TLS 和正式入口。中国内地服务器的域名/IP 网站入口适用备案要求，见 [阿里云说明](https://help.aliyun.com/zh/icp-filing/basic-icp-service/product-overview/icp-filing-requirements-for-a-regular-website)。
2. 使用独立 production 部署及 HTTPS origin，验证 Secure Cookie、CSRF、HTTP 重定向和证书链；不要直接开放当前内部预览的 HTTP 端口。
3. 明确处理出厂反向代理占用的 80/443，只对正式应用放行；继续限制面板及数据库/API 内部端口，收紧管理来源。
4. 接入外部健康监测和定期异地备份，做实际恢复切换演练，再公开分享地址。

执行命令与账号运维见 [公网部署说明](public-deployment.md)。

## 云端截图

截图来自本次真实运行实例，已清理对应验收会话。

![云端工作台与引用回答](screenshots/cloud-workspace.png)

![管理只读界面](screenshots/cloud-management.png)
