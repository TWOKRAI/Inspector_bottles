# -*- coding: utf-8 -*-
"""RecipeFormWidget --- карточная форма одного рецепта.

Извлечено из RecipesTab для уменьшения LOC tab.py.
Используется BaseListNavTab._create_item_widget.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
)


class RecipeFormWidget(QGroupBox):
    """Карточная форма одного рецепта (Cards-режим)."""

    def __init__(self) -> None:
        super().__init__("Информация о рецепте")
        form = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Имя рецепта")
        form.addRow("Имя:", self.name_edit)

        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setPlaceholderText("Описание")
        self.desc_edit.setMaximumHeight(80)
        form.addRow("Описание:", self.desc_edit)

        self.created_label = QLabel("—")
        form.addRow("Создан:", self.created_label)

        self.modified_label = QLabel("—")
        form.addRow("Изменён:", self.modified_label)

    def populate(self, name: str, desc: str, created: str, modified: str) -> None:
        """Заполнить форму данными рецепта."""
        self.name_edit.setText(name)
        self.desc_edit.setPlainText(desc)
        self.created_label.setText(created or "—")
        self.modified_label.setText(modified or "—")

    def clear(self) -> None:
        """Очистить форму."""
        self.populate("", "", "—", "—")
