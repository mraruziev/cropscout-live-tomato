@echo off
rem Double-click me: the robot decides with the CropSCOUT ONNX models (a PlantVillage photo per plant).
rem Needs ..\cropscout-live-tomato next to this folder and its models (setup downloads them).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the Python environment...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" live_viewer.py --cropscout %*
if errorlevel 1 (
  echo.
  echo Stopped with an error - see above. If models are missing, run:
  echo   .venv\Scripts\python.exe ..\cropscout-live-tomato\live\fetch_models.py
  pause
)
