# 创建「本机开发用」代码签名证书，并把公钥导入当前用户的信任存储。
#
# 为什么需要：Windows 11 的 Smart App Control 会拦截**未签名**的新构建产物
# （CreateProcess 返回 4551 "An Application Control policy has blocked this file."），
# PyInstaller 的 exe 与 Inno 的 setup 都会中招。用本机信任的自签名证书签过后即可运行。
#
# 安全边界：
#   - 私钥只落在 CurrentUser\My（非导出、不需要管理员）；
#   - 公钥导入 CurrentUser\Root + CurrentUser\TrustedPublisher，**只影响当前用户**；
#   - 这是开发证书，不是公开发布凭证：别的机器不信任它，正式分发必须换 CA 证书。
#
# 用法：
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/make_dev_signing_cert.ps1
#   pwsh ... -Subject "CN=My Name"
#   pwsh ... -Remove        # 从两个信任存储里移除同名证书（私钥保留在 My）
param(
    [string]$Subject = "CN=DSH Pet Core Dev, O=DSH Pet, C=CN",
    [int]$Years = 3,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

function Find-Cert {
    Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.Subject -eq $Subject } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
}

if ($Remove) {
    $cert = Find-Cert
    if (-not $cert) { throw "no certificate with subject: $Subject" }
    foreach ($store in @("Root", "TrustedPublisher")) {
        Get-ChildItem "Cert:\CurrentUser\$store" |
            Where-Object { $_.Thumbprint -eq $cert.Thumbprint } |
            Remove-Item -Force
        Write-Host "removed from CurrentUser\$store"
    }
    Write-Host "private key kept in CurrentUser\My ($($cert.Thumbprint))"
    exit 0
}

$cert = Find-Cert
if ($cert) {
    Write-Host "reuse existing certificate: $($cert.Thumbprint)"
} else {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
        -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter (Get-Date).AddYears($Years)
    Write-Host "created certificate: $($cert.Thumbprint)"
}

$cerPath = Join-Path $env:TEMP "dsh-pet-core-dev-signing.cer"
Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
foreach ($store in @("Root", "TrustedPublisher")) {
    $already = Get-ChildItem "Cert:\CurrentUser\$store" |
        Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
    if ($already) {
        Write-Host "already trusted in CurrentUser\$store"
    } else {
        Import-Certificate -FilePath $cerPath -CertStoreLocation "Cert:\CurrentUser\$store" | Out-Null
        Write-Host "trusted in CurrentUser\$store"
    }
}

Write-Host ""
Write-Host "thumbprint: $($cert.Thumbprint)"
Write-Host "build with:"
Write-Host "  pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 -Clean -Installer -SignThumbprint $($cert.Thumbprint)"
