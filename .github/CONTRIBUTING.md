# Contributing to CodexBar

感谢改进 CodexBar。桌面应用只支持 Windows，开发使用 Python 3.13+、Tk、pywebview 和 PyInstaller。

## 开发环境

默认使用 uv 锁定环境：

```powershell
uv sync --frozen --group build
uv run --frozen python -m unittest discover -q
uv run --frozen python -m compileall -q .\codexbar .\codexbar.pyw .\codexbar_dashboard.pyw
uv run --frozen pythonw .\codexbar.pyw
```

不要仅运行单个旧测试文件而遗漏其他模块。行为修改应添加能够复现实际问题的测试；文档修改通常只需检查内容与链接，避免无关重构。

也可使用已准备好的 Conda 环境。每次运行 Python、pip、测试和构建都需显式指定同一环境；本次本地验证环境为 `codexbar-build`：

```powershell
conda run --no-capture-output -n codexbar-build python -m unittest discover -q
conda run --no-capture-output -n codexbar-build pythonw .\codexbar.pyw
.\scripts\build_exe.ps1 -CondaEnvironment codexbar-build
```

环境必须具备 Tk 和项目依赖；Conda 构建不自动保证依赖与 uv 锁文件一致，不要混用另一环境的解释器或 pip。

## 构建与验证

```powershell
uv sync --frozen --group build
.\scripts\build_exe.ps1
.\scripts\verify_portable.ps1
```

脚本收集页面资源、中文使用说明、法律文件和许可证，执行凭据/路径审计与实际 EXE 自检，再生成 `dist/` 下的 ZIP 和 SHA-256。
公开分发需要完整 ZIP，不能只上传单个 EXE。构建会替换旧产物，先退出从该目录运行的实例。

源码账本由 `codexbar_dashboard.pyw` 打开；打包后由 `CodexBar.exe --dashboard` 打开。
`--self-test <报告路径>` 检查真实 Tk/WebView2 与页面桥接，但使用临时合成日志，不代表真实账号额度或 SSH 验证。
复现与限制见 [验证记录](../verification/README.md)，版本发布见 [发布指南](../docs/RELEASING.md)。

## 数据与安全边界

禁止提交真实 OAuth token、API key、账号 ID、登录文件、原始日志、rollout、私人对话标题或本机绝对路径。测试使用明显虚构的值和隔离临时目录。

- 保持 Codex 登录、数据库和 rollout 只读；不要关闭 TLS 或 SSH 主机密钥校验。
- 日志用量不按额度账号归属，不用额度百分比推算 token。
- 缓存输入和推理 token 不得重复计入总量或费用。
- 新增来源必须明确覆盖范围、不可读取状态，以及是否经过真实连接验证。
- WebView 仅暴露所需 API；“官方账号用量”只打开固定官方 URL。
- 不扩大 GitHub Actions 权限，不绕过许可证收集或隐私审计。

## 提交与 Pull Request

项目采用 DCO。提交时使用 `git commit -s`，表示有权按 MIT License 提交贡献；见 <https://developercertificate.org/>。

PR 应说明用户可见行为与安全影响，列出实际验证，更新相关中英文文档。
保留上游版权与署名，并遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。提交贡献即表示同意按仓库 MIT License 授权。