"""RecipeSlotComboModel — чистая Python-модель списка слотов рецептов (Phase 1, Task 1.1).

Используется `RecipePanelBase` для наполнения `QComboBox` — знает список доступных slot-id,
их читаемые метки и текущий индекс. Без PyQt-зависимостей: view (Qt) связывается с моделью
через тонкий адаптер в `_recipe_panel_base.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


def _default_label(slot_id: str) -> str:
    return f"Слот {slot_id}"


@dataclass
class RecipeSlotComboModel:
    """Список слотов + текущий выбранный индекс + конвертеры index ↔ slot_id.

    Attributes:
        slots: упорядоченный список идентификаторов слотов (строки).
        current_index: 0-based combo-индекс текущего выбора; 0 если список пуст или вне границ.
        label_fn: функция форматирования метки для combo-ячейки (по умолчанию — "Слот {id}").
    """

    slots: list[str] = field(default_factory=list)
    current_index: int = 0
    label_fn: Callable[[str], str] | None = None

    # ---- Factory --------------------------------------------------------

    @classmethod
    def from_manager(
        cls,
        recipe_manager: Any,
        index_min: int,
        index_max: int,
        label_fn: Callable[[str], str] | None = None,
    ) -> RecipeSlotComboModel:
        """Построить модель из `RecipeManager` или сгенерировать диапазон индексов.

        Если у `recipe_manager` есть метод `list_slots()` и результат непустой — использует его.
        Иначе генерирует `[str(i) for i in range(index_min, index_max + 1)]`.
        """
        slots: list[str] = []
        if recipe_manager is not None and hasattr(recipe_manager, "list_slots"):
            try:
                found = recipe_manager.list_slots()
            except Exception:
                found = None
            if isinstance(found, list) and found:
                slots = [str(s) for s in found]
        if not slots:
            lo, hi = min(index_min, index_max), max(index_min, index_max)
            slots = [str(i) for i in range(lo, hi + 1)]
        return cls(slots=slots, current_index=0, label_fn=label_fn)

    # ---- Queries --------------------------------------------------------

    @property
    def labels(self) -> list[str]:
        fn = self.label_fn or _default_label
        return [fn(s) for s in self.slots]

    def is_empty(self) -> bool:
        return not self.slots

    def slot_id_for_index(self, combo_idx: int) -> str:
        """Slot-id по combo-индексу; fallback — `slots[0]` или пустая строка."""
        if not self.slots:
            return ""
        if 0 <= combo_idx < len(self.slots):
            return self.slots[combo_idx]
        return self.slots[0]

    def index_for_slot_id(self, slot_id: str) -> int:
        """Combo-индекс по slot-id; fallback — 0 при отсутствии."""
        try:
            return self.slots.index(str(slot_id))
        except ValueError:
            return 0

    def current_slot_id(self) -> str:
        return self.slot_id_for_index(self.current_index)


__all__ = ["RecipeSlotComboModel"]
