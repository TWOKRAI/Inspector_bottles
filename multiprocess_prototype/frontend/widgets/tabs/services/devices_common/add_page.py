# -*- coding: utf-8 -*-
"""AddDevicePage — встроенная страница добавления устройства (Фаза D).

Решение владельца: **пробное подключение перед сохранением**. Поток:
  1. ввод параметров (общая :class:`DeviceFormWidget`);
  2. «Проверить связь» — пробный upsert в hub с origin=``probe`` (НЕ в рецепт) +
     device_connect → live-статус (✓ подключено / ✗ ошибка) по
     ``devices.state.<id>.conn``;
  3. «Добавить» — персист в рецепт (RecipeDevicesStore, истина) + re-tag
     origin=``recipe:<slug>`` в hub; устройство уже подключено;
  4. «Отмена» / уход со страницы — пробное устройство удаляется из hub.

Нет активного рецепта → форма заблокирована с подсказкой.

Камеры (kind=hikvision): автопоиск (hik_enum) — отложен вместе с hikvision-секцией.

Refs: plans/device-tree-recipe.md Фаза D
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .device_form import DeviceFormWidget
from .recipe_devices import RecipeDevicesError

_CONN_TEXT = {
    "connected": ("● связь есть", "color: green;"),
    "connecting": ("◌ подключение…", "color: orange;"),
    "disconnected": ("○ нет связи", "color: gray;"),
    "error": ("✕ ошибка связи", "color: red;"),
}

_PROBE_ORIGIN = "probe"


class AddDevicePage(QWidget):
    """Страница добавления устройства с пробным подключением перед сохранением.

    Args:
        kind:         вид устройства (``robot``/``vfd``/...).
        presenter:    DevicesPresenter — upsert/connect/remove/protocols/list (hub).
        recipe_store: RecipeDevicesStore — персист в рецепт (истина).
        on_committed: callback(device_id) — устройство сохранено (master: refresh+select).
        on_cancel:    callback() — отмена (master: вернуть заглушку).
        bindings:     GuiStateBindings — live-статус conn.
    """

    def __init__(
        self,
        *,
        kind: str,
        presenter: Any,
        recipe_store: Any,
        on_committed: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        bindings: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._presenter = presenter
        self._recipe_store = recipe_store
        self._on_committed = on_committed
        self._on_cancel = on_cancel
        self._form: DeviceFormWidget | None = None
        self._probe_id: str | None = None  # id пробного устройства в hub (не в рецепте)
        self._committed = False

        self._root = QVBoxLayout(self)
        self._title = QLabel("<b>Добавить устройство</b>")
        self._root.addWidget(self._title)

        if not recipe_store.has_active():
            hint = QLabel("Активируйте рецепт во вкладке «Рецепты», чтобы добавить устройство.")
            hint.setStyleSheet("color: gray;")
            self._root.addWidget(hint)
            self._root.addStretch(1)
            return

        # Плейсхолдер формы (заполнится после загрузки протоколов/устройств)
        self._form_slot = QVBoxLayout()
        self._root.addLayout(self._form_slot)

        self._status = QLabel("Заполните параметры и нажмите «Проверить связь».")
        self._status.setStyleSheet("color: gray;")
        self._root.addWidget(self._status)

        row = QHBoxLayout()
        self._btn_check = QPushButton("Проверить связь")
        self._btn_add = QPushButton("Добавить")
        self._btn_cancel = QPushButton("Отмена")
        for b in (self._btn_check, self._btn_add, self._btn_cancel):
            row.addWidget(b)
        row.addStretch(1)
        self._root.addLayout(row)
        self._root.addStretch(1)

        self._btn_check.clicked.connect(self._on_check)
        self._btn_add.clicked.connect(self._on_commit)
        self._btn_cancel.clicked.connect(self._on_cancel_clicked)
        self._set_buttons_enabled(False)

        if bindings is not None and hasattr(bindings, "bind_fanout"):
            bindings.bind_fanout("devices.state.*.conn", self._on_conn_delta, owner=self)

        # Загрузить протоколы → robot-устройства → построить форму
        self._presenter.device_protocols(self._kind, self._on_protocols)

    # ------------------------------------------------------------------ #
    # Сборка формы (async)
    # ------------------------------------------------------------------ #

    def _on_protocols(self, protocols: list) -> None:
        proto_names = [p if isinstance(p, str) else p.get("name", str(p)) for p in protocols]
        self._presenter.device_list(lambda devices: self._build_form(proto_names, devices))

    def _build_form(self, protocols: list[str], all_devices: list[dict]) -> None:
        robots = [d for d in all_devices if d.get("kind") == "robot"]
        self._form = DeviceFormWidget(kind=self._kind, protocols=protocols, robot_devices=robots)
        self._form_slot.addWidget(self._form)
        self._set_buttons_enabled(True)

    # ------------------------------------------------------------------ #
    # Пробное подключение
    # ------------------------------------------------------------------ #

    def _on_check(self) -> None:
        if self._form is None:
            return
        entry = self._form.get_entry()
        dev_id = entry.get("id")
        if not dev_id:
            self._set_status("Укажите ID устройства.", "error")
            return
        # Сменился id — убрать прошлое пробное устройство
        if self._probe_id and self._probe_id != dev_id:
            self._presenter.device_remove(self._probe_id)
        self._probe_id = dev_id
        self._set_status("Подключение…", "connecting")
        # Пробный upsert (origin=probe, НЕ в рецепт) → connect
        self._presenter.device_upsert(
            {**entry, "origin": _PROBE_ORIGIN},
            on_result=lambda _r: self._presenter.device_connect(dev_id),
        )

    def _on_conn_delta(self, path: str, value: Any) -> None:
        parts = path.split(".")
        if len(parts) < 4 or parts[2] != self._probe_id:
            return
        conn = value.get("conn", "?") if isinstance(value, dict) else value
        self._set_status_conn(str(conn))

    # ------------------------------------------------------------------ #
    # Сохранение / отмена
    # ------------------------------------------------------------------ #

    def _on_commit(self) -> None:
        if self._form is None:
            return
        entry = self._form.get_entry()
        if not entry.get("id"):
            self._set_status("Укажите ID устройства.", "error")
            return
        # 1. рецепт (истина)
        try:
            self._recipe_store.upsert(entry)
        except RecipeDevicesError as exc:
            self._set_status(str(exc), "error")
            return
        # 2. hub: re-tag probe→recipe (устройство уже подключено, если проверяли)
        slug = self._recipe_store.active_slug()
        payload = {**entry, "origin": f"recipe:{slug}"} if slug else dict(entry)
        self._presenter.device_upsert(payload)
        # пробное устройство стало настоящим — не удалять при уходе
        self._committed = True
        committed_id = entry["id"]
        self._probe_id = None
        if self._on_committed:
            self._on_committed(committed_id)

    def _on_cancel_clicked(self) -> None:
        self.cleanup()
        if self._on_cancel:
            self._on_cancel()

    def cleanup(self) -> None:
        """Убрать пробное (несохранённое) устройство из hub — при отмене/уходе."""
        if self._probe_id and not self._committed:
            self._presenter.device_remove(self._probe_id)
        self._probe_id = None

    def reset(self) -> None:
        """Подготовить страницу к новому добавлению (после успешного commit)."""
        self._committed = False
        self._probe_id = None
        self._set_status("Заполните параметры и нажмите «Проверить связь».", None)

    # ------------------------------------------------------------------ #
    # Утилиты
    # ------------------------------------------------------------------ #

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for b in (self._btn_check, self._btn_add):
            b.setEnabled(enabled)

    def _set_status(self, text: str, level: str | None) -> None:
        self._status.setText(text)
        color = {"error": "color: red;", "connecting": "color: orange;"}.get(level or "", "color: gray;")
        self._status.setStyleSheet(color)

    def _set_status_conn(self, conn: str) -> None:
        text, style = _CONN_TEXT.get(conn, (f"? {conn}", "color: gray;"))
        self._status.setText(text)
        self._status.setStyleSheet(style)


__all__ = ["AddDevicePage"]
