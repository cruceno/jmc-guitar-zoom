"""Subtle glass, painted: a static backdrop, one softened copy per window size and near-opaque panels.

No live blur and no QGraphicsEffect: the backdrop is generated when the size changes and every panel
only blits the part of the softened copy that lies behind it, then paints tint, specular and rim.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QWidget

from . import tokens

PANEL_RADIUS = 16
SOFTEN_DIVISOR = 12  # the softened copy is rendered at 1/12 scale and scaled back up


def render_backdrop(size: QSize, dpr: float = 1.0) -> QImage:
    """Base colour plus four faint radial lights (amber, teal, indigo, ivory)."""
    image = QImage(round(size.width() * dpr), round(size.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(tokens.color("backdrop-base"))
    p = QPainter(image)
    w, h = image.width(), image.height()
    reach = max(w, h) * 0.65
    for light, (fx, fy) in (("light-amber", (0.06, 0.95)), ("light-teal", (0.92, 0.08)),
                            ("light-indigo", (0.78, 0.92)), ("light-ivory", (0.35, 0.0))):
        c = tokens.color(light)
        gradient = QRadialGradient(QPointF(w * fx, h * fy), reach)
        gradient.setColorAt(0.0, c)
        gradient.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.fillRect(image.rect(), gradient)
    p.end()
    return image


def soften(image: QImage) -> QImage:
    """Blur by scaling down and back up (smooth); enough for lights that are already gradients."""
    small = image.scaled(max(1, image.width() // SOFTEN_DIVISOR), max(1, image.height() // SOFTEN_DIVISOR),
                         Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return small.scaled(image.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


class Backdrop:
    """The static backdrop and its softened copy for one window size."""

    def __init__(self) -> None:
        self.size = QSize()
        self.dpr = 1.0
        self.image = QPixmap()
        self.blurred = QPixmap()
        self.builds = 0

    def ensure(self, size: QSize, dpr: float = 1.0) -> bool:
        """Rebuild when the size or the pixel ratio changed; True when it did."""
        if size == self.size and dpr == self.dpr and not self.image.isNull():
            return False
        image = render_backdrop(size, dpr)
        self.image = QPixmap.fromImage(image)
        self.blurred = QPixmap.fromImage(soften(image))
        self.image.setDevicePixelRatio(dpr)
        self.blurred.setDevicePixelRatio(dpr)
        self.size, self.dpr = QSize(size), dpr
        self.builds += 1
        return True


class BackdropRoot(QWidget):
    """Central widget: paints the backdrop; rebuilds it 150 ms after the last resize."""

    def __init__(self) -> None:
        super().__init__()
        self.backdrop = Backdrop()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._rebuild)

    def _rebuild(self) -> None:
        self.backdrop.ensure(self.size(), self.devicePixelRatioF())
        self.update()
        for panel in self.findChildren(GlassPanel):
            panel.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self.backdrop.image.isNull():
            self._rebuild()  # first size: build now, so the first paint is right
        else:
            self._timer.start()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        self.backdrop.ensure(self.size(), self.devicePixelRatioF()) if self.backdrop.image.isNull() else None
        p = QPainter(self)
        p.drawPixmap(QRectF(self.rect()), self.backdrop.image, QRectF(self.backdrop.image.rect()))


class GlassPanel(QFrame):
    """Rounded panel over the backdrop: softened backdrop, tint, specular and a gradient rim."""

    def __init__(self, root: BackdropRoot, variant: str = "panel") -> None:
        super().__init__()
        self._root = root
        self._tint = {"panel": "glass-tint", "strong": "glass-tint-strong", "overlay": "glass-tint-overlay"}[variant]
        self.setObjectName("glassPanel")

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, PANEL_RADIUS, PANEL_RADIUS)
        blurred = self._root.backdrop.blurred
        if not blurred.isNull():
            origin = self.mapTo(self._root, self.rect().topLeft())
            dpr = blurred.devicePixelRatio()
            p.save()
            p.setClipPath(path)
            p.drawPixmap(QRectF(self.rect()), blurred,
                         QRectF(origin.x() * dpr, origin.y() * dpr, self.width() * dpr, self.height() * dpr))
            p.restore()
        p.fillPath(path, tokens.color(self._tint))
        specular = QLinearGradient(0, 0, 0, self.height() * 0.38)
        specular.setColorAt(0.0, tokens.color("glass-specular"))
        specular.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, specular)
        rim = QLinearGradient(0, 0, 0, self.height())
        rim.setColorAt(0.0, tokens.color("glass-rim-top"))
        rim.setColorAt(0.5, tokens.color("glass-rim-bottom"))
        rim.setColorAt(1.0, tokens.color("glass-rim-top").darker(110))
        p.setPen(QPen(rim, 1))
        p.drawPath(path)


def paint_glow(p: QPainter, rect: QRectF, token: str, radius: float, spread: float = 10) -> None:
    """Soft glow around a rounded rect (selection, focus, enabled Save): painted, never a blur effect."""
    c = tokens.color(token)
    for i in range(4):
        grow = spread * (i + 1) / 4
        alpha = max(1, round(c.alpha() * (0.45 / (i + 1))))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.red(), c.green(), c.blue(), alpha))
        p.drawRoundedRect(rect.adjusted(-grow, -grow, grow, grow), radius + grow, radius + grow)


class GlowHost(QWidget):
    """Holds one widget with margin around it and paints a glow behind it while it is enabled."""

    def __init__(self, child: QWidget, token: str = "glow-accent", radius: float = 24, margin: int = 14) -> None:
        super().__init__()
        from PySide6.QtWidgets import QVBoxLayout

        self.child, self._token, self._radius = child, token, radius
        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.addWidget(child)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        if self.child.isEnabled():
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_glow(p, QRectF(self.child.geometry()), self._token, self._radius)
