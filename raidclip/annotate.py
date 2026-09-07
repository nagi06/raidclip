"""静止画に注釈を付けるダイアログ。矢印・円・四角・線・ペン・文字・番号マーカー・モザイク・トリミング。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QAction, QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QImage,
    QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QMessageBox, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

TOOLS = [
    ("arrow", "矢印", "A"),
    ("line", "直線", "L"),
    ("rect", "四角", "R"),
    ("ellipse", "円", "E"),
    ("pen", "ペン", "P"),
    ("text", "文字", "T"),
    ("number", "番号", "N"),
    ("blur", "モザイク", "B"),
    ("crop", "トリミング", "C"),
]

COLORS = [
    ("#ff3b30", "赤"), ("#3b82f6", "青"), ("#22c55e", "緑"), ("#facc15", "黄"),
    ("#f97316", "橙"), ("#a855f7", "紫"), ("#ffffff", "白"), ("#111111", "黒"),
]

WIDTHS = [("細", 3), ("中", 6), ("太", 10)]


@dataclass
class Shape:
    kind: str
    pts: list[QPointF] = field(default_factory=list)  # 画像座標
    color: QColor = field(default_factory=lambda: QColor("#ff3b30"))
    width: int = 6
    text: str = ""
    number: int = 0

    def rect(self) -> QRectF:
        if len(self.pts) < 2:
            p = self.pts[0] if self.pts else QPointF()
            return QRectF(p, p)
        return QRectF(self.pts[0], self.pts[-1]).normalized()


# ---------------------------------------------------------------- 描画


def pixelate(img: QImage, rect: QRect, block: int = 14) -> None:
    rect = rect.intersected(img.rect())
    if rect.width() < 2 or rect.height() < 2:
        return
    part = img.copy(rect)
    small = part.scaled(
        max(1, rect.width() // block), max(1, rect.height() // block),
        Qt.IgnoreAspectRatio, Qt.FastTransformation,
    )
    big = small.scaled(rect.size(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
    p = QPainter(img)
    p.drawImage(rect.topLeft(), big)
    p.end()


def _outlined_text(p: QPainter, pos: QPointF, text: str, color: QColor, px: int):
    font = QFont()
    font.setPixelSize(px)
    font.setBold(True)
    path = QPainterPath()
    lines = text.split("\n")
    fm = QFontMetrics(font)
    y = pos.y()
    for line in lines:
        path.addText(QPointF(pos.x(), y), font, line)
        y += fm.height()
    dark = color.lightness() > 128
    p.setPen(QPen(QColor(0, 0, 0) if dark else QColor(255, 255, 255), max(2, px / 8),
                  Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    p.drawPath(path)


def draw_shape(p: QPainter, s: Shape):
    pen = QPen(s.color, s.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if s.kind == "line" and len(s.pts) >= 2:
        p.drawLine(s.pts[0], s.pts[-1])
    elif s.kind == "arrow" and len(s.pts) >= 2:
        a, b = s.pts[0], s.pts[-1]
        p.drawLine(a, b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = max(12.0, s.width * 3.5)
        left = QPointF(b.x() - size * math.cos(ang - 0.5), b.y() - size * math.sin(ang - 0.5))
        right = QPointF(b.x() - size * math.cos(ang + 0.5), b.y() - size * math.sin(ang + 0.5))
        p.setBrush(QBrush(s.color))
        p.drawPolygon(QPolygonF([b, left, right]))
    elif s.kind == "rect" and len(s.pts) >= 2:
        p.drawRect(s.rect())
    elif s.kind == "ellipse" and len(s.pts) >= 2:
        p.drawEllipse(s.rect())
    elif s.kind == "pen" and len(s.pts) >= 2:
        path = QPainterPath(s.pts[0])
        for q in s.pts[1:]:
            path.lineTo(q)
        p.drawPath(path)
    elif s.kind == "text" and s.pts:
        _outlined_text(p, s.pts[0], s.text, s.color, 14 + s.width * 4)
    elif s.kind == "number" and s.pts:
        r = 12 + s.width * 2.5
        c = s.pts[0]
        p.setPen(QPen(QColor(255, 255, 255), max(2, s.width / 2)))
        p.setBrush(QBrush(s.color))
        p.drawEllipse(c, r, r)
        font = QFont()
        font.setPixelSize(int(r * 1.3))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(QColor(255, 255, 255) if s.color.lightness() < 160 else QColor(0, 0, 0)))
        p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(s.number))
    elif s.kind in ("blur", "crop") and len(s.pts) >= 2:
        # 編集中の表示用。blur の実体は render() で画像に焼き込む
        pen = QPen(QColor(255, 255, 255) if s.kind == "blur" else QColor(255, 220, 0),
                   2, Qt.DashLine)
        p.setPen(pen)
        p.drawRect(s.rect())


def render(base: QImage, shapes: list[Shape], crop: Optional[QRectF], preview: bool) -> QImage:
    """base に注釈を焼き込んだ画像を返す。preview=True なら crop 枠を描くだけで切り抜かない。"""
    img = base.copy()
    for s in shapes:
        if s.kind == "blur" and len(s.pts) >= 2:
            pixelate(img, s.rect().toRect())
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    for s in shapes:
        if s.kind == "blur":
            continue
        draw_shape(p, s)
    if preview and crop is not None:
        # トリミング枠の外を暗くする
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        outer = QPainterPath()
        outer.addRect(QRectF(img.rect()))
        inner = QPainterPath()
        inner.addRect(crop)
        p.drawPath(outer.subtracted(inner))
        p.setPen(QPen(QColor(255, 220, 0), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(crop)
    p.end()
    if not preview and crop is not None:
        r = crop.toRect().intersected(img.rect())
        if r.width() > 1 and r.height() > 1:
            img = img.copy(r)
    return img


# ---------------------------------------------------------------- キャンバス


class Canvas(QWidget):
    def __init__(self, base: QImage, parent=None):
        super().__init__(parent)
        self.base = base
        self.shapes: list[Shape] = []
        self.history: list[tuple] = []
        self.redo_stack: list[tuple] = []
        self.crop: Optional[QRectF] = None
        self.tool = "arrow"
        self.color = QColor(COLORS[0][0])
        self.pen_width = WIDTHS[1][1]
        self.current: Optional[Shape] = None
        self.cache: Optional[QImage] = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(False)
        self.setCursor(Qt.CrossCursor)

    # 表示座標 <-> 画像座標
    def _geom(self) -> tuple[float, float, float]:
        iw, ih = self.base.width(), self.base.height()
        scale = min(self.width() / iw, self.height() / ih)
        ox = (self.width() - iw * scale) / 2
        oy = (self.height() - ih * scale) / 2
        return scale, ox, oy

    def to_img(self, pos) -> QPointF:
        scale, ox, oy = self._geom()
        x = (pos.x() - ox) / scale
        y = (pos.y() - oy) / scale
        x = min(max(0.0, x), self.base.width())
        y = min(max(0.0, y), self.base.height())
        return QPointF(x, y)

    def invalidate(self):
        self.cache = None
        self.update()

    def paintEvent(self, ev):
        if self.cache is None:
            shapes = self.shapes + ([self.current] if self.current else [])
            crop = self.crop
            if self.current and self.current.kind == "crop" and len(self.current.pts) >= 2:
                crop = self.current.rect()
            self.cache = render(self.base, shapes, crop, preview=True)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(40, 40, 40))
        scale, ox, oy = self._geom()
        target = QRectF(ox, oy, self.base.width() * scale, self.base.height() * scale)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(target, self.cache)
        p.end()

    def resizeEvent(self, ev):
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pt = self.to_img(ev.position())
        if self.tool == "text":
            text, ok = QInputDialog.getMultiLineText(self, "文字", "内容:")
            if ok and text.strip():
                self.push(Shape("text", [pt], QColor(self.color), self.pen_width, text=text))
            return
        if self.tool == "number":
            n = sum(1 for s in self.shapes if s.kind == "number") + 1
            self.push(Shape("number", [pt], QColor(self.color), self.pen_width, number=n))
            return
        self.current = Shape(self.tool, [pt], QColor(self.color), self.width)
        self.invalidate()

    def mouseMoveEvent(self, ev):
        if not self.current:
            return
        pt = self.to_img(ev.position())
        if self.current.kind == "pen":
            self.current.pts.append(pt)
        else:
            self.current.pts = [self.current.pts[0], pt]
        self.invalidate()

    def mouseReleaseEvent(self, ev):
        if not self.current or ev.button() != Qt.LeftButton:
            return
        s, self.current = self.current, None
        r = s.rect()
        tiny = r.width() < 3 and r.height() < 3
        if s.kind == "crop":
            if not tiny:
                self.set_crop(r)
        elif s.kind == "pen" or not tiny:
            self.push(s)
        self.invalidate()

    # 履歴: ("shape", Shape) か ("crop", 変更前の枠, 変更後の枠)
    def push(self, s: Shape):
        self.shapes.append(s)
        self.history.append(("shape", s))
        self.redo_stack.clear()
        self.invalidate()

    def set_crop(self, r: Optional[QRectF]):
        self.history.append(("crop", self.crop, r))
        self.crop = r
        self.redo_stack.clear()
        self.invalidate()

    def undo(self):
        if not self.history:
            return
        item = self.history.pop()
        if item[0] == "shape":
            self.shapes.remove(item[1])
        else:
            self.crop = item[1]
        self.redo_stack.append(item)
        self.invalidate()

    def redo(self):
        if not self.redo_stack:
            return
        item = self.redo_stack.pop()
        if item[0] == "shape":
            self.shapes.append(item[1])
        else:
            self.crop = item[2]
        self.history.append(item)
        self.invalidate()

    def clear_crop(self):
        if self.crop is not None:
            self.set_crop(None)

    def final_image(self) -> QImage:
        return render(self.base, self.shapes, self.crop, preview=False)


# ---------------------------------------------------------------- ダイアログ


class AnnotateDialog(QDialog):
    def __init__(self, image_path: str, default_save: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("静止画に注釈")
        self.resize(1100, 760)
        self.default_save = default_save
        base = QImage(image_path)
        if base.isNull():
            raise ValueError(f"画像を読めません: {image_path}")
        self.canvas = Canvas(base.convertToFormat(QImage.Format_RGB32))

        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        for key, label, sc in TOOLS:
            b = QToolButton()
            b.setText(f"{label} ({sc})")
            b.setCheckable(True)
            b.setToolTip(f"ショートカット: {sc}")
            b.clicked.connect(lambda _c=False, k=key: self.set_tool(k))
            self.tool_group.addButton(b)
            bar.addWidget(b)
            if key == "arrow":
                b.setChecked(True)
            a = QAction(self)
            a.setShortcut(QKeySequence(sc))
            a.triggered.connect(lambda _c=False, k=key, btn=b: (btn.setChecked(True), self.set_tool(k)))
            self.addAction(a)
        bar.addSpacing(12)
        self.color_group = QButtonGroup(self)
        for i, (hexv, name) in enumerate(COLORS):
            b = QToolButton()
            b.setCheckable(True)
            b.setFixedSize(26, 26)
            b.setToolTip(name)
            b.setStyleSheet(
                f"QToolButton{{background:{hexv};border:2px solid #666;border-radius:4px}}"
                f"QToolButton:checked{{border:3px solid #fff}}"
            )
            b.clicked.connect(lambda _c=False, h=hexv: self.set_color(h))
            self.color_group.addButton(b)
            bar.addWidget(b)
            if i == 0:
                b.setChecked(True)
        bar.addSpacing(12)
        bar.addWidget(QLabel("太さ"))
        self.cb_width = QComboBox()
        for label, w in WIDTHS:
            self.cb_width.addItem(label, w)
        self.cb_width.setCurrentIndex(1)
        self.cb_width.currentIndexChanged.connect(
            lambda i: setattr(self.canvas, "pen_width", self.cb_width.itemData(i)))
        bar.addWidget(self.cb_width)
        bar.addStretch(1)
        v.addLayout(bar)

        v.addWidget(self.canvas, 1)

        bottom = QHBoxLayout()
        b_undo = QPushButton("元に戻す (Ctrl+Z)")
        b_undo.clicked.connect(self.canvas.undo)
        b_redo = QPushButton("やり直し (Ctrl+Y)")
        b_redo.clicked.connect(self.canvas.redo)
        b_uncrop = QPushButton("トリミング解除")
        b_uncrop.clicked.connect(self.canvas.clear_crop)
        self.lbl_hint = QLabel(
            "ドラッグで描画。文字と番号はクリックで置く。モザイクとトリミングは範囲をドラッグ。"
        )
        b_copy = QPushButton("クリップボードにコピー (Ctrl+C)")
        b_copy.clicked.connect(self.copy_clipboard)
        b_save = QPushButton("PNG で保存… (Ctrl+S)")
        b_save.setDefault(True)
        b_save.clicked.connect(self.save_png)
        b_close = QPushButton("閉じる")
        b_close.clicked.connect(self.reject)
        for w in (b_undo, b_redo, b_uncrop):
            bottom.addWidget(w)
        bottom.addWidget(self.lbl_hint, 1)
        for w in (b_copy, b_save, b_close):
            bottom.addWidget(w)
        v.addLayout(bottom)

        for keys, fn in (
            (["Ctrl+Z"], self.canvas.undo),
            (["Ctrl+Y", "Ctrl+Shift+Z"], self.canvas.redo),
            (["Ctrl+S"], self.save_png),
            (["Ctrl+C"], self.copy_clipboard),
        ):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(fn)
            self.addAction(a)

    def set_tool(self, key: str):
        self.canvas.tool = key
        if key == "crop":
            self.canvas.setCursor(Qt.SizeAllCursor)
        elif key in ("text", "number"):
            self.canvas.setCursor(Qt.PointingHandCursor)
        else:
            self.canvas.setCursor(Qt.CrossCursor)

    def set_color(self, hexv: str):
        self.canvas.color = QColor(hexv)

    def copy_clipboard(self):
        img = self.canvas.final_image()
        QGuiApplication.clipboard().setImage(img)
        self.lbl_hint.setText(f"コピーしました ({img.width()}x{img.height()})。Discord に Ctrl+V で貼れます。")

    def save_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "PNG で保存", self.default_save, "PNG 画像 (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        img = self.canvas.final_image()
        if not img.save(path, "PNG"):
            QMessageBox.critical(self, "保存失敗", f"書き込めません: {path}")
            return
        self.default_save = path
        self.lbl_hint.setText(f"保存しました: {path} ({img.width()}x{img.height()})")
