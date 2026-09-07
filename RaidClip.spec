# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 用。 pyinstaller RaidClip.spec で dist/RaidClip/ に出力される。
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["raidclip.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("raidclip"),
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 使わない Qt モジュールを削って軽くする
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
        "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtLocation", "PySide6.QtPositioning",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtXml",
        "PySide6.QtSvgWidgets", "PySide6.QtOpenGLWidgets", "PySide6.QtHttpServer",
        "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtTextToSpeech",
        "PySide6.QtSpatialAudio", "PySide6.QtGraphs", "PySide6.QtStateMachine",
        "tkinter", "imageio_ffmpeg",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="RaidClip",
    console=False,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="RaidClip")
