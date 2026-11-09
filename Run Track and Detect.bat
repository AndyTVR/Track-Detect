@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo  Run Install.bat first.
  pause
  exit /b 1
)
title Track and Detect - close this window to stop
rem pick up any components added by an update (needs internet once)
.venv\Scripts\python.exe -c "import flask, cv2, numpy, imageio_ffmpeg, reportlab" 2>nul || (
  echo  Installing new components for this update...
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
.venv\Scripts\python.exe app.py %*
pause
