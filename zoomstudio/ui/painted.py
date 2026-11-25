"""Small widgets that paint their own text and shape.

A style sheet that declares ``QWidget { font-size }`` overrides ``QWidget.setFont`` for labels, so every
text that needs an exact family, weight, size or letter spacing is painted with ``QPainter.setFont``, which
the style sheet does not touch (the way the cards do it).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QLabel, QPushButton, QSizePolicy, QStatusBar, QWidget

from . import strings as S
from . import tokens
from .fonts import display_font, ui_font


def _resolve(color: QColor | str) -> QColor:
    """A token name, a ``#rrggbb`` string or a QColor."""
    if isinstance(color, str) and not color.startswith("#"):
        return tokens.color(color)
    return QColor(color)


class PaintedText(QWidget):
    """One line of text in an exact font and colour, painted (not a ``QLabel``)."""

    def __init__(self, text: str = "", font: QFont | None = None, color: QColor | str = "text-primary",
                 align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter, spacing: float = 0.0) -> None:
        super().__init__()
        self._text = text
        self._font = QFont(font) if font is not None else ui_font()
        if spacing:
            self._font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        self._color = _resolve(color)
        self._align = align
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def setColor(self, color: QColor | str) -> None:  # noqa: N802 (Qt API)
        self._color = _resolve(color)
        self.update()

    def color(self) -> QColor:
        return QColor(self._color)

    def paint_font(self) -> QFont:
        return QFont(self._font)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        metrics = QFontMetrics(self._font)
        return QSize(metrics.horizontalAdvance(self._text) + 2, metrics.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(0, QFontMetrics(self._font).height())

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font)
        p.setPen(self._color)
        p.drawText(QRectF(self.rect()), self._align | Qt.AlignmentFlag.AlignVCenter, self._text)


class SectionLabel(PaintedText):
    """Section header: Exo 2 13 px, SemiBold, spaced capitals («PATCHES»)."""

    def __init__(self, text: str, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
                 color: str = "text-secondary") -> None:
        super().__init__(text.upper(), display_font(tokens.px("text-label-size"), 600), color, align, spacing=1.1)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        super().setText(text.upper())


class KeyChipButton(QPushButton):
    """A push button with a keyboard-key chip («T») painted at its right edge."""

    CHIP_W = 22

    def __init__(self, text: str, key: str) -> None:
        super().__init__(text)
        self.key = key
        self.setProperty("keychip", True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        hint = super().sizeHint()
        return QSize(hint.width() + self.CHIP_W + 4, hint.height())

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        chip = QRectF(self.width() - self.CHIP_W - 12, (self.height() - 20) / 2, self.CHIP_W, 20)
        color = tokens.color("text-secondary" if self.isEnabled() else "text-disabled")
        p.setPen(QPen(color, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(chip, 6, 6)
        p.setFont(ui_font(12, QFont.Weight.Medium))
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, self.key)


class LiveSwitch(QAbstractButton):
    """«En vivo» switch: a 26 px pill with an 18 px knob and the word NO / SÍ beside it."""

    TRACK_W, TRACK_H, KNOB = 44, 26, 18

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setText(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(text)

    def state_text(self) -> str:
        return S.SWITCH_ON if self.isChecked() else S.SWITCH_OFF

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        label = QFontMetrics(ui_font()).horizontalAdvance(self.text())
        return QSize(label + 10 + self.TRACK_W + 4, self.TRACK_H + 4)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled, on = self.isEnabled(), self.isChecked()
        p.setFont(ui_font())
        p.setPen(tokens.color("text-primary" if enabled else "text-disabled"))
        label_w = QFontMetrics(ui_font()).horizontalAdvance(self.text())
        p.drawText(QRectF(0, 0, label_w + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        track = QRectF(label_w + 12, (self.height() - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H)
        if on and enabled:
            p.setBrush(tokens.color("accent"))
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setBrush(tokens.color("input-bg"))
            p.setPen(QPen(tokens.color("border-strong" if enabled else "border-control"), 1.5,
                          Qt.PenStyle.SolidLine if enabled else Qt.PenStyle.DashLine))
        p.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        gap = (self.TRACK_H - self.KNOB) / 2
        knob_x = track.right() - gap - self.KNOB if on else track.left() + gap
        knob = QRectF(knob_x, track.top() + gap, self.KNOB, self.KNOB)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tokens.color("on-accent" if on and enabled else "text-secondary" if enabled else "text-disabled"))
        p.drawEllipse(knob)
        p.setFont(ui_font(11, QFont.Weight.Bold))
        p.setPen(tokens.color("on-accent" if on and enabled else "text-secondary" if enabled else "text-disabled"))
        if not on:
            text_rect = QRectF(knob.right() + 2, track.top(), track.right() - knob.right() - 6, self.TRACK_H)
        else:
            text_rect = QRectF(track.left() + 6, track.top(), knob.left() - track.left() - 8, self.TRACK_H)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.state_text())
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(tokens.color("focus-ring"), 2))
            p.drawRoundedRect(track.adjusted(-3, -3, 3, 3), self.TRACK_H / 2 + 3, self.TRACK_H / 2 + 3)


class DotLabel(QWidget):
    """A coloured dot with a glow and a text beside it («● Cambios sin guardar»)."""

    def __init__(self, text: str = "", token: str = "status-warn", font: QFont | None = None) -> None:
        super().__init__()
        self._text, self._token = text, token
        self._font = font or ui_font(tokens.px("text-body-size"), QFont.Weight.Bold)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        self._text = text
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        metrics = QFontMetrics(self._font)
        return QSize(metrics.horizontalAdvance(self._text) + 22, max(22, metrics.height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(7, self.height() / 2)
        color = tokens.color(self._token)
        glow = QRadialGradient(c, 7)
        glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 110))
        glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, 7, 7)
        p.setBrush(color)
        p.drawEllipse(c, 4, 4)
        p.setFont(self._font)
        p.setPen(tokens.color("text-primary"))
        p.drawText(QRectF(18, 0, self.width() - 18, self.height()), Qt.AlignmentFlag.AlignVCenter, self._text)


class ConnectionPill(QLabel):
    """Connection state pill: a dot (green connected, blue folder, hollow none) with a glow, then the text."""

    DOT_TOKENS = {"ok": "status-ok", "info": "status-info", "none": None}

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setObjectName("connectionPill")
        self.kind = "none"

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(18, self.height() / 2)
        token = self.DOT_TOKENS.get(self.kind)
        if token is None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(tokens.color("border-strong"), 1.5))
            p.drawEllipse(c, 4, 4)
            return
        color = tokens.color(token)
        glow = QRadialGradient(c, 8)
        glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 120))
        glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, 8, 8)
        p.setBrush(color)
        p.drawEllipse(c, 4, 4)


class StatusBar(QStatusBar):
    """Status bar whose messages are plain unless they were shown with ``show_error`` (red text)."""

    def __init__(self) -> None:
        super().__init__()
        self.setSizeGripEnabled(False)
        self._next_is_error = False

    def show_error(self, text: str, timeout: int = 0) -> None:
        self._next_is_error = True
        self.showMessage(text, timeout)

    def showMessage(self, text: str, timeout: int = 0) -> None:  # noqa: N802 (Qt API)
        error, self._next_is_error = self._next_is_error, False
        if bool(self.property("error")) != error:
            self.setProperty("error", error)
            self.style().unpolish(self)
            self.style().polish(self)
        super().showMessage(text, timeout)


class GroupChip(QWidget):
    """Effect group as a rounded chip: border in the group colour, tint fill, text in the group text colour."""

    def __init__(self, text: str = "", group: str = "") -> None:
        super().__init__()
        self._text = text
        self._group = group
        self._font = ui_font(13, QFont.Weight.Medium)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_group(self, text: str, group: str) -> None:
        self._text, self._group = text, group
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(QFontMetrics(self._font).horizontalAdvance(self._text) + 24, 26)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        from .theme import group_color, group_fill_color, group_text_color

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        p.setBrush(group_fill_color(self._group))
        p.setPen(QPen(group_color(self._group), 1.5))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setFont(self._font)
        p.setPen(group_text_color(self._group))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
