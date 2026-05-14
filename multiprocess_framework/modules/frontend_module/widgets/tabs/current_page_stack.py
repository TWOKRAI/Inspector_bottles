# -*- coding: utf-8 -*-
"""
CurrentPageStack — QStackedWidget, чей размер определяется только текущей страницей.

Стандартный QStackedLayout.minimumSize() = max всех дочерних виджетов,
даже скрытых. Из-за этого scroll area выделяет место под самую большую
страницу, и мастер-скроллбар показывает диапазон даже на маленькой.

Решение: при смене страницы ставим неактивным виджетам
QSizePolicy.Ignored — QStackedLayout пропустит их в расчёте
minimumSize. Активной странице возвращаем Preferred.

Извлечён из prototype SettingsTab для переиспользования в любом табе
с дифференциальным скроллом (DiffScrollTabLayout и аналоги).
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QSizePolicy, QStackedWidget, QWidget


class CurrentPageStack(QStackedWidget):
    """QStackedWidget, чей sizeHint/minimumSizeHint отражает только текущую страницу.

    При смене страницы неактивным виджетам ставится QSizePolicy.Ignored,
    активному — Preferred. Это позволяет родительскому scroll area
    корректно рассчитывать диапазон скроллбара.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(0, 0))
        self.currentChanged.connect(self._apply_size_policies)

    def sizeHint(self) -> QSize:
        w = self.currentWidget()
        if w is not None:
            return w.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        w = self.currentWidget()
        if w is not None:
            return w.minimumSizeHint()
        return super().minimumSizeHint()

    def _apply_size_policies(self, index: int) -> None:
        """Ignored на неактивных страницах → layout не считает их размер."""
        for i in range(self.count()):
            w = self.widget(i)
            if w is None:
                continue
            if i == index:
                w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            else:
                w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.updateGeometry()
