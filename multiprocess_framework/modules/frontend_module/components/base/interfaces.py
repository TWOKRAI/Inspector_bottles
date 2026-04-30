# -*- coding: utf-8 -*-
"""
Контракты v2 base:

- **View**: `IControlView`, `INumericView` — только UI.
- **Presenter**: `IFieldBinding` + `IRegisterPort` — то, что ждут `SyncTrait` / `SchemaTrait`.

`BindingConfig` и `RegisterAdapter` — эталонные реализации портов; другие типы допустимы
структурно (duck typing), если поля/методы совпадают.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, TypeVar

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.schemas.register_binding import ResolvedMeta

T = TypeVar("T")

# --- Привязка к полю регистра (структурно совместима с BindingConfig) ---


class IFieldBinding(Protocol):
    """Привязка к `register_name.field_name` (+ `access_level`; опционально `index` для массивов)."""

    register_name: str
    field_name: str
    access_level: int


# --- Порт чтения/записи (реализация по умолчанию — RegisterAdapter) ---


class IRegisterPort(Protocol):
    """Минимум методов регистра, который используют traits (реализация — `RegisterAdapter`)."""

    def read(
        self, register_name: str, field_name: str, index: Optional[int] = None
    ) -> Any:
        ...

    def write(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        index: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        ...

    def subscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
        index: Optional[int] = None,
    ) -> None:
        ...

    def resolve_meta(
        self,
        register_name: str,
        field_name: str,
        config: Any,
    ) -> Optional[ResolvedMeta]:
        ...


# --- Минимум RegistersManager для адаптера регистра ---

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

# Алиас для обратной совместимости; единый контракт для GUI (ADR-071).
RegistersManagerLike = IRegistersManagerGui


# --- Виджет: только UI, без знания о traits ---


class IControlView(Protocol[T]):
    """Протокол View для контрола типа T."""

    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        """Настроить метку, подсказку, доступность."""
        ...

    def set_value(self, value: T) -> None:
        """Установить значение с эмитом on_changed."""
        ...

    def set_value_silent(self, value: T) -> None:
        """Установить значение без эмита."""
        ...

    def get_value(self) -> T:
        """Текущее значение."""
        ...

    def set_enabled(self, enabled: bool) -> None:
        """Включить/выключить редактирование."""
        ...

    def on_changed(self, callback: Callable[[T], None]) -> None:
        """Подписка на изменение (движение слайдера, клик чекбокса)."""
        ...

    def on_finished(self, callback: Callable[[T], None]) -> None:
        """Подписка на фиксацию (Enter, LostFocus). Для чекбокса — no-op."""
        ...

    def show_error(self, message: str) -> None:
        """Показать сообщение об ошибке валидации пользователю."""
        ...


# --- Числовая ось: диапазон, валидаторы, legacy-виджет для старых layout’ов ---


class INumericView(IControlView[float], Protocol):
    """Протокол числового View (Slider, SpinBox). Расширяет IControlView[float]."""

    def set_range(self, min_val: float, max_val: float, step: float) -> None:
        """Диапазон в UI-координатах."""
        ...

    def set_validator_int(self) -> None:
        """Валидатор для целых чисел."""
        ...

    def set_validator_float(self) -> None:
        """Валидатор для чисел с плавающей точкой."""
        ...

    def get_legacy_element(self) -> object:
        """Основной виджет для legacy ui_elements (slider или spinbox)."""
        ...


__all__ = [
    "IControlView",
    "INumericView",
    "IFieldBinding",
    "IRegisterPort",
    "IRegistersManagerGui",
    "RegistersManagerLike",
]
