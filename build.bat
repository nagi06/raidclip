@echo off
rem ローカルで Windows 用の実行ファイルを作る。Python 3.11+ が必要。
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements-dev.txt
pyinstaller --noconfirm RaidClip.spec
if not exist ffmpeg\ffmpeg.exe (
  echo.
  echo ffmpeg\ffmpeg.exe が無いので同梱しません。dist\RaidClip\ffmpeg\ に ffmpeg.exe と ffprobe.exe を置いてください。
) else (
  xcopy /y /i ffmpeg\ffmpeg.exe dist\RaidClip\ffmpeg\ >nul
  xcopy /y /i ffmpeg\ffprobe.exe dist\RaidClip\ffmpeg\ >nul
)
echo.
echo 完了: dist\RaidClip\RaidClip.exe
pause
