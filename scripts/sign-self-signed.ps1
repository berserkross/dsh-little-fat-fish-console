<#
.SYNOPSIS
  用本机的自签名代码签名证书给构建产物签名（仅供本机/自用，不能消除 SmartScreen）。

.DESCRIPTION
  自签名证书的根就是它自己，所以只有把这个 .cer 导入「受信任的根证书颁发机构」的机器
  才会显示「签名有效」。别人的机器上显示的是「未知发布者（已签名但链不可信）」，
  和未签名没有实质区别。要给别人发布的版本请用真实 CA 证书，见 docs/build-and-signing.md。

  私钥策略是 NonExportable：证书只活在这台机器的 CurrentUser\My 里，导不出 .pfx。
  换机器/重装系统就得重新生成；已签名文件的历史签名仍可验证（时间戳在）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\sign-self-signed.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\sign-self-signed.ps1 -TrustLocal
#>
param(
    [string]$Exe = (Join-Path $PSScriptRoot '..\dist\DSHConsole.exe'),
    [string]$Subject = 'CN=YANG TIANRUI',
    [string]$CerPath = (Join-Path $PSScriptRoot '..\certs\dsh-console-selfsigned.cer'),
    [string]$TimestampServer = 'http://timestamp.digicert.com',
    [switch]$TrustLocal
)

$ErrorActionPreference = 'Stop'

$Exe = [System.IO.Path]::GetFullPath($Exe)
$CerPath = [System.IO.Path]::GetFullPath($CerPath)
if (-not (Test-Path -LiteralPath $Exe)) {
    Write-Host "找不到产物：$Exe（先跑 py -3.11 -m PyInstaller --noconfirm DSHConsole.spec）"
    exit 1
}

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $Subject } |
    Select-Object -First 1

if (-not $cert) {
    Write-Host "没有现成证书，生成一张自签名代码签名证书：$Subject"
    $certParams = @{
        Type = 'CodeSigningCert'
        Subject = $Subject
        FriendlyName = 'DSH Console (self-signed, local only)'
        CertStoreLocation = 'Cert:\CurrentUser\My'
        NotAfter = (Get-Date).AddYears(3)
        KeyExportPolicy = 'NonExportable'
        KeyUsage = 'DigitalSignature'
        TextExtension = @('2.5.29.37={text}1.3.6.1.5.5.7.3.3')
    }
    $cert = New-SelfSignedCertificate @certParams
}

Write-Host "证书指纹：$($cert.Thumbprint)"
Write-Host "有效期至：$($cert.NotAfter)"

# 公开证书随仓库走：别人可以选择信任它，但它不是发布级凭证。
$cerDir = Split-Path -Parent $CerPath
if (-not (Test-Path -LiteralPath $cerDir)) { New-Item -ItemType Directory -Path $cerDir | Out-Null }
Export-Certificate -Cert $cert -FilePath $CerPath -Type CERT | Out-Null
Write-Host "公开证书已导出：$CerPath"

if ($TrustLocal) {
    # 用 .NET 直接写存储：Import-Certificate 往 Root 写会弹确认框，非交互环境下会失败。
    $already = @(Get-ChildItem Cert:\CurrentUser\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }).Count
    if ($already -eq 0) {
        $public = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $CerPath
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser')
        $store.Open('ReadWrite')
        $store.Add($public)
        $store.Close()
        Write-Host "已加入 CurrentUser\Root（仅当前用户，可用下面的命令撤销）"
    } else {
        Write-Host "CurrentUser\Root 里已经有这张证书"
    }
}

$hashBefore = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash

Set-AuthenticodeSignature -FilePath $Exe -Certificate $cert -TimestampServer $TimestampServer -HashAlgorithm SHA256 | Out-Null

$check = Get-AuthenticodeSignature $Exe
$hashAfter = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash

Write-Host ""
Write-Host "产物：$Exe"
Write-Host "大小：$((Get-Item -LiteralPath $Exe).Length) B"
Write-Host "签名前 SHA256：$hashBefore"
Write-Host "签名后 SHA256：$hashAfter"
Write-Host "签名者：$($check.SignerCertificate.Subject)"
if ($check.TimeStamperCertificate) {
    Write-Host "时间戳：$($check.TimeStamperCertificate.Subject)"
} else {
    Write-Host "时间戳：无（时间戳服务器不可达时会退化到这里）"
}
Write-Host "验证状态：$($check.Status) — $($check.StatusMessage)"
Write-Host ""
Write-Host "本机撤销信任：certutil -user -delstore Root $($cert.Thumbprint)"
Write-Host "本机删除证书：Remove-Item Cert:\CurrentUser\My\$($cert.Thumbprint)"

if ($check.Status -ne 'Valid') {
    Write-Host ""
    Write-Host "状态不是 Valid：这台机器没信任这张自签名证书。加 -TrustLocal 重跑，或手动导入 $CerPath。"
    exit 1
}
exit 0
