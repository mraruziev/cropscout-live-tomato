@echo off
rem Build the PHP-free copy of the page into dist\static\ (models from vision\private\ unless --models is given)
setlocal
set ROOT=%~dp0..
if exist "%ROOT%\.venv\Scripts\python.exe" (set PY="%ROOT%\.venv\Scripts\python.exe") else (set PY=python)
%PY% -I "%ROOT%\tools\build_static.py" %*
