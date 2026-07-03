param(
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "data\web-ui.pid"

$pids = @()
$lines = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING"
foreach ($line in $lines) {
    $parts = ($line.ToString().Trim() -split "\s+")
    $pids += [int]$parts[-1]
}

if (Test-Path $PidFile) {
    $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($savedPid -match '^\d+$') {
        $pids += [int]$savedPid
    }
}

$pids = $pids | Sort-Object -Unique
if (-not $pids -or $pids.Count -eq 0) {
    Write-Host "No Web UI listener found on port $Port."
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    exit 0
}

foreach ($pidValue in $pids) {
    try {
        $proc = Get-Process -Id $pidValue -ErrorAction Stop
        Stop-Process -Id $pidValue -Force
        Write-Host "Stopped $($proc.ProcessName) PID $pidValue."
    } catch {
        Write-Host "PID $pidValue is not running."
    }
}

if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
