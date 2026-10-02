"""ゲーム画面の上に重ねて見るための別窓プレーヤー。

- 常に最前面・枠なし。映像をドラッグで移動、縁をドラッグでサイズ変更
- 切り出し範囲をループ再生、再生速度、不透明度を変えられる
- 操作バーはマウスが窓の外に出ると隠れ、映像だけになる
- 位置・サイズ・不透明度・速度・ミュートは次回も引き継ぐ
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QImage, QKeySequence, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QSlider, QStyle, QToolButton,
    QVBoxLayout, QWidget,
)

RATES = [("0.25x", 0.25), ("0.5x", 0.5), ("0.75x", 0.75), ("1x", 1.0), ("1.25x", 1.25), ("1.5x", 1.5)]
EDGE = 6          # この幅の縁をドラッグするとサイズ変更
HIDE_DELAY = 800  # 窓の外に出てから操作バーを隠すまで (ms)


def clock(sec: float) -> str:
    sec = max(0.0, sec)
    m = int(sec // 60)
    return f"{m}:{sec - m * 60:04.1f}"


class VideoCanvas(QWidget):
    """QVideoSink から受けたフレームをアスペクト比を保って描く。

    QVideoWidget はネイティブ子ウィンドウになり窓の不透明度が効かないことがあるため、自前で描く。
    マウス操作は親 (OverlayPlayer) が受ける。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setMinimumSize(160, 90)

    def set_frame(self, frame):
        if not frame.isValid():
            return
        img = frame.toImage()
        if not img.isNull():
            self.image = img
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        if not self.image.isNull():
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            size = self.image.size().scaled(self.size(), Qt.KeepAspectRatio)
            r = QRect(QPoint(0, 0), size)
            r.moveCenter(self.rect().center())
            p.drawImage(r, self.image)
        p.end()


class SeekSlider(QSlider):
    """クリックした位置へ直接飛ぶスライダー。"""

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.maximum() > self.minimum():
            v = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(ev.position().x()), self.width())
            self.setValue(v)
            self.sliderMoved.emit(v)
        super().mousePressEvent(ev)


class OverlayPlayer(QWidget):
    closed = Signal()

    def __init__(self):
        # 親を持たせない: 親付きだとメイン窓を最小化したときに一緒に消えるため
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle("RaidClip - 別窓再生")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setStyleSheet("""
            OverlayPlayer { background: #181818; }
            QLabel, QCheckBox { color: #ddd; }
            QToolButton { color: #ddd; background: transparent; border: none; padding: 2px 6px;
                          font-size: 14px; }
            QToolButton:hover { background: #333; }
            QComboBox { color: #ddd; background: #2a2a2a; border: 1px solid #444; padding: 0 4px; }
        """)

        self.settings = QSettings("RaidClip", "RaidClip")
        self.in_ms = 0
        self.out_ms = 0
        self._drag_from: QPoint | None = None  # 移動中のマウス位置 - 窓の左上
        self._pending_pos: int | None = None   # 読み込み完了後にシークする位置

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.sink = QVideoSink(self)
        self.player.setVideoOutput(self.sink)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda ms: self.seek.setRange(0, max(0, ms)))
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.playbackStateChanged.connect(lambda _s: self._update_play_icon())

        self._build_ui()
        self.sink.videoFrameChanged.connect(self.canvas.set_frame)

        self._hide_timer = QTimer(self, singleShot=True, interval=HIDE_DELAY)
        self._hide_timer.timeout.connect(self._maybe_hide_controls)

        self._restore_settings()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(EDGE, EDGE, EDGE, EDGE)
        v.setSpacing(2)
        self.canvas = VideoCanvas()
        v.addWidget(self.canvas, 1)

        self.controls = QWidget()
        self.controls.setMouseTracking(True)
        cv = QVBoxLayout(self.controls)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        row1 = QHBoxLayout()
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.lbl_time = QLabel("0:00.0")
        row1.addWidget(self.seek, 1)
        row1.addWidget(self.lbl_time)
        cv.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_play.setToolTip("再生 / 一時停止 (Space、映像をダブルクリックでも可)")
        self.btn_play.clicked.connect(self.toggle_play)
        self.cb_loop = QCheckBox("範囲ループ")
        self.cb_loop.setToolTip("メイン画面で指定した開始〜終了を繰り返す (L)")
        self.cb_loop.setChecked(True)
        self.cb_rate = QComboBox()
        for name, _r in RATES:
            self.cb_rate.addItem(name)
        self.cb_rate.setToolTip("再生速度")
        self.cb_rate.currentIndexChanged.connect(
            lambda i: self.player.setPlaybackRate(RATES[i][1]))
        self.sl_opacity = QSlider(Qt.Horizontal)
        self.sl_opacity.setRange(20, 100)
        self.sl_opacity.setFixedWidth(80)
        self.sl_opacity.setToolTip("不透明度")
        self.sl_opacity.valueChanged.connect(lambda x: self.setWindowOpacity(x / 100))
        self.btn_mute = QToolButton()
        self.btn_mute.setCheckable(True)
        self.btn_mute.setToolTip("ミュート (M)")
        self.btn_mute.toggled.connect(self._on_mute)
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("閉じる (Esc)")
        self.btn_close.clicked.connect(self.close)

        row2.addWidget(self.btn_play)
        row2.addWidget(self.cb_loop)
        row2.addWidget(self.cb_rate)
        row2.addStretch(1)
        row2.addWidget(QLabel("透明"))
        row2.addWidget(self.sl_opacity)
        row2.addWidget(self.btn_mute)
        row2.addWidget(self.btn_close)
        cv.addLayout(row2)
        v.addWidget(self.controls)

        def act(keys, fn):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(fn)
            self.addAction(a)

        act(["Space", "K"], self.toggle_play)
        act(["L"], self.cb_loop.toggle)
        act(["M"], self.btn_mute.toggle)
        act(["Left"], lambda: self.seek_rel(-2))
        act(["Right"], lambda: self.seek_rel(2))
        act(["Escape"], self.close)

    def _restore_settings(self):
        s = self.settings
        geo = s.value("overlay/geometry")
        if geo is None or not self.restoreGeometry(geo):
            # 初回: 主画面の右上に 640x360 程度で出す
            scr = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(640 + 2 * EDGE, 360 + 70)
            self.move(scr.right() - self.width() - 20, scr.top() + 20)
        self.sl_opacity.setValue(int(s.value("overlay/opacity", 100)))
        self.setWindowOpacity(self.sl_opacity.value() / 100)
        rate = float(s.value("overlay/rate", 1.0))
        idx = next((i for i, (_n, r) in enumerate(RATES) if abs(r - rate) < 1e-6), 3)
        self.cb_rate.setCurrentIndex(idx)
        self.player.setPlaybackRate(RATES[idx][1])
        # ゲーム音と重なるので既定はミュート
        muted = str(s.value("overlay/muted", "true")).lower() in ("true", "1")
        self.btn_mute.setChecked(muted)
        self._on_mute(muted)

    def _save_settings(self):
        s = self.settings
        s.setValue("overlay/geometry", self.saveGeometry())
        s.setValue("overlay/opacity", self.sl_opacity.value())
        s.setValue("overlay/rate", RATES[self.cb_rate.currentIndex()][1])
        s.setValue("overlay/muted", self.btn_mute.isChecked())

    # ------------------------------------------------------------ 外部から
    def open_media(self, path: str, start_ms: int, in_ms: int, out_ms: int, volume: float):
        """メイン画面から呼ぶ。同じ動画なら読み込み直さずに位置だけ合わせる。"""
        self.set_range(in_ms, out_ms)
        if self._looping() and not (in_ms <= start_ms < out_ms - 50):
            start_ms = in_ms
        self.audio.setVolume(volume)
        src = QUrl.fromLocalFile(path)
        if self.player.source() != src:
            # 読み込み前の setPosition は無視されるので、読み込み完了時に合わせる
            self._pending_pos = start_ms
            self.player.setSource(src)
        else:
            self.player.setPosition(start_ms)
        self.show()
        self._show_controls()
        self._hide_timer.start()
        self.player.play()

    def set_range(self, in_ms: int, out_ms: int):
        self.in_ms, self.out_ms = in_ms, out_ms

    # ------------------------------------------------------------ 再生
    def _looping(self) -> bool:
        return self.cb_loop.isChecked() and self.out_ms - self.in_ms >= 200

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            return
        if self._looping():
            pos = self.player.position()
            if pos < self.in_ms or pos >= self.out_ms - 50:
                self.player.setPosition(self.in_ms)
        self.player.play()

    def seek_rel(self, sec: float):
        dur = self.player.duration()
        self.player.setPosition(int(min(max(0, self.player.position() + sec * 1000), dur)))

    def _on_position(self, ms: int):
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        self.lbl_time.setText(clock(ms / 1000))
        if (self._looping() and self.player.playbackState() == QMediaPlayer.PlayingState
                and ms >= self.out_ms):
            self.player.setPosition(self.in_ms)

    def _on_status(self, status):
        if self._pending_pos is not None and status in (
                QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            pos, self._pending_pos = self._pending_pos, None
            self.player.setPosition(pos)
        if status == QMediaPlayer.EndOfMedia and self._looping():
            self.player.setPosition(self.in_ms)
            self.player.play()

    def _on_mute(self, muted: bool):
        self.audio.setMuted(muted)
        self.btn_mute.setText("🔇" if muted else "🔊")

    def _update_play_icon(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.btn_play.setText("⏸" if playing else "▶")

    # ------------------------------------------------------------ 操作バーの表示
    def _show_controls(self):
        self._hide_timer.stop()
        self.controls.show()

    def _maybe_hide_controls(self):
        if self._drag_from is not None or self.frameGeometry().contains(QCursor.pos()):
            return
        if self.cb_rate.view().isVisible():  # 速度のプルダウンを開いている間は隠さない
            self._hide_timer.start()
            return
        self.controls.hide()

    def enterEvent(self, ev):
        self._show_controls()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hide_timer.start()
        super().leaveEvent(ev)

    # ------------------------------------------------------------ 移動・サイズ変更
    def _edges(self, pos: QPoint) -> Qt.Edges:
        edges = Qt.Edges()
        if pos.x() < EDGE:
            edges |= Qt.LeftEdge
        elif pos.x() >= self.width() - EDGE:
            edges |= Qt.RightEdge
        if pos.y() < EDGE:
            edges |= Qt.TopEdge
        elif pos.y() >= self.height() - EDGE:
            edges |= Qt.BottomEdge
        return edges

    def _cursor_for(self, edges) -> Qt.CursorShape:
        lt, rb = Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge
        rt, lb = Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge
        if edges in (lt, rb):
            return Qt.SizeFDiagCursor
        if edges in (rt, lb):
            return Qt.SizeBDiagCursor
        if edges & (Qt.LeftEdge | Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges & (Qt.TopEdge | Qt.BottomEdge):
            return Qt.SizeVerCursor
        return Qt.SizeAllCursor

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position().toPoint()
        edges = self._edges(pos)
        if edges and self.windowHandle() and self.windowHandle().startSystemResize(edges):
            return
        self._drag_from = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None:
            self.move(ev.globalPosition().toPoint() - self._drag_from)
        else:
            self.setCursor(self._cursor_for(self._edges(ev.position().toPoint())))

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_from = None

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self._edges(ev.position().toPoint()):
            self.toggle_play()

    def wheelEvent(self, ev):
        # ホイールで不透明度を変える (ゲーム中に手早く薄くしたいとき用)
        step = 5 if ev.angleDelta().y() > 0 else -5
        self.sl_opacity.setValue(self.sl_opacity.value() + step)

    def closeEvent(self, ev):
        self.player.pause()
        self._save_settings()
        self.closed.emit()
        super().closeEvent(ev)

    def shutdown(self):
        """アプリ終了時に呼ぶ。"""
        if self.isVisible():
            self.close()
        self.player.stop()
