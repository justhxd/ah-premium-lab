param(
    [int]$Port = 8765,
    [string]$HostName = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DataDir = Join-Path $Root "data"
$PidFile = Join-Path $DataDir "web-ui.pid"
$BrowseHost = if ($HostName -eq "0.0.0.0") { "127.0.0.1" } else { $HostName }
$Url = "http://${BrowseHost}:$Port/"

function Get-ListenerPid {
    param([int]$Port)
    $line = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING" | Select-Object -First 1
    if (-not $line) { return $null }
    $parts = ($line.ToString().Trim() -split "\s+")
    return [int]$parts[-1]
}

if (-not (Test-Path $Python)) {
    throw "Cannot find project Python: $Python"
}

if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

$listenerPid = Get-ListenerPid -Port $Port
if ($listenerPid) {
    Write-Host "Web UI is already running on $Url (PID $listenerPid)."
    Start-Process $Url
    exit 0
}

$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $Python
$psi.Arguments = "-X utf8 -m ha_backtest.web --host $HostName --port $Port"
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $true
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

$process = [System.Diagnostics.Process]::Start($psi)
$process.Id | Set-Content -Encoding utf8 $PidFile

Start-Sleep -Seconds 2
$listenerPid = Get-ListenerPid -Port $Port
if (-not $listenerPid) {
    throw "Web UI did not start on $Url. Try running: .\.venv\Scripts\python.exe -X utf8 -m ha_backtest.web"
}

Write-Host "Web UI started: $Url (PID $listenerPid)."
Start-Process $Url
