$ErrorActionPreference = "Stop"
$TaskRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$TaskZip = Join-Path $TaskRoot "dist\CodexBar-Windows-x64.zip"
$TaskDestination = Join-Path $TaskRoot ("build\便携版 验证-" + [guid]::NewGuid().ToString("N"))
$TaskReport = Join-Path $TaskRoot "build\portable-runtime-check.json"

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($TaskZip, $TaskDestination)
$TaskExecutable = Join-Path $TaskDestination "CodexBar\CodexBar.exe"
$TaskSavedEnvironment = @{}
$TaskEnvironmentNames = @("PATH", "PYTHONHOME", "PYTHONPATH", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_SHLVL")
foreach ($TaskName in $TaskEnvironmentNames) {
    $TaskSavedEnvironment[$TaskName] = [Environment]::GetEnvironmentVariable($TaskName, "Process")
}
try {
    foreach ($TaskName in $TaskEnvironmentNames) {
        [Environment]::SetEnvironmentVariable($TaskName, $null, "Process")
    }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $TaskProcess = Start-Process -FilePath $TaskExecutable `
        -WorkingDirectory (Split-Path -Parent $TaskExecutable) `
        -ArgumentList @("--self-test", ('"' + $TaskReport + '"')) `
        -WindowStyle Hidden -PassThru
    if (-not $TaskProcess.WaitForExit(60000)) {
        $TaskProcess.Kill()
        throw "Portable runtime check timed out."
    }
    if ($TaskProcess.ExitCode -ne 0) {
        throw "Portable runtime check failed (exit $($TaskProcess.ExitCode))."
    }
} finally {
    foreach ($TaskName in $TaskEnvironmentNames) {
        [Environment]::SetEnvironmentVariable($TaskName, $TaskSavedEnvironment[$TaskName], "Process")
    }
}
$TaskResult = Get-Content -Raw -LiteralPath $TaskReport | ConvertFrom-Json
if (-not $TaskResult.success -or -not $TaskResult.frozen) {
    throw "Portable runtime report did not pass."
}
Get-Content -Raw -LiteralPath $TaskReport
Write-Host "Portable ZIP verified with Python/Conda paths removed."
