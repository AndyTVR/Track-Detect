@echo off
setlocal
title Track and Detect - building the Windows program
cd /d "%~dp0"
set "LOG=%~dp0build_log.txt"
echo Build started %date% %time% > "%LOG%"
echo.
echo  Track ^& Detect by Thermal Vision Ecology - build the Windows program
echo  =====================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo  Run Install.bat first, then run this again.
  echo.
  pause
  exit /b 1
)
set "PY=.venv\Scripts\python.exe"

echo  [1/4] Getting the packaging tool (needs internet, a minute or two)...
"%PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%PY%" -m pip install -r requirements.txt pyinstaller
if not errorlevel 1 goto build

rem ---- the packaging tool wouldn't install: note why, then try Python 3.13
echo. >> "%LOG%"
echo ==== diagnostics ==== >> "%LOG%"
"%PY%" -VV >> "%LOG%" 2>&1
"%PY%" -c "import platform,sys,sysconfig;print(platform.machine(),sysconfig.get_platform(),sys.version)" >> "%LOG%" 2>&1
"%PY%" -m pip --version >> "%LOG%" 2>&1
"%PY%" -m pip config list >> "%LOG%" 2>&1
"%PY%" -m pip install pyinstaller -v >> "%LOG%" 2>&1
echo.
echo  The packaging tool wouldn't install for this Python. Trying Python 3.13
echo  instead (it installs alongside; your current Python isn't changed)...
echo.
py -V:3.13 -c "print('ok')" >nul 2>&1
if errorlevel 1 (
  py install 3.13
  if errorlevel 1 goto nopy
)
if not exist ".venv-build\Scripts\python.exe" py -V:3.13 -m venv .venv-build
if not exist ".venv-build\Scripts\python.exe" goto nopy
set "PY=.venv-build\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%PY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed

:build
echo.
echo  [2/4] Building Track and Detect.exe (this takes a few minutes)...
if not exist "TrackAndDetect.spec" (
  echo  TrackAndDetect.spec is missing from this folder. Copy in the latest files and try again.
  goto failed
)
if exist "build" rmdir /s /q "build"
if exist "dist\Track and Detect" rmdir /s /q "dist\Track and Detect"
"%PY%" -m PyInstaller --noconfirm --clean TrackAndDetect.spec
if errorlevel 1 goto failed
if not exist "dist\Track and Detect\Track and Detect.exe" goto failed

echo.
echo  [3/4] Keeping your settings and adding a desktop shortcut...
if not exist "%APPDATA%\Track and Detect" mkdir "%APPDATA%\Track and Detect"
if exist "settings.json" if not exist "%APPDATA%\Track and Detect\settings.json" copy /y "settings.json" "%APPDATA%\Track and Detect\settings.json" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Track and Detect.lnk');" ^
  "$s.TargetPath = (Resolve-Path 'dist\Track and Detect\Track and Detect.exe').Path;" ^
  "$s.WorkingDirectory = (Resolve-Path 'dist\Track and Detect').Path;" ^
  "$s.IconLocation = (Resolve-Path 'dist\Track and Detect\Track and Detect.exe').Path + ',0';" ^
  "$s.Description = 'Track and Detect by Thermal Vision Ecology'; $s.Save()"

echo.
echo  [4/4] Making a zip you can give to colleagues...
if exist "Track and Detect for Windows.zip" del /q "Track and Detect for Windows.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\Track and Detect' -DestinationPath 'Track and Detect for Windows.zip'"

echo.
echo  Done.
echo   - Desktop shortcut: Track and Detect
echo   - Program folder:   %~dp0dist\Track and Detect
echo   - To share:         %~dp0Track and Detect for Windows.zip
echo     (colleagues unzip it anywhere and double-click Track and Detect.exe;
echo      they don't need Python or Install.bat)
echo Build finished OK >> "%LOG%"
echo.
explorer "dist\Track and Detect"
pause
exit /b 0

:nopy
echo.
echo  Couldn't set up Python 3.13 automatically. Install it from the Microsoft
echo  Store or python.org (3.13, 64-bit), then run this again.
:failed
echo.
echo  The build didn't finish. Details are in build_log.txt in this folder.
echo  Tell Claude, which can read that file, or send a screenshot.
echo Build FAILED >> "%LOG%"
echo.
pause
exit /b 1
