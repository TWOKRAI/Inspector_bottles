# -*- coding: utf-8 -*-
"""RecipeFormWidget — форма метаданных рецепта v2.

Отображает поля рецепта: имя, описание, версию, даты создания/изменения,
сводку blueprint (процессы, плагины, сервисы, дисплеи).

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.7
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class RecipeFormWidget(QGroupBox):
    """Форма метаданных рецепта v2 (blueprint-based).

    Поля:
        name_edit      — QLineEdit, редактируемое.
        desc_edit      — QTextEdit, редактируемое.
        version_label  — QLabel, read-only.
        created_label  — QLabel, read-only.
        modified_label — QLabel, read-only.
        summary_label  — QLabel, сводка blueprint.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Инициализировать форму рецепта."""
        super().__init__("Информация о рецепте", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        """Построить UI формы."""
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        # Редактируемые поля
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Имя рецепта")
        form.addRow("Имя:", self.name_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Описание")
        self.desc_edit.setMaximumHeight(80)
        form.addRow("Описание:", self.desc_edit)

        # Read-only поля
        self.version_label = QLabel("—")
        form.addRow("Версия:", self.version_label)

        self.created_label = QLabel("—")
        form.addRow("Создан:", self.created_label)

        self.modified_label = QLabel("—")
        form.addRow("Изменён:", self.modified_label)

        # Сводка blueprint
        self.summary_label = QLabel("—")
        self.summary_label.setWordWrap(True)
        form.addRow("Blueprint:", self.summary_label)

        vbox.addLayout(form)
        vbox.addStretch(1)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def populate(self, slug: str, data: dict | None) -> None:
        """Заполнить форму данными рецепта.

        Args:
            slug: slug рецепта (имя файла без .yaml).
            data: dict с YAML-данными рецепта v2 или None для сброса.
        """
        if data is None:
            self.clear()
            return

        self.name_edit.setText(data.get("name", slug))
        self.desc_edit.setText(data.get("description", ""))
        self.version_label.setText(str(data.get("version", "—")))
        self.created_label.setText(str(data.get("created", "—")))
        self.modified_label.setText(str(data.get("modified", "—")))

        # Сводка blueprint: подсчёт компонентов
        blueprint = data.get("blueprint", {}) or {}
        processes = blueprint.get("processes", [])

        # Подсчёт плагинов из всех процессов
        plugins_count = 0
        for proc in processes:
            plugins_count += len(proc.get("plugins", []) if isinstance(proc, dict) else [])

        # Сервисы и дисплеи — из application-секций рецепта
        services_count = len(data.get("active_services", []) or [])
        displays_count = len(data.get("display_bindings", []) or [])

        summary = (
            f"Процессы: {len(processes)} | "
            f"Плагины: {plugins_count} | "
            f"Сервисы: {services_count} | "
            f"Дисплеи: {displays_count}"
        )
        self.summary_label.setText(summary)

    def clear(self) -> None:
        """Очистить все поля формы."""
        self.name_edit.clear()
        self.desc_edit.clear()
        self.version_label.setText("—")
        self.created_label.setText("—")
        self.modified_label.setText("—")
        self.summary_label.setText("—")

    def get_form_data(self) -> dict:
        """Вернуть редактируемые поля формы.

        Returns:
            dict с ключами 'name' и 'description'.
        """
        return {
            "name": self.name_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
        }
