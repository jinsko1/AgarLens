@echo off
setlocal

cd /d "%~dp0"

echo.
echo AgarLens setup
echo ==============
echo.

if not "%AGARLENS_PYTHON%"=="" (
  set "PYTHON_BIN=%AGARLENS_PYTHON%"
) else (
  set "PYTHON_BIN=python"
)

echo Using Python:
"%PYTHON_BIN%" --version
if errorlevel 1 (
  echo.
  echo Python 3 was not found.
  echo Install Python 3, then run this setup file again.
  echo.
  pause
  exit /b 1
)

if not exist "%CD%\venv" (
  echo.
  echo Creating local virtual environment...
  "%PYTHON_BIN%" -m venv "%CD%\venv"
) else (
  echo.
  echo Using existing local virtual environment.
)

echo.
echo Installing AgarLens dependencies...
"%CD%\venv\Scripts\python.exe" -m pip install --upgrade pip
"%CD%\venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
if exist "%CD%\runs\detect\train-5\weights\best.pt" (
  echo YOLO model found:
  echo %CD%\runs\detect\train-5\weights\best.pt
) else (
  echo YOLO model was not found at:
  echo %CD%\runs\detect\train-5\weights\best.pt
  echo.
  echo The app can still open, but the colony counter needs best.pt in that location.
)

echo.
echo Setup complete.
echo Next time, double-click run_agarlens.bat to start AgarLens.
echo.
pause
