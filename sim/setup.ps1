# One-time setup: creates .venv and installs the requirements.
# Run from VS Code:  Terminal > Run Task > "Setup: create .venv + install"
# or from PowerShell in this folder:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# VS Code run/debug configs ship in vscode-config\ ; install them as .vscode\ (kept if already present)
if ((Test-Path "vscode-config") -and -not (Test-Path ".vscode")) {
    Copy-Item -Recurse "vscode-config" ".vscode"
    Write-Host "Installed .vscode\ (launch configs, tasks, interpreter setting)."
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m venv .venv
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m venv .venv
} else {
    Write-Host "Python not found. Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run."
    exit 1
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install -r requirements-cropscout.txt
& .\.venv\Scripts\python.exe -c "import mujoco; print('MuJoCo', mujoco.__version__, 'ready')"

# CropSCOUT models for --cropscout mode: the repo this folder lives in (sim/), else a sibling repo
$cropscout = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $cropscout "live\fetch_models.py"))) {
    $cropscout = Join-Path $cropscout "cropscout-live-tomato"
}
if (Test-Path (Join-Path $cropscout "live\fetch_models.py")) {
    Write-Host "Fetching CropSCOUT ONNX models into $cropscout\live\models ..."
    & .\.venv\Scripts\python.exe (Join-Path $cropscout "live\fetch_models.py")
} else {
    Write-Host "cropscout-live-tomato not found around this folder; --cropscout mode will need --cropscout-dir."
}
Write-Host ""
Write-Host "Done. In VS Code: Ctrl+Shift+P > 'Python: Select Interpreter' > .venv, then press F5 (Live viewer)."
