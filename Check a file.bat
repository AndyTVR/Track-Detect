@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo  Drag an .ats file onto this icon to check it decodes correctly.
  pause
  exit /b 1
)
.venv\Scripts\python.exe check_file.py "%~1"
pause
