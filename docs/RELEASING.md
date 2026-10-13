# 发布 Windows 版本

此文档适用于当前仓库的维护者。工作流通过 `GITHUB_REPOSITORY` 发布到运行它的仓库，不固定发布到上游。源码上传与 EXE 分发的区别见 [GitHub 上传指南](GITHUB_UPLOAD.md)。

## 本地构建

默认使用锁定的 uv 环境：

```powershell
uv sync --frozen --group build
uv run --frozen python -m unittest discover -q
.\scripts\build_exe.ps1
.\scripts\verify_portable.ps1
```

使用已准备好的 Conda 环境时，必须显式指定环境。此次本地验证使用 `codexbar-build`：

```powershell
conda run --no-capture-output -n codexbar-build python -m unittest discover -q
.\scripts\build_exe.ps1 -CondaEnvironment codexbar-build
.\scripts\verify_portable.ps1
```

若 `conda` 不在 PATH，构建脚本支持 `-CondaExecutable` 指定其完整路径。Conda 方式使用所选环境的依赖，不能声称与 `uv.lock` 完全相同；CI 默认使用 uv 锁定依赖。

构建会清理项目内旧 `build/` 并替换 `dist/CodexBar/` 的内容；先退出从该目录启动的旧版。脚本依次执行 PyInstaller 打包、许可证收集、隐私审计、实际 EXE 合成数据自检，再生成 ZIP 和 SHA-256。独立便携验证将 ZIP 解压到含中文和空格的目录，并移除子进程的 Python/Conda 搜索路径。

产物：

```text
dist/CodexBar/CodexBar.exe
dist/CodexBar-Windows-x64.zip
dist/CodexBar-Windows-x64.zip.sha256
```

ZIP 是完整 one-folder 便携包，不能只上传 EXE。当前构建未签名；若未来加入签名，应在生成 ZIP 和最终校验值之前完成。

## 准备正式版本

1. 确定新版本号，并同步 `pyproject.toml`、`codexbar/__init__.py`、`codexbar/version_info.txt` 中的版本，更新锁文件。不要用未改动的旧版本标签发布不同代码。
2. 如需更改项目主页、Issues 或 Security 地址，在已确定自己的仓库 URL 后更新 `pyproject.toml` 的 `[project.urls]`，然后更新并检查锁文件。保留原作者与 MIT 版权声明。
3. 在 `docs/releases/<tag>.md` 写入对应发布说明，说明实际功能、验证结果和已知限制；将 [CHANGELOG.md](../CHANGELOG.md) 中对应的 Unreleased 修改归入该版本。
4. 运行完整测试及构建，提交并推送源码，检查当前仓库的 CI 结果。
5. 创建并推送 `v<版本号>` 标签。下面的占位符必须替换后使用：

   ```powershell
   git tag -a vX.Y.Z -m "CodexBar vX.Y.Z"
   git push origin refs/tags/vX.Y.Z
   ```

Release 工作流检出标签对应的源码，核对版本，运行测试、编译、构建、许可证收集、隐私审计和打包 EXE 自检，通过后将 ZIP 与 SHA-256 发布到当前仓库。

如果标签推送没有启动发布，可在当前仓库 **Actions → Release → Run workflow** 中填写已有标签。查看 [工作流](../.github/workflows/release.yml)；新仓库需允许 Actions 运行。CI 产物保留 14 天，不应替代长期 Releases 下载。

## 手动上传便携包

在当前仓库 **Releases → Draft a new release** 选择对应代码的标签，填写说明，附上 ZIP 及同一构建的 SHA-256 文件，检查后发布。GitHub 自动生成的 Source code ZIP 不包含已构建应用。

当前本地修改基于 0.3.1，尚未单独标记新版本；上传源码本身不会创建正式版本。

## 发布前检查

- README、版本信息、发布说明与应用行为一致，未把设备日志写成全账号/云端总量。
- 包含 `使用说明.txt`、隐私与安全说明、MIT 许可和第三方许可证。
- ZIP 与 SHA-256 匹配；不要附带本机账号、配置、原始日志或会话数据。
- 实际 EXE 自检和 ZIP 解压验证通过；仍需自行验证目标机器的显示、真实额度请求与需要支持的 SSH 连接。
- 发布说明区分合成数据检查与真实服务验证，注明未签名、WebView2 依赖和已知统计限制。