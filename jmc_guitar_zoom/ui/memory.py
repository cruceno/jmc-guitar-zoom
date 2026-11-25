"""The pedal's memory bars (top bar and effects screen): the state is told by FREE bytes, not by percent.

On the A1 FOUR the user memory is 3,087,950 bytes and the effects fill it: about 100,000 bytes free is 96.7 % used
and perfectly normal, so a percent scale would sit in red all the time. What decides whether an effect fits is the
free space: effects run about 11 to 55 KB, plus the 4 KB spare the installer keeps.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar, QWidget

from . import strings as S
from .icons import icon

# free bytes at or above this: every effect fits with room to spare (the largest is about 55 KB plus the margin)
MEMORY_OK_FREE = 160_000
# below this: roughly where a large effect no longer fits (55 KB plus the 4 KB margin, and the list file); amber between
MEMORY_LOW_FREE = 64_000

# the fill of each state: the tokens the stylesheet paints the bar's chunk with (every one reaches 3:1 on the track)
FILL_TOKENS = {"ok": ("accent-pressed", "accent-hover"), "low": ("status-warn",), "critical": ("status-danger",)}
ICON_TOKENS = {"low": "status-warn", "critical": "status-danger"}


def memory_state(free: int) -> str:
    """``"ok"``, ``"low"`` or ``"critical"`` for ``free`` bytes."""
    if free >= MEMORY_OK_FREE:
        return "ok"
    return "low" if free >= MEMORY_LOW_FREE else "critical"


def apply_state(bar: QProgressBar, icon_label: QLabel, word_label: QLabel, others: tuple[QWidget, ...],
                free: int | None) -> None:
    """Colour ``bar`` for ``free`` bytes (``None``: unknown) and show the word and the icon beside it.

    The word, the icon and the tooltip carry the state too: colour is never the only signal. ``others`` (the figure
    labels) get the same tooltip.
    """
    state = "" if free is None else memory_state(free)
    bar.setProperty("memory", state)
    bar.style().unpolish(bar)
    bar.style().polish(bar)
    word = {"low": S.MEMORY_LOW, "critical": S.MEMORY_CRITICAL}.get(state, "")
    tip = "" if free is None else S.memory_state_tip(state, free)
    word_label.setText(word)
    word_label.setVisible(bool(word))
    icon_label.setVisible(bool(word))
    if word:
        icon_label.setPixmap(icon("alert", ICON_TOKENS[state], 16).pixmap(16, 16))
        word_label.setProperty("memory", state)
        word_label.style().unpolish(word_label)
        word_label.style().polish(word_label)
    for widget in (icon_label, word_label):
        widget.setToolTip(tip)
        widget.setAccessibleName(word)
    bar.setAccessibleName(tip)
    for widget in (bar, *others):
        widget.setToolTip(tip)
