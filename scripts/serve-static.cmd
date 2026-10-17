@echo off
rem Serve dist\static\ at http://localhost:8081/ with no PHP (camera works on localhost)
setlocal
set ROOT=%~dp0..
if exist "%ROOT%\.venv\Scripts\python.exe" (set PY="%ROOT%\.venv\Scripts\python.exe") else (set PY=python)
%PY% -I "%ROOT%\tools\serve_static.py" %*
