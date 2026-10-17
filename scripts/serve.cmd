@echo off
rem Double-click or run from any shell: serves http://localhost:8080/vision/
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %*
