# Copy the ONNX models into vision/private/ (they are too big for git).
# Windows equivalent of scripts/link-models.sh. Symlinks need admin rights on
# Windows, so the files are copied instead. Each copy is checked against the
# sha256 in vision/private/model-metadata.json so a stale model is caught here
# rather than as a cryptic error in the browser.
# Usage: scripts\install-models.ps1 C:\path\to\folder\with\onnx\models
param([Parameter(Mandatory = $true)][string]$Source)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root 'vision\private'
if (-not (Test-Path $Source -PathType Container)) { Write-Error "Not a folder: $Source" }

$meta = Get-Content (Join-Path $dest 'model-metadata.json') -Raw | ConvertFrom-Json
$expected = @{
    'cropscout-crop-view'     = $meta.crop_view.onnx_sha256
    'cropscout-disease'       = $meta.disease.onnx_sha256
    'cropscout-leaf-detector' = $meta.leaf_detector.onnx_sha256
}
foreach ($s in $meta.condition_specialists) { $expected["cropscout-$($s.id)"] = $s.onnx_sha256 }

$required = @('cropscout-crop-view', 'cropscout-disease', 'cropscout-cucumber-leaf', 'cropscout-lemon-leaf', 'cropscout-tomato-leaf')
$optional = @('cropscout-leaf-detector')
$failed = $false

foreach ($name in $required + $optional) {
    $src = Join-Path $Source "$name.onnx"
    if (-not (Test-Path $src)) {
        if ($name -in $optional) { Write-Host "skipped  $name.onnx (optional leaf finder, not in $Source)"; continue }
        Write-Host "MISSING  $src" -ForegroundColor Red; $failed = $true; continue
    }
    $hash = (Get-FileHash $src -Algorithm SHA256).Hash.ToLower()
    $want = $expected[$name]
    if ($want -and $hash -ne $want) {
        Write-Host "MISMATCH $name.onnx: sha256 $hash does not match model-metadata.json ($want)" -ForegroundColor Yellow
        $failed = $true
    }
    Copy-Item $src (Join-Path $dest "$name.onnx") -Force
    $mb = [math]::Round((Get-Item $src).Length / 1MB, 1)
    Write-Host "copied   $name.onnx ($mb MB)"
}

if ($failed) { Write-Error 'Some models are missing or do not match the metadata. The page will refuse to load mismatched models.' }
Write-Host 'Done. Start the site with scripts\serve.ps1 and open http://localhost:8080/vision/'
