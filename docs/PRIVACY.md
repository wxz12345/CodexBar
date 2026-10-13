# CodexBar 隐私说明

CodexBar 是完全在用户 Windows 电脑上运行的开源桌面工具。项目不运营服务器，
不包含遥测、广告、分析 SDK 或远程崩溃上报。

## 本机读取

CodexBar 可能只读访问以下数据：

- `$CODEX_HOME/auth.json`（未设置时为 `~/.codex/auth.json`）：检测完整的 ChatGPT OAuth 登录。该文件不会被修改。
- Codex SQLite 和 rollout JSONL：任务栏选择本机来源，或账本选择本机及汇总来源时，统计本机 Codex 对话产生的 token 用量。
- 用户主动设置的模型价格、自定义 CA 证书和显示配置。

Token 日志来源遵循 `CODEX_HOME`，默认 `~/.codex`，包括数据库索引和
`sessions` / `archived_sessions` 目录。任务栏每次读取单个本机或 SSH 来源。账本默认读取本机；
用户可通过“汇总设备”选择本机和 SSH 来源汇总日志，历史、趋势和排行使用同一结果。
设备选择保存在与 `config.json` 同目录的 `aggregate_sources.json`，不改变任务栏来源。
启动时账本默认读取本机，不自动连接 SSH。日志不会按当前 OAuth 账号归属或筛选；用户负责确认
勾选的设备使用同一账号，CodexBar 不自动核验账号归属。未选设备、未记录日志和云端任务不包含在汇总中。

Token 用量页面可能在本机显示对话标题、模型名称和工作目录末级名称。这些信息只在
本地窗口中处理，不会由 CodexBar 上传。

## SSH 远程读取

用户在任务栏或账本选择远程数据源时，CodexBar 通过本机 OpenSSH、用户已有的 SSH 配置和密钥连接指定主机。
主机列表从 Codex Desktop 的本地连接设置及 `~/.ssh/config` 读取；列出主机不会发起连接。账本启动时使用本机来源；只有在用户切换到 SSH 来源或汇总已选设备时才连接相应主机。
远程 Python 脚本在内存中运行，只读打开远程 Codex SQLite 和 rollout，不安装程序或写入远程文件。

通过加密 SSH 返回的数据限于 token 计数、时间戳、模型、会话 ID、标题、工作目录和识别回放所需的标记。
用户消息仅保留用于计数的事件类型和时间戳；不会返回消息正文、工具输出、`auth.json` 或 OAuth 凭据。
汇总跨设备事件时按 session 标识、UTC 时间和 usage 去重；缺少可靠标识的事件会保留并提示可能重复。
读取数据仅用于本机统计，不发送给 OpenAI 或其他服务。

远程统计数据在系统临时目录中保存为 CodexBar 自有的 SQLite 和精简 JSONL，以复用本机统计逻辑。
正常关闭面板时删除；如果进程被强制结束或电脑断电，临时目录可能残留。
这些文件包含会话标题、目录和用量，没有认证凭据或完整对话正文。
远程 SSH 认证和主机密钥校验遵循用户自己的 OpenSSH 配置，程序不改写 SSH 配置或私钥。
任务栏来源保存在本机 `config.json` 的 `usage_source` 字段；账本的来源选择独立，修改它不会改变任务栏。
任务栏首次读取远程来源失败时显示不可用；断线时若已有缓存则保留并标记不完整。
账本汇总状态会列出新鲜、缓存和失败设备及更新时间。失败设备不会被当成零用量；若全部已选设备均失败且没有缓存，账本显示不可用。

## 本机写入

CodexBar 自有数据保存在 `%LOCALAPPDATA%\CodexBar`：

- `credentials.dat`：使用 Windows DPAPI 当前用户作用域加密的 OAuth 账号缓存。
- `config.json`：组件尺寸、颜色、字体、刷新间隔和任务栏来源别名 `usage_source`。
- `aggregate_sources.json`：用户为账本汇总选择的本机和 SSH 来源；与任务栏来源独立。
- `model_prices.json`：用户自定义模型价格。
- `official_model_prices.json`：官网公开模型和价格的缓存。
- `error.log` 与 `error.log.1`：经过脱敏并限制大小的诊断日志。

旧版本可能在 `~/.codex/.codexbar_cfg.json` 保存显示配置。新版本只在首次迁移时读取
旧配置，不再写回该文件。

## 网络请求

额度功能访问：

- `https://chatgpt.com/backend-api/wham/usage`
- `https://auth.openai.com/oauth/token`

请求会发送所选账号的 OAuth access token、账号 ID，或在刷新登录时发送 refresh token。
这是查询 ChatGPT/Codex 订阅额度所必需的数据。CodexBar 不会发送 rollout、对话标题、
工作目录、token 日报、模型价格或诊断日志。

模型与价格自动更新只读取 `https://developers.openai.com/api/docs/pricing.md` 的公开文档，
每日同步一次；失败后保留缓存并在一小时后重试。此请求不携带 OAuth 凭据、账号 ID、
本机对话、Token 统计或自定义价格，无需 API key。仅允许跳转到 OpenAI 官方 HTTPS 文档域名。

如果设置系统代理或自定义 CA，网络流量会经过用户选择的代理。用户应只信任自己控制或
明确信任的代理与证书机构。

用户点击账本的“官方账号用量”时，程序通过系统浏览器打开固定地址
`https://chatgpt.com/codex/settings/usage`。CodexBar 不向该 URL 附加凭据、日志或统计数据；
浏览器登录与后续网页请求由浏览器和官方页面处理。

## 清除和卸载

右键 CodexBar 可以清除当前账号或全部账号。完整卸载需要：

1. 退出 CodexBar 并删除程序目录。
2. 删除 `%LOCALAPPDATA%\CodexBar`，清除加密账号、设置、价格和日志。
3. 如不再回滚旧版本，可自行删除 `~/.codex/.codexbar_cfg.json` 和
   `~/.codex/.quota_widget_cfg.json`。

仅删除 EXE 不会删除 `%LOCALAPPDATA%\CodexBar` 中的数据。CodexBar 永远不会自动删除
`~/.codex/auth.json` 或 Codex 对话记录。

## 诊断信息

提交问题时请使用“导出脱敏诊断信息”，不要上传 `auth.json`、`credentials.dat`、
rollout JSONL 或包含 token 的截图。自动脱敏是纵深保护，不应替代提交前人工检查。
