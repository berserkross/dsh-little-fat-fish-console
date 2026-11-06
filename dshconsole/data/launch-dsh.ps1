param(
    [string]$Harness = '',   # DSH 安装目录（含 node_modules\@deepseek-ai\dsh）；空则按布局推导，仍找不到则报错退出
    [string]$NodeExe = '',   # node.exe 全路径；空则用 PATH 里的 node
    [string]$BinJs   = '',   # bin.js 全路径；空则由 $Harness 推导
    [string]$DshHome = '',   # DSH_HOME；空则由 $Harness 推导
    [int]$Port       = 3080, # 本机网页端口
    [string]$Chrome  = '',   # 打开地址用的浏览器；空则用系统默认浏览器
    [switch]$NoOpen          # 不打开浏览器（自动化/验收用）
)

$ErrorActionPreference = 'SilentlyContinue'

# ---------------- 参数回退（GUI 一律显式传参，这里只兜双击独立运行） ----------------
# 推导以「bin.js 实际存在」为准：先按标准布局（DSH_HOME 的父目录），
# 再按本机布局（Documents\Codex\apps\deepseek-harness）。
if (-not $Harness) {
    $candidates = @()
    if ($env:DSH_HOME) { $candidates += (Split-Path -Parent $env:DSH_HOME) }
    $candidates += (Join-Path $env:USERPROFILE 'Documents\Codex\apps\deepseek-harness')
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath (Join-Path $c 'node_modules\@deepseek-ai\dsh\lib\bin.js'))) {
            $Harness = $c
            break
        }
    }
}
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
    if ($NoOpen) { return }
    if ($Chrome -and (Test-Path -LiteralPath $Chrome)) {
        Start-Process -FilePath $Chrome -ArgumentList $url
    } else {
        Start-Process -FilePath $url
    }
}

# ---------------- 运行判定：与 GUI 的 probe.classify 同一条规则 ----------------
# 只认「本机这一份 bin.js」的 node 进程：别的安装目录里同形状的进程不算。
$escaped = [regex]::Escape($bin)
$dshProcs = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match $escaped }
if (@($dshProcs).Count -gt 0) {
    Write-Host ("DSH 已在运行（PID " + $dshProcs[0].ProcessId + "），不再拉起第二份。")
    exit 0
}

# ---------------- 启动串行化闸 ----------------
# 同一时刻只允许一个入口拉起 DSH：多入口（GUI/脚本/切换/重启）互斥，掐死 EADDRINUSE。
$gate = New-Object System.Threading.Mutex($false, 'Local\DshConsole.DshStart')
$owns = $false
try { $owns = $gate.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owns = $true }
if (-not $owns) {
    Write-Host '另一个入口正在启动 DSH，稍后再试。'
    $gate.Dispose()
    exit 1
}

Set-Content -LiteralPath $out -Value ''
Set-Content -LiteralPath $err -Value ''
try {
    Start-Process -FilePath $node -ArgumentList @($bin, 'web', '--no-open', '--port', "$Port") -WorkingDirectory $base -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden | Out-Null
} finally {
    $gate.ReleaseMutex()
    $gate.Dispose()
}

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
