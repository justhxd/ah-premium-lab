[CmdletBinding()]
param(
    [string]$Python = "",
    [int]$SmokePort = 18765,
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $Python = "python"
}
$PythonUtf8Args = @("-X", "utf8")

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
    if (-not ($version -match '^3\.11\.')) {
        throw "Python 3.11 is required, but $($resolved.Source) is $version"
    }

    return $resolved.Source
}

function Invoke-CheckedCommand {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "==> $Name"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
    Write-Host "OK: $Name" -ForegroundColor Green
}

function Wait-JsonEndpoint {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            return Invoke-RestMethod -Uri $Url -TimeoutSec 2
        } catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for $Url."
}

function Invoke-ApiSmokeTest {
    Write-Host ""
    Write-Host "==> API smoke test"

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $PythonExe
    $psi.Arguments = "-X utf8 -m ha_backtest.web --host 127.0.0.1 --port $SmokePort"
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $server = [System.Diagnostics.Process]::Start($psi)

    try {
        $baseUrl = "http://127.0.0.1:$SmokePort"
        $strategies = Wait-JsonEndpoint -Url "$baseUrl/api/strategies"
        if (-not $strategies.strategies -or $strategies.strategies.Count -lt 1) {
            throw "No strategies returned from /api/strategies."
        }

        $status = Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 5
        if (-not $status.summary) {
            throw "No summary returned from /api/status."
        }

        Write-Host "OK: API smoke test ($baseUrl)" -ForegroundColor Green
    } finally {
        if ($server -and -not $server.HasExited) {
            Stop-Process -Id $server.Id -Force
            $server.WaitForExit()
        }
    }
}

$PythonExe = Resolve-Python -Command $Python

Push-Location $Root
try {
    Invoke-CheckedCommand `
        -Name "Python compile" `
        -FilePath $PythonExe `
        -Arguments ($PythonUtf8Args + @("-m", "compileall", "-q", "src", "tests", "diagnose_backtest_run.py"))

    Invoke-CheckedCommand `
        -Name "pytest" `
        -FilePath $PythonExe `
        -Arguments ($PythonUtf8Args + @("-m", "pytest"))

    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        throw "Cannot find node. Install Node.js to run frontend syntax checks."
    }

    $jsFiles = Get-ChildItem -Path (Join-Path $Root "ui") -Filter "*.js" -File
    foreach ($file in $jsFiles) {
        Invoke-CheckedCommand `
            -Name "Frontend syntax: $($file.Name)" `
            -FilePath $node.Source `
            -Arguments @("--check", $file.FullName)
    }

    if ($SkipSmoke) {
        Write-Host ""
        Write-Host "Skipped API smoke test." -ForegroundColor Yellow
    } else {
        Invoke-ApiSmokeTest
    }

    Write-Host ""
    Write-Host "All checks passed." -ForegroundColor Green
} finally {
    Pop-Location
}
