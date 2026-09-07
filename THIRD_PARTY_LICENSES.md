# 同梱している第三者ソフトウェアとライセンス

RaidClip 本体は MIT ライセンスです (LICENSE を参照)。配布 zip には次のソフトウェアが含まれます。

## ffmpeg / ffprobe (`ffmpeg/` フォルダ)

- ライセンス: GNU GPL v3 (libx264 などの GPL コンポーネントを含むビルドのため)
- ライセンス全文: `ffmpeg/LICENSE-ffmpeg.txt`
- 入手元 (バイナリとソース): https://github.com/BtbN/FFmpeg-Builds/releases
  (ビルド時に取得できなかった場合は https://www.gyan.dev/ffmpeg/builds/ の release-essentials)
- ffmpeg のソース: https://ffmpeg.org/download.html / https://git.ffmpeg.org/ffmpeg.git
- RaidClip は ffmpeg を外部プロセスとして起動しているだけで、リンクはしていません。
  ffmpeg.exe / ffprobe.exe は同じ場所に置いた別のビルドに差し替えて使えます。

## Qt for Python (PySide6) と Qt 6

- ライセンス: GNU LGPL v3
- ライセンス全文: https://www.gnu.org/licenses/lgpl-3.0.html
- 入手元: https://pypi.org/project/PySide6/ / https://www.qt.io/
- Qt のライブラリは DLL として個別に同梱されており (`_internal/` 配下)、
  同じバージョンの Qt に差し替えることができます。

## Python

- ライセンス: PSF License (https://docs.python.org/3/license.html)
- 入手元: https://www.python.org/

## PyInstaller (ブートローダー)

- ライセンス: GPL v2 with a special exception (ビルドした実行ファイルへの GPL の適用を免除)
- https://pyinstaller.org/en/stable/license.html
