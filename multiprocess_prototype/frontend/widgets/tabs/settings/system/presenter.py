# -*- coding: utf-8 -*-
"""SystemSettingsPresenter — бизнес-логика секции «Настройки системы».

Отвечает за:
- загрузку и сохранение system.yaml через yaml_io
- синхронизацию значений редакторов с конфигом
- управление dirty-флагом
- валидацию через SystemConfig
- запись действий в ActionBus (undo/redo)
- синхронизацию undo/redo с RegisterView

НЕ импортирует Qt-классы напрямую. Работает исключительно через SystemSettingsView Protocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabPresenterBase

from .view import SystemSettingsView
from ..yaml_io import load_settings, save_settings, schema_to_field_infos

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext
    from multiprocess_prototype.backend.config.schemas import SystemConfig
    from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

logger = logging.getLogger(__name__)


class SystemSettingsPresenter(TabPresenterBase[SystemSettingsView, None]):
    """Презентер секции «Настройки системы».

    Хранит состояние конфига и dirty-флаг, делегирует все UI-операции в view.
    Не содержит Qt-кода.
    """

    def __init__(
        self,
        *,
        view: SystemSettingsView,
        rm=None,
        ui=None,
        ctx: "AppContext",
    ) -> None:
        super().__init__(view=view, rm=rm, ui=ui)
        self._ctx = ctx

        # Текущий конфиг (загружается при инициализации)
        self._cfg: "SystemConfig" = load_settings()

        # FieldInfo для обхода редакторов
        self._field_infos: list["FieldInfo"] = schema_to_field_infos(self._cfg)

        # Dirty-флаг
        self._dirty: bool = False

        # Колбэки для уведомления SettingsTab (без Qt Signal)
        self.on_settings_saved: Callable[[dict], None] | None = None
        self.on_dirty_changed: Callable[[bool], None] | None = None

        # Редакторы синхронизируются через sync_editors_to_cfg() из set_presenter() —
        # после подключения сигналов порядок вызова контролирует section.

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def save(self) -> bool:
        """Собрать значения из редакторов, валидировать и сохранить в YAML.

        Returns:
            True при успешном сохранении, False при ошибке валидации.
        """
        import pydantic
        from multiprocess_prototype.backend.config.schemas import SystemConfig

        # Собрать значения из view
        editor_values = self._view.get_editor_values()
        dict_form: dict[str, Any] = {}
        for key, value in editor_values.items():
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            section, field_name = parts
            if section not in dict_form:
                dict_form[section] = {}
            dict_form[section][field_name] = value

        # Валидация
        try:
            validated = SystemConfig.model_validate(dict_form)
        except pydantic.ValidationError as exc:
            self._show_validation_errors(exc)
            return False

        # Сохранить на диск
        self._view.clear_validation_errors()
        save_settings(validated)
        self._cfg = validated

        # Уведомить слушателей
        if self.on_settings_saved is not None:
            try:
                self.on_settings_saved(dict_form)
            except Exception:
                logger.exception("Ошибка в on_settings_saved")

        self._set_dirty(False)
        return True

    def reload(self) -> None:
        """Перечитать system.yaml и сбросить все изменения."""
        self._cfg = load_settings()
        self._field_infos = schema_to_field_infos(self._cfg)
        self.sync_editors_to_cfg()
        self._view.clear_validation_errors()
        self._set_dirty(False)

    def on_field_changed(self) -> None:
        """Обработать изменение любого поля редактора → пометить dirty."""
        self._set_dirty(True)

    def on_field_changed_action_bus(
        self,
        register_name: str,
        field_name: str,
        old_value: object,
        new_value: object,
    ) -> None:
        """Записать изменение поля в ActionBus для undo/redo."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

        action = V2ActionBuilder.field_set_timed(
            register_name,
            field_name,
            new_value,
            old_value,
            description=f"{register_name}.{field_name} = {new_value}",
        )
        bus.record(action)

    def on_bus_undo_redo_sync(self) -> None:
        """Синхронизировать редакторы с ActionBus при undo/redo."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        event = bus.last_event
        if event is None:
            return
        event_type, action = event
        if event_type not in ("undo", "redo"):
            return
        if action.action_type != "field_set":
            return
        register_name = action.register_name or ""
        value = action.backward_patch.get("value") if event_type == "undo" else action.forward_patch.get("value")
        key = f"{register_name}.{action.field_name}"
        self._view.set_editor_value(key, value)

    # ------------------------------------------------------------------
    # Геттеры состояния (делегируют от SettingsTab)
    # ------------------------------------------------------------------

    def is_dirty(self) -> bool:
        """Вернуть текущий dirty-флаг."""
        return self._dirty

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def sync_editors_to_cfg(self) -> None:
        """Синхронизировать значения редакторов с текущим self._cfg.

        Публичный метод — вызывается из set_presenter() ДО подключения сигналов.
        """
        for fi in self._field_infos:
            section_name = fi.plugin_name
            field_name = fi.field_name
            key = f"{section_name}.{field_name}"
            section_obj = getattr(self._cfg, section_name, None)
            if section_obj is None:
                continue
            value = getattr(section_obj, field_name, None)
            if value is None:
                continue
            try:
                self._view.set_editor_value(key, value)
            except Exception:
                logger.debug("Не удалось установить значение редактора %s", key)

    def _set_dirty(self, dirty: bool) -> None:
        """Установить dirty-флаг и уведомить слушателей."""
        self._dirty = dirty
        self._view.set_dirty_indicator(dirty)
        if self.on_dirty_changed is not None:
            try:
                self.on_dirty_changed(dirty)
            except Exception:
                logger.exception("Ошибка в on_dirty_changed")

    def _show_validation_errors(self, exc: object) -> None:
        """Передать ошибки валидации pydantic в view."""
        # exc: pydantic.ValidationError — не импортируем pydantic для type hints
        for error in exc.errors():  # type: ignore[attr-defined]
            loc = error.get("loc", ())
            if len(loc) >= 2:
                key = f"{loc[0]}.{loc[1]}"
                self._view.show_validation_error(key, error["msg"])
