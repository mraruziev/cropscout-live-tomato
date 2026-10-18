@echo off
rem Downloads PlantVillage tomato leaf photos (incl. HEALTHY leaves) into leaf_photos\ and rebuilds the leaf textures.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" fetch_leaf_photos.py 24
if exist "assets" rmdir /s /q "assets"
echo Leaf textures will be rebuilt on the next run.
pause
