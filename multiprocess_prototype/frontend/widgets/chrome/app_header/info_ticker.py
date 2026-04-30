# multiprocess_prototype/frontend/widgets/app_header/info_ticker.py
"""InfoTickerWidget — бегущая строка для шапки (марки)."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QLabel,
    QTimer,
    QWidget,
)

_DEFAULT_HEIGHT = 22
_TICK_INTERVAL_MS = 30
_PIXELS_PER_TICK = 1
_GAP_PX = 60  # пробел между концом и началом текста


class InfoTickerWidget(QWidget):
    """QLabel внутри QWidget со сдвигом по x через QTimer (loop scroll)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_DEFAULT_HEIGHT)
        self._label = QLabel(self)
        self._label.setObjectName("InfoTickerLabel")
        self._label.move(0, 0)
        self._offset = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        """Обновить текст бегущей строки и пересчитать размер."""
        self._label.setText(text or " ")
        self._label.adjustSize()
        self._label.setFixedHeight(self.height())
        self._offset = self.width()
        self._label.move(self._offset, 0)
        if text:
            self._timer.start()
        else:
            self._timer.stop()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API naming
        self._label.setFixedHeight(self.height())
        super().resizeEvent(event)

    def _tick(self) -> None:
        if self.width() <= 0:
            return
        self._offset -= _PIXELS_PER_TICK
        label_width = self._label.width()
        if self._offset + label_width + _GAP_PX < 0:
            self._offset = self.width()
        self._label.move(self._offset, 0)
