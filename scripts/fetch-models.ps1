# Fetch the ONNX models from the repo's "models" branch and install them into vision/private/.
# The branch is an orphan that holds only the six .onnx files (they are gitignored on the code
# branches). Usage: scripts\fetch-models.ps1 [-Branch models]
param([string]$Branch = 'models')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

git fetch origin $Branch
if ($LASTEXITCODE -ne 0) { Write-Error "Could not fetch origin/$Branch. Has the branch been pushed yet?" }

$tmp = Join-Path $env:TEMP 'cropscout-models'
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp 'models.zip'
git archive --format=zip -o $zip "origin/$Branch"
if ($LASTEXITCODE -ne 0) { Write-Error "git archive of origin/$Branch failed." }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
Remove-Item $zip

& (Join-Path $PSScriptRoot 'install-models.ps1') $tmp
