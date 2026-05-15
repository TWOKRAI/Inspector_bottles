# -*- coding: utf-8 -*-
"""
CheckboxView — QLabel + QCheckBox с настраиваемой позицией.

Реализует контракт `IControlView[bool]` для `CheckboxPresenter`.
"""

from __future__ import annotations

from typing import Callable, Literal, Optional

from multiprocess_framework.modules.frontend_module.components.base.infrastructure.signal_utils import (
    block_signals,
)
from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
    Signal,
)

# Геометрия квадрата чекбокса и отступы layout (px).
CHECKBOX_FIXED_WIDTH_PX = 44
CHECKBOX_FIXED_HEIGHT_PX = 44
LAYOUT_CONTENT_MARGINS_PX = 4
LAYOUT_SPACING_PX = 4

Position = Literal["left", "right", "top", "bottom"]


class CheckboxView(QWidget):
    """Композитный виджет: подпись (`QLabel`) + `QCheckBox` в одном из четырёх порядков."""

    # Публичный сигнал: эмитится при смене состояния чекбокса пользователем.
    # Передаёт bool (отмечен / нет). Используется для binding через
    # ActionBusRegistersManager и других внешних подписчиков.
    value_changed = Signal(bool)

    def __init__(
        self,
        position: Position = "left",
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Args:
            position: Порядок «метка / чекбокс» в горизонтальном или вертикальном layout.
            parent: Родительский Qt-виджет.
        """
        super().__init__(parent)
        self._position = position
        self._label = QLabel()
        self._checkbox = QCheckBox()
        self._checkbox.setFixedSize(CHECKBOX_FIXED_WIDTH_PX, CHECKBOX_FIXED_HEIGHT_PX)
        self._build_layout()

        # Эмит value_changed при смене состояния (stateChanged → bool).
        # Не конфликтует с on_changed() — тот подключает дополнительный callback.
        self._checkbox.stateChanged.connect(
            lambda _state: self.value_changed.emit(self._checkbox.isChecked()),
        )

    def _build_layout(self) -> None:
        """Собрать `QHBoxLayout` или `QVBoxLayout` в соответствии с `position`."""
        if self._position in ("top", "bottom"):
            layout: QHBoxLayout | QVBoxLayout = QVBoxLayout()
            items: tuple = (self._label, self._checkbox) if self._position == "top" else (self._checkbox, self._label)
        else:
            layout = QHBoxLayout()
            items = (self._label, self._checkbox) if self._position == "left" else (self._checkbox, self._label)

        layout.setContentsMargins(
            LAYOUT_CONTENT_MARGINS_PX,
            LAYOUT_CONTENT_MARGINS_PX,
            LAYOUT_CONTENT_MARGINS_PX,
            LAYOUT_CONTENT_MARGINS_PX,
        )
        layout.setSpacing(LAYOUT_SPACING_PX)
        for w in items:
            layout.addWidget(w)
        self.setLayout(layout)

    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        """Задать текст метки, подсказку и доступность редактирования чекбокса."""
        self._label.setText(label)
        self._label.setToolTip(tooltip)
        self.set_enabled(enabled)

    def set_value(self, value: bool) -> None:
        """Установить состояние галочки; сигналы Qt не блокируются."""
        self._checkbox.setChecked(value)

    def set_value_silent(self, value: bool) -> None:
        """Установить состояние без эмита `stateChanged` (синхронизация из модели)."""
        with block_signals(self._checkbox):
            self._checkbox.setChecked(value)

    def get_value(self) -> bool:
        """Текущее состояние: True, если отмечен."""
        return self._checkbox.isChecked()

    def set_enabled(self, enabled: bool) -> None:
        """Включить или отключить только интерактивность чекбокса (метка остаётся видимой)."""
        self._checkbox.setEnabled(enabled)

    def on_changed(self, callback: Callable[[bool], None]) -> None:
        """Подписка на смену состояния; в callback передаётся bool (отмечен / нет)."""
        # PySide6: stateChanged(int) и Qt.Checked = Qt.CheckState.Checked (enum) — прямое
        # сравнение int==enum даёт False. Читаем актуальное состояние через isChecked().
        self._checkbox.stateChanged.connect(lambda _state: callback(self._checkbox.isChecked()))

    def on_finished(self, callback: Callable[[bool], None]) -> None:
        """Заглушка контракта `IControlView`: для чекбокса запись идёт сразу в `on_changed`."""
        pass

    def show_error(self, message: str) -> None:
        """Показать предупреждение об ошибке записи в регистр (или валидации)."""
        QMessageBox.warning(self, "Ошибка валидации", message)
