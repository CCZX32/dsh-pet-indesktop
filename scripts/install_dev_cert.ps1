# 把开发签名证书（公钥）装进当前用户的信任存储。
#
# 为什么需要：Smart App Control（VerifiedAndReputablePolicyState=1）只放行「签名有效
# 且签发者受信任」的 PE。dsh-pet-core 的安装包/主程序/卸载器都用自签开发证书
# （CN=DSH Pet Core Dev）签名，所以**换一台机器测试时必须先把公钥装进
# CurrentUser\Root + CurrentUser\TrustedPublisher**，否则 setup 和卸载器照样被拦。
#
# 安全边界：这是一张自签证书。装上它等于信任「持有该私钥的人」签出的任何程序。
# 只在你自己控制的测试机上装，不要装到公用/办公机器。
#
# 用法：
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/install_dev_cert.ps1 `
#       -CertPath dist-sac-2026-10-27\dsh-pet-core-dev.cer
#   # 校验
#   pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/install_dev_cert.ps1 -Check
param(
    [string]$CertPath = "",
    [switch]$Check,
    [string]$Subject = "CN=DSH Pet Core Dev"
)

$ErrorActionPreference = "Stop"

function Find-DevCert([string]$Store) {
    Get-ChildItem $Store -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -like "*$Subject*" }
}

if ($Check) {
    $root = Find-DevCert 'Cert:\CurrentUser\Root'
    $pub = Find-DevCert 'Cert:\CurrentUser\TrustedPublisher'
    Write-Host "CurrentUser\Root:            $(if ($root) { "$($root.Thumbprint) exp=$($root.NotAfter)" } else { 'MISSING' })"
    Write-Host "CurrentUser\TrustedPublisher: $(if ($pub) { "$($pub.Thumbprint) exp=$($pub.NotAfter)" } else { 'MISSING' })"
    if (-not $root -or -not $pub) {
        Write-Host "结论：本机不信任开发证书，Smart App Control 会拦 setup/卸载器。"
        exit 1
    }
    Write-Host "结论：本机已信任开发证书。"
    exit 0
}

if (-not $CertPath) { throw "缺少 -CertPath（或改用 -Check 只做校验）" }
if (-not (Test-Path -LiteralPath $CertPath)) { throw "证书文件不存在：$CertPath" }

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2((Resolve-Path -LiteralPath $CertPath).Path)
Write-Host "证书：$($cert.Subject)  $($cert.Thumbprint)  exp=$($cert.NotAfter)"
if ($cert.HasPrivateKey) {
    # 导出的是 .cer（只有公钥）；带了私钥说明导出方式错了，别继续。
    throw "证书文件里含私钥：请只分发公钥 .cer"
}

foreach ($store in @('Cert:\CurrentUser\Root', 'Cert:\CurrentUser\TrustedPublisher')) {
    $existing = Get-ChildItem $store -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
    if ($existing) {
        Write-Host "已存在：$store"
        continue
    }
    Import-Certificate -FilePath (Resolve-Path -LiteralPath $CertPath).Path -CertStoreLocation $store | Out-Null
    Write-Host "已导入：$store"
}

Write-Host "完成。重新运行 setup 即可（SAC 不需要重启）。"
