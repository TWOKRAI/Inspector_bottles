# -*- coding: utf-8 -*-
"""DeviceCrudActions — CRUD-поток устройств: рецепт (истина) → hub (runtime).

План device-tree-recipe, Фаза C. Единый поток для add/edit/remove устройства:
  1. персист в активный рецепт через :class:`RecipeDevicesStore` (источник истины);
  2. при успехе — отражение в процесс ``devices`` (runtime, существующие команды
     device_upsert/device_remove с origin ``recipe:<slug>``);
  3. ``refresh_cb()`` — обновить список устройств (master-detail).

Ошибка hub НЕ откатывает рецепт (рецепт — истина; hub догонит при активации),
но показывается пользователю. Нет активного рецепта → подсказка, добавление
заблокировано.

Все запросы к бэкенду — через :class:`DevicesPresenter` (off-main-thread через
RequestRunner), результат — в main-thread через callback.

Refs: plans/device-tree-recipe.md Фаза C
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtWidgets import QApplication, QMessageBox

from .recipe_devices import RecipeDevicesError

logger = logging.getLogger(__name__)


class DeviceCrudActions:
    """CRUD-хелпер устройств одной секции (рецепт-first).

    Args:
        kind:          вид устройства (``robot``, ``vfd``, ...).
        presenter:     DevicesPresenter — отражение в процесс devices (runtime).
        recipe_store:  RecipeDevicesStore — персист в активный рецепт (истина).
        refresh_cb:    callback() — обновить список устройств после операции.
        parent_widget: родитель для диалогов (может быть None).
    """

    def __init__(
        self,
        *,
        kind: str,
        presenter: Any,
        recipe_store: Any,
        refresh_cb: Callable[[], None] | None = None,
        parent_widget: Any = None,
    ) -> None:
        self._kind = kind
        self._presenter = presenter
        self._recipe_store = recipe_store
        self._refresh_cb = refresh_cb
        self._parent = parent_widget

    # ------------------------------------------------------------------ #
    # Публичные обработчики
    # ------------------------------------------------------------------ #

    def on_add_clicked(self) -> None:
        """«Добавить» — проверить рецепт, запросить протоколы, открыть диалог."""
        if not self._recipe_store.has_active():
            self._no_active_recipe()
            return
        self._presenter.device_protocols(self._kind, self._on_protocols_for_add)

    def on_edit_clicked(self, device_id: str) -> None:
        """«Изменить» — describe устройства, открыть диалог редактирования."""
        if not device_id:
            return
        self._presenter.device_describe(
            device_id,
            lambda info: self._on_describe_for_edit(device_id, info),
        )

    def on_remove_clicked(self, device_id: str) -> None:
        """«Удалить» — подтверждение, затем remove из рецепта и hub."""
        if not device_id:
            return
        reply = QMessageBox.question(
            self._parent,
            "Удалить устройство",
            f"Удалить устройство «{device_id}» из рецепта?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # 1. рецепт (истина)
        try:
            self._recipe_store.remove(device_id)
        except RecipeDevicesError as exc:
            self._warn(str(exc))
            return
        # 2. hub (runtime)
        self._presenter.device_remove(device_id, lambda r: self._after_hub("remove", r))
        # 3. список
        self._refresh()

    # ------------------------------------------------------------------ #
    # Add: protocols -> device_list -> dialog
    # ------------------------------------------------------------------ #

    def _on_protocols_for_add(self, protocols: list[dict]) -> None:
        self._presenter.device_list(lambda devices: self._open_add_dialog(protocols, devices))

    def _open_add_dialog(self, protocols: list[dict], all_devices: list[dict]) -> None:
        from .editor_dialog import DeviceEditorDialog

        proto_names = [p if isinstance(p, str) else p.get("name", str(p)) for p in protocols]
        robot_devices = [d for d in all_devices if d.get("kind") == "robot"]
        parent = self._parent or QApplication.activeWindow()
        dlg = DeviceEditorDialog(
            kind=self._kind,
            protocols=proto_names,
            robot_devices=robot_devices,
            parent=parent,
        )
        if dlg.exec() != dlg.Accepted:
            return
        entry = dlg.get_entry()
        if not entry.get("id"):
            logger.warning("DeviceCrudActions: пустой id — add пропущен")
            return
        self._persist_and_sync(entry, "add")

    # ------------------------------------------------------------------ #
    # Edit: describe -> protocols -> device_list -> dialog
    # ------------------------------------------------------------------ #

    def _on_describe_for_edit(self, device_id: str, info: dict) -> None:
        self._presenter.device_protocols(
            self._kind,
            lambda protocols: self._open_edit_dialog(protocols, device_id, info),
        )

    def _open_edit_dialog(self, protocols: list[dict], device_id: str, existing: dict) -> None:
        proto_names = [p if isinstance(p, str) else p.get("name", str(p)) for p in protocols]
        self._presenter.device_list(
            lambda all_devices: self._show_edit_dialog(proto_names, all_devices, device_id, existing)
        )

    def _show_edit_dialog(
        self,
        proto_names: list[str],
        all_devices: list[dict],
        device_id: str,
        existing: dict,
    ) -> None:
        from .editor_dialog import DeviceEditorDialog

        robot_devices = [d for d in all_devices if d.get("kind") == "robot" and d.get("id") != device_id]
        parent = self._parent or QApplication.activeWindow()
        # describe возвращает {entry: {...}, ...} либо плоский dict — берём entry если есть
        existing_entry = existing.get("entry") if isinstance(existing.get("entry"), dict) else existing
        dlg = DeviceEditorDialog(
            kind=self._kind,
            protocols=proto_names,
            robot_devices=robot_devices,
            existing=existing_entry,
            parent=parent,
        )
        if dlg.exec() != dlg.Accepted:
            return
        entry = dlg.get_entry()
        self._persist_and_sync(entry, "edit")

    # ------------------------------------------------------------------ #
    # Персист: рецепт → hub → refresh
    # ------------------------------------------------------------------ #

    def _persist_and_sync(self, entry: dict, action: str) -> None:
        """Записать устройство в рецепт (истина), затем отразить в hub."""
        # 1. рецепт (истина)
        try:
            self._recipe_store.upsert(entry)
        except RecipeDevicesError as exc:
            self._warn(str(exc))
            return
        # 2. hub (runtime) с origin recipe:<slug>
        slug = self._recipe_store.active_slug()
        payload = {**entry, "origin": f"recipe:{slug}"} if slug else dict(entry)
        self._presenter.device_upsert(payload, on_result=lambda r: self._after_hub(action, r))
        # 3. список (рецепт уже обновлён — отобразится сразу)
        self._refresh()

    def _after_hub(self, action: str, result: dict) -> None:
        if result.get("status") not in ("ok", None) and result:
            logger.warning("DeviceCrudActions: hub %s вернул: %s", action, result)
            self._warn(f"Рецепт обновлён, но процесс устройств вернул ошибку: {result.get('message', result)}")
        self._refresh()

    # ------------------------------------------------------------------ #
    # Утилиты
    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        if self._refresh_cb:
            self._refresh_cb()

    def _no_active_recipe(self) -> None:
        QMessageBox.information(
            self._parent or QApplication.activeWindow(),
            "Нет активного рецепта",
            "Активируйте рецепт во вкладке «Рецепты», чтобы добавлять устройства.",
        )

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self._parent or QApplication.activeWindow(), "Устройства", message)


__all__ = ["DeviceCrudActions"]
