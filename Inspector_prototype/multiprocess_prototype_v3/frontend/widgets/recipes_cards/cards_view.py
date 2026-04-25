# multiprocess_prototype_v3/frontend/widgets/recipes_cards/cards_view.py
"""Карточное представление слотов рецептов: сетка с кнопками Загрузить / Сохранить."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QGridLayout,
    QGroupBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    Signal,
)

_COLS = 4  # фиксированное число колонок в сетке

_STYLE_ACTIVE = (
    "QGroupBox { border: 2px solid #2e86de; border-radius: 4px; "
    "margin-top: 10px; font-weight: bold; } "
    "QGroupBox::title { color: #2e86de; }"
)
_STYLE_NORMAL = ""


class RecipesCardsView(QWidget):
    """Сетка карточек рецептов с кнопками load / save для каждого слота."""

    load_requested = Signal(int)
    save_requested = Signal(int)

    def __init__(
        self,
        *,
        slot_min: int = 0,
        slot_max: int = 21,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._slot_min = slot_min
        self._slot_max = slot_max
        self._cards_by_slot: dict[int, QGroupBox] = {}
        self._active_slot: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._grid_layout = QGridLayout(self._inner)
        self._scroll.setWidget(self._inner)
        layout.addWidget(self._scroll)

        self.rebuild_cards(slot_min, slot_max)

    def rebuild_cards(self, slot_min: int, slot_max: int) -> None:
        """Очистить грид и создать карточки для каждого слота."""
        self._slot_min = slot_min
        self._slot_max = slot_max
        # Очистить старые виджеты
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards_by_slot.clear()

        for i, slot_id in enumerate(range(slot_min, slot_max + 1)):
            row = i // _COLS
            col = i % _COLS
            card = self._build_card(slot_id)
            self._grid_layout.addWidget(card, row, col)
            self._cards_by_slot[slot_id] = card

        # Восстановить подсветку активного слота если он входит в диапазон
        if self._active_slot is not None:
            self.set_active_slot(self._active_slot)

    def set_active_slot(self, slot_id: int | None) -> None:
        """Подсветить карточку активного слота (рамка + bold заголовок)."""
        # Сброс предыдущего
        prev = self._active_slot
        if prev is not None and prev in self._cards_by_slot:
            self._cards_by_slot[prev].setStyleSheet(_STYLE_NORMAL)
        self._active_slot = slot_id
        if slot_id is not None and slot_id in self._cards_by_slot:
            self._cards_by_slot[slot_id].setStyleSheet(_STYLE_ACTIVE)

    def _build_card(self, slot_id: int) -> QGroupBox:
        """Одна карточка: QGroupBox с кнопками Загрузить / Сохранить."""
        box = QGroupBox(f"Рецепт #{slot_id}")
        v = QVBoxLayout(box)

        btn_load = QPushButton("Загрузить")
        sid = slot_id  # замкнуть
        btn_load.clicked.connect(lambda _, s=sid: self.load_requested.emit(s))
        v.addWidget(btn_load)

        btn_save = QPushButton("Сохранить")
        btn_save.clicked.connect(lambda _, s=sid: self.save_requested.emit(s))
        v.addWidget(btn_save)

        return box
