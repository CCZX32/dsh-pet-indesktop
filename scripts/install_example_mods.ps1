# 安装 examples/petcore-mods 下的 5 个示例 feature mod
# 用法：pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/install_example_mods.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) {
    throw "missing .venv/Scripts/python.exe; create the venv first"
}

$ids = @(
    "fun.divination",
    "fun.festival",
    "reminder.todo",
    "voice.chime",
    "media.music"
)

foreach ($id in $ids) {
    $pack = Join-Path $root "examples/petcore-mods/$id"
    if (-not (Test-Path (Join-Path $pack "mod.json"))) {
        throw "missing example mod: $pack"
    }
    Write-Host "installing $id ..."
    & $python -m petcore mods install $pack --force
    if ($LASTEXITCODE -ne 0) {
        throw "install failed: $id"
    }
}

& $python -c "from petcore import paths; from petcore.config import Config; c=Config.load(paths.data_root()); c.set('allow_feature_mods', True); c.save(); print('allow_feature_mods=True')"
Write-Host "done. restart petcore or use Settings -> Extensions -> Reload."
