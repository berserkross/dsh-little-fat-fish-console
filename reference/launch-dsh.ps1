$ErrorActionPreference = 'SilentlyContinue'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$node = 'D:\Program Files\nodejs\node.exe'
if (-not (Test-Path -LiteralPath $node)) {
    $node = 'C:\Users\Ibash\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
}
$bin = Join-Path $base 'node_modules\@deepseek-ai\dsh\lib\bin.js'
$out = Join-Path $base 'dsh-web.stdout.log'
$err = Join-Path $base 'dsh-web.stderr.log'
$urlFile = Join-Path $base 'dsh-web.url.txt'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:DSH_HOME = 'C:\Users\Ibash\Documents\Codex\.dsh'

function Open-Url([string]$url) {
    if (Test-Path -LiteralPath $chrome) {
        Start-Process -FilePath $chrome -ArgumentList $url
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
        $m = Select-String -LiteralPath $out -Pattern 'http://127\.0\.0\.1:3080/\?token=(\S+)' | Select-Object -Last 1
        if ($m) { return $m.Matches[0].Value }
    }
    return $null
}

$running = netstat -ano | Select-String ':3080\s+.*LISTENING'
if ($running) {
    $url = Read-RecordedUrl
    if ($url) {
        # The recorded token is per-process: a server restarted elsewhere makes
        # it stale. Ask the server; any 2xx/3xx means the token is still valid.
        $fresh = $false
        try {
            $probe = Invoke-WebRequest -Uri $url -MaximumRedirection 0 -UseBasicParsing -TimeoutSec 5
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
    Open-Url 'http://127.0.0.1:3080/'
    exit 0
}

Set-Content -LiteralPath $out -Value ''
Set-Content -LiteralPath $err -Value ''
Start-Process -FilePath $node -ArgumentList @($bin, 'web', '--no-open') -WorkingDirectory $base -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden | Out-Null

$url = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $m = Select-String -LiteralPath $out -Pattern 'http://127\.0\.0\.1:3080/\?token=(\S+)' | Select-Object -Last 1
    if ($m) {
        $url = $m.Matches[0].Value
        break
    }
}
if ($url) {
    Set-Content -LiteralPath $urlFile -Value $url
    Open-Url $url
}
