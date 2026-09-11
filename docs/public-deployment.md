# 公网部署与账号运维

rc.3 已提供独立账号和 HTTPS 部署配置。仓库验收覆盖本机真实模型、独立新卷和本地受信任 CA 的 HTTPS；公开域名、云服务器、防火墙、DNS、公开证书签发和异地备份仍须在目标服务器上验收。不能把本地报告说成已经上线。

## 需要准备什么

1. 一台能运行 Linux Docker / Compose 的服务器，以及 SSH 管理权限。为 PostgreSQL、镜像构建、PDF 子进程和 API 留出足够内存/磁盘；最终容量以服务器实测为准。
2. 自己控制的域名，DNS 指向服务器；正确配置的 A/AAAA 记录和入站 TCP 80/443。API、数据库、mock 和 Web 内部端口不对公网开放，SSH 只允许管理来源。
3. 两个有效 Provider 凭据：DeepSeek chat、智谱 embedding。只由服务端保管，在 Provider 控制台设置消费提醒/额度。应用内的调用和 token 限额不是账单上限。
4. 私有、加密的异地备份位置、独立保存的解密密钥，以及检查 `/ready` 的监控。域名/服务器的购买、联网授权和外部存储写入由所有者决定。

## 启动正式入口

在服务器上使用经过验收的 Git checkout，安装 Docker、Python 3.12 和 Git。本地 Release 提供 Git bundle，可以在未 push 的情况下保留构建所需的 Git 版本信息：

```sh
git clone omniagent-studio-v1.0.0-rc.3.bundle omniagent-studio
cd omniagent-studio
git checkout v1.0.0-rc.3
```

部署命令要求 Git checkout；仅解压源码 ZIP 不包含 Git 元数据。不要复制旧数据库或把整个开发目录上传。首次从安全进程环境提供 `DEEPSEEK_API_KEY`、`ZHIPUAI_API_KEY`，不要将密钥写入命令历史、`.env`、工单或截图。Linux shell 的部署命令为：

```sh
export OMNIAGENT_BIND_IP=0.0.0.0
python3 scripts/ops.py bootstrap --mode real --environment production --origin https://studio.example.com --project omniagent-secure-public
python3 scripts/ops.py health --mode real --project omniagent-secure-public
```

将示例域名替换为实际域名，origin 不带尾部 `/`。Caddy 使用实际域名申请证书，HTTP 重定向至 HTTPS；证书和配置保存在该项目专用卷。默认绑定仍是 `127.0.0.1`，显式设置绑定地址才开放入口。不要在已有的本地项目上更换 origin；使用独立 production 项目。

初始管理员信息保存在 `.local/deployments/omniagent-secure-public/admin.json`，启动仅显示路径。本机所有者私下读取后登录，立即在界面更改密码；该文件不会随密码更新，改密后应由所有者安全归档或删除旧的引导凭据。后续 bootstrap 不覆盖账号。使用“账号管理”为每位访问者建立独立 member/viewer 账号并限定 Profile，不共享管理员。没有公开注册；viewer 不能执行业务写操作或进入管理接口。禁用、改角色/授权或改密码都会注销旧设备。

Linux 私有目录权限为 0700。被选中挂载的秘密文件为只读文件，只有容器选定的 secret 挂载路径可见；管理员引导 JSON 和备份 key 为 0600。Windows 本地演示依赖当前用户目录 ACL，不能把 `.local` 放入公共共享目录。`.local`、密钥、数据库和私人文件不进入 Git 或镜像构建上下文。

部署环境、模式与 origin 保存在私有 `deployment.json`；重启命令沿用该配置。以后启动时也保留 `OMNIAGENT_BIND_IP=0.0.0.0` 等外部端口设置。`--mode real` 仍须明确给出；production 禁止 `reset/test/eval/benchmark`。旧版演示 bearer 在正式服务中无效。

## 额度和账号恢复

生产默认每用户每天最多 100 次模型尝试 / 500,000 保守 token，实例合计 1,000 次 / 2,000,000 token。可在启动进程设置 `OMNIAGENT_USER_DAILY_MODEL_CALLS`、`OMNIAGENT_GLOBAL_DAILY_MODEL_CALLS`、`OMNIAGENT_USER_DAILY_TOKENS`、`OMNIAGENT_GLOBAL_DAILY_TOKENS` 后执行 `up`。这些是 UTC 固定窗口内预留的上界，失败/重试不退还，跨 worker 和重启一致；真实 usage 仍从 Provider 响应记录。

另有登录、请求、会话创建、上传、embedding 与 SSE 并发限制。公开站点应先只邀请少量评审访问，观察真实费用、数据库和资源消耗，再调整额度。不要关闭服务端限制来解决登录失败。

忘记密码时，主机管理员可通过 `omniagent account-password` 的标准输入 JSON 操作恢复，字段为 `username` 和 `password`；从权限受限的文件重定向给容器，不通过命令行参数传密码。该操作撤销账号所有已登录设备。执行前设置 `OMNIAGENT_SECRET_DIR` 为本部署私有目录，再使用与本部署相同的 Compose 文件/项目名。

## 备份、清理和恢复

安装锁定 Python 环境后：

```sh
uv run python scripts/backup.py backup --project omniagent-secure-public
uv run python scripts/backup.py restore --project omniagent-secure-public --input /private/path/snapshot.oab
python3 scripts/ops.py purge --mode real --project omniagent-secure-public
```

备份为 AES-256-GCM 加密的 PostgreSQL 自定义归档，保存在部署私有目录的 `backups/`；解密 key 在同级 `backup.key`。将归档复制到私有异地存储，并把 key 放在不同的密钥保管位置，否则同机丢失无法恢复。当前实现限制为 128 MiB 归档，超过时拒绝并要求专门的流式备份方案；没有自动删除旧备份。

restore 验证完整密文后创建 `omniagent_restore_<随机值>` 新库，保留会话、checkpoint、审批和效果回执，删除恢复库的登录 token。原数据库不被覆盖。恢复报告给出新库名称和计数；切换正式流量前，由操作者停写、检查恢复库、将本部署 `database_url`/`mock_url`/`owner_url` 的库名一致切到新库后再启动并重新登录。不要将 restore 成功等同于已经切换正式流量。原库可作为受限回滚来源，保留时间由数据策略决定。

`purge` 删除已到 TTL 的会话/checkpoint、过期登录、限流窗口和 SSE 租约。建议目标主机定时运行备份和 purge，监控失败和磁盘空间，并定期恢复到独立测试实例。仓库只提供命令，未在未知服务器安装后台计划或上传任何数据。

## 上线前在目标机器复核

- 用新建低权限账号登录；无法访问管理接口或其他账号会话。无需给访客管理员身份。
- 检查公开证书链、HTTP→HTTPS、Secure/HttpOnly/SameSite cookie、HSTS 与无跨源写入；确认公网无法访问 PostgreSQL/API/mock 内部端口。
- 验证真实 HR 引用与拒答、产品 HTTP/MCP、销售审批编辑、重复点击、服务重启和 SSE 重连。
- 做一次加密备份/恢复，确认异地归档和独立 key 可用；接入外部 `/ready` 监测，并保留最后一次恢复结果。
- 运行当前提交的 secret/history/image 扫描和依赖审计。Fake 全套评测只针对独立测试数据库，不能对正式用户库运行。

本地 HTTPS 回归脚本为 `scripts/public_smoke.py`，它只接受登记为 production 的精确 origin；可通过 `--ca-file` 指定本地 CA，绝不关闭 TLS 校验。该探针会建立并停用自己创建的短期测试账号，适用于部署验收，不作为每分钟运行的健康检查。

当前范围没有 SSO、MFA、邮件找回密码、多组织 SaaS、自动异地备份或抗大流量 DDoS 服务。它们没有被描述为已交付。后续公网域名一旦准备好，应补录目标服务器验收结果和公开地址。
