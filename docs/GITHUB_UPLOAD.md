# 上传到 GitHub

源码仓库用于保存代码与文档；Releases 用于提供可下载、点击启动的应用。不要把整个开发目录连同环境和构建缓存一并上传。

## 上传源码

若基于上游继续维护，推荐在 GitHub Fork 原作者的仓库 [zhuxianghcl-ctrl/CodexBar](https://github.com/zhuxianghcl-ctrl/CodexBar) 到自己的账号，再在自己的 Fork 中创建工作分支（例如 `codex/taskbar-usage-source`）。Fork 复制仓库及历史，分支用于管理具体修改，两者是不同操作。

这份源码基于 [Silver-Ray/CodexBar](https://github.com/Silver-Ray/CodexBar)，它也是原作者仓库的 Fork。迁移修改时应保留这份代码所包含的派生改动与来源署名。也可以创建新仓库，但仍需保留原作者和派生来源，以及 MIT 版权声明。

推荐在确认远程仓库后使用 Git 提交，执行前先检查 `git rev-parse --show-toplevel`、`git status` 和实际暂存文件，确保操作的是目标项目而非父目录的仓库。若本目录只是解压的源码，优先在另一个目录克隆自己的 Fork，再迁移修改以保留历史；若选择初始化新仓库，应先确认项目根目录。

应提交：

- `codexbar/`、入口脚本、测试、`scripts/`、`CodexBar.spec`。
- `pyproject.toml`、`uv.lock`、`.gitignore`、`.gitattributes`、`.github/`。
- 中英文 README、`CHANGELOG.md`、`docs/`、`verification/README.md`。
- `LICENSE`、`THIRD_PARTY_NOTICES.md`、`third_party_licenses/` 及其他源码必需文件。

不应提交：

- `.venv/`、Conda 环境、`build/`、`dist/`、Python 缓存。
- 本机生成的自检 JSON 报告、诊断日志、账号文件、环境变量文件。
- `auth.json`、`credentials.dat`、私钥、原始 rollout 或私人会话数据。

`.gitignore` 已覆盖上述常见文件，但不会移除已经跟踪的文件，也不能代替检查其他敏感文件。
**GitHub 网页“Upload files”不会自动遵循本机的 .gitignore。** 如果使用网页上传，必须手动排除环境、构建目录、报告和敏感文件，并检查隐藏文件是否需要上传。

当前维护仓库为 [wxz12345/CodexBar](https://github.com/wxz12345/CodexBar)，SSH 地址为 `git@github.com:wxz12345/CodexBar.git`；`pyproject.toml` 的主页、源码、Issues 和 Security 地址均指向此仓库。原项目与派生来源仍在 README 中保留，不要删除原作者署名或 MIT 版权声明。

现有仓库可以保留 Git 提交历史，但向独立仓库推送不会自动建立 GitHub 的 Fork 关系。`.publish/` 是本地准备推送时使用的隔离目录，由 `.gitignore` 排除。

## 上传可直接使用的应用

构建完成后，在仓库的 **Releases** 中附上：

```text
dist/CodexBar-Windows-x64.zip
dist/CodexBar-Windows-x64.zip.sha256
```

这两个文件是 Release 附件，不需要强制加入 Git 源码提交。用户下载应用 ZIP、全部解压后双击 EXE。
不能只上传 `CodexBar.exe`；不能把 GitHub 的 Source code ZIP 当作便携版。

详细版本、标签、CI 和手动发布步骤见 [Windows 发布指南](RELEASING.md)。
已有 ZIP 的最终校验值以旁边的 `.sha256` 为准，不要复用旧构建的值。

## 新仓库设置

- 按需启用 GitHub Actions；现有 Release 工作流自动面向当前仓库。
- 如使用现有 CI 默认分支规则，默认分支应为 `main`；其他名称需调整 [ci.yml](../.github/workflows/ci.yml)。
- 在仓库 Security 设置中启用 Private vulnerability reporting，并按 [安全政策](../.github/SECURITY.md) 提供私密报告渠道。
- 上传后检查 README 图片与文档链接，并确认 Releases 确实包含应用附件。
