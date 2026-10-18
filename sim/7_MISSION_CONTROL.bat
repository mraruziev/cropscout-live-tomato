@echo off
rem Double-click me: ONE window with the digital twin, the CropSCOUT camera/AI panel and the sprayer IoT telemetry.
rem Uses the CropSCOUT models when the repo + models are present, otherwise the sim's own labels.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" mission_control.py --cropscout %*
if errorlevel 1 ( echo. & echo Stopped with an error - see above. & pause )
