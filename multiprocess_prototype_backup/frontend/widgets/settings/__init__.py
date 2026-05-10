"""Settings widgets — таб настроек приложения.

Реэкспорт Qt-классов — **ленивый** (через `__getattr__`), чтобы pure-Python тесты
могли импортировать `widgets.settings` без поднятия PySide6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — только для type-checkers
    from .settings_tab import SettingsContainerWidget


_LAZY_ATTRS: dict[str, str] = {
    "SettingsContainerWidget": "settings_tab",
}


def __getattr__(name: str) -> Any:
    submod_name = _LAZY_ATTRS.get(name)
    if submod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(f".{submod_name}", package=__name__)
    return getattr(mod, name)


__all__ = sorted(_LAZY_ATTRS.keys())
