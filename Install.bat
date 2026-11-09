@echo off
setlocal
cd /d "%~dp0"
echo.
echo  Track ^& Detect by Thermal Vision Ecology - one-time setup
echo  ==========================================================
echo.
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo  Python was not found.
  echo  Install Python 3.11 or newer from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" in the installer, then run this again.
  pause
  exit /b 1
)
echo  Creating a private Python environment in this folder...
%PY% -m venv .venv
if not exist .venv\Scripts\python.exe (
  echo  Could not create the environment.
  pause
  exit /b 1
)
echo  Installing components - needs internet, about 150 MB, one time only...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo  Install failed - see the messages above.
  pause
  exit /b 1
)
echo.
echo  Done. Double-click "Run Track and Detect.bat" to start.
pause
