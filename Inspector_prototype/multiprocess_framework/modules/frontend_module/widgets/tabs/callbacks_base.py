# -*- coding: utf-8 -*-
"""
Колбэки вкладок: Qt-обёртка и сериализация frozen dataclass ↔ dict.

- callback_no_args — сигналы Qt с лишними аргументами.
- tab_callbacks_from_dict / tab_callbacks_to_dict — launcher и GuiCommandHandler;
  если передан dataclass, имена полей можно не указывать (порядок как в fields()).
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")


def callback_no_args(fn: Optional[Callable[[], None]]) -> Callable[..., None]:
    """
    Обёртка для Qt clicked(bool): игнорирует аргументы, вызывает fn().

        on_start = callback_no_args(callbacks.on_start)
        button.clicked.connect(on_start)
    """

    def _wrapper(*_args: Any, **_kwargs: Any) -> None:
        if fn is not None:
            fn()

    return _wrapper


def _dataclass_field_names(obj_or_cls: Any) -> tuple[str, ...]:
    cls = obj_or_cls if isinstance(obj_or_cls, type) else type(obj_or_cls)
    if not is_dataclass(cls):
        raise TypeError(
            "field_names must be passed when the class is not a @dataclass"
        )
    return tuple(f.name for f in fields(cls))


def tab_callbacks_from_dict(
    cls: type[T],
    d: Dict[str, Any],
    field_names: Optional[tuple[str, ...]] = None,
) -> T:
    """
    Собрать frozen dataclass колбэков из словаря.

    Args:
        cls: класс dataclass (например CameraTabCallbacks).
        d: словарь с полями-колбэками.
        field_names: имена полей; если None — берутся из dataclasses.fields(cls).

    Returns:
        Экземпляр cls; отсутствующие ключи в d → None.
    """
    names = field_names if field_names is not None else _dataclass_field_names(cls)
    return cls(**{k: d.get(k) for k in names})  # type: ignore[return-value]


def tab_callbacks_to_dict(
    instance: Any,
    field_names: Optional[tuple[str, ...]] = None,
) -> Dict[str, Optional[Callable[..., Any]]]:
    """
    Экземпляр frozen dataclass → dict для кода, ожидающего словарь.

    Args:
        instance: экземпляр dataclass.
        field_names: имена полей; если None — из dataclasses.fields(type(instance)).
    """
    names = field_names if field_names is not None else _dataclass_field_names(instance)
    return {k: getattr(instance, k, None) for k in names}
