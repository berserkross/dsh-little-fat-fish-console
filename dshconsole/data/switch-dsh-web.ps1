param(
    [switch]$Restore,   # 恢复为仅本机访问
    [switch]$DryRun,    # 只打印计划，不做任何改动
    [switch]$Force,     # 跳过确认
    [switch]$NoPause,   # 结束时不等待按键（自动化用）

    [string]$Harness  = '',    # DSH 安装目录；空则回退 DSH_HOME 父目录，仍为空则报错退出
    [string]$NodeExe  = '',    # node.exe 全路径；空则用 PATH 里的 node
    [string]$BinJs    = '',    # bin.js 全路径；空则由 $Harness 推导
    [string]$DshHome  = '',    # DSH_HOME；空则由 $Harness 推导
    [int]$Port        = 3080,  # 网页端口（端口转发与信任来源都用它）
    [string]$RuleName = '',    # 防火墙规则名；空则按端口生成
    [string]$ServeHost = ''    # tailscale serve 的 MagicDNS 域名，形如 host:80；非空则一并加入 trusted-host
)

# ============================================================
#  DSH 手机访问切换器
#  - 首选路径：tailscale serve —— 由 tailscaled 自己监听 80/443 并代理到
#              127.0.0.1:<Port>，不需要管理员权限、不需要端口转发、不需要动防火墙。
#              这条路在 Python 侧（dshconsole/tailscale.py、phone.py）编排，
#              本脚本只需用 -ServeHost 把 MagicDNS 域名加进 trusted-host。
#  - 默认模式：回退路径 —— 把 DSH 网页（127.0.0.1:<Port>）经 netsh 端口转发
#              开放给 Tailscale IP（及局域网 IP），并加 trusted-host 放行 /api
#  - -Restore ：拆除开放，恢复仅本机可访问
#  说明：当前版本 dsh 禁止监听 0.0.0.0，所以用 netsh 端口转发 + token 地址。
# ============================================================

$ErrorActionPreference = 'Stop'

# ---------------- 参数回退（GUI 一律显式传参，这里只兜双击独立运行） ----------------
if (-not $Harness -and $env:DSH_HOME) { $Harness = Split-Path -Parent $env:DSH_HOME }
if (-not $Harness) {
    Write-Host "找不到 DeepSeek Harness：请用 -Harness 指定安装目录，或设置 DSH_HOME 环境变量。" -ForegroundColor Red
    exit 1
}
if (-not $NodeExe -or -not (Test-Path -LiteralPath $NodeExe)) {
    $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($cmd) { $NodeExe = $cmd.Source }
}
if (-not $BinJs) { $BinJs = Join-Path $Harness 'node_modules\@deepseek-ai\dsh\lib\bin.js' }
if (-not $RuleName) { $RuleName = "DSH Web $Port access" }
$OutLog = Join-Path $Harness 'dsh-web.stdout.log'
$ErrLog = Join-Path $Harness 'dsh-web.stderr.log'

if (-not $DshHome) { $DshHome = Join-Path $Harness '.dsh' }
$env:DSH_HOME    = $DshHome
$env:DSH_PROFILE = 'web'

$Mode = if ($Restore) { 'restore' } else { 'expose' }

function Write-Info([string]$m) { Write-Host $m }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-LanIPv4 {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.AddressState -eq 'Preferred' } |
        Select-Object -ExpandProperty IPAddress -Unique
}

function Stop-DshNode {
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'deepseek-ai\\dsh\\lib\\bin\.js' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 900
}

function Get-TokenUrl {
    param([string]$LogFile, [int]$TimeoutSec = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $LogFile) {
            $text = Get-Content $LogFile -Raw -ErrorAction SilentlyContinue
            if ($text -and ($text -match "http://127\.0\.0\.1:(?<port>\d+)/\?token=(?<tok>[A-Za-z0-9_\-]+)")) {
                return $Matches[0].Trim()
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Add-Proxy([string]$ListenIp) {
    netsh interface portproxy delete v4tov4 listenaddress=$ListenIp listenport=$Port 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenaddress=$ListenIp listenport=$Port connectaddress=127.0.0.1 connectport=$Port 2>$null | Out-Null
}

function Remove-Proxy([string]$ListenIp) {
    netsh interface portproxy delete v4tov4 listenaddress=$ListenIp listenport=$Port 2>$null | Out-Null
}

function Ensure-Firewall {
    # 实测：WLAN 与以太网都被 Windows 判为「公用」，而老规则只写了 Private,Domain ——
    # 规则存在、Enabled=True，局域网路径却整条静默失效。所以两件事都要做：
    #   1) 新建规则就用 Any；2) 已存在的规则要 Set-NetFirewallRule 补 Profile
    #      （只判断「规则在不在」会漏掉这个坑）。
    if (-not (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP `
            -LocalPort $Port -Profile Any -Program $NodeExe -ErrorAction SilentlyContinue | Out-Null
    } else {
        Set-NetFirewallRule -DisplayName $RuleName -Profile Any -Enabled True -ErrorAction SilentlyContinue | Out-Null
    }
}

function Remove-Firewall {
    Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Start-Dsh([string[]]$ExtraArgs) {
    $argv = @($BinJs, 'web', '--no-open', '--port', "$Port") + $ExtraArgs
    Start-Process -FilePath $NodeExe -ArgumentList $argv -WorkingDirectory $Harness `
        -WindowStyle Hidden -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog | Out-Null
}

function Pause-End {
    if ($NoPause -or $DryRun) { return }
    Write-Host ''
    Write-Host '按任意键关闭本窗口...'
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
}

# ---------------- 自提权 ----------------
if (-not $DryRun -and -not (Test-Admin)) {
    Write-Info '需要管理员权限（端口转发/防火墙），正在弹出 UAC 授权...'
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Restore) { $argList += '-Restore' }
    if ($Force)   { $argList += '-Force' }
    if ($NoPause) { $argList += '-NoPause' }
    # 参数化后关键一步：值参数必须一并透传，否则提权后的子进程只剩空默认值
    foreach ($pair in @(
        @('-Harness',  $Harness),
        @('-NodeExe',  $NodeExe),
        @('-BinJs',    $BinJs),
        @('-DshHome',  $DshHome),
        @('-Port',     "$Port"),
        @('-RuleName', $RuleName),
        @('-ServeHost', $ServeHost))) {
        if ($pair[1]) {
            $argList += $pair[0]
            $argList += ('"{0}"' -f $pair[1])
        }
    }
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList | Out-Null
    } catch {
        Write-Info '已取消 UAC 授权，未做任何更改。'
    }
    exit
}

$tsIps  = @(Get-LanIPv4 | Where-Object { $_ -like '100.*' })
$lanIps = @(Get-LanIPv4 | Where-Object { $_ -notlike '100.*' })
$allIps = @(@($tsIps) + @($lanIps) | Select-Object -Unique)

# ---------------- 计划与确认 ----------------
if ($Mode -eq 'expose') {
    Write-Info '=== DSH 手机访问：开启 ==='
    Write-Info "将把 DSH 网页（端口 $Port，当前仅本机可访问）开放给："
    if ($tsIps.Count) { Write-Info ("  · Tailscale : " + ($tsIps -join ', ')) }
    if ($lanIps.Count) { Write-Info ("  · 局域网   : " + ($lanIps -join ', ')) }
    Write-Info '  · 本机     : 127.0.0.1'
    Write-Info ''
    Write-Info '安全提示：该界面没有账号密码，能直接操作这台电脑；只在你信任的网络里用，'
    Write-Info '          不用时请双击「DSH 手机访问（恢复本机）」关掉。'
    Write-Info ''
    if ($DryRun) {
        Write-Info '[DryRun] 将执行：'
        foreach ($ip in $allIps) { Write-Info "  netsh portproxy v4tov4 listenaddress=$ip listenport=$Port -> 127.0.0.1:$Port" }
        Write-Info "  防火墙规则：node.exe TCP $Port 入站允许（Any：Private/Domain/Public）"
        Write-Info "  启动 DSH 网页进程（端口 $Port，trusted-host 含各网卡地址）"
        Pause-End
        exit
    }
    if (-not $Force) {
        $ans = Read-Host '这会重启网页服务，当前页面会断开（重启后刷新即可继续）。继续？(Y/N)'
        if ($ans -notmatch '^[Yy]') { Write-Info '已取消。'; Pause-End; exit }
    }
} else {
    Write-Info '=== DSH 手机访问：恢复本机 ==='
    if ($DryRun) {
        Write-Info "[DryRun] 将删除全部 $Port 端口转发、防火墙规则，并重启为仅本机模式。"
        Pause-End
        exit
    }
    if (-not $Force) {
        $ans = Read-Host '将移除开放并重启网页服务，当前页面会断开（重启后刷新即可继续）。继续？(Y/N)'
        if ($ans -notmatch '^[Yy]') { Write-Info '已取消。'; Pause-End; exit }
    }
}

# ---------------- 执行 ----------------
Write-Info '停止当前 DSH 网页服务...'
Stop-DshNode

if ($Mode -eq 'expose') {
    Ensure-Firewall
    foreach ($ip in $allIps) { Add-Proxy $ip }
    $trusted = @('--trusted-host', "127.0.0.1:$Port", '--trusted-host', "localhost:$Port")
    foreach ($ip in $allIps) { $trusted += @('--trusted-host', "$ip`:$Port") }
    # serve 路径的 Host 头是 MagicDNS 域名（端口 80/443），不在网卡 IP 列表里，单独补。
    if ($ServeHost) { $trusted += @('--trusted-host', $ServeHost) }
    Write-Info '启动 DSH 网页服务（手机可访问）...'
    Start-Dsh $trusted
} else {
    foreach ($ip in $allIps) { Remove-Proxy $ip }
    Remove-Firewall
    Write-Info '启动 DSH 网页服务（仅本机）...'
    Start-Dsh @()
}

$url = Get-TokenUrl $OutLog
if (-not $url) {
    Write-Info '!! 启动失败：40 秒内没有拿到带 token 的地址，请把下面两个日志发给我：'
    Write-Info "   $OutLog"
    Write-Info "   $ErrLog"
    Pause-End
    exit 1
}

Write-Info ''
Write-Info '启动成功。'
Write-Info "本机访问：$url"
if ($Mode -eq 'expose') {
    $tok = ($url -split 'token=')[1]
    foreach ($ip in $tsIps) { Write-Info "手机访问(Tailscale)：http://$ip`:$Port/?token=$tok" }
    foreach ($ip in $lanIps) { Write-Info "手机访问(局域网)：http://$ip`:$Port/?token=$tok" }
    Write-Info ''
    Write-Info '提示：'
    Write-Info '  - 手机第一次打开后建议加入书签；token 只用于本机打开，不外泄。'
    Write-Info '  - 电脑不能休眠/睡眠，否则手机连不上。'
    Write-Info '  - 校园网常带设备隔离，直连未必通；Tailscale 最稳。'
}
Write-Info ''
Start-Process $url | Out-Null
Pause-End
