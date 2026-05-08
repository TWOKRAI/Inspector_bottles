"""RecipesTab — таб управления рецептами.

Композиция: SlotSelector(8) + InfoPanel + ActionToolbar(Load/Save/Delete).
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype_2.frontend.widgets.primitives import (
    ActionToolbar,
    SlotSelector,
)

from .presenter import RecipesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext


class RecipesTab(QWidget):
    """Таб рецептов — 8 слотов с Load/Save/Delete."""

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = RecipesPresenter(ctx)
        self._selected_slot: int = -1

        self._init_ui()
        self._sync_slots()

    @classmethod
    def create(cls, ctx: "AppContext") -> "RecipesTab":
        return cls(ctx)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Заголовок
        header = QLabel("Рецепты")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # Слот-селектор
        self._slot_selector = SlotSelector(count=8)
        self._slot_selector.slot_selected.connect(self._on_slot_selected)
        layout.addWidget(self._slot_selector)

        # Панель информации
        info_group = QGroupBox("Информация о рецепте")
        info_layout = QFormLayout(info_group)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Имя рецепта")
        info_layout.addRow("Имя:", self._name_edit)

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Описание")
        self._desc_edit.setMaximumHeight(80)
        info_layout.addRow("Описание:", self._desc_edit)

        self._created_label = QLabel("—")
        info_layout.addRow("Создан:", self._created_label)

        self._modified_label = QLabel("—")
        info_layout.addRow("Изменён:", self._modified_label)

        layout.addWidget(info_group)

        # Тулбар
        self._toolbar = ActionToolbar(actions=[
            ("load", "Загрузить"),
            ("save", "Сохранить"),
            ("delete", "Удалить"),
        ])
        self._toolbar.action_triggered.connect(self._on_action)
        layout.addWidget(self._toolbar)

        layout.addStretch()

    def _sync_slots(self) -> None:
        """Синхронизировать SlotSelector с данными presenter."""
        states = self._presenter.get_slot_states()
        labels = self._presenter.get_slot_labels()
        for i in range(8):
            self._slot_selector.set_slot_state(i, states[i])
            self._slot_selector.set_slot_label(i, labels[i])

    def _on_slot_selected(self, slot: int) -> None:
        """Обработать выбор слота."""
        self._selected_slot = slot
        info = self._presenter.get_recipe_info(slot)

        if info:
            self._name_edit.setText(info.name)
            self._desc_edit.setPlainText(info.description)
            self._created_label.setText(info.created or "—")
            self._modified_label.setText(info.modified or "—")
            self._toolbar.set_enabled("load", True)
            self._toolbar.set_enabled("delete", True)
        else:
            self._name_edit.setText("")
            self._desc_edit.setPlainText("")
            self._created_label.setText("—")
            self._modified_label.setText("—")
            self._toolbar.set_enabled("load", False)
            self._toolbar.set_enabled("delete", False)

    def _on_action(self, action_id: str) -> None:
        """Обработать действие тулбара."""
        if self._selected_slot < 0:
            return

        if action_id == "save":
            name = self._name_edit.text().strip() or f"Recipe {self._selected_slot}"
            desc = self._desc_edit.toPlainText().strip()
            self._presenter.save_to_slot(self._selected_slot, name, desc)
            self._sync_slots()
            self._on_slot_selected(self._selected_slot)

        elif action_id == "load":
            data = self._presenter.load_from_slot(self._selected_slot)
            if data:
                pass  # Phase 12: apply topology from recipe

        elif action_id == "delete":
            self._presenter.delete_from_slot(self._selected_slot)
            self._sync_slots()
            self._on_slot_selected(self._selected_slot)
