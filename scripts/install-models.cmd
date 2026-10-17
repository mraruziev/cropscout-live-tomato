@echo off
rem Usage: scripts\install-models.cmd C:\path\to\folder\with\onnx\models
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-models.ps1" %*
