# -*- coding: utf-8 -*-
"""DeviceComboController — выпадающий список устройств + кнопки управления.

Наполнение комбо: подписка через ``bind_fanout("devices.registry.*", cb)``
для push-обновлений из StateStore. Если bindings недоступен — fallback:
обновление по кнопке/при показе секции через ``device_list`` запрос.

Отображает: ``name (id)`` + индикатор conn (цвет/текст из
``devices.state.<id>.conn``).
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .presenter import DevicesPresenter

logger = logging.getLogger(__name__)


class DeviceComboController:
    """Выпадающий список устройств определённого kind + кнопки CRUD/connect.

    Виджет ``widget()`` содержит QComboBox + ряд кнопок. Контроллер
    наполняет комбо через bind_fanout (push) или device_list (pull).

    Args:
        kind: фильтр по виду устройства (``robot``, ``vfd``, ``hikvision``).
        presenter: DevicesPresenter для CRUD/connect.
        bindings: GuiStateBindings | None — реактивные подписки на StateStore.
        on_device_changed: callback(device_id | None) при смене выбора в комбо.
        on_add_clicked: callback() при нажатии «Добавить» (открыть диалог).
        on_edit_clicked: callback(device_id) при нажатии «Изменить».
        show_crud: True — показать кнопки Добавить/Изменить/Удалить.
    """

    def __init__(
        self,
        *,
        kind: str,
        presenter: DevicesPresenter,
        bindings: Any = None,
        on_device_changed: Any = None,
        on_add_clicked: Any = None,
        on_edit_clicked: Any = None,
        show_crud: bool = True,
    ) -> None:
        self._kind = kind
        self._presenter = presenter
        self._bindings = bindings
        self._on_device_changed = on_device_changed
        self._on_add_clicked = on_add_clicked
        self._on_edit_clicked = on_edit_clicked

        # Локальный кэш реестра {device_id: entry_dict}
        self._registry: dict[str, dict] = {}
        # Подписки на conn-состояние {device_id: BindingHandle}
        self._conn_handles: dict[str, Any] = {}
        # Текущие conn-статусы {device_id: str}
        self._conn_states: dict[str, str] = {}

        # Строим виджет
        self._widget = QWidget()
        root = QVBoxLayout(self._widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        root.addWidget(self._combo)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._btn_connect = QPushButton("Подключить")
        self._btn_disconnect = QPushButton("Отключить")
        row.addWidget(self._btn_connect)
        row.addWidget(self._btn_disconnect)

        if show_crud:
            self._btn_add = QPushButton("Добавить")
            self._btn_edit = QPushButton("Изменить")
            self._btn_remove = QPushButton("Удалить")
            row.addWidget(self._btn_add)
            row.addWidget(self._btn_edit)
            row.addWidget(self._btn_remove)
            self._btn_add.clicked.connect(self._on_add)
            self._btn_edit.clicked.connect(self._on_edit)
            self._btn_remove.clicked.connect(self._on_remove)
        else:
            self._btn_add = None
            self._btn_edit = None
            self._btn_remove = None

        row.addStretch(1)
        root.addLayout(row)

        # Проводка
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)

        # Подписка на реестр через bind_fanout (push)
        if self._bindings is not None and hasattr(self._bindings, "bind_fanout"):
            self._bindings.bind_fanout(
                "devices.registry.*",
                self._on_registry_delta,
                owner=self._widget,
            )
        # Также подписка на conn-состояние
        if self._bindings is not None and hasattr(self._bindings, "bind_fanout"):
            self._bindings.bind_fanout(
                "devices.state.*.conn",
                self._on_conn_delta,
                owner=self._widget,
            )

    def widget(self) -> QWidget:
        """Виджет с комбо и кнопками."""
        return self._widget

    def current_device_id(self) -> str | None:
        """ID выбранного устройства (userData комбо)."""
        return self._combo.currentData()

    def refresh(self) -> None:
        """Явный pull-запрос списка устройств (fallback при отсутствии bindings)."""
        self._presenter.device_list(self._on_device_list, kind=self._kind)

    # ------------------------------------------------------------------ #
    # Push-подписки (bindings)
    # ------------------------------------------------------------------ #

    def _on_registry_delta(self, path: str, value: Any) -> None:
        """Callback от bind_fanout("devices.registry.*"): устройство в реестре."""
        # path = "devices.registry.<id>", value = entry dict
        if not isinstance(value, dict):
            return
        dev_id = value.get("id") or ""
        if not dev_id:
            # Извлекаем id из пути
            parts = path.split(".")
            if len(parts) >= 3:
                dev_id = parts[2]
        if not dev_id:
            return
        # Фильтр по kind
        if value.get("kind") != self._kind:
            # Если устройство другого kind — убрать из кэша если было
            if dev_id in self._registry:
                del self._registry[dev_id]
                self._rebuild_combo()
            return
        self._registry[dev_id] = value
        self._rebuild_combo()

    def _on_conn_delta(self, path: str, value: Any) -> None:
        """Callback от bind_fanout("devices.state.*.conn"): conn-статус."""
        # path = "devices.state.<id>.conn", value = {"conn": "connected"|...} or str
        parts = path.split(".")
        if len(parts) < 4:
            return
        dev_id = parts[2]
        if dev_id not in self._registry:
            return
        if isinstance(value, dict):
            conn = value.get("conn", "?")
        elif isinstance(value, str):
            conn = value
        else:
            conn = str(value)
        self._conn_states[dev_id] = str(conn)
        self._rebuild_combo()

    # ------------------------------------------------------------------ #
    # Pull-запрос (fallback)
    # ------------------------------------------------------------------ #

    def _on_device_list(self, devices: list[dict]) -> None:
        """Обработчик ответа device_list."""
        self._registry.clear()
        for d in devices:
            dev_id = d.get("id", "")
            if dev_id:
                self._registry[dev_id] = d
        self._rebuild_combo()

    # ------------------------------------------------------------------ #
    # Перестройка комбо
    # ------------------------------------------------------------------ #

    def _rebuild_combo(self) -> None:
        """Перестроить содержимое QComboBox из кэша реестра."""
        prev = self._combo.currentData()
        self._combo.blockSignals(True)
        self._combo.clear()
        for dev_id, entry in sorted(self._registry.items()):
            name = entry.get("name", dev_id)
            conn = self._conn_states.get(dev_id, "?")
            label = f"{name} ({dev_id}) [{conn}]"
            self._combo.addItem(label, dev_id)
        # Восстановить выбор
        if prev:
            idx = self._combo.findData(prev)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)
        # Сигнализировать об изменении выбора если изменился
        new = self._combo.currentData()
        if new != prev and self._on_device_changed:
            self._on_device_changed(new)

    # ------------------------------------------------------------------ #
    # Кнопки
    # ------------------------------------------------------------------ #

    def _on_connect(self) -> None:
        dev_id = self.current_device_id()
        if dev_id:
            self._presenter.device_connect(dev_id)

    def _on_disconnect(self) -> None:
        dev_id = self.current_device_id()
        if dev_id:
            self._presenter.device_disconnect(dev_id)

    def _on_add(self) -> None:
        if self._on_add_clicked:
            self._on_add_clicked()

    def _on_edit(self) -> None:
        dev_id = self.current_device_id()
        if dev_id and self._on_edit_clicked:
            self._on_edit_clicked(dev_id)

    def _on_remove(self) -> None:
        dev_id = self.current_device_id()
        if dev_id:
            self._presenter.device_remove(dev_id)

    def _on_combo_changed(self, _index: int) -> None:
        if self._on_device_changed:
            self._on_device_changed(self.current_device_id())
