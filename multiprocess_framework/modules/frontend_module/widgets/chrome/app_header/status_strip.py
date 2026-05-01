# multiprocess_framework/modules/frontend_module/widgets/chrome/app_header/status_strip.py
"""StatusStripWidget — строка статусов в шапке (плейсхолдеры под будущие индикаторы)."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QLabel,
    QWidget,
)

_DEFAULT_HEIGHT = 22


class StatusStripWidget(QWidget):
    """Горизонтальная строка с QLabel-индикаторами; ключи задаются через set_status."""

    def __init__(self, keys: list[str] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_DEFAULT_HEIGHT)
        self._labels: dict[str, QLabel] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(16)

        for key in keys or ["status_1", "status_2", "status_3"]:
            lbl = QLabel(self._placeholder_text(key))
            lbl.setObjectName("StatusIndicator")
            layout.addWidget(lbl)
            self._labels[key] = lbl

        layout.addStretch()

    @staticmethod
    def _placeholder_text(key: str) -> str:
        return f"[{key}]"

    def set_status(self, key: str, text: str, *, color: str | None = None) -> None:
        """Обновить текст индикатора по ключу. color — CSS-цвет (опц.)."""
        lbl = self._labels.get(key)
        if lbl is None:
            return
        lbl.setText(text)
        if color is not None:
            lbl.setStyleSheet(f"color: {color};")

    def add_status(self, key: str, initial_text: str = "") -> None:
        """Добавить новый индикатор runtime (например, при подключении источника)."""
        if key in self._labels:
            return
        lbl = QLabel(initial_text or self._placeholder_text(key))
        lbl.setObjectName("StatusIndicator")
        layout = self.layout()
        if layout is not None:
            # вставить перед stretch (последний item)
            insert_pos = max(layout.count() - 1, 0)
            layout.insertWidget(insert_pos, lbl)
        self._labels[key] = lbl
