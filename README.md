# CodexBar

[English](README_EN.md) | 简体中文

Windows 任务栏上的 Codex 监控工具：查看账号额度、今日 token、用量趋势和 API 等价花费。
下载便携包，全部解压后双击 `CodexBar.exe` 即可使用，无需安装 Python 或 Conda。

原项目由 [zhuxianghcl-ctrl/CodexBar](https://github.com/zhuxianghcl-ctrl/CodexBar) 开发。本次修改基于其派生仓库 [Silver-Ray/CodexBar](https://github.com/Silver-Ray/CodexBar)，保留原项目 MIT 许可与署名。当前修改基于 0.3.1，尚未单独标记新版本；详见 [更新记录](CHANGELOG.md)。CodexBar 是社区项目，非 OpenAI 官方产品。

<p align="center">
  <img src="docs/images/taskbar-widget.png" alt="CodexBar 任务栏小组件" width="645">
</p>

## 下载与启动

系统要求：Windows 10/11 x64；Token 账本需要 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。

1. 在**本仓库的 Releases 页面**下载 `CodexBar-Windows-x64.zip`。若尚无 Release，维护者需先按 [发布指南](docs/RELEASING.md) 上传便携包。
2. 右键 ZIP，选择“全部解压”。
3. 打开解压后的 `CodexBar` 文件夹，双击 `CodexBar.exe`。

保留完整文件夹，包括 `_internal` 和许可证文件；不能单独复制 EXE。GitHub 自动提供的 **Source code (zip)** 是源码，不是可直接启动的应用。

如果旧版或源码版已经运行，请先通过它的右键菜单退出。程序有单实例保护，重复启动会静默退出新进程。

当前包未签名，Windows SmartScreen 可能提示“发布者未知”。可下载同一 Release 的 `.zip.sha256`，核对 ZIP 的 SHA-256：

```powershell
(Get-FileHash .\CodexBar-Windows-x64.zip -Algorithm SHA256).Hash.ToLowerInvariant()
Get-Content .\CodexBar-Windows-x64.zip.sha256
```

## 功能与操作

- **账号额度**：显示服务端提供的额度窗口、剩余比例和重置时间；支持缓存并切换多个 ChatGPT OAuth 账号。
- **任务栏用量**：按所选本机或 SSH 来源显示该设备今日 token 和 API 等价花费；空间不足时折叠或提供托盘入口。
- **Token 账本**：每日输入、缓存输入、输出、推理 token、对话排行及周/月/年趋势。
- **账本多设备汇总**：在“汇总设备”中勾选本机和 SSH 主机，合并查看历史、趋势和对话排行。
- **SSH 数据来源**：任务栏单独查看一个来源；账本可选择单个 SSH 主机或汇总已选设备。
- **显示设置**：调整长度、字号、颜色、刷新间隔和模型价格，支持高 DPI。

单击组件打开账本，双击打开设置。任务栏或托盘图标的右键菜单中，可在“用量来源”选择本机或已发现的 SSH 主机；任务栏会记住该选择。账本自己的来源选择独立，不会改变任务栏来源。
账本默认只读取本机，不会在启动时自动连接 SSH。点击“汇总设备”，勾选本机及使用同一账号的 SSH 设备并保存后，账本会切换到“全部已选设备（汇总）”。此选择保存在与 `config.json` 同目录的 `aggregate_sources.json`，独立于任务栏来源。请由你确认设备使用同一账号；程序不会通过 OAuth 自动核验或筛选账号归属。
已有 ChatGPT OAuth 登录时会自动检测账号；显示 `AUTH` 时，先完成 Codex 登录，再通过右键菜单刷新。
额度认证或网络请求失败时，日志用量仍独立读取：任务栏使用其单个来源，账本使用其当前来源或汇总选择。首次无法读取远程来源时显示不可用，不会以本机数据或零值代替。

## 统计范围与准确性

**账号额度与日志 token 是两种数据。切换额度账号不会筛选、归属或合并日志。**

| 数据 | 当前覆盖范围 |
| --- | --- |
| 账号额度 | 所选 OAuth 账号的服务端额度状态 |
| 任务栏 token | 所选本机或单个 SSH 来源的可读取 Codex 日志；一次显示一个来源，不按账号区分 |
| 账本 token | 默认本机；也可汇总用户选中的本机和 SSH 日志，历史、趋势及排行使用同一汇总结果 |
| 全账号 token 总量 | 尚未实现；汇总仅覆盖用户选中且可读取的日志，不包含未选设备、未记录日志或云端任务 |

读取范围由 `CODEX_HOME` 决定，未设置时使用 `~/.codex`。统计结合 SQLite 索引与 `sessions`、`archived_sessions` 目录扫描，补充未入库日志，处理相对路径、归档移动后失效的索引路径，并按实际文件路径去重。

- 将 `token_count` 累计快照转换为增量；按可识别的回放边界处理重复历史。
- 缓存输入属于输入，推理属于输出，总量不再次加上这两部分。
- 日期按运行 CodexBar 的 Windows 本地时区划分，包括 SSH 来源。
- 跨设备事件按 session 标识、UTC 时间和 usage 去重；缺少可靠标识的事件会保留，并提示结果可能重复。
- 发现记录缺失或无法读取时标记不完整；该标记不能检测所有未记录的任务。
- 已删除、不可访问、未记录的日志，以及未选中的设备和云端任务，无法恢复或推算。

汇总状态会显示新鲜设备数、缓存和失败设备以及更新时间。失败设备不会当作零用量；若所有已选设备都失败且没有缓存，账本会显示不可用。

金额按公开 API 价格估算，**不是 ChatGPT 订阅账单或实际扣费**。模型价格支持每日公开文档同步、离线缓存和手动覆盖；未识别模型仍计入 token，但金额可能不完整。

账本的“官方账号用量”按钮会在浏览器打开 [Codex 账号用量页面](https://chatgpt.com/codex/settings/usage)。
工作区 [Analytics API](https://learn.chatgpt.com/docs/enterprise/analytics-api) 需要工作区启用和相应 Admin 权限，本项目尚未接入该 API。
额度查询使用未公开接口，本地日志格式也可能随上游变化，日志统计不具备账单级完整性保证。

## SSH 使用条件

本机需有 Windows OpenSSH 客户端，远程主机需有 Python 3.8+、可读取的 Codex 日志，以及可用的非交互 SSH 认证。
来源列表读取 Codex Desktop 连接配置和 `~/.ssh/config` 中的主机别名；认证和主机密钥校验遵循用户自己的 OpenSSH 配置。

探针只读远程数据，不在主机安装程序；通过 SSH 返回精简记账事件与会话元数据，不返回消息正文、工具输出或登录凭据。
任务栏和账本的 SSH 读取使用相同的只读探针、缓存和超时规则。任务栏远程 token 数前显示“远程”；来源菜单和托盘提示显示当前来源及错误或状态。断线时若有缓存则保留并标记不完整；首次读取失败时显示不可用。任务栏来源保存在本机配置 `usage_source`；账本的汇总设备选择保存在同目录的 `aggregate_sources.json`，两者独立。

## 隐私与本地数据

项目不包含遥测、广告或远程日志上传。Codex 登录文件、数据库和 rollout 只读。
OAuth 缓存通过 Windows DPAPI 加密，设置、缓存和脱敏日志保存在 `%LOCALAPPDATA%\CodexBar`。

额度查询与登录刷新会向 ChatGPT/OpenAI 发送所选账号的必要认证信息；价格同步只读取公开文档。日志、对话标题和 token 报表不会由 CodexBar 上传。详见 [隐私说明](docs/PRIVACY.md) 与 [安全政策](.github/SECURITY.md)。

提交 Issue 时不要附上 `auth.json`、`credentials.dat`、原始 rollout 或未经检查的日志。可使用“导出脱敏诊断信息”，分享前仍需人工检查。
卸载时退出程序并删除解压目录；如需清除账号和设置，再删除 `%LOCALAPPDATA%\CodexBar`，保留 Codex 自己的会话与登录文件。

## 从源码运行

开发环境使用 Windows、Python 3.13+ 和 [uv](https://docs.astral.sh/uv/)。在项目根目录执行：

```powershell
uv sync --frozen
uv run --frozen pythonw .\codexbar.pyw
```

也可双击 `启动 CodexBar.bat`，按锁文件同步环境后启动。
使用 Conda 时应显式指定已准备好的环境，避免混用解释器；本次本地验证使用 `codexbar-build`，见 [贡献指南](.github/CONTRIBUTING.md)。

## 构建与验证

默认锁定依赖的构建方式：

```powershell
uv sync --frozen --group build
uv run --frozen python -m unittest discover -q
.\scripts\build_exe.ps1
```

脚本生成 `dist/CodexBar-Windows-x64.zip` 和对应 `.sha256`，包含许可证收集、隐私审计，以及实际 EXE 的 Tk/WebView2 合成数据自检。独立便携验证：

```powershell
.\scripts\verify_portable.ps1
```

2026-10-11 本地验证：288 项测试通过，源码与打包 EXE 自检通过；ZIP 在含中文及空格的路径中解压、移除子进程 Python/Conda 搜索路径后自检通过。
**这些检查使用合成日志，不代表真实 SSH 连接或真实账号额度查询已经验证。** 复现方式及限制见 [验证记录](verification/README.md)。

## 截图

以下沿用上游截图展示基本界面；最新统计范围提示和按钮以实际应用为准。

![桌面与任务栏](docs/images/desktop-overview.jpg)

<p align="center">
  <img src="docs/images/settings-window.png" alt="设置界面" width="377">
</p>

## 项目文档与许可

- [更新记录](CHANGELOG.md)
- [上传 GitHub 指南](docs/GITHUB_UPLOAD.md)
- [Windows 发布指南](docs/RELEASING.md)
- [架构说明](docs/ARCHITECTURE.md)
- [贡献指南](.github/CONTRIBUTING.md)
- [行为准则](.github/CODE_OF_CONDUCT.md)
- [MIT License](LICENSE) 与 [第三方声明](THIRD_PARTY_NOTICES.md)

感谢原作者 [zhuxianghcl-ctrl](https://github.com/zhuxianghcl-ctrl/CodexBar)、派生仓库 [Silver-Ray/CodexBar](https://github.com/Silver-Ray/CodexBar) 及贡献者。再分发源码或便携包时，请保留原版权声明和所附第三方许可证。

维护时可从 [诊断脱敏](codexbar/diagnostics.py)、[Windows 版本信息](codexbar/version_info.txt)、[发布隐私审计](scripts/audit_release.py) 和 [许可证收集](scripts/collect_licenses.py) 了解对应实现。
