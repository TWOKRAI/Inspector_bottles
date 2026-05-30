# -*- coding: utf-8 -*-
"""Диалоги вкладки «Процессы»: создание процесса и создание воркера.

Оба — простые модальные QDialog, возвращающие dict параметров через ``result_data()``
после accept(). GUI работает с dict (не SchemaBase).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from ..data import WORKER_EXECUTION_MODES, WORKER_PRIORITIES

# Категории процесса для выбора при создании.
_CATEGORIES: list[tuple[str, str]] = [
    ("utility", "Утилиты"),
    ("source", "Источники"),
    ("processing", "Обработка"),
    ("rendering", "Рендеринг"),
    ("output", "Вывод"),
    ("control", "Управление"),
    ("service", "Сервисы"),
]


class CreateProcessDialog(QDialog):
    """Диалог создания процесса: имя + категория."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создать процесс")
        self.setModal(True)

        form = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("имя_процесса")
        form.addRow("Имя:", self._name_edit)

        self._category_combo = QComboBox()
        for key, title in _CATEGORIES:
            self._category_combo.addItem(title, key)
        form.addRow("Категория:", self._category_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)

    def _on_accept(self) -> None:
        if self._name_edit.text().strip():
            self.accept()

    def result_data(self) -> dict[str, Any]:
        """Параметры создания (валидны после accept)."""
        return {
            "name": self._name_edit.text().strip(),
            "category": self._category_combo.currentData(),
        }


class CreateWorkerDialog(QDialog):
    """Диалог создания воркера: имя + приоритет + режим + интервал."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создать воркер")
        self.setModal(True)

        form = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("имя_воркера")
        form.addRow("Имя:", self._name_edit)

        self._priority_combo = QComboBox()
        self._priority_combo.addItems(WORKER_PRIORITIES)
        self._priority_combo.setCurrentText("NORMAL")
        form.addRow("Приоритет:", self._priority_combo)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(WORKER_EXECUTION_MODES)
        form.addRow("Режим:", self._mode_combo)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(0, 600_000)
        self._interval_spin.setSpecialValueText("—")
        self._interval_spin.setSuffix(" мс")
        form.addRow("Интервал цикла:", self._interval_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        if self._name_edit.text().strip():
            self.accept()

    def result_data(self) -> dict[str, Any]:
        """Параметры создания воркера (валидны после accept)."""
        interval = self._interval_spin.value()
        return {
            "worker_name": self._name_edit.text().strip(),
            "priority": self._priority_combo.currentText(),
            "execution_mode": self._mode_combo.currentText(),
            "target_interval_ms": interval if interval > 0 else None,
        }
