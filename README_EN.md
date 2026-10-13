# CodexBar

English | [简体中文](README.md)

A Windows taskbar widget for Codex quota, tokens, trends, and API-equivalent cost estimates.
Extract the portable ZIP and double-click `CodexBar.exe`; Python and Conda are not required.

The original project is [zhuxianghcl-ctrl/CodexBar](https://github.com/zhuxianghcl-ctrl/CodexBar). These changes build on its fork, [Silver-Ray/CodexBar](https://github.com/Silver-Ray/CodexBar), preserving the original MIT license and attribution. Changes are based on 0.3.1 and do not yet have a separate version tag; see the [changelog](CHANGELOG.md). This is a community project, not affiliated with OpenAI or an official OpenAI product.

<p align="center">
  <img src="docs/images/taskbar-widget.png" alt="CodexBar taskbar widget" width="645">
</p>

## Download and run

Requirements: Windows 10/11 x64 and [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) for the token dashboard.

1. Download `CodexBar-Windows-x64.zip` from **this repository's Releases page**. If no release exists, a maintainer must first publish it following the [release guide](docs/RELEASING.md).
2. Extract the entire ZIP.
3. Open the extracted `CodexBar` folder and run `CodexBar.exe`.

Keep the complete folder, including `_internal` and license files; the EXE cannot run by itself. GitHub's **Source code (zip)** download contains source, not the ready-to-run app.
Exit any older or source instance first. Single-instance protection silently exits a second process.

The package is unsigned, so Windows SmartScreen may show an unknown publisher warning. Download the matching `.zip.sha256` and compare the SHA-256:

```powershell
(Get-FileHash .\CodexBar-Windows-x64.zip -Algorithm SHA256).Hash.ToLowerInvariant()
Get-Content .\CodexBar-Windows-x64.zip.sha256
```

## Features and controls

- **Account quota:** server quota windows, remaining percentages, reset times, and multiple cached ChatGPT OAuth accounts.
- **Taskbar usage:** today's tokens and estimated cost for the selected local or SSH source; a compact view or tray icon when space is limited.
- **Dashboard:** daily input, cached input, output, reasoning, conversation rankings, and weekly/monthly/yearly trends.
- **Multi-device ledger:** select this PC and SSH hosts in **Aggregate devices** to combine history, trends, and conversation rankings.
- **SSH sources:** the taskbar shows one source at a time; the ledger can show one SSH host or aggregate selected devices.
- **Customization:** width, font, colors, refresh interval, model prices, and high DPI support.

Click for the dashboard and double-click for settings. In the taskbar or tray icon's right-click menu, use **Usage source** to select this PC or a discovered SSH host; the taskbar remembers its selection. The dashboard has its own independent source selector and does not change the taskbar source.
The dashboard starts with this PC and does not connect to SSH automatically. Click **“汇总设备” (Aggregate devices)**, select this PC and SSH hosts that you believe use the same account, and save; the dashboard switches to **“全部已选设备（汇总）” (All selected devices (aggregate))**. The selection is stored in `aggregate_sources.json` beside `config.json`, independently of the taskbar source. You are responsible for confirming account ownership; CodexBar does not verify or filter device logs by OAuth account.
Existing ChatGPT OAuth logins are detected automatically; if `AUTH` appears, complete Codex login and refresh.
Log collection remains independent of quota authentication and network requests: the taskbar uses its single source, and the dashboard uses its current source or aggregate selection. If a remote source cannot be read on its first attempt, it is shown as unavailable instead of substituting local data or zero.

## Scope and accuracy

**Account quota and log-based tokens are separate data. Switching the quota account does not filter, attribute, or merge logs.**

| Data | Current coverage |
| --- | --- |
| Account quota | Server quota for the selected OAuth account |
| Taskbar tokens | Readable Codex logs from the selected local or single SSH source; one source at a time, across accounts |
| Dashboard tokens | Local by default; can aggregate selected local and SSH logs, with the same combined result for history, trends, and rankings |
| Full account token total | Not implemented; aggregation covers only selected readable logs, excluding unselected devices, unrecorded logs, and cloud tasks |

Discovery respects `CODEX_HOME`, defaulting to `~/.codex`. It combines SQLite indexes with `sessions` and `archived_sessions` scans, including unindexed logs, relative paths, moved archived logs, and duplicate file discovery.

- Cumulative `token_count` snapshots become increments; identifiable replay boundaries help handle copied history.
- Cached input belongs to input and reasoning belongs to output. Neither is added twice.
- Dates use the Windows machine's local timezone, including for SSH sources.
- Cross-device events are deduplicated by session identifier, UTC time, and usage. Events without a reliable identifier are retained and may produce a duplicate warning.
- Detected missing or unreadable records mark results incomplete. This cannot detect every unrecorded task.
- Deleted, inaccessible, or unrecorded logs and unselected devices or cloud tasks cannot be reconstructed or inferred.

Aggregate status shows the number of fresh devices, cached or failed devices, and the update time. Failed devices are never counted as zero; if every selected device fails and no cache is available, the ledger reports the source as unavailable.

Dollar values are public API-price estimates, **not subscription bills or actual charges**. Prices support daily public-document updates, offline caching, and manual overrides. Unknown models still contribute tokens, but their cost may be unavailable.

The **官方账号用量** (Official account usage) button opens the [official Codex usage page](https://chatgpt.com/codex/settings/usage) in your browser.
The workspace [Analytics API](https://learn.chatgpt.com/docs/enterprise/analytics-api) requires workspace enablement and appropriate admin permissions; this project does not integrate it.
Quota lookup uses an undocumented endpoint, and log formats may change. Log totals carry no billing-grade completeness guarantee.

## SSH requirements

Windows OpenSSH, working noninteractive authentication, and remote Python 3.8+ with readable Codex logs are required.
Hosts come from Codex Desktop connections and `~/.ssh/config` aliases. Authentication and host-key verification follow your OpenSSH configuration.

The probe reads remote data without installing anything. It returns accounting events and metadata, excluding message bodies, tool output, and credentials.
The taskbar and dashboard use the same read-only probe, cache, and timeout rules. Remote taskbar token counts are prefixed with **Remote**; the source menu and tray tooltip show the selected source and its status or errors. Disconnections retain a cached snapshot and mark it incomplete; a failed first read shows as unavailable. The taskbar selection is saved in the local `usage_source` config setting; ledger device selections are stored in `aggregate_sources.json` beside `config.json` and do not change the taskbar.

## Privacy and local data

CodexBar does not include telemetry, advertising, or remote log upload. Codex login files, databases, and rollouts are read-only.
OAuth caches use Windows DPAPI; settings, caches, and sanitized logs live under `%LOCALAPPDATA%\CodexBar`.

Quota and login refresh send necessary authentication information to ChatGPT/OpenAI. Pricing sync reads public documentation. CodexBar does not upload logs, titles, or token reports. See [privacy](docs/PRIVACY.md) and [security](.github/SECURITY.md).

Do not attach `auth.json`, `credentials.dat`, raw rollouts, or unchecked logs to Issues. Inspect sanitized exports before sharing.
Uninstall by exiting and deleting the app folder. Optionally delete `%LOCALAPPDATA%\CodexBar` to clear cached accounts and settings; preserve Codex's own files.

## Run from source

Use Windows, Python 3.13+, and [uv](https://docs.astral.sh/uv/). From the project root:

```powershell
uv sync --frozen
uv run --frozen pythonw .\codexbar.pyw
```

The included `启动 CodexBar.bat` also synchronizes the locked environment and starts the app.
With Conda, explicitly select a prepared environment for every command. Local validation used `codexbar-build`; see [contributing](.github/CONTRIBUTING.md).

## Build and validation

The default build uses locked dependencies:

```powershell
uv sync --frozen --group build
uv run --frozen python -m unittest discover -q
.\scripts\build_exe.ps1
```

It generates `dist/CodexBar-Windows-x64.zip` and its `.sha256`, collects licenses, audits privacy, and checks the actual EXE's Tk/WebView2 runtime with synthetic data. Independently verify the ZIP:

```powershell
.\scripts\verify_portable.ps1
```

Local validation on 2026-10-11 passed 288 tests, source and packaged GUI self-tests, and an extracted-ZIP check in a path containing Chinese characters and spaces with Python/Conda search paths removed from the child process.
**These synthetic checks do not validate live SSH or real account quota queries.** See the [validation record](verification/README.md).

## Screenshots

Inherited upstream screenshots illustrate the basic UI. See the app for the current scope notice and new account-usage button.

![Desktop and taskbar](docs/images/desktop-overview.jpg)

<p align="center">
  <img src="docs/images/settings-window.png" alt="Settings" width="377">
</p>

## Documentation and license

- [Changelog](CHANGELOG.md)
- [GitHub upload guide](docs/GITHUB_UPLOAD.md)
- [Windows release guide](docs/RELEASING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Contributing](.github/CONTRIBUTING.md)
- [Code of conduct](.github/CODE_OF_CONDUCT.md)
- [MIT License](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md)

Thanks to the original author [zhuxianghcl-ctrl](https://github.com/zhuxianghcl-ctrl/CodexBar), the fork [Silver-Ray/CodexBar](https://github.com/Silver-Ray/CodexBar), and contributors. Preserve the original copyright notices and bundled third-party licenses when redistributing source or binaries.
