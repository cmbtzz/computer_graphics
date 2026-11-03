@echo off
setlocal
set "TASK_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%TASK_PYTHON%" set "TASK_PYTHON=python"
"%TASK_PYTHON%" "%~dp0task2_environment.py" %*
if errorlevel 1 pause
