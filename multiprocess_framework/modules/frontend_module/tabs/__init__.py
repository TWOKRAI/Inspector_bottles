# -*- coding: utf-8 -*-
"""Механизм вкладок приложения (generic).

Публичный API (NEW-D1):
- ``TabSpec`` — декларативное описание вкладки (id/title/permission/factory).
- ``TabRegistry`` — построение, ленивая инстанциация и permission-фильтрация.
- ``LazyTab`` — обёртка ленивой инициализации содержимого.
- ``AccessContextSource`` — контракт источника прав для фильтрации.

Приложение описывает свои вкладки как ``list[TabSpec]`` в composition root и
передаёт их реестру. Реестр не знает конкретных вкладок и не импортирует
прикладной слой (0 обратных импортов).
"""

from __future__ import annotations

from .lazy_tab import LazyTab
from .registry import AccessContextSource, PlaceholderFactory, TabRegistry
from .spec import TabSpec

__all__ = [
    "TabSpec",
    "TabRegistry",
    "LazyTab",
    "AccessContextSource",
    "PlaceholderFactory",
]
