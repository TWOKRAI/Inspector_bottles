# -*- coding: utf-8 -*-
"""
BaseConfigurableWidget — базовый виджет с привязкой к RegistersManager.

Инкапсулирует операции со схемами:
- _get_register_meta() — метаданные поля из регистра
- _read_value() / _write_value() — чтение/запись значения
- _resolve_meta() — слияние метаданных регистра с ComponentConfig

Конструктор: config, register_name, field_name, registers_manager, access_level, parent.
Подклассы переопределяют _load_metadata() и используют self._resolved_meta.
"""
from __future__ import annotations

import warnings
from typing import Any, Optional

from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget
from multiprocess_framework.modules.frontend_module.schemas.register_binding import (
    RegisterFieldMeta,
    ResolvedMeta,
)


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
    Используют self._resolved_meta для построения UI.
    """

    def __init__(
        self,
        config: Any = None,
        register_name: Optional[str] = None,
        field_name: Optional[str] = None,
        registers_manager: Optional[Any] = None,
        access_level: Optional[int] = None,
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)

        self._config: Any = config
        self._register_name: Optional[str] = None
        self._field_name: Optional[str] = None
        self._registers_manager: Optional[Any] = registers_manager
        self._access_level: int = 0
        self._resolved_meta: Optional[ResolvedMeta] = None
        self._is_initialized: bool = False

        _reg = register_name
        _field = field_name
        _access = access_level if access_level is not None else 0
        if config is not None:
            cfg_dict = self._config_to_dict(config)
            if cfg_dict.get("register_name"):
                _reg = cfg_dict["register_name"]
            if cfg_dict.get("field_name"):
                _field = cfg_dict["field_name"]
            if cfg_dict.get("access_level") is not None:
                _access = int(cfg_dict["access_level"])
        register_name = _reg
        field_name = _field
        access_level = _access
        self._access_level = access_level

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

    @staticmethod
    def _config_to_dict(config: Any) -> dict:
        """Извлечь dict из config (model_dump или dict)."""
        if config is None:
            return {}
        if hasattr(config, "model_dump"):
            try:
                return config.model_dump()
            except Exception:
                return {}
        return dict(config) if isinstance(config, dict) else {}

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

    def _get_register_meta(self) -> RegisterFieldMeta:
        """Метаданные поля из схемы регистра."""
        meta_dict = self.get_metadata()
        return RegisterFieldMeta.from_dict(meta_dict)

    def _read_value(self) -> Any:
        """Текущее значение поля из регистра."""
        return self.get_field_value()

    def _write_value(self, value: Any) -> tuple[bool, Optional[str]]:
        """Записать значение с валидацией. Возвращает (success, error_message)."""
        return self.set_field_value(value)

    def _resolve_meta(self) -> Optional[ResolvedMeta]:
        """Слияние метаданных регистра с переопределениями из config."""
        meta = self._get_register_meta()
        if not meta.raw and not self._register_name:
            return None
        config = self._config if self._config is not None else {}
        return ResolvedMeta.merge(meta, config, self._field_name or "")

    def _apply_configuration(self) -> None:
        """Применить конфигурацию: resolve meta, загрузить UI, привязать observer."""
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

        self._resolved_meta = self._resolve_meta()
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

    def _apply_access(self) -> None:
        """
        Централизованное применение AccessTrait к виджету.

        Логика:
        - can_view == False → скрыть виджет (setVisible(False))
        - can_view == True, can_modify == False → disabled + QSS readOnly=true
        - can_view == True, can_modify == True  → видим и enabled

        Вызывается после update AccessTrait (например из _update_access_level или
        set_access_context).
        """
        if not hasattr(self, "_trait") or self._trait is None:
            return
        if not self._trait.can_view():
            self.setVisible(False)
            return
        self.setVisible(True)
        self.setEnabled(self._trait.can_modify())
        self.setProperty("readOnly", not self._trait.can_modify())
        # Repolish — обновить QSS-стили, зависящие от свойства readOnly
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def _update_access_level(self, level: int = 0) -> None:
        """
        Deprecated: Обновить UI при смене access_level.

        Используйте _apply_access() с AccessTrait вместо этого метода.
        Сохранён для обратной совместимости с подклассами.
        """
        warnings.warn(
            "_update_access_level() is deprecated, use _apply_access() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Если у виджета есть _trait — обновим его через legacy path и применим
        if hasattr(self, "_trait") and self._trait is not None:
            self._trait.update(level)
            self._apply_access()

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
