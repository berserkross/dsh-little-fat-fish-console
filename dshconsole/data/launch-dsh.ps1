param(
    [string]$Harness = '',   # DSH 安装目录（含 node_modules\@deepseek-ai\dsh）；空则回退 DSH_HOME 父目录，仍为空则报错退出
    [string]$NodeExe = '',   # node.exe 全路径；空则用 PATH 里的 node
    [string]$BinJs   = '',   # bin.js 全路径；空则由 $Harness 推导
    [string]$DshHome = '',   # DSH_HOME；空则由 $Harness 推导
    [int]$Port       = 3080, # 本机网页端口
    [string]$Chrome  = ''    # 打开地址用的浏览器；空则用系统默认浏览器
)

$ErrorActionPreference = 'SilentlyContinue'

# ---------------- 参数回退（GUI 一律显式传参，这里只兜双击独立运行） ----------------
if (-not $Harness -and $env:DSH_HOME) { $Harness = Split-Path -Parent $env:DSH_HOME }
if (-not $Harness) {
    Write-Host "找不到 DeepSeek Harness：请用 -Harness 指定安装目录，或设置 DSH_HOME 环境变量。" -ForegroundColor Red
    exit 1
}
$base = $Harness

$node = $NodeExe
if (-not $node -or -not (Test-Path -LiteralPath $node)) {
    $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($cmd) { $node = $cmd.Source }
}
if (-not $node -or -not (Test-Path -LiteralPath $node)) {
    $rt = Get-ChildItem -LiteralPath (Join-Path $env:USERPROFILE '.cache\codex-runtimes') -Filter node.exe -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($rt) { $node = $rt.FullName }
}

$bin = $BinJs
if (-not $bin) { $bin = Join-Path $base 'node_modules\@deepseek-ai\dsh\lib\bin.js' }

$out = Join-Path $base 'dsh-web.stdout.log'
$err = Join-Path $base 'dsh-web.stderr.log'
$urlFile = Join-Path $base 'dsh-web.url.txt'

if (-not $DshHome) { $DshHome = Join-Path $base '.dsh' }
$env:DSH_HOME = $DshHome

function Open-Url([string]$url) {
    if ($Chrome -and (Test-Path -LiteralPath $Chrome)) {
        Start-Process -FilePath $Chrome -ArgumentList $url
    } else {
        Start-Process -FilePath $url
    }
}

function Read-RecordedUrl {
    if (Test-Path -LiteralPath $urlFile) {
        $u = (Get-Content -LiteralPath $urlFile -Raw).Trim()
        if ($u -match '^https?://') { return $u }
    }
    if (Test-Path -LiteralPath $out) {
        $m = Select-String -LiteralPath $out -Pattern "http://127\.0\.0\.1:$Port/\?token=(\S+)" | Select-Object -Last 1
        if ($m) { return $m.Matches[0].Value }
    }
    return $null
}

# 用“DSH node 进程是否存在”判断运行状态：netsh portproxy 的转发监听会让 netstat 误报端口在线
$dshProcs = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'deepseek-ai[\\/]dsh[\\/]lib[\\/]bin\.js' }
if (@($dshProcs).Count -gt 0) {
    $url = Read-RecordedUrl
    if ($url) {
        # The recorded token is per-process: a server restarted elsewhere makes
        # it stale. Ask the server; any 2xx/3xx means the token is still valid.
        $fresh = $false
        try {
            $probe = Invoke-WebRequest -Uri $url -MaximumRedirection 0 -UseBasicParsing -TimeoutSec 2
            if ([int]$probe.StatusCode -ge 200 -and [int]$probe.StatusCode -lt 400) { $fresh = $true }
        } catch {
            if ($_.Exception.Response) {
                $code = [int]$_.Exception.Response.StatusCode
                if ($code -ge 200 -and $code -lt 400) { $fresh = $true }
            }
        }
        if ($fresh) {
            Open-Url $url
            exit 0
        }
    }
    # No usable token: open the clean URL and rely on the browser session
    # cookie (minted by a previous token visit; its signing secret is
    # persisted in .credentials.yaml and survives restarts).
    Open-Url "http://127.0.0.1:$Port/"
    exit 0
}

Set-Content -LiteralPath $out -Value ''
Set-Content -LiteralPath $err -Value ''
Start-Process -FilePath $node -ArgumentList @($bin, 'web', '--no-open', '--port', "$Port") -WorkingDirectory $base -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden | Out-Null

$url = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $m = Select-String -LiteralPath $out -Pattern "http://127\.0\.0\.1:$Port/\?token=(\S+)" | Select-Object -Last 1
    if ($m) {
        $url = $m.Matches[0].Value
        break
    }
}

if ($url) {
    Set-Content -LiteralPath $urlFile -Value $url
    Open-Url $url
}
