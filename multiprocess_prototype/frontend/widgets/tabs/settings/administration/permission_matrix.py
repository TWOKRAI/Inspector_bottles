# -*- coding: utf-8 -*-
"""PermissionMatrix — матрица прав для выбранной роли.

Строки = уникальные ресурсы из списка permissions роли.
Колонки: «Ресурс» | «View» | «Edit».

PR2: все чекбоксы disabled (режим только чтение).
PR4: поддержка editable-режима через параметр editable=True.

В editable-режиме:
  - Чекбоксы активны.
  - Coherence-инвариант: edit=True → view=True; view=False → edit=False.
  - _pending_permissions: set[str] — текущий набор разрешений.
  - Кнопка «Сохранить» испускает сигнал permissions_changed(role_name, old, new).
  - Кнопка «Сбросить» восстанавливает начальное состояние без испускания сигнала.
  - Системные роли (hidden_in_ui=True) всегда read-only, даже если editable=True.
"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class PermissionMatrix(QWidget):
    """Матрица permissions: строки = ресурсы, колонки = View / Edit.

    В режиме editable=False (по умолчанию) все чекбоксы disabled — read-only.
    В режиме editable=True чекбоксы активны, доступна кнопка «Сохранить».

    Системные роли (hidden_in_ui=True) всегда read-only, даже при editable=True.

    Сигналы:
        permissions_changed(role_name: str, old_perms: list[str], new_perms: list[str]):
            Испускается кнопкой «Сохранить», только если permissions изменились.

    Структура отображения:
      ┌──────────────────┬──────┬──────┐
      │ Ресурс           │ View │ Edit │
      ├──────────────────┼──────┼──────┤
      │ tabs.recipes     │  ✓   │  ✓   │
      │ tabs.pipeline    │  ✓   │      │
      │ ...              │      │      │
      └──────────────────┴──────┴──────┘
    """

    # Сигнал: (role_name, old_permissions, new_permissions)
    permissions_changed = Signal(str, list, list)

    # Индексы колонок
    _COL_RESOURCE = 0
    _COL_VIEW = 1
    _COL_EDIT = 2

    def __init__(self, parent: QWidget | None = None, *, editable: bool = False) -> None:
        super().__init__(parent)

        self._editable = editable
        self._role_name: str = ""
        self._initial_permissions: list[str] = []
        self._pending_permissions: set[str] = set()

        # _checkboxes: perm_string → QCheckBox (например, "tabs.recipes.view" → cb)
        self._checkboxes: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Ресурс", "View", "Edit"])

        # Колонка «Ресурс» растягивается, View/Edit — фиксированные
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self._COL_RESOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self._COL_VIEW, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._COL_EDIT, QHeaderView.ResizeMode.ResizeToContents)

        # Минимальная ширина колонок View/Edit
        self._table.setColumnWidth(self._COL_VIEW, 60)
        self._table.setColumnWidth(self._COL_EDIT, 60)

        # Скрыть вертикальные заголовки (номера строк)
        self._table.verticalHeader().setVisible(False)

        # Read-only: запретить редактирование и выделение через клики по ячейкам
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        layout.addWidget(self._table)

        # Кнопки «Сохранить» / «Сбросить» — размещаются в action-колонке
        # родительской панелью (RolesPanel), а не inline
        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setToolTip("Сохранить изменения прав роли")
        self._btn_reset = QPushButton("Сбросить")
        self._btn_reset.setToolTip("Сбросить изменения прав к исходному состоянию")
        self._btn_save.setEnabled(False)  # активируется когда есть изменения

        # Скрываем кнопки если не editable-режим
        self._btn_save.setVisible(editable)
        self._btn_reset.setVisible(editable)

        self._btn_save.clicked.connect(self._on_save_clicked)
        self._btn_reset.clicked.connect(self._on_reset_clicked)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_role(self, role_dict: dict) -> None:
        """Отобразить permissions роли в матрице.

        Если hidden_in_ui=True — чекбоксы всегда disabled (read-only),
        даже если конструктор был вызван с editable=True.

        Алгоритм:
          - Из permissions строк формата «ресурс.action» выделить ресурс
            (всё до последней точки) и action (последний сегмент).
          - Каждый уникальный ресурс — одна строка.
          - Колонки View/Edit — чекбоксы по наличию action «view»/«edit».
          - Строки отсортированы по алфавиту имени ресурса.
        """
        self._table.setRowCount(0)
        self._checkboxes.clear()

        self._role_name = role_dict.get("name", "")
        permissions: list[str] = role_dict.get("permissions", [])

        # Системные роли — всегда read-only
        is_hidden = role_dict.get("hidden_in_ui", False)
        effective_editable = self._editable and not is_hidden

        # Снимаем snapshot начальных permissions для сравнения и «Сбросить»
        self._initial_permissions = list(permissions)
        self._pending_permissions = set(permissions)

        # Группируем actions по ресурсам
        buckets: dict[str, set[str]] = defaultdict(set)
        for perm in permissions:
            if "." not in perm:
                continue
            resource, _, action = perm.rpartition(".")
            buckets[resource].add(action)

        # Заполняем строки таблицы (по алфавиту)
        for resource in sorted(buckets.keys()):
            actions = buckets[resource]
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Колонка «Ресурс» — текстовая ячейка
            resource_item = QTableWidgetItem(resource)
            resource_item.setFlags(resource_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, self._COL_RESOURCE, resource_item)

            # Колонки «View» и «Edit» — чекбоксы
            cb_view = self._make_checkbox_cell("view" in actions, enabled=effective_editable)
            cb_edit = self._make_checkbox_cell("edit" in actions, enabled=effective_editable)

            perm_view = f"{resource}.view"
            perm_edit = f"{resource}.edit"

            self._checkboxes[perm_view] = cb_view
            self._checkboxes[perm_edit] = cb_edit

            # Подключаем сигналы для coherence и отслеживания изменений
            # toggled вызывается при программной установке — coherence-рекурсия безопасна
            # (терминирует на 2-й итерации, т.к. setChecked(state) при том же state — no-op)
            cb_view.toggled.connect(lambda checked, p=perm_view: self._on_checkbox_toggled(p, checked))
            cb_edit.toggled.connect(lambda checked, p=perm_edit: self._on_checkbox_toggled(p, checked))

            container_view = self._wrap_checkbox(cb_view)
            container_edit = self._wrap_checkbox(cb_edit)

            self._table.setCellWidget(row, self._COL_VIEW, container_view)
            self._table.setCellWidget(row, self._COL_EDIT, container_edit)

        # Показать/скрыть кнопки в зависимости от effective_editable
        self._btn_save.setVisible(effective_editable)
        self._btn_reset.setVisible(effective_editable)
        self._btn_save.setEnabled(False)  # сбрасываем состояние кнопки

    def clear(self) -> None:
        """Очистить матрицу (убрать все строки)."""
        self._table.setRowCount(0)
        self._checkboxes.clear()
        self._role_name = ""
        self._initial_permissions = []
        self._pending_permissions = set()

    # ------------------------------------------------------------------
    # Слоты
    # ------------------------------------------------------------------

    def _on_checkbox_toggled(self, perm: str, checked: bool) -> None:
        """Обработчик переключения чекбокса: обновляет _pending и coherence."""
        # Обновляем pending_permissions
        if checked:
            self._pending_permissions.add(perm)
        else:
            self._pending_permissions.discard(perm)

        # Coherence-инвариант (выполняется до обновления кнопки Save)
        self._handle_coherence(perm, checked)

        # Обновляем состояние кнопки «Сохранить»
        self._update_save_button()

    def _on_save_clicked(self) -> None:
        """Испускает permissions_changed если есть изменения."""
        new_perms = sorted(self._pending_permissions)
        old_perms = sorted(self._initial_permissions)

        if new_perms == old_perms:
            return

        self.permissions_changed.emit(self._role_name, list(self._initial_permissions), new_perms)
        # После сохранения обновляем snapshot
        self._initial_permissions = list(new_perms)
        self._btn_save.setEnabled(False)

    def _on_reset_clicked(self) -> None:
        """Восстанавливает чекбоксы из _initial_permissions без испускания сигнала."""
        self._pending_permissions = set(self._initial_permissions)
        self._restore_checkboxes_from_pending()
        self._btn_save.setEnabled(False)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _handle_coherence(self, perm: str, checked: bool) -> None:
        """Enforced coherence-инвариант между edit и view.

        - edit=True  → view должен быть True (set view).
        - view=False → edit должен быть False (clear edit).
        """
        if perm.endswith(".edit") and checked:
            view_perm = perm[:-5] + ".view"  # заменяем ".edit" на ".view"
            cb = self._checkboxes.get(view_perm)
            if cb is not None and not cb.isChecked():
                # Блокируем рекурсию — toggled снова вызовет _on_checkbox_toggled,
                # но для .view с checked=True это безопасно (coherence не нужен).
                cb.setChecked(True)
        elif perm.endswith(".view") and not checked:
            edit_perm = perm[:-5] + ".edit"  # заменяем ".view" на ".edit"
            cb = self._checkboxes.get(edit_perm)
            if cb is not None and cb.isChecked():
                cb.setChecked(False)

    def _update_save_button(self) -> None:
        """Активирует/деактивирует кнопку «Сохранить» по наличию изменений."""
        has_changes = sorted(self._pending_permissions) != sorted(self._initial_permissions)
        self._btn_save.setEnabled(has_changes)

    def _restore_checkboxes_from_pending(self) -> None:
        """Синхронизировать состояние чекбоксов с _pending_permissions."""
        for perm, cb in self._checkboxes.items():
            cb.setChecked(perm in self._pending_permissions)

    @staticmethod
    def _make_checkbox_cell(checked: bool, *, enabled: bool) -> QCheckBox:
        """Создать QCheckBox с заданным состоянием и режимом редактирования."""
        checkbox = QCheckBox()
        checkbox.setChecked(checked)
        checkbox.setEnabled(enabled)
        return checkbox

    @staticmethod
    def _wrap_checkbox(cb: QCheckBox) -> QWidget:
        """Обернуть QCheckBox в центрированный контейнер (паттерн для setCellWidget)."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(cb)
        return container
