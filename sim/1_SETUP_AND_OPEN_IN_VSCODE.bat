@echo off
rem Double-click me. Creates the Python environment, installs MuJoCo + the CropSCOUT model
rem dependencies, downloads the CropSCOUT models, then opens this project in VS Code.
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Greenhouse sim: setup (takes a few minutes the first time)
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup stopped with an error - read the message above.
  echo If it says Python was not found: install Python 3.10+ from python.org
  echo with "Add python.exe to PATH" ticked, then double-click this file again.
  pause
  exit /b 1
)
echo.
echo Opening the project in VS Code...
set "CODE=%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
if exist "%CODE%" (
  start "" "%CODE%" "%~dp0greenhouse_sim.code-workspace"
) else (
  where code >nul 2>&1 && (start "" code "%~dp0greenhouse_sim.code-workspace") || (start "" "%~dp0greenhouse_sim.code-workspace")
)
echo.
echo In VS Code: press F5 to run the live viewer (pick ".venv" if it asks for an interpreter).
echo You can close this window.
pause

