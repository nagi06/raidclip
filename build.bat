@echo off
rem Build a Windows executable locally. Requires Python 3.11+ (python.org installer).
rem Output: dist\RaidClip\RaidClip.exe   Log: build.log
rem (ASCII only: cmd.exe on Japanese Windows reads this file as CP932.)
setlocal
cd /d "%~dp0"

rem --- find python (py launcher first, then python on PATH)
set PY=
py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY python -c "import sys" >nul 2>&1 && set PY=python
if not defined PY (
  echo [ERROR] Python 3 not found. Install it from https://www.python.org/downloads/windows/
  echo         and tick "Add python.exe to PATH" in the installer.
  pause
  exit /b 1
)
%PY% -c "import sys; print('Using Python', sys.version)"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" || (
  echo [ERROR] Python 3.11 or newer is required.
  pause
  exit /b 1
)

echo === build started %date% %time% > build.log

if not exist .venv (
  echo [1/3] creating .venv
  %PY% -m venv .venv >> build.log 2>&1 || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail

echo [2/3] installing packages (first time takes a few minutes)
python -m pip install --upgrade pip >> build.log 2>&1
pip install -r requirements-dev.txt >> build.log 2>&1 || goto :fail

echo [3/3] running PyInstaller
pyinstaller --noconfirm RaidClip.spec >> build.log 2>&1 || goto :fail

if exist ffmpeg\ffmpeg.exe (
  if not exist dist\RaidClip\ffmpeg mkdir dist\RaidClip\ffmpeg
  copy /y ffmpeg\ffmpeg.exe dist\RaidClip\ffmpeg\ >nul
  copy /y ffmpeg\ffprobe.exe dist\RaidClip\ffmpeg\ >nul
  echo [OK] ffmpeg bundled.
) else (
  echo [WARN] ffmpeg\ffmpeg.exe not found. Put ffmpeg.exe and ffprobe.exe into dist\RaidClip\ffmpeg\ before use.
  echo        Download: https://www.gyan.dev/ffmpeg/builds/  (release-essentials)
)

echo.
echo [DONE] dist\RaidClip\RaidClip.exe
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed. Last lines of build.log:
echo ----------------------------------------------
powershell -NoProfile -Command "Get-Content build.log -Tail 40"
echo ----------------------------------------------
echo Full log: build.log
pause
exit /b 1
