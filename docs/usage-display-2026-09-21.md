# 用量显示与每日额度

上线源码：`67a6b622c57ecb12a2f6a0d01830a95ae5dff744`。

聊天输入框旁的模型调用统计属于最近一轮请求，不是累计提问次数。新请求重新计数，恢复原请求沿用原计数；意图判断、回答生成及失败重试可能分别占用调用次数。

本次显示本轮模型、工具的已用次数与上限，保留已确认的模型输入输出 token 合计，另列 `reserved_tokens / max_tokens` 预算占用。两种 token 数字不能混用：本轮预算按保守预留累计限制，已确认用量仅来自返回的模型 usage，不包括 embedding 或未返回的 usage。成本没有可信数值时不再显示占位文案。

`GET /api/auth/usage` 只根据已认证身份查询当前日窗口，返回个人、适用时的访客共享以及平台共享额度。公开接口不接受其他用户身份，不返回用户明细；匿名访问仍需登录。额度读取不扣模型或 token 额度，普通 HTTP 限流仍适用。

每日 token 额度占用包含已结算用量与未结算预留，结算后调整；按现有 UTC 日窗口重置，界面将重置时间转换为浏览器本地时间。请求结束、页面恢复可见、手动刷新及可见页面每 30 秒轮询会刷新快照。失败时显示暂不可用，不把读取失败或旧快照当作零用量。

## 构建与部署记录

- 前端 ESLint、Prettier、TypeScript 检查与 Vite 构建通过。
- 后端改动文件 Ruff check、format check 与全量源码 mypy 通过；Git diff check 通过。
- 四个应用镜像从同一固定提交构建；[构建清单](artifacts/usage-display-20260921/build-manifest.json)保留源码与镜像校验值。
- 部署前加密备份成功；保留数据库、原额度计数及上一版应用镜像。API、Web、mock、edge、PostgreSQL 健康，migration 与 seed 退出码为 0，见[部署记录](artifacts/usage-display-20260921/deployment.json)。
- 按所有者要求，没有运行 pytest、Vitest、浏览器测试或模型试聊；新增回归测试代码未执行。健康状态与静态检查不替代业务验收。
- 本次未执行 Git push。
