# -*- coding: utf-8 -*-
"""
BaseConfigurableWidget — базовый виджет с привязкой к RegistersManager.

Гибкая конфигурация:
- register_name + field_name (явно или через "register.field")
- Опционально: field (model_class, field_name) для автоопределения
- RegistersManager и access_level — из parent при отсутствии

Совместим с минимальным IRegistersManager (get_register, get_field_metadata,
validate_field_value). Опционально: subscribe, set_field_value, can_modify_field.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend_module.core.qt_imports import QWidget


def _get_registers_from_parent(parent: Any, max_depth: int = 5) -> Optional[Any]:
    """Получить RegistersManager из parent (рекурсивно вверх)."""
    current = parent
    for _ in range(max_depth):
        if current is None:
            break
        if hasattr(current, "registers_manager"):
            rm = getattr(current, "registers_manager")
            if rm is not None:
                return rm
        current = getattr(current, "parent", lambda: None)()
        if callable(current):
            current = current()
    return None


def _get_access_level_from_parent(parent: Any, max_depth: int = 5) -> int:
    """Получить access_level из parent."""
    current = parent
    for _ in range(max_depth):
        if current is None:
            break
        if hasattr(current, "access_level"):
            return int(getattr(current, "access_level", 0))
        current = getattr(current, "parent", lambda: None)()
        if callable(current):
            current = current()
    return 0


def _parse_register_field(value: str) -> tuple[Optional[str], Optional[str]]:
    """Парсинг 'register.field' в (register_name, field_name)."""
    if "." in value:
        parts = value.split(".", 1)
        return parts[0], parts[1]
    return None, value


class BaseConfigurableWidget(QWidget):
    """
    Базовый виджет с привязкой к регистру.

    Подклассы переопределяют _load_metadata(), _update_value_silent(), _update_access_level().
    """

    def __init__(
        self,
        register_name: Optional[str] = None,
        field_name: Optional[str] = None,
        registers_manager: Optional[Any] = None,
        access_level: int = 0,
        parent: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)

        self._register_name: Optional[str] = None
        self._field_name: Optional[str] = None
        self._registers_manager: Optional[Any] = registers_manager
        self._access_level: int = access_level
        self._is_initialized: bool = False

        if parent and not registers_manager:
            self._registers_manager = _get_registers_from_parent(parent)
        if parent and access_level == 0:
            self._access_level = _get_access_level_from_parent(parent)

        if register_name:
            self._register_name = register_name
        if field_name:
            reg, field = _parse_register_field(field_name)
            if reg:
                self._register_name = reg
            self._field_name = field or field_name
            if not self._register_name:
                self._auto_detect_register()

        if self._register_name and self._field_name and self._registers_manager:
            self._apply_configuration()

    def _auto_detect_register(self) -> None:
        """Найти register_name по field_name среди зарегистрированных регистров."""
        if not self._registers_manager or not self._field_name:
            return
        names = getattr(self._registers_manager, "register_names", None)
        if callable(names):
            for reg_name in names():
                reg = self._registers_manager.get_register(reg_name)
                if reg and hasattr(reg, "model_fields"):
                    if self._field_name in getattr(reg, "model_fields", {}):
                        self._register_name = reg_name
                        return

    def _apply_configuration(self) -> None:
        """Применить конфигурацию: загрузить метаданные и привязать observer."""
        if not all([self._registers_manager, self._register_name, self._field_name]):
            return
        meta = self._registers_manager.get_field_metadata(
            self._register_name, self._field_name
        )
        if not meta and not self._register_name:
            self._auto_detect_register()
            if self._register_name:
                meta = self._registers_manager.get_field_metadata(
                    self._register_name, self._field_name
                )
        if not meta:
            return

        if not self._is_initialized:
            self._load_metadata()
            self._is_initialized = True
            self._bind_to_manager()
        else:
            self._unbind_from_manager()
            self._load_metadata()
            self._bind_to_manager()

    def _load_metadata(self) -> None:
        """Загрузить метаданные и построить UI. Переопределить в подклассе."""
        pass

    def _bind_to_manager(self) -> None:
        """Подписаться на изменения поля (если менеджер поддерживает)."""
        if (
            self._registers_manager
            and self._register_name
            and self._field_name
            and hasattr(self._registers_manager, "subscribe")
        ):
            self._registers_manager.subscribe(
                self._register_name, self._field_name, self._update_value_silent
            )

    def _unbind_from_manager(self) -> None:
        """Отписаться от изменений."""
        if (
            self._registers_manager
            and self._register_name
            and self._field_name
            and hasattr(self._registers_manager, "unsubscribe")
        ):
            self._registers_manager.unsubscribe(
                self._register_name, self._field_name, self._update_value_silent
            )

    def _update_value_silent(self, value: Any) -> None:
        """Обновить отображение без эмита сигналов. Переопределить в подклассе."""
        pass

    def _update_access_level(self) -> None:
        """Обновить UI при смене access_level. Переопределить в подклассе."""
        pass

    def _can_modify(self) -> bool:
        """Проверить, может ли пользователь изменять поле."""
        if hasattr(self._registers_manager, "can_modify_field"):
            return self._registers_manager.can_modify_field(
                self._register_name, self._field_name, self._access_level
            )
        meta = self.get_metadata()
        required = meta.get("access_level", 0)
        return self._access_level >= required and not meta.get("readonly", False)

    # --- Публичные свойства ---

    @property
    def register_name(self) -> Optional[str]:
        return self._register_name

    @property
    def field_name(self) -> Optional[str]:
        return self._field_name

    @property
    def registers_manager(self) -> Optional[Any]:
        return self._registers_manager

    @property
    def access_level(self) -> int:
        return self._access_level

    def get_metadata(self) -> dict:
        """Метаданные текущего поля."""
        if not all([self._registers_manager, self._register_name, self._field_name]):
            return {}
        meta = self._registers_manager.get_field_metadata(
            self._register_name, self._field_name
        )
        if meta:
            return meta
        reg = self._registers_manager.get_register(self._register_name)
        if reg and hasattr(reg, "get_field_metadata"):
            return reg.get_field_metadata(self._field_name) or {}
        return {}

    def get_field_value(self) -> Any:
        """Текущее значение поля из регистра."""
        if not all([self._registers_manager, self._register_name, self._field_name]):
            return None
        reg = self._registers_manager.get_register(self._register_name)
        if not reg:
            return None
        val = getattr(reg, self._field_name, None)
        return getattr(val, "value", val) if val is not None else val

    def set_field_value(self, value: Any) -> tuple[bool, Optional[str]]:
        """Установить значение с валидацией. Возвращает (success, error_message)."""
        if not all([self._registers_manager, self._register_name, self._field_name]):
            return False, "Конфигурация не завершена"
        if not self._can_modify():
            return False, "Недостаточно прав доступа"
        is_valid, err = self._registers_manager.validate_field_value(
            self._register_name, self._field_name, value, self._access_level
        )
        if not is_valid:
            return False, err
        if hasattr(self._registers_manager, "set_field_value"):
            return self._registers_manager.set_field_value(
                self._register_name, self._field_name, value
            )
        reg = self._registers_manager.get_register(self._register_name)
        if not reg:
            return False, "Регистр не найден"
        setattr(reg, self._field_name, value)
        return True, None

    def closeEvent(self, event: Any) -> None:
        """Отписаться при закрытии."""
        self._unbind_from_manager()
        if hasattr(super(), "closeEvent"):
            super().closeEvent(event)  # type: ignore
