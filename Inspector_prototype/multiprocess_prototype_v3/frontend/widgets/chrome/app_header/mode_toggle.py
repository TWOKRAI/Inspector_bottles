# multiprocess_prototype_v3/frontend/widgets/app_header/mode_toggle.py
"""HeaderModeToggle — checkable-кнопка переключения режима шапки (A ↔ B)."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QPushButton,
    QSize,
    Signal,
)


class HeaderModeToggle(QPushButton):
    """Кнопка-переключатель: 0 = инфо-режим (A), 1 = окна (B). Эмитит mode_changed."""

    mode_changed = Signal(int)

    def __init__(self, initial: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(QSize(48, 48))
        self.setToolTip("Переключить режим шапки")
        self._set_visual(initial)
        self.setChecked(bool(initial))
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        mode = 1 if checked else 0
        self._set_visual(mode)
        self.mode_changed.emit(mode)

    def _set_visual(self, mode: int) -> None:
        self.setText("B" if mode == 1 else "A")

    def set_mode(self, mode: int) -> None:
        """Программно установить режим без эмита сигнала."""
        if mode not in (0, 1):
            return
        if self.isChecked() == bool(mode):
            return
        self.blockSignals(True)
        self.setChecked(bool(mode))
        self.blockSignals(False)
        self._set_visual(mode)
