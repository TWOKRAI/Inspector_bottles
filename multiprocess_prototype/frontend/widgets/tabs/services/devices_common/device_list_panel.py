# -*- coding: utf-8 -*-
"""DeviceListPanel — вторая колонка (master) со списком устройств сервиса.

План device-tree-recipe, Фаза C. Список зарегистрированных устройств данного
``kind`` из активного рецепта (``RecipeDevicesStore.list(kind)`` — источник истины),
у каждого элемента имя + conn-индикатор (● connected / ○ disconnected / ✕ error из
``devices.state.<id>.conn`` через bindings). Последний элемент ВСЕГДА —
**«+ Добавить устройство»** (отдельная роль).

Динамика: подписка на ``devices.registry.*`` (после Фазы А дельты доходят до GUI)
→ debounce (QTimer ~200 мс) → ``refresh()`` с сохранением выбора. conn-индикаторы —
по дельтам ``devices.state.*.conn``.

Сигналы:
    device_selected(device_id) — выбран элемент-устройство.
    add_requested()            — выбран элемент «+ Добавить устройство».

Refs: plans/device-tree-recipe.md Фаза C
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

# Роли элементов списка (Qt.UserRole + N)
_ROLE_DEVICE_ID = int(Qt.ItemDataRole.UserRole) + 1
_ROLE_IS_ADD = int(Qt.ItemDataRole.UserRole) + 2

# Текстовые conn-индикаторы (без зависимости от иконок)
_CONN_GLYPH = {
    "connected": "●",
    "connecting": "◌",
    "disconnecting": "◌",
    "disconnected": "○",
    "error": "✕",
}

_DEBOUNCE_MS = 200


class DeviceListPanel(QWidget):
    """Список устройств одного ``kind`` + строка «+ Добавить устройство»."""

    device_selected = Signal(str)
    add_requested = Signal()

    def __init__(
        self,
        *,
        kind: str,
        recipe_store: Any,
        bindings: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._recipe_store = recipe_store
        self._bindings = bindings
        self._conn_states: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        self._title = QLabel("Устройства")
        self._title.setStyleSheet("font-weight: bold; padding: 2px;")
        root.addWidget(self._title)
        self._list = QListWidget()
        self._list.setMinimumWidth(180)
        root.addWidget(self._list, 1)

        self._list.itemClicked.connect(self._on_item_clicked)

        # Debounce refresh по штормам дельт реестра
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.refresh)

        # Подписки на StateStore (push). registry-дельта = триггер refresh
        # (перечитать рецепт); conn-дельта = обновить индикатор.
        if bindings is not None and hasattr(bindings, "bind_fanout"):
            bindings.bind_fanout("devices.registry.*", self._on_registry_delta, owner=self)
            bindings.bind_fanout("devices.state.*.conn", self._on_conn_delta, owner=self)

        self.refresh()

    # ------------------------------------------------------------------ #
    # Публичное API
    # ------------------------------------------------------------------ #

    def current_device_ids(self) -> list[str]:
        """ID устройств, сейчас показанных в списке (без строки «+ Добавить»)."""
        ids: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item.data(_ROLE_IS_ADD):
                dev_id = item.data(_ROLE_DEVICE_ID)
                if dev_id:
                    ids.append(str(dev_id))
        return ids

    def select_device(self, device_id: str) -> None:
        """Выбрать устройство по id (если присутствует)."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(_ROLE_DEVICE_ID) == device_id:
                self._list.setCurrentRow(i)
                return

    def refresh(self) -> None:
        """Перечитать список устройств из активного рецепта (выбор сохраняется)."""
        prev = self._selected_device_id()
        self._list.blockSignals(True)
        self._list.clear()
        for entry in self._recipe_store.list(kind=self._kind):
            dev_id = str(entry.get("id", ""))
            if not dev_id:
                continue
            item = QListWidgetItem(self._format_label(entry))
            item.setData(_ROLE_DEVICE_ID, dev_id)
            self._list.addItem(item)
        # Строка-действие «+ Добавить устройство» — всегда последняя
        add_item = QListWidgetItem("+ Добавить устройство")
        add_item.setData(_ROLE_IS_ADD, True)
        add_item.setForeground(Qt.GlobalColor.darkGreen)
        self._list.addItem(add_item)
        # Восстановить выбор
        if prev:
            self.select_device(prev)
        self._list.blockSignals(False)

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _selected_device_id(self) -> str | None:
        item = self._list.currentItem()
        if item is None or item.data(_ROLE_IS_ADD):
            return None
        dev_id = item.data(_ROLE_DEVICE_ID)
        return str(dev_id) if dev_id else None

    def _format_label(self, entry: dict) -> str:
        dev_id = str(entry.get("id", ""))
        name = entry.get("name") or dev_id
        conn = self._conn_states.get(dev_id, "disconnected")
        glyph = _CONN_GLYPH.get(conn, "○")
        return f"{glyph} {name}"

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(_ROLE_IS_ADD):
            self.add_requested.emit()
            return
        dev_id = item.data(_ROLE_DEVICE_ID)
        if dev_id:
            self.device_selected.emit(str(dev_id))

    def _on_registry_delta(self, _path: str, _value: Any) -> None:
        # Любое изменение реестра — перечитать рецепт с debounce (шторм дельт).
        self._debounce.start()

    def _on_conn_delta(self, path: str, value: Any) -> None:
        parts = path.split(".")
        if len(parts) < 4:
            return
        dev_id = parts[2]
        if isinstance(value, dict):
            conn = value.get("conn", "?")
        else:
            conn = value
        self._conn_states[dev_id] = str(conn)
        # Только перерисовать метки (без перечитывания рецепта)
        self._debounce.start()


__all__ = ["DeviceListPanel"]
