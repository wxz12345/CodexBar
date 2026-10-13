param(
    [string]$CondaEnvironment = "",
    [string]$CondaExecutable = "conda"
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = [System.IO.Path]::GetFullPath((Split-Path -Parent $ScriptDir))
$RootPrefix = $Root.TrimEnd(
    [char[]]@(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
) + [System.IO.Path]::DirectorySeparatorChar
Set-Location $Root

function Invoke-BuildPython {
    param([string[]]$Arguments)
    if ($CondaEnvironment) {
        & $CondaExecutable run --no-capture-output -n $CondaEnvironment python @Arguments
    } else {
        uv run --frozen --group build python @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Build Python command failed (exit $LASTEXITCODE)."
    }
}

function Resolve-RepositoryChildPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Candidate = [System.IO.Path]::GetFullPath($Path)
    if (-not $Candidate.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside the repository: $Candidate"
    }
    return $Candidate
}

$BuildDir = Resolve-RepositoryChildPath (Join-Path $Root "build")
$StagingDir = Resolve-RepositoryChildPath (Join-Path $BuildDir "release-dist")
$StagedAppDir = Resolve-RepositoryChildPath (Join-Path $StagingDir "CodexBar")
$DistAppDir = Resolve-RepositoryChildPath (Join-Path $Root "dist\CodexBar")
$ReleaseZip = Resolve-RepositoryChildPath (Join-Path $Root "dist\CodexBar-Windows-x64.zip")
$ReleaseHash = Resolve-RepositoryChildPath ($ReleaseZip + ".sha256")
$ExePath = Join-Path $DistAppDir "CodexBar.exe"
$DashboardAsset = Join-Path $DistAppDir "_internal\codexbar\web_assets\dashboard.html"
$IconAsset = Join-Path $DistAppDir "_internal\codexbar\assets\codexbar.ico"
$PublicPriceAsset = Join-Path $DistAppDir "_internal\codexbar\assets\official_model_prices.json"
$RemoteProbeAsset = Join-Path $DistAppDir "_internal\codexbar\assets\remote_usage_probe.py"

# Check before deleting anything: a running release can lock only some files,
# leaving an unusable half-removed bundle if cleanup silently continues.
$RunningRelease = Get-Process -Name CodexBar -ErrorAction SilentlyContinue | Where-Object {
    [string]::Equals($_.Path, $ExePath, [System.StringComparison]::OrdinalIgnoreCase)
}
if ($RunningRelease) {
    throw "Close the running release at $ExePath before building. No files were removed."
}

Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue

Invoke-BuildPython -Arguments @("-m", "PyInstaller", "--clean", "--noconfirm", "--distpath", $StagingDir, "CodexBar.spec")
if ($LASTEXITCODE -ne 0) {
    throw "Build failed: PyInstaller did not complete successfully."
}

# A terminal whose current directory is the release folder prevents deleting
# the folder itself. Build elsewhere, then replace its contents in place.
if (-not (Test-Path -LiteralPath (Join-Path $StagedAppDir "CodexBar.exe"))) {
    throw "Build failed: the staged executable was not created."
}
New-Item -ItemType Directory -Path $DistAppDir -Force | Out-Null
Get-ChildItem -LiteralPath $DistAppDir -Force | ForEach-Object {
    $PreviousFile = Resolve-RepositoryChildPath $_.FullName
    Remove-Item -LiteralPath $PreviousFile -Recurse -Force -ErrorAction Stop
}
Get-ChildItem -LiteralPath $StagedAppDir -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $DistAppDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build failed: dist\CodexBar\CodexBar.exe was not created."
}
if (-not (Test-Path -LiteralPath $DashboardAsset)) {
    throw "Build failed: dashboard.html was not bundled."
}
if (-not (Test-Path -LiteralPath $IconAsset)) {
    throw "Build failed: codexbar.ico was not bundled."
}
if (-not (Test-Path -LiteralPath $PublicPriceAsset)) {
    throw "Build failed: the public offline pricing snapshot was not bundled."
}
if (-not (Test-Path -LiteralPath $RemoteProbeAsset)) {
    throw "Build failed: the SSH accounting probe was not bundled."
}

$ReleaseDocuments = @(
    @{ Source = "LICENSE"; Destination = "LICENSE" },
    @{ Source = "docs\PRIVACY.md"; Destination = "PRIVACY.md" },
    @{ Source = ".github\SECURITY.md"; Destination = "SECURITY.md" },
    @{ Source = "THIRD_PARTY_NOTICES.md"; Destination = "THIRD_PARTY_NOTICES.md" }
    @{ Source = "docs\QUICK_START.txt"; Destination = "使用说明.txt" }
)
foreach ($Document in $ReleaseDocuments) {
    Copy-Item -LiteralPath (Join-Path $Root $Document.Source) `
        -Destination (Join-Path $DistAppDir $Document.Destination)
}

$LicenseDir = Join-Path $DistAppDir "licenses"
Invoke-BuildPython -Arguments @(".\scripts\collect_licenses.py", $LicenseDir)
if ($LASTEXITCODE -ne 0) {
    throw "Build failed: third-party license collection failed."
}

Invoke-BuildPython -Arguments @(".\scripts\audit_release.py", $DistAppDir, "--verify-python-runtime")
if ($LASTEXITCODE -ne 0) {
    throw "Build failed: release privacy audit failed."
}

$RuntimeReport = Join-Path $BuildDir "packaged-runtime-check.json"
$CheckProcess = Start-Process -FilePath $ExePath `
    -ArgumentList @("--self-test", ('"' + $RuntimeReport + '"')) `
    -WindowStyle Hidden -PassThru
if (-not $CheckProcess.WaitForExit(60000)) {
    $CheckProcess.Kill()
    throw "Build failed: packaged GUI runtime check timed out."
}
if ($CheckProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $RuntimeReport)) {
    throw "Build failed: packaged GUI runtime check failed."
}
$RuntimeResult = Get-Content -Raw -LiteralPath $RuntimeReport | ConvertFrom-Json
if (-not $RuntimeResult.success -or -not $RuntimeResult.frozen) {
    throw "Build failed: packaged GUI runtime check did not pass."
}

Remove-Item -LiteralPath $ReleaseZip -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ReleaseHash -Force -ErrorAction SilentlyContinue
Compress-Archive -LiteralPath $DistAppDir -DestinationPath $ReleaseZip -CompressionLevel Optimal
$HashAlgorithm = [System.Security.Cryptography.SHA256]::Create()
$HashStream = [System.IO.File]::OpenRead($ReleaseZip)
try {
    $Hash = [System.BitConverter]::ToString($HashAlgorithm.ComputeHash($HashStream)).Replace("-", "").ToLowerInvariant()
} finally {
    $HashStream.Dispose()
    $HashAlgorithm.Dispose()
}
$HashLine = "$Hash  $(Split-Path -Leaf $ReleaseZip)"
[System.IO.File]::WriteAllText($ReleaseHash, $HashLine + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Write-Host "Built: $ExePath"
Write-Host "Release: $ReleaseZip"
Write-Host "SHA256: $ReleaseHash"
