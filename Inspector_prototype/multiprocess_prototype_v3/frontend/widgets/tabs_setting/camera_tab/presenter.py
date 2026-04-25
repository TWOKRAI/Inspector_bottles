# multiprocess_prototype_v3/frontend/widgets/camera_tab/presenter.py
"""Презентер вкладки камеры: тип камеры в регистрах, колбэк в capture, обновление стека.

Task 3.10: расширение на N камер из CameraRegistry — camera selector, status/FPS/drops.
"""

from __future__ import annotations

import logging
from typing import Any

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui
from multiprocess_framework.modules.frontend_module.widgets.tabs import TabPresenterBase

from multiprocess_prototype_v3.frontend.coordinators.logical_cameras import (
    ensure_logical_camera_and_seed_roi,
)

from .register_ops import persist_camera_type, set_camera_type_field, set_camera_type_via_bus
from .schemas import CameraTabUiConfig
from .view import CameraTabView

logger = logging.getLogger(__name__)

# Маппинг статусов камеры на цвета для UI
_STATUS_COLORS: dict[str, str] = {
    "running": "green",
    "stopped": "gray",
    "error": "red",
}


class CameraTabPresenter(TabPresenterBase[CameraTabView, CameraTabUiConfig]):
    def __init__(
        self,
        *,
        view: CameraTabView,
        rm: IRegistersManagerGui | None,
        ui: CameraTabUiConfig,
        callbacks_map: dict[str, Any],
        camera_registry: Any | None = None,
        action_bus: Any | None = None,
    ) -> None:
        """callbacks_map — колбэки дочерних виджетов + on_camera_type_changed для IPC.

        camera_registry — CameraRegistry (Task 3.9) или None для fallback-режима.
        action_bus — ActionBus для undo-able записи полей (или None для прямого rm-вызова).
        """
        super().__init__(view=view, rm=rm, ui=ui)
        self._callbacks_map = callbacks_map
        self._camera_registry = camera_registry
        self._bus = action_bus
        # camera_id текущей выбранной камеры в selector-е (-1 = нет)
        self._selected_camera_id: int = -1
        # Упорядоченный список camera_id для маппинга индекса selector → camera_id
        self._camera_id_list: list[int] = []

    # ------------------------------------------------------------------
    # Публичный API — инициализация multi-camera UI
    # ------------------------------------------------------------------

    def init_multi_camera_ui(self) -> None:
        """Заполнить camera selector из реестра и подписаться на изменения.

        Вызывается из widget после _init_ui, когда все Qt-виджеты уже созданы.
        Если camera_registry is None — ничего не делаем (fallback на 1 камеру).
        """
        if self._camera_registry is None:
            return

        self._populate_camera_selector()
        self._camera_registry.add_callback(self._on_registry_changed)

        # Показать данные первой камеры, если есть
        if self._camera_id_list:
            self._selected_camera_id = self._camera_id_list[0]
            self._refresh_camera_info()

    def cleanup(self) -> None:
        """Отписаться от callback-ов реестра (вызывается при уничтожении виджета)."""
        if self._camera_registry is not None:
            self._camera_registry.remove_callback(self._on_registry_changed)

    # ------------------------------------------------------------------
    # Обработчики UI-событий
    # ------------------------------------------------------------------

    def on_camera_type_changed(self, index: int) -> None:
        """Запись camera_type в регистр и диск, команда воркеру, смена страницы стека."""
        camera_type = self._ui.camera_type_for_combo_index(index)
        set_camera_type_via_bus(self._bus, self._rm, camera_type)
        ensure_logical_camera_and_seed_roi(self._rm)
        persist_camera_type(camera_type)
        # Явная команда — register_update обрабатывается только в capture_worker,
        # который при остановленном захвате не читает очередь.
        cb = self._callbacks_map.get("on_camera_type_changed")
        if cb:
            cb(camera_type)
        self._view.set_stack_index(index)

    def apply_initial_camera_type(self, camera_type: str, stack_index: int) -> None:
        """При старте: записать тип в rm/диск и выставить combo+стек без сигнала."""
        if self._rm is not None:
            set_camera_type_field(self._rm, camera_type)
            ensure_logical_camera_and_seed_roi(self._rm)
            persist_camera_type(camera_type)
        self._view.set_combo_index(stack_index, block_signals=True)
        self._view.set_stack_index(stack_index)

    def on_camera_selector_changed(self, index: int) -> None:
        """Пользователь выбрал другую камеру в camera selector."""
        if index < 0 or index >= len(self._camera_id_list):
            return
        self._selected_camera_id = self._camera_id_list[index]
        self._refresh_camera_info()

    def on_start_camera(self) -> None:
        """Placeholder: запуск камеры (IPC будет в Task 3.13)."""
        if self._selected_camera_id < 0:
            return
        logger.info(
            "Start camera %d (placeholder — IPC в Task 3.13)",
            self._selected_camera_id,
        )

    def on_stop_camera(self) -> None:
        """Placeholder: остановка камеры (IPC будет в Task 3.13)."""
        if self._selected_camera_id < 0:
            return
        logger.info(
            "Stop camera %d (placeholder — IPC в Task 3.13)",
            self._selected_camera_id,
        )

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _populate_camera_selector(self) -> None:
        """Заполнить ComboBox камер из реестра."""
        if self._camera_registry is None:
            return

        entries = self._camera_registry.all_entries()
        self._camera_id_list = [e.camera_id for e in entries]
        items = [f"camera_{e.camera_id}: {e.camera_type}" for e in entries]
        self._view.populate_camera_selector(items, block_signals=True)

    def _refresh_camera_info(self) -> None:
        """Обновить status/FPS/drops labels для текущей выбранной камеры."""
        if self._camera_registry is None or self._selected_camera_id < 0:
            return

        entry = self._camera_registry.get_entry(self._selected_camera_id)
        if entry is None:
            return

        color = _STATUS_COLORS.get(entry.status, "gray")
        self._view.set_camera_status_text(entry.status.capitalize(), color)
        self._view.set_camera_fps_text(f"FPS: {entry.fps:.1f}")
        self._view.set_camera_drops_text(f"Drops: {entry.drops_count}")

    def _on_registry_changed(self, camera_id: int, field: str, value: Any) -> None:
        """Callback из CameraRegistry — обновить UI, если изменилась выбранная камера."""
        if camera_id != self._selected_camera_id:
            return

        # Обновляем только изменившееся поле для производительности
        if field == "status":
            color = _STATUS_COLORS.get(str(value), "gray")
            self._view.set_camera_status_text(str(value).capitalize(), color)
        elif field == "fps":
            self._view.set_camera_fps_text(f"FPS: {float(value):.1f}")
        elif field == "drops_count":
            self._view.set_camera_drops_text(f"Drops: {int(value)}")
