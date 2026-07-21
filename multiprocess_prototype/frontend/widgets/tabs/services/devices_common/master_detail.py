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

import json
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
    "disconnecting": "◌ отключение…",
    "disconnected": "○ отключено",
    "error": "✕ ошибка",
}


def _render_device_io(value: dict) -> tuple[str, str, str]:
    """Рендер io_peek устройства: {input:{op,reg,values}, output:{op,reg,value}}.

    Вход (RX) — последнее чтение регистров; выход (TX) — последняя запись.
    """
    in_data = value.get("input") or {}
    out_data = value.get("output") or {}
    in_reg = in_data.get("reg", "—") if in_data else "—"
    out_reg = out_data.get("reg", "—") if out_data else "—"
    status = f"вход (RX): {in_reg} · выход (TX): {out_reg}"
    in_text = json.dumps(in_data, indent=2, ensure_ascii=False) if in_data else "— (нет чтений)"
    out_text = json.dumps(out_data, indent=2, ensure_ascii=False) if out_data else "— (нет записей)"
    return status, in_text, out_text


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
        on_cleanup:     callback() — вызывается при удалении страницы из стека
            (bug-hunt A-5): отвязывает controller устройства (unbind(), стоп
            stale-таймера) до deleteLater(). Тот же getattr("cleanup")-приём,
            что уже используется для страницы добавления (_cleanup_add_page).
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
        on_cleanup: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_id = device_id
        self._presenter = devices_presenter
        self._on_edit = on_edit
        self._on_remove = on_remove
        self._on_cleanup = on_cleanup

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

        # Панель «Вход/Выход» (Modbus TX/RX) внизу — переиспользует IoDebugSection
        # плагинов, подписка на devices.state.<id>.io_peek (публикует device_hub).
        try:
            from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.io_debug_section import (
                IoDebugSection,
            )

            self._io_section = IoDebugSection(
                bindings,
                peek_pattern="devices.state.*.io_peek",
                render_fn=_render_device_io,
                title="Modbus I/O (вход/выход)",
            )
            self._io_section.set_active_path(f"devices.state.{device_id}.io_peek")
            root.addWidget(self._io_section)
        except Exception:
            self._io_section = None  # pipeline-пакет недоступен — панель опциональна

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

    def cleanup(self) -> None:
        """Отвязать controller устройства (bug-hunt A-5).

        Вызывается DeviceMasterDetail перед удалением страницы из стека
        (устройство пропало из активного рецепта). Idempotent, если
        on_cleanup сам идемпотентен (unbind() controller'ов — идемпотентны).
        """
        if self._on_cleanup is not None:
            try:
                self._on_cleanup()
            except Exception:
                pass

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
        add_page_factory: Callable[[Callable[[str], None], Callable[[], None]], QWidget] | None = None,
        on_add: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._recipe_store = recipe_store
        self._device_page_factory = device_page_factory
        # add_page_factory(on_committed, on_cancel) -> встроенная страница добавления
        # (Фаза D). on_add — fallback через модальный диалог, если страницы нет.
        self._add_page_factory = add_page_factory
        self._on_add = on_add
        # bug-hunt A-5: значение — сам виджет страницы (не индекс в стеке).
        # Индекс инвалидируется при любом removeWidget() на более ранней
        # позиции — храня виджет, обращаемся к нему через setCurrentWidget()/
        # indexOf() и не зависим от сдвига индексов при удалении страниц.
        self._pages: dict[str, QWidget] = {}
        self._add_page: QWidget | None = None
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
        """Обновить список устройств; удалить страницы устройств, исчезнувших из рецепта.

        bug-hunt A-5: раньше страница устройства, пропавшего из активного
        рецепта (remove из CRUD или переключение на другой рецепт), оставалась
        в стеке навсегда — вместе с живым controller'ом (bind_fanout-подписка
        + parentless QTimer stale-проверки раз в 2с). Теперь такая страница
        полностью снимается: cleanup() отвязывает controller, виджет удаляется
        из стека и планируется на удаление.
        """
        self._placeholder.setText(self._placeholder_text())
        self._panel.refresh()
        live_ids = set(self._panel.current_device_ids())
        cur_widget = self._stack.currentWidget()
        for dev_id, page in list(self._pages.items()):
            if dev_id in live_ids:
                continue
            if page is cur_widget:
                self._stack.setCurrentIndex(0)
            self._remove_device_page(dev_id)

    def _remove_device_page(self, device_id: str) -> None:
        """Снять и уничтожить кэшированную страницу устройства (bug-hunt A-5)."""
        page = self._pages.pop(device_id, None)
        if page is None:
            return
        cleanup = getattr(page, "cleanup", None)
        if callable(cleanup):
            cleanup()
        self._stack.removeWidget(page)
        page.deleteLater()

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
        # Уход со страницы добавления — убрать пробное (несохранённое) подключение
        self._cleanup_add_page()
        page = self._pages.get(device_id)
        if page is None:
            page = self._device_page_factory(device_id)
            self._pages[device_id] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def _show_add(self) -> None:
        # Приоритет: встроенная страница добавления (Фаза D) → модальный диалог
        # (fallback) → заглушка-подсказка.
        if self._add_page_factory is not None:
            # Пересоздаём страницу для чистой формы при каждом «+ Добавить»
            self._destroy_add_page()
            self._add_page = self._add_page_factory(self._after_add_commit, self._after_add_cancel)
            self._add_index = self._stack.addWidget(self._add_page)
            self._stack.setCurrentIndex(self._add_index)
            return
        if self._on_add is not None:
            self._on_add()
            return
        self._placeholder.setText("Добавление устройств появится на странице добавления (Фаза D)")
        self._stack.setCurrentIndex(0)

    def _after_add_commit(self, device_id: str) -> None:
        """Устройство сохранено — обновить список и открыть его страницу."""
        self.refresh()
        self.select_device(device_id)

    def _after_add_cancel(self) -> None:
        """Отмена добавления — вернуться к заглушке."""
        self._stack.setCurrentIndex(0)

    def _cleanup_add_page(self) -> None:
        """Best-effort: убрать пробное подключение страницы добавления."""
        if self._add_page is not None:
            cleanup = getattr(self._add_page, "cleanup", None)
            if callable(cleanup):
                cleanup()

    def _destroy_add_page(self) -> None:
        if self._add_page is not None:
            self._cleanup_add_page()
            self._stack.removeWidget(self._add_page)
            self._add_page.deleteLater()
            self._add_page = None
            self._add_index = None


__all__ = ["DeviceMasterDetail", "DeviceDetailPage"]
