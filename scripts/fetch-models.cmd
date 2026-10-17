@echo off
rem Fetch the models branch from GitHub and install the .onnx files into vision\private\
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fetch-models.ps1" %*
