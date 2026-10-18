@echo off
rem Double-click me to watch the robot in the MuJoCo viewer (no VS Code needed).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the Python environment...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" live_viewer.py %*
if errorlevel 1 (
  echo.
  echo The viewer stopped with an error - see above. If it mentions the camera or OpenGL,
  echo try 4_RUN_LIVE_VIEWER_NO_CAMERA.bat
  pause
)
