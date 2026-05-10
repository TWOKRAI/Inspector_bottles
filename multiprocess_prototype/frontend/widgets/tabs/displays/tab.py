"""DisplaysTab — таб управления дисплеями.

Композиция: SlotSelector (пресеты) + ActionToolbar + CrudTable.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget

from multiprocess_prototype.frontend.widgets.primitives import (
    ActionToolbar,
    CrudTable,
    SlotSelector,
)

from .presenter import DisplaysPresenter, DISPLAY_PRESETS

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class DisplaysTab(QWidget):
    """Таб управления дисплеями.

    Пресеты раскладок + таблица слотов с привязкой к source процессам.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = DisplaysPresenter(ctx)
        self._source_combos: list[QComboBox] = []  # combo для привязки source

        self._init_ui()

    @classmethod
    def create(cls, ctx: "AppContext") -> "DisplaysTab":
        return cls(ctx)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Заголовок
        header = QLabel("Дисплеи")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # Пресеты (SlotSelector)
        preset_label = QLabel("Пресеты раскладки:")
        layout.addWidget(preset_label)

        preset_names = list(DISPLAY_PRESETS.keys())
        self._preset_selector = SlotSelector(count=len(preset_names))
        for i, name in enumerate(preset_names):
            self._preset_selector.set_slot_label(i, name)
        self._preset_selector.slot_selected.connect(self._on_preset_selected)
        layout.addWidget(self._preset_selector)

        # Тулбар
        self._toolbar = ActionToolbar(actions=[
            ("add_slot", "Добавить слот"),
            ("remove_slot", "Удалить"),
        ])
        self._toolbar.action_triggered.connect(self._on_toolbar_action)
        layout.addWidget(self._toolbar)

        # Таблица слотов
        self._table = CrudTable(columns=["Слот", "Источник", "Метка"])
        self._table.selection_changed.connect(self._on_table_selection)
        layout.addWidget(self._table, stretch=1)

    # ------------------------------------------------------------------ #
    #  Обработчики                                                         #
    # ------------------------------------------------------------------ #

    def _on_preset_selected(self, index: int) -> None:
        """Применить пресет раскладки."""
        preset_names = list(DISPLAY_PRESETS.keys())
        if 0 <= index < len(preset_names):
            preset_name = preset_names[index]
            self._presenter.apply_preset(preset_name)
            self._sync_table()

    def _on_toolbar_action(self, action_id: str) -> None:
        if action_id == "add_slot":
            self._presenter.add_slot()
            self._sync_table()
        elif action_id == "remove_slot":
            row = self._table.selected_row()
            if row >= 0:
                self._presenter.remove_slot(row)
                self._sync_table()

    def _on_table_selection(self, row: int) -> None:
        self._toolbar.set_enabled("remove_slot", row >= 0)

    def _sync_table(self) -> None:
        """Синхронизировать таблицу с presenter."""
        slots = self._presenter.slots
        rows = [[s["slot_id"], s["source"], s["label"]] for s in slots]
        self._table.set_data(rows)

        # Добавить combo для выбора source в каждую строку
        sources = self._presenter.get_available_sources()
        self._source_combos.clear()
        for i, slot in enumerate(slots):
            combo = QComboBox()
            combo.addItem("—")
            combo.addItems(sources)
            current_source = slot.get("source", "")
            if current_source and current_source in sources:
                combo.setCurrentText(current_source)
            combo.currentTextChanged.connect(
                lambda text, idx=i: self._on_source_changed(idx, text)
            )
            self._table.set_cell_widget(i, 1, combo)
            self._source_combos.append(combo)

    def _on_source_changed(self, index: int, source: str) -> None:
        """Обработать изменение привязки source."""
        if source == "—":
            source = ""
        self._presenter.set_slot_source(index, source)
