@echo off
rem Fallback: same mission without the offscreen nozzle camera (decisions from the plant flags).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" live_viewer.py --no-camera %*
if errorlevel 1 ( echo. & echo Stopped with an error - see above. & pause )
