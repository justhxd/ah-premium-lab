param(
    [int]$Port = 8765,
    [string]$HostName = "0.0.0.0",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
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

function Resolve-Python {
    param([string]$Command)

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $resolved) {
        throw "Cannot find Python command: $Command"
    }

    $version = & $resolved.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot run Python command: $($resolved.Source)"
    }
    $versionParts = $version -split "\."
    $major = [int]$versionParts[0]
    $minor = [int]$versionParts[1]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        throw "Python 3.10 or newer is required, but $($resolved.Source) is $version"
    }

    return $resolved.Source
}

$PythonExe = Resolve-Python -Command $Python

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
$psi.FileName = $PythonExe
$psi.Arguments = "-X utf8 -m ha_backtest.web --host $HostName --port $Port"
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $true
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

$process = [System.Diagnostics.Process]::Start($psi)
$process.Id | Set-Content -Encoding utf8 $PidFile

Start-Sleep -Seconds 2
$listenerPid = Get-ListenerPid -Port $Port
if (-not $listenerPid) {
    throw "Web UI did not start on $Url. Try running: python -m ha_backtest.web"
}

Write-Host "Web UI started: $Url (PID $listenerPid)."
Start-Process $Url
