# -*- coding: utf-8 -*-
"""
ComboView — QLabel + QComboBox с binding к строковому значению регистра.

Реализует контракт `IControlView[str]` для `ComboPresenter`.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from multiprocess_framework.modules.frontend_module.components.base.infrastructure.signal_utils import (
    block_signals,
)
from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QWidget,
    Signal,
)


class ComboView(QWidget):
    """Композитный виджет: QLabel + QComboBox в горизонтальном ряду."""

    # Эмитится при смене выбора пользователем; передаёт str.
    value_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Args:
            parent: Родительский Qt-виджет.
        """
        super().__init__(parent)
        self._label = QLabel()
        self._combo = QComboBox()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self._label)
        layout.addWidget(self._combo)
        # Эмит value_changed при смене выбора пользователем.
        self._combo.currentTextChanged.connect(lambda text: self.value_changed.emit(text))

    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        """Задать текст метки, подсказку и доступность редактирования."""
        self._label.setText(label)
        self._label.setToolTip(tooltip)
        self.set_enabled(enabled)

    def set_items(self, items: List[str]) -> None:
        """Установить список вариантов; сохраняет текущий выбор если он в новом списке."""
        current = self._combo.currentText()
        with block_signals(self._combo):
            self._combo.clear()
            self._combo.addItems(items)
        if current in items:
            with block_signals(self._combo):
                self._combo.setCurrentText(current)

    def set_value(self, value: str) -> None:
        """Установить выбранный item; эмитит currentTextChanged → value_changed."""
        self._combo.setCurrentText(str(value))

    def set_value_silent(self, value: str) -> None:
        """Установить выбор без эмита value_changed (синхронизация из модели)."""
        with block_signals(self._combo):
            self._combo.setCurrentText(str(value))

    def get_value(self) -> str:
        """Текущий выбранный текст."""
        return self._combo.currentText()

    def set_enabled(self, enabled: bool) -> None:
        """Включить или отключить только ComboBox (метка остаётся видимой)."""
        self._combo.setEnabled(enabled)

    def on_changed(self, callback: Callable[[str], None]) -> None:
        """Подписка на смену выбора; callback получает str."""
        self._combo.currentTextChanged.connect(callback)

    def on_finished(self, callback: Callable[[str], None]) -> None:
        """Заглушка контракта `IControlView`: для combo запись идёт сразу в `on_changed`."""
        pass

    def show_error(self, message: str) -> None:
        """Показать предупреждение об ошибке записи."""
        QMessageBox.warning(self, "Ошибка", message)
