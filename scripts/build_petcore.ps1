# petcore onedir 打包脚本
# 用法：
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 -Clean
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 -Clean -Installer
param(
    [switch]$Clean,
    [switch]$Installer,
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) {
    throw "missing .venv/Scripts/python.exe; create the venv first"
}

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--onedir",
    $(if ($Console) { "--console" } else { "--windowed" }),
    "--name", "dsh-pet-core",
    "--icon", "$root/assets/icon.ico",
    "--paths", $root,
    "--add-data", "$root/assets;assets",
    # 右键菜单默认布局随包分发；PyInstaller 只收集 .py，漏掉这份 JSON 会让
    # 菜单退化成「桌宠设置/退出」（代码侧有内置兜底，但打包仍必须带文件）。
    "--add-data", "$root/petcore/menu_templates;petcore/menu_templates",
    "--collect-submodules", "petcore",
    "--hidden-import", "pet.webm_clip",
    "--hidden-import", "pet.library",
    "--hidden-import", "pet.frameseq_clip",
    "--hidden-import", "pet.frameseq_provision",
    "--hidden-import", "PIL",
    # 内置/示例 mod 以数据形式随包分发，PyInstaller 静态分析看不到它们的惰性 import：
    # psutil（网络信息/回收内存）、QtTextToSpeech（示例 mod voice.chime）。
    "--hidden-import", "psutil",
    "--hidden-import", "PySide6.QtTextToSpeech",
    # API 密钥存系统钥匙串（惰性 import）：keyring 的 Windows 后端与依赖必须显式收集。
    "--hidden-import", "keyring.backends.Windows",
    "--collect-submodules", "keyring",
    "--collect-submodules", "win32ctypes",
    "packaging/petcore_entry.py"
)
if ($Clean) {
    $pyiArgs = @($pyiArgs[0], $pyiArgs[1], "--clean") + $pyiArgs[2..($pyiArgs.Count - 1)]
}
$builtin = Join-Path $root "petcore/builtin"
if (Test-Path $builtin) {
    $pyiArgs = @($pyiArgs[0], $pyiArgs[1], "--add-data", "$builtin;petcore/builtin") + $pyiArgs[2..($pyiArgs.Count - 1)]
}

Write-Host "== PyInstaller =="
& $python @pyiArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$exe = Join-Path $root "dist/dsh-pet-core/dsh-pet-core.exe"
if (-not (Test-Path $exe)) {
    throw "missing build output: $exe"
}

Write-Host "== smoke --check =="
& $exe --check --out "$root/dist/check.json"
if ($LASTEXITCODE -ne 0) {
    throw "packaged --check failed with exit code $LASTEXITCODE"
}
Write-Host "built: $root/dist/dsh-pet-core"

if ($Installer) {
    $iscc = Join-Path $root "tools/InnoSetup/ISCC.exe"
    if (-not (Test-Path $iscc)) {
        throw "missing tools/InnoSetup/ISCC.exe; run scripts/setup_packaging.ps1 first"
    }
    $version = (& $python -c "import petcore; print(petcore.__version__)").Trim()
    Write-Host "== Inno Setup =="
    & $iscc "/DMyAppVersion=$version" "packaging/petcore.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
    Write-Host "installer: $root/dist/dsh-pet-core-setup.exe"
}
