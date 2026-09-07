"""RaidClip GUI (PySide6)。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QSlider, QStyle, QVBoxLayout, QWidget,
)

from raidclip import __version__
from raidclip import ffmpeg_tools as ft
from raidclip.annotate import AnnotateDialog

SLIDER_SCALE = 1000  # スライダーはミリ秒単位


def clock(sec: float) -> str:
    """表示用 M:SS.s"""
    sec = max(0.0, sec)
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m}:{s:04.1f}"


class RangeSlider(QSlider):
    """通常のスライダーに In/Out の帯を描き足したもの。"""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.in_pos = 0
        self.out_pos = 0

    def set_range_marks(self, in_ms: int, out_ms: int):
        self.in_pos, self.out_pos = in_ms, out_ms
        self.update()

    def paintEvent(self, ev):
        from PySide6.QtGui import QColor, QPainter

        super().paintEvent(ev)
        if self.maximum() <= 0 or self.out_pos <= self.in_pos:
            return
        w = self.width()
        x1 = int(w * self.in_pos / self.maximum())
        x2 = int(w * self.out_pos / self.maximum())
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(80, 160, 255, 90))
        p.drawRect(x1, 0, max(2, x2 - x1), self.height())
        p.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"RaidClip {__version__}")
        self.resize(960, 700)
        self.setAcceptDrops(True)

        self.src: str | None = None
        self.info: ft.MediaInfo | None = None
        self.in_sec = 0.0
        self.out_sec = 0.0
        self.proc: QProcess | None = None
        self.queue: list[list[str]] = []
        self.pass_index = 0
        self.pass_total = 1
        self.dst: str | None = None
        self._passlog: str | None = None

        self.ffmpeg = ft.find_binary("ffmpeg")

        self._build_ui()
        self._build_shortcuts()
        self._update_enabled()

        if not self.ffmpeg:
            QTimer.singleShot(0, self._warn_no_ffmpeg)

    # ------------------------------------------------------------ UI 構築
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)

        # ファイル
        top = QHBoxLayout()
        self.btn_open = QPushButton("動画を開く…")
        self.btn_open.clicked.connect(self.open_file)
        self.lbl_file = QLabel("mp4 をここにドラッグ&ドロップ、または「動画を開く」")
        self.lbl_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(self.btn_open)
        top.addWidget(self.lbl_file, 1)
        v.addLayout(top)

        # プレビュー
        self.video = QVideoWidget()
        self.video.setMinimumHeight(320)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.6)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(lambda _s: self._update_play_icon())
        self.player.errorOccurred.connect(self._on_player_error)
        v.addWidget(self.video, 1)

        # シーク
        self.slider = RangeSlider()
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderPressed.connect(lambda: self.player.pause())
        v.addWidget(self.slider)

        ctl = QHBoxLayout()
        style = self.style()
        self.btn_play = QPushButton()
        self.btn_play.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.clicked.connect(self.toggle_play)
        self.lbl_time = QLabel("0:00.0 / 0:00.0")
        self.btn_back = QPushButton("◀ 5秒")
        self.btn_back.clicked.connect(lambda: self.seek_rel(-5))
        self.btn_fwd = QPushButton("5秒 ▶")
        self.btn_fwd.clicked.connect(lambda: self.seek_rel(5))
        self.btn_frame_back = QPushButton("◀ 0.1秒")
        self.btn_frame_back.clicked.connect(lambda: self.seek_rel(-0.1))
        self.btn_frame_fwd = QPushButton("0.1秒 ▶")
        self.btn_frame_fwd.clicked.connect(lambda: self.seek_rel(0.1))
        self.btn_frame = QPushButton("静止画に注釈 (S)")
        self.btn_frame.clicked.connect(self.capture_frame)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(60)
        self.vol.setFixedWidth(100)
        self.vol.valueChanged.connect(lambda x: self.audio.setVolume(x / 100))
        for w in (self.btn_play, self.btn_back, self.btn_frame_back,
                  self.btn_frame_fwd, self.btn_fwd):
            ctl.addWidget(w)
        ctl.addWidget(self.lbl_time, 1)
        ctl.addWidget(self.btn_frame)
        ctl.addWidget(QLabel("音量"))
        ctl.addWidget(self.vol)
        v.addLayout(ctl)

        # 範囲
        rng = QGroupBox("切り出し範囲 (I キー: 開始をここに / O キー: 終了をここに)")
        rl = QHBoxLayout(rng)
        self.btn_set_in = QPushButton("開始 = 現在位置")
        self.btn_set_in.clicked.connect(self.set_in_here)
        self.ed_in = QLineEdit("0:00.0")
        self.ed_in.setFixedWidth(90)
        self.ed_in.editingFinished.connect(self._on_in_edited)
        self.btn_go_in = QPushButton("▶開始へ")
        self.btn_go_in.clicked.connect(lambda: self.seek_to(self.in_sec))
        self.btn_set_out = QPushButton("終了 = 現在位置")
        self.btn_set_out.clicked.connect(self.set_out_here)
        self.ed_out = QLineEdit("0:00.0")
        self.ed_out.setFixedWidth(90)
        self.ed_out.editingFinished.connect(self._on_out_edited)
        self.btn_go_out = QPushButton("▶終了へ")
        self.btn_go_out.clicked.connect(lambda: self.seek_to(self.out_sec))
        self.btn_preview = QPushButton("範囲を再生")
        self.btn_preview.clicked.connect(self.preview_range)
        self.lbl_len = QLabel("長さ: 0:00.0")
        for w in (self.btn_set_in, self.ed_in, self.btn_go_in):
            rl.addWidget(w)
        rl.addSpacing(16)
        for w in (self.btn_set_out, self.ed_out, self.btn_go_out):
            rl.addWidget(w)
        rl.addSpacing(16)
        rl.addWidget(self.btn_preview)
        rl.addWidget(self.lbl_len, 1)
        v.addWidget(rng)

        # 出力
        outg = QGroupBox("保存")
        ol = QVBoxLayout(outg)
        mode = QHBoxLayout()
        self.rb_copy = QRadioButton("高速 (無劣化・秒単位でずれる事あり)")
        self.rb_copy.setChecked(True)
        self.rb_accurate = QRadioButton("正確 (再エンコード)")
        self.rb_fit = QRadioButton("Discord のサイズに収める:")
        self.cb_size = QComboBox()
        for name in ft.DISCORD_PRESETS_MB:
            self.cb_size.addItem(name)
        self.cb_size.setEnabled(False)
        self.rb_fit.toggled.connect(self.cb_size.setEnabled)
        for w in (self.rb_copy, self.rb_accurate, self.rb_fit, self.cb_size):
            mode.addWidget(w)
        mode.addStretch(1)
        ol.addLayout(mode)

        row = QHBoxLayout()
        self.btn_save = QPushButton("切り出して保存…")
        self.btn_save.setMinimumHeight(36)
        self.btn_save.clicked.connect(self.start_export)
        self.btn_cancel = QPushButton("中止")
        self.btn_cancel.clicked.connect(self.cancel_export)
        self.btn_cancel.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.btn_open_folder = QPushButton("保存先フォルダを開く")
        self.btn_open_folder.clicked.connect(self.open_folder)
        self.btn_open_folder.setEnabled(False)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.progress, 1)
        row.addWidget(self.btn_open_folder)
        ol.addLayout(row)
        self.lbl_status = QLabel("")
        ol.addWidget(self.lbl_status)
        v.addWidget(outg)

    def _build_shortcuts(self):
        def act(keys, fn):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(fn)
            self.addAction(a)

        act(["Space", "K"], self.toggle_play)
        act(["I"], self.set_in_here)
        act(["O"], self.set_out_here)
        act(["Left"], lambda: self.seek_rel(-5))
        act(["Right"], lambda: self.seek_rel(5))
        act(["Shift+Left", ","], lambda: self.seek_rel(-0.1))
        act(["Shift+Right", "."], lambda: self.seek_rel(0.1))
        act(["S"], self.capture_frame)
        act(["Ctrl+O"], self.open_file)
        act(["Ctrl+S"], self.start_export)

    def _warn_no_ffmpeg(self):
        QMessageBox.warning(
            self, "ffmpeg が見つかりません",
            "ffmpeg.exe が見つかりません。\n\n"
            "配布 zip の ffmpeg フォルダごと展開してください。\n"
            "または https://www.gyan.dev/ffmpeg/builds/ から ffmpeg.exe と ffprobe.exe を\n"
            "RaidClip.exe と同じフォルダに置いてください。",
        )

    # ------------------------------------------------------------ ファイル
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            p = u.toLocalFile()
            if p:
                self.load(p)
                break

    @Slot()
    def open_file(self):
        start_dir = str(Path(self.src).parent) if self.src else str(Path.home() / "Videos")
        p, _ = QFileDialog.getOpenFileName(
            self, "動画を開く", start_dir, "MP4 動画 (*.mp4 *.m4v *.mov);;すべて (*)"
        )
        if p:
            self.load(p)

    def load(self, path: str):
        if self.proc:
            QMessageBox.information(self, "処理中", "保存処理が終わるまで待ってください。")
            return
        try:
            self.info = ft.probe(path) if self.ffmpeg else None
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "読み込み失敗", f"動画情報を取得できません:\n{e}")
            return
        self.src = path
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        dur = self.info.duration if self.info else 0.0
        self.in_sec = 0.0
        self.out_sec = dur
        self._refresh_range_labels()
        size_mb = (self.info.size_bytes / 1024 / 1024) if self.info else 0
        desc = f"{Path(path).name}"
        if self.info:
            desc += f"   {self.info.width}x{self.info.height}  {clock(dur)}  {size_mb:.1f}MB"
        self.lbl_file.setText(desc)
        self.progress.setValue(0)
        self.lbl_status.setText("")
        self.btn_open_folder.setEnabled(False)
        self._update_enabled()
        self.player.pause()

    # ------------------------------------------------------------ 再生
    def _on_duration(self, ms: int):
        self.slider.setRange(0, max(0, ms))
        if self.info is None or self.info.duration <= 0:
            self.out_sec = ms / 1000
            if self.info:
                self.info.duration = ms / 1000
            self._refresh_range_labels()
        self._refresh_marks()

    def _on_position(self, ms: int):
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.lbl_time.setText(f"{clock(ms / 1000)} / {clock(self.duration())}")
        # 「範囲を再生」中は終了位置で止める
        if self._preview_stop_at is not None and ms >= self._preview_stop_at:
            self._preview_stop_at = None
            self.player.pause()

    _preview_stop_at: int | None = None

    def _on_slider_moved(self, ms: int):
        self.player.setPosition(ms)

    def _on_player_error(self, err, msg):
        if err != QMediaPlayer.NoError:
            self.lbl_status.setText(f"プレビュー再生エラー: {msg}（切り出し自体は可能です）")

    def duration(self) -> float:
        if self.info and self.info.duration > 0:
            return self.info.duration
        return self.player.duration() / 1000

    def toggle_play(self):
        if not self.src:
            return
        self._preview_stop_at = None
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _update_play_icon(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.btn_play.setIcon(self.style().standardIcon(
            QStyle.SP_MediaPause if playing else QStyle.SP_MediaPlay))

    def seek_to(self, sec: float):
        if not self.src:
            return
        sec = min(max(0.0, sec), self.duration())
        self.player.setPosition(int(sec * 1000))

    def seek_rel(self, d: float):
        self.seek_to(self.player.position() / 1000 + d)

    def preview_range(self):
        if not self.src:
            return
        self.seek_to(self.in_sec)
        self._preview_stop_at = int(self.out_sec * 1000)
        self.player.play()

    # ------------------------------------------------------------ 範囲
    def current_sec(self) -> float:
        return self.player.position() / 1000

    def set_in_here(self):
        if not self.src:
            return
        self.in_sec = self.current_sec()
        if self.out_sec <= self.in_sec:
            self.out_sec = self.duration()
        self._refresh_range_labels()

    def set_out_here(self):
        if not self.src:
            return
        self.out_sec = self.current_sec()
        if self.out_sec <= self.in_sec:
            self.in_sec = 0.0
        self._refresh_range_labels()

    def _on_in_edited(self):
        try:
            self.in_sec = min(ft.parse_time(self.ed_in.text()), self.duration())
        except ValueError:
            pass
        self._refresh_range_labels()

    def _on_out_edited(self):
        try:
            self.out_sec = min(ft.parse_time(self.ed_out.text()), self.duration())
        except ValueError:
            pass
        self._refresh_range_labels()

    def _refresh_range_labels(self):
        self.ed_in.setText(clock(self.in_sec))
        self.ed_out.setText(clock(self.out_sec))
        length = max(0.0, self.out_sec - self.in_sec)
        self.lbl_len.setText(f"長さ: {clock(length)}")
        self._refresh_marks()

    def _refresh_marks(self):
        self.slider.set_range_marks(int(self.in_sec * 1000), int(self.out_sec * 1000))

    def _update_enabled(self):
        loaded = self.src is not None
        busy = self.proc is not None
        for w in (self.btn_play, self.btn_back, self.btn_fwd, self.btn_frame_back,
                  self.btn_frame_fwd, self.btn_set_in, self.btn_set_out,
                  self.btn_go_in, self.btn_go_out, self.btn_preview,
                  self.ed_in, self.ed_out, self.slider):
            w.setEnabled(loaded)
        self.btn_frame.setEnabled(loaded and self.ffmpeg is not None)
        self.btn_save.setEnabled(loaded and not busy and self.ffmpeg is not None)
        self.btn_open.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    # ------------------------------------------------------------ 静止画
    @Slot()
    def capture_frame(self):
        if not self.src or not self.ffmpeg:
            return
        self.player.pause()
        t = self.current_sec()
        tmp = os.path.join(tempfile.gettempdir(), f"raidclip_frame_{os.getpid()}.png")
        try:
            ft.extract_frame(self.ffmpeg, self.src, tmp, t)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "静止画の取得に失敗", str(e))
            return
        stem = Path(self.src).stem
        stamp = clock(t).replace(":", "-").replace(".", "_")
        default_save = str(Path(self.src).with_name(f"{stem}_{stamp}.png"))
        try:
            dlg = AnnotateDialog(tmp, default_save, self)
        except ValueError as e:
            QMessageBox.critical(self, "静止画の取得に失敗", str(e))
            return
        dlg.exec()
        try:
            os.remove(tmp)
        except OSError:
            pass

    # ------------------------------------------------------------ 書き出し
    @Slot()
    def start_export(self):
        if not self.src or self.proc or not self.ffmpeg:
            return
        if self.out_sec - self.in_sec < 0.2:
            QMessageBox.warning(self, "範囲が不正", "終了位置は開始位置より後にしてください。")
            return
        dst, _ = QFileDialog.getSaveFileName(
            self, "保存先", ft.default_output_path(self.src), "MP4 動画 (*.mp4)"
        )
        if not dst:
            return
        if not dst.lower().endswith(".mp4"):
            dst += ".mp4"
        if os.path.abspath(dst) == os.path.abspath(self.src):
            QMessageBox.warning(self, "保存先が不正", "元の動画には上書きできません。")
            return

        self.player.pause()
        self.dst = dst
        try:
            self.queue = self._build_queue(dst)
        except ValueError as e:
            QMessageBox.warning(self, "設定を見直してください", str(e))
            return
        self.pass_total = len(self.queue)
        self.pass_index = 0
        self.progress.setValue(0)
        self.btn_open_folder.setEnabled(False)
        self._run_next()

    def _build_queue(self, dst: str) -> list[list[str]]:
        a, b = self.in_sec, self.out_sec
        if self.rb_copy.isChecked():
            return [ft.build_copy_cmd(self.ffmpeg, self.src, dst, a, b)]
        if self.rb_accurate.isChecked():
            return [ft.build_accurate_cmd(self.ffmpeg, self.src, dst, a, b)]
        target_mb = ft.DISCORD_PRESETS_MB[self.cb_size.currentText()]
        height = self.info.height if self.info else 1080
        self._passlog = os.path.join(tempfile.gettempdir(), f"raidclip_{os.getpid()}")
        plan = ft.plan_fit(target_mb, b - a, height, self._passlog)
        self.lbl_status.setText(
            f"目標 {target_mb}MB: 映像 {plan.video_kbps}kbps / 音声 {plan.audio_kbps}kbps"
            + (f" / {plan.scale_height}p に縮小" if plan.scale_height else "")
        )
        return ft.build_fit_cmds(self.ffmpeg, self.src, dst, a, b, plan)

    def _run_next(self):
        cmd = self.queue[self.pass_index]
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(self._on_finished)
        self._stderr_tail: list[str] = []
        self.proc.start(cmd[0], cmd[1:])
        label = "書き出し中…"
        if self.pass_total > 1:
            label = f"書き出し中… ({self.pass_index + 1}/{self.pass_total} パス)"
        self.lbl_status.setText(label if not self.lbl_status.text() else
                                f"{self.lbl_status.text().split('  |')[0]}  | {label}")
        self._update_enabled()

    def _on_stdout(self):
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        total = max(0.001, self.out_sec - self.in_sec)
        for line in data.splitlines():
            t = ft.parse_progress_line(line)
            if t is None:
                continue
            frac = min(1.0, t / total)
            overall = (self.pass_index + frac) / self.pass_total
            self.progress.setValue(int(overall * 1000))

    def _on_stderr(self):
        data = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")
        self._stderr_tail.extend(data.splitlines())
        self._stderr_tail = self._stderr_tail[-30:]

    def _on_finished(self, code: int, status):
        proc, self.proc = self.proc, None
        proc.deleteLater()
        cancelled = getattr(self, "_cancelled", False)
        self._cancelled = False
        if cancelled:
            self._cleanup_partial()
            self.lbl_status.setText("中止しました。")
            self.progress.setValue(0)
            self._update_enabled()
            return
        if code != 0 or status != QProcess.NormalExit:
            tail = "\n".join(self._stderr_tail[-8:])
            self._cleanup_partial()
            self.lbl_status.setText("失敗しました。")
            self.progress.setValue(0)
            self._update_enabled()
            QMessageBox.critical(self, "書き出し失敗", f"ffmpeg がエラーで終了しました。\n\n{tail}")
            return
        self.pass_index += 1
        if self.pass_index < self.pass_total:
            self._run_next()
            return
        self._cleanup_passlog()
        self.progress.setValue(1000)
        size_mb = os.path.getsize(self.dst) / 1024 / 1024 if os.path.exists(self.dst) else 0
        self.lbl_status.setText(f"保存しました: {self.dst}  ({size_mb:.1f}MB)")
        self.btn_open_folder.setEnabled(True)
        self._update_enabled()

    def cancel_export(self):
        if self.proc:
            self._cancelled = True
            self.proc.kill()

    def _cleanup_partial(self):
        self._cleanup_passlog()
        if self.dst and os.path.exists(self.dst):
            try:
                os.remove(self.dst)
            except OSError:
                pass

    def _cleanup_passlog(self):
        if not self._passlog:
            return
        d = Path(self._passlog).parent
        for f in d.glob(Path(self._passlog).name + "*"):
            try:
                f.unlink()
            except OSError:
                pass
        self._passlog = None

    def open_folder(self):
        if not self.dst:
            return
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.dst)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", self.dst])
        else:
            subprocess.Popen(["xdg-open", str(Path(self.dst).parent)])

    def closeEvent(self, ev):
        if self.proc:
            r = QMessageBox.question(self, "処理中", "書き出し中です。中止して終了しますか？")
            if r != QMessageBox.Yes:
                ev.ignore()
                return
            self.cancel_export()
        self.player.stop()
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RaidClip")
    icon = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        w.load(sys.argv[1])
    sys.exit(app.exec())
