# -*- coding: utf-8 -*-
"""
IControlView[T], INumericView — контракты для View-компонентов.

INumericView расширяет IControlView[float] методами set_range, set_validator_*.
"""
from __future__ import annotations

from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


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
