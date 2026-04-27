# multiprocess_prototype_v3/frontend/widgets/recipes_slot_buttons/panel.py
"""
RecipesSlotButtonsPanel — левая панель вкладки «Рецепты»:

- Вертикальный QListWidget с названиями слотов (стиль как в Настройках)
- Слот #0 — «Текущие параметры» (live registers)

Сигналы:
  slot_selected(int) — клик по слоту (visual switch, без apply)
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QWidget,
    Signal,
)

from .._navigation_panel_base import NavigationPanelBase


class RecipesSlotButtonsPanel(NavigationPanelBase):
    """Список слотов-рецептов (левая навигация)."""

    slot_selected = Signal(int)

    # Дополнительный стиль: выделенный элемент — синий фон, жирный шрифт
    _STYLE = (
        "QListWidget { font-size: 15px; }"
        "QListWidget::item { padding: 10px 12px; }"
        "QListWidget::item:selected { background-color: #d5e8fb; color: #000; font-weight: bold; }"
    )

    def __init__(
        self,
        *,
        slot_min: int = 0,
        slot_max: int = 21,
        label_provider: Callable[[int], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(width=200, parent=parent)
        self._slot_min = slot_min
        self._slot_max = slot_max
        self._label_provider = label_provider
        self._selected_slot: int | None = None
        self._applied_slot: int | None = None
        # Пользовательские имена слотов (slot_id → str)
        self._custom_names: dict[int, str] = {}

        # Применяем расширенный стиль поверх базового
        self._list.setStyleSheet(self._STYLE)

        self._rebuild()

    def _rebuild(self) -> None:
        """Очистить и построить список слотов заново."""
        self._clear_items()
        self._slot_id_by_row: dict[int, int] = {}
        self._row_by_slot_id: dict[int, int] = {}

        for row_idx, slot_id in enumerate(range(self._slot_min, self._slot_max + 1)):
            item = self._add_item(self._display_label(slot_id))
            item.setSizeHint(QSize(0, 40))
            self._slot_id_by_row[row_idx] = slot_id
            self._row_by_slot_id[slot_id] = row_idx

        if self._selected_slot is not None:
            self.set_selected_slot(self._selected_slot, emit=False)
        if self._applied_slot is not None:
            self.set_applied_slot(self._applied_slot)

    def _base_label(self, slot_id: int) -> str:
        """Базовое имя слота (без маркера applied)."""
        # Пользовательское имя
        custom = self._custom_names.get(slot_id)
        if custom:
            return custom
        # Provider
        if self._label_provider is not None:
            try:
                text = self._label_provider(slot_id)
                if text:
                    return text
            except Exception:  # noqa: BLE001
                pass
        if slot_id == 0:
            return "Текущие параметры"
        return f"Сорт #{slot_id}"

    def _display_label(self, slot_id: int) -> str:
        """Текст для отображения (с маркером applied)."""
        base = self._base_label(slot_id)
        if slot_id == self._applied_slot:
            return f"● {base}"
        return base

    def _on_row_changed(self, row: int) -> None:
        """Переопределение: маппинг row → slot_id → emit slot_selected."""
        slot_id = self._slot_id_by_row.get(row)
        if slot_id is None:
            return
        self._selected_slot = slot_id
        self.slot_selected.emit(slot_id)

    def set_selected_slot(self, slot_id: int, *, emit: bool = False) -> None:
        """Подсветить выбранный слот — без сигнала по умолчанию."""
        self._selected_slot = slot_id
        row = self._row_by_slot_id.get(slot_id)
        if row is not None:
            self._set_current_row(row, emit=emit)
        if emit:
            self.slot_selected.emit(slot_id)

    def set_applied_slot(self, slot_id: int | None) -> None:
        """Подсветить реально применённый слот (жирный шрифт + маркер ●)."""
        prev = self._applied_slot
        self._applied_slot = slot_id
        # Сбросить стиль у предыдущего
        if prev is not None:
            self._refresh_item(prev)
        # Применить стиль к новому
        if slot_id is not None:
            self._refresh_item(slot_id)

    def _refresh_item(self, slot_id: int) -> None:
        """Обновить текст и шрифт элемента списка."""
        row = self._row_by_slot_id.get(slot_id)
        if row is None:
            return
        item = self._list.item(row)
        if item is None:
            return
        is_applied = slot_id == self._applied_slot
        font = item.font()
        font.setBold(is_applied)
        item.setFont(font)
        item.setText(self._display_label(slot_id))

    def set_slot_name(self, slot_id: int, name: str) -> None:
        """Установить пользовательское имя слота (из QLineEdit «Название»)."""
        if name.strip():
            self._custom_names[slot_id] = name.strip()
        else:
            self._custom_names.pop(slot_id, None)
        self._refresh_item(slot_id)

    def get_slot_name(self, slot_id: int) -> str:
        """Получить текущее имя слота."""
        return self._base_label(slot_id)

    def selected_slot(self) -> int | None:
        return self._selected_slot

    def rebuild(self, slot_min: int, slot_max: int) -> None:
        self._slot_min = slot_min
        self._slot_max = slot_max
        self._rebuild()
