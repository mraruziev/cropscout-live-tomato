# Serve the site locally at http://localhost:8080/vision/ (camera works on localhost without HTTPS).
# Windows equivalent of scripts/serve.sh. Usage: scripts\serve.ps1 [-Port 8080]
param([int]$Port = 8080)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$php = Get-Command php -ErrorAction SilentlyContinue
if (-not $php) {
    # winget installs PHP here without always refreshing PATH for the current shell.
    $candidate = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -Filter 'PHP.PHP.*' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($candidate -and (Test-Path (Join-Path $candidate.FullName 'php.exe'))) {
        $env:Path = "$($candidate.FullName);$env:Path"
    } else {
        Write-Error 'php was not found. Install it with: winget install PHP.PHP.8.4'
    }
}

Write-Host "Serving $root at http://localhost:$Port/vision/  (Ctrl+C to stop)"
php -S "localhost:$Port" -t .
