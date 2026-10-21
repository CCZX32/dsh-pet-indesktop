# 本项目内安装打包工具：PyInstaller（.venv）+ Inno Setup（tools/InnoSetup）
# 用法：pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/setup_packaging.ps1
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) {
    throw "missing .venv/Scripts/python.exe; create the venv first"
}

Write-Host "== PyInstaller =="
& $python -m pip install --upgrade "pyinstaller>=6.10,<7"
if ($LASTEXITCODE -ne 0) {
    throw "pip install pyinstaller failed"
}
& $python -m PyInstaller --version

$innoVersion = "6.7.3"
$innoUrl = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-$innoVersion.exe"
$innoSha256 = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"
$cache = Join-Path $root ".cache/packaging"
$installer = Join-Path $cache "innosetup-$innoVersion.exe"
$target = Join-Path $root "tools/InnoSetup"
$iscc = Join-Path $target "ISCC.exe"

if ((Test-Path $iscc) -and -not $Force) {
    Write-Host "Inno Setup already installed: $iscc"
    & $iscc /? | Select-Object -First 3
    exit 0
}

New-Item -ItemType Directory -Force -Path $cache | Out-Null
if (-not (Test-Path $installer)) {
    Write-Host "downloading Inno Setup $innoVersion ..."
    try {
        Invoke-WebRequest -Uri $innoUrl -OutFile $installer -UseBasicParsing
    } catch {
        Write-Host "Invoke-WebRequest failed; retrying with curl.exe --ssl-no-revoke"
        & curl.exe -L --ssl-no-revoke --fail --max-time 300 -o $installer $innoUrl
        if ($LASTEXITCODE -ne 0) {
            throw "download failed: $innoUrl (manual download allowed; expected sha256 $innoSha256)"
        }
    }
}

$actual = (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLowerInvariant()
if ($actual -ne $innoSha256) {
    throw "sha256 mismatch for Inno Setup: $actual (expected $innoSha256)"
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
Write-Host "installing Inno Setup portable into $target ..."
$process = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/PORTABLE=1",
    "/DIR=$target"
)
if ($process.ExitCode -ne 0) {
    throw "Inno Setup installer exited with code $($process.ExitCode)"
}
if (-not (Test-Path $iscc)) {
    throw "ISCC.exe not found after install: $iscc"
}
Write-Host "Inno Setup installed: $iscc"
& $iscc /? | Select-Object -First 3
