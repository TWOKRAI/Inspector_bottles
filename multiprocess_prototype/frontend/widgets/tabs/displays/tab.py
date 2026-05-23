# -*- coding: utf-8 -*-
"""DisplaysTab — таб управления дисплеями.

Шаблон визуально и архитектурно идентичен Recipes:
``BaseListNavTab`` + ``DiffScrollTabLayout``. 3 колонки + мастер-скролл.

- **Колонка 1 (action_width=160):** кнопки управления слотами выбранного
  пресета — «Добавить слот», «Удалить»; Undo/Redo в статичной зоне.
- **Колонка 2 (nav_width=230):** список пресетов раскладки
  (none / 1×1 / 1+1 / 2×2) — выбор переключает таблицу.
- **Колонка 3 (content):** ``CrudTable`` со слотами активного пресета +
  combo-box для привязки source-процесса к каждому слоту.

Пресеты — это не «глобальные» actions, а единицы навигации (как рецепты),
поэтому остаются в nav-колонке, не в action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.frontend.widgets.primitives import CrudTable
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .presenter import DISPLAY_PRESETS, DisplaysPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


def _layout_factory() -> DiffScrollTabLayout:
    # Размеры колонок согласованы с Recipes/Processes/Services/Plugins.
    return DiffScrollTabLayout(title="Дисплеи", action_width=160, nav_width=230)


class DisplaysTab(BaseListNavTab):
    """Таб «Дисплеи» — BaseListNavTab + DiffScrollTabLayout (как Recipes).

    Пресеты в nav-колонке, действия в action-колонке, таблица слотов в content.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        self._presenter = DisplaysPresenter(ctx)
        self._source_combos: list[QComboBox] = []
        # Текущий выбранный пресет (ключ из DISPLAY_PRESETS).
        self._selected_preset: str = ""

        # Таблица создаётся один раз и переиспользуется для всех пресетов.
        self._table: CrudTable | None = None

        super().__init__(
            title="Дисплеи",
            ctx=ctx,
            layout_factory=_layout_factory,
            parent=parent,
        )

        # Авто-refresh content scroll при смене активного пресета.
        self._tab_layout.connect_stack(self._content_stack, "content")

        self._setup_actions()
        self._sync_nav()

    @classmethod
    def create(cls, ctx: "AppContext") -> "DisplaysTab":
        """Фабричный метод для TabFactory."""
        return cls(ctx)

    # ------------------------------------------------------------------ #
    #  BaseListNavTab hooks                                                #
    # ------------------------------------------------------------------ #

    def _create_item_widget(self, key: str) -> QWidget:
        """Все пресеты используют одну общую CrudTable.

        BaseListNavTab требует уникальный виджет на ключ — но логически
        таблица одна. Решение: на первый вызов создаём таблицу-singleton,
        на остальные — возвращаем пустые QWidget-страницы, а при смене
        пресета программно переключаем стек на страницу с таблицей.
        """
        if self._table is None:
            self._table = CrudTable(columns=["Слот", "Источник", "Метка"])
            self._table.selection_changed.connect(self._on_table_selection)
            return self._table
        # Для последующих пресетов — пустая страница (на ней мы НЕ переключаемся).
        return QWidget()

    def _on_nav_changed(self, key: str) -> None:
        """Смена пресета в nav: применить пресет и обновить таблицу."""
        # ВАЖНО: не вызываем super()._on_nav_changed — мы сами управляем стеком,
        # таблица одна на все пресеты, переключения страниц не нужно.
        self._selected_preset = key
        self.item_selected.emit(key)
        self.section_changed.emit(key)
        if not self._can_edit():
            return
        self._presenter.apply_preset(key)
        self._sync_table()

    # ------------------------------------------------------------------ #
    #  Action column                                                       #
    # ------------------------------------------------------------------ #

    def _setup_actions(self) -> None:
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        lay = self._tab_layout
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        self._btn_add = QPushButton("Добавить слот")
        self._btn_add.clicked.connect(lambda: self._on_toolbar_action("add_slot"))
        action_layout.addWidget(self._btn_add)

        self._btn_remove = QPushButton("Удалить")
        self._btn_remove.setEnabled(False)
        self._btn_remove.clicked.connect(lambda: self._on_toolbar_action("remove_slot"))
        action_layout.addWidget(self._btn_remove)

        action_layout.addStretch(1)
        lay.set_action_widget(action_widget)

        # Undo/Redo в статичной зоне.
        bus = self._ctx.action_bus() if hasattr(self._ctx, "action_bus") else None
        lay.enable_undo_redo(bus)

        # Permission gating.
        _auth = getattr(self._ctx, "auth", None)
        auth_state = getattr(_auth, "state", None) if _auth is not None else None
        for btn in (self._btn_add, self._btn_remove):
            install_permission_aware_enable(btn, "tabs.displays.edit", auth_state)

    # ------------------------------------------------------------------ #
    #  Nav populate                                                        #
    # ------------------------------------------------------------------ #

    def _sync_nav(self) -> None:
        """Заполнить навигацию списком пресетов."""
        assert self._nav_widget is not None
        self._nav_widget.blockSignals(True)
        self._nav_widget.clear()
        while self._content_stack.count() > 0:
            w = self._content_stack.widget(0)
            self._content_stack.removeWidget(w)
            if w is not None and w is not self._table:
                w.deleteLater()
        self._key_to_item.clear()
        self._key_to_index.clear()
        self._nav_widget.blockSignals(False)

        for preset_name in DISPLAY_PRESETS.keys():
            self.add_item(preset_name, preset_name)

        # Дефолтная выборка — первый пресет (none → пустая таблица).
        first = next(iter(DISPLAY_PRESETS.keys()), None)
        if first is not None:
            self.select_item(first)

    # ------------------------------------------------------------------ #
    #  Permissions                                                         #
    # ------------------------------------------------------------------ #

    def _can_edit(self) -> bool:
        """Имеет ли текущий пользователь право мутаций в displays."""
        _auth = getattr(self._ctx, "auth", None)
        auth_state = getattr(_auth, "state", None) if _auth is not None else None
        if auth_state is None:
            return True
        return auth_state.access_context.has_permission("tabs.displays.edit")

    # ------------------------------------------------------------------ #
    #  Action handlers                                                     #
    # ------------------------------------------------------------------ #

    def _on_toolbar_action(self, action_id: str) -> None:
        if not self._can_edit():
            return
        if action_id == "add_slot":
            self._presenter.add_slot()
            self._sync_table()
        elif action_id == "remove_slot":
            if self._table is None:
                return
            row = self._table.selected_row()
            if row >= 0:
                self._presenter.remove_slot(row)
                self._sync_table()

    # Сохранён для backward-compat (тесты использовали _on_preset_selected(index)).
    def _on_preset_selected(self, index: int) -> None:
        """Применить пресет по индексу (legacy API для тестов)."""
        preset_names = list(DISPLAY_PRESETS.keys())
        if 0 <= index < len(preset_names):
            self.select_item(preset_names[index])

    def _on_table_selection(self, row: int) -> None:
        self._btn_remove.setEnabled(row >= 0)

    def _sync_table(self) -> None:
        """Синхронизировать таблицу с presenter."""
        if self._table is None:
            return
        slots = self._presenter.slots
        rows = [[s["slot_id"], s["source"], s["label"]] for s in slots]
        self._table.set_data(rows)

        # Combo для выбора source в каждой строке.
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
                lambda text, idx=i: self._on_source_changed(idx, text),
            )
            self._table.set_cell_widget(i, 1, combo)
            self._source_combos.append(combo)

    def _on_source_changed(self, index: int, source: str) -> None:
        """Обработать изменение привязки source."""
        if source == "—":
            source = ""
        self._presenter.set_slot_source(index, source)
