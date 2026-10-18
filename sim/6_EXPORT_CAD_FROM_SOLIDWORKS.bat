@echo off
rem Double-click me with SolidWorks open: exports your A08 assembly to meshes\cropscout_full.stl
rem through the SolidWorks API (binary, mm, CAD origin kept, one file). Then the sim uses the real CAD.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the Python environment...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" -c "import win32com" 2>nul || ".venv\Scripts\python.exe" -m pip install pywin32
".venv\Scripts\python.exe" export_stl_from_solidworks.py %*
echo.
pause
