@echo off
setlocal

cd /d "%~dp0"
set YOLO_AUTOINSTALL=false

if not "%AGARLENS_PYTHON%"=="" (
  set "PYTHON_BIN=%AGARLENS_PYTHON%"
) else if exist "%CD%\venv\Scripts\python.exe" (
  set "PYTHON_BIN=%CD%\venv\Scripts\python.exe"
) else if exist "%CD%\.venv\Scripts\python.exe" (
  set "PYTHON_BIN=%CD%\.venv\Scripts\python.exe"
) else (
  set "PYTHON_BIN=python"
)

"%PYTHON_BIN%" "%CD%\growth_analyzer_gui.py"
