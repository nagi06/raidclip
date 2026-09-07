@echo off
rem Build a Windows executable locally. Requires Python 3.11+ on PATH.
rem Output: dist\RaidClip\RaidClip.exe
rem (ASCII only: cmd.exe on Japanese Windows reads this file as CP932, so no UTF-8 text here.)
cd /d "%~dp0"

if not exist .venv (
  python -m venv .venv
  if errorlevel 1 goto :fail
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements-dev.txt
if errorlevel 1 goto :fail

pyinstaller --noconfirm RaidClip.spec
if errorlevel 1 goto :fail

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
echo [ERROR] Build failed. See messages above.
pause
exit /b 1
