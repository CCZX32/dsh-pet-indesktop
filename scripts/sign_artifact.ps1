# 给单个文件做 Authenticode 签名（含时间戳）。
#
# 用途有两个：
#   1. build_petcore.ps1 签 setup.exe / dsh-pet-core.exe；
#   2. Inno Setup 的 SignTool 钩子签**安装时才生成的** unins000.exe（本机没有
#      Windows SDK 的 signtool.exe，所以用这个脚本充当签名工具）。
#
# 证书必须在 Cert:\CurrentUser\My，且公钥已导入 CurrentUser\Root +
# TrustedPublisher——否则 Smart App Control 仍然会拦。
param(
    [Parameter(Mandatory = $true)][string]$Thumbprint,
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Error "sign_artifact: missing file: $Path"
    exit 1
}
$cert = Get-Item "Cert:\CurrentUser\My\$Thumbprint" -ErrorAction SilentlyContinue
if (-not $cert -or -not $cert.HasPrivateKey) {
    Write-Error "sign_artifact: no code-signing private key for thumbprint $Thumbprint"
    exit 1
}

# 时间戳服务器不可达时也要把签名落上（否则离线构建直接失败）。
$sig = $null
try {
    $sig = Set-AuthenticodeSignature -FilePath $Path -Certificate $cert `
        -HashAlgorithm SHA256 -TimestampServer $TimestampServer
} catch {
    Write-Host "sign_artifact: timestamp unavailable, signing without it: $($_.Exception.Message)"
}
if (-not $sig -or $sig.Status -ne "Valid") {
    $sig = Set-AuthenticodeSignature -FilePath $Path -Certificate $cert -HashAlgorithm SHA256
}
if ($sig.Status -ne "Valid") {
    Write-Error "sign_artifact: signature invalid for $Path : $($sig.Status) $($sig.StatusMessage)"
    exit 1
}
Write-Host "sign_artifact: signed $Path ($($cert.Subject))"
