# -*- coding: utf-8 -*-
"""DeviceMasterDetail + DeviceDetailPage — master-detail устройств сервиса.

План device-tree-recipe, Фаза C. Страница сервиса = слева список устройств
(:class:`DeviceListPanel`), справа QStackedWidget со страницами:
  - заглушка («выберите устройство» / «активируйте рецепт»);
  - страницы устройств (lazy, по device_id) — :class:`DeviceDetailPage`,
    оборачивающая существующие контролы (робот: телеметрия/CVT/рисование;
    ПЧ: пуск/частота/статус) шапкой с conn-индикатором и кнопками
    Подключить/Отключить/Изменить/Удалить;
  - страница добавления (Фаза D, опционально через ``add_page_factory``).

Выбор в списке переключает стек; «+ Добавить» открывает страницу добавления.

Refs: plans/device-tree-recipe.md Фаза C
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .device_list_panel import DeviceListPanel

_CONN_TEXT = {
    "connected": "● подключено",
    "connecting": "◌ подключение…",
    "disconnected": "○ отключено",
    "error": "✕ ошибка",
}


class DeviceDetailPage(QWidget):
    """Страница одного устройства: шапка (имя, conn, кнопки) + контролы.

    Args:
        device_id:      id устройства (для команд connect/disconnect/edit/remove).
        name:           человекочитаемое имя для заголовка.
        inner_widget:   виджет существующих контролов устройства (робот/ПЧ/камера).
        devices_presenter: DevicesPresenter — device_connect/device_disconnect.
        on_edit:        callback(device_id) — «Изменить» (reuse DeviceCrudActions).
        on_remove:      callback(device_id) — «Удалить» (reuse DeviceCrudActions).
        bindings:       GuiStateBindings — для conn-индикатора (lazy).
    """

    def __init__(
        self,
        *,
        device_id: str,
        name: str,
        inner_widget: QWidget,
        devices_presenter: Any,
        on_edit: Callable[[str], None] | None = None,
        on_remove: Callable[[str], None] | None = None,
        bindings: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_id = device_id
        self._presenter = devices_presenter
        self._on_edit = on_edit
        self._on_remove = on_remove

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # Шапка: имя + conn + кнопки
        header = QHBoxLayout()
        self._name_label = QLabel(f"<b>{name}</b>  <span style='color:gray'>({device_id})</span>")
        header.addWidget(self._name_label)
        self._conn_label = QLabel(_CONN_TEXT["disconnected"])
        header.addWidget(self._conn_label)
        header.addStretch(1)

        self._btn_connect = QPushButton("Подключить")
        self._btn_disconnect = QPushButton("Отключить")
        self._btn_edit = QPushButton("Изменить")
        self._btn_remove = QPushButton("Удалить")
        for btn in (self._btn_connect, self._btn_disconnect, self._btn_edit, self._btn_remove):
            header.addWidget(btn)
        root.addLayout(header)

        root.addWidget(inner_widget, 1)

        # Проводка кнопок
        self._btn_connect.clicked.connect(lambda: self._presenter.device_connect(self._device_id))
        self._btn_disconnect.clicked.connect(lambda: self._presenter.device_disconnect(self._device_id))
        self._btn_edit.clicked.connect(self._handle_edit)
        self._btn_remove.clicked.connect(self._handle_remove)

        # conn-индикатор через bindings
        if bindings is not None and hasattr(bindings, "bind_fanout"):
            bindings.bind_fanout("devices.state.*.conn", self._on_conn_delta, owner=self)

    def _handle_edit(self) -> None:
        if self._on_edit:
            self._on_edit(self._device_id)

    def _handle_remove(self) -> None:
        if self._on_remove:
            self._on_remove(self._device_id)

    def _on_conn_delta(self, path: str, value: Any) -> None:
        parts = path.split(".")
        if len(parts) < 4 or parts[2] != self._device_id:
            return
        conn = value.get("conn", "?") if isinstance(value, dict) else value
        self._conn_label.setText(_CONN_TEXT.get(str(conn), f"? {conn}"))


class DeviceMasterDetail(QWidget):
    """Master-detail: список устройств (слева) + страницы (справа)."""

    def __init__(
        self,
        *,
        kind: str,
        recipe_store: Any,
        bindings: Any = None,
        device_page_factory: Callable[[str], QWidget],
        add_page_factory: Callable[[], QWidget] | None = None,
        on_add: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._recipe_store = recipe_store
        self._device_page_factory = device_page_factory
        self._add_page_factory = add_page_factory
        # on_add — обработчик «+ Добавить» через модальный диалог (interim до Фазы D,
        # пока нет встроенной страницы добавления add_page_factory).
        self._on_add = on_add
        self._pages: dict[str, int] = {}
        self._add_index: int | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        self._panel = DeviceListPanel(kind=kind, recipe_store=recipe_store, bindings=bindings)
        splitter.addWidget(self._panel)

        self._stack = QStackedWidget()
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # index 0 — заглушка
        self._placeholder = QLabel(self._placeholder_text())
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: gray;")
        self._stack.addWidget(self._placeholder)

        self._panel.device_selected.connect(self._show_device)
        self._panel.add_requested.connect(self._show_add)

    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """Обновить список устройств; если выбранное исчезло — показать заглушку."""
        self._placeholder.setText(self._placeholder_text())
        self._panel.refresh()
        # Если текущая страница-устройство удалена из рецепта — на заглушку
        live_ids = set(self._panel.current_device_ids())
        cur = self._stack.currentIndex()
        for dev_id, idx in list(self._pages.items()):
            if dev_id not in live_ids and idx == cur:
                self._stack.setCurrentIndex(0)

    def select_device(self, device_id: str) -> None:
        """Программно выбрать и показать устройство."""
        self._panel.select_device(device_id)
        self._show_device(device_id)

    @property
    def panel(self) -> DeviceListPanel:
        return self._panel

    # ------------------------------------------------------------------ #

    def _placeholder_text(self) -> str:
        if not self._recipe_store.has_active():
            return "Активируйте рецепт, чтобы управлять устройствами"
        return "Выберите устройство в списке слева"

    def _show_device(self, device_id: str) -> None:
        if device_id not in self._pages:
            page = self._device_page_factory(device_id)
            self._pages[device_id] = self._stack.addWidget(page)
        self._stack.setCurrentIndex(self._pages[device_id])

    def _show_add(self) -> None:
        # Приоритет: встроенная страница добавления (Фаза D) → модальный диалог
        # (interim) → заглушка-подсказка.
        if self._add_page_factory is not None:
            if self._add_index is None:
                self._add_index = self._stack.addWidget(self._add_page_factory())
            self._stack.setCurrentIndex(self._add_index)
            return
        if self._on_add is not None:
            self._on_add()
            return
        self._placeholder.setText("Добавление устройств появится на странице добавления (Фаза D)")
        self._stack.setCurrentIndex(0)


__all__ = ["DeviceMasterDetail", "DeviceDetailPage"]
