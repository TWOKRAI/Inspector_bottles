# -*- coding: utf-8 -*-
"""Хелперы для QTreeWidget в Settings таб.

Реэкспорт из framework для обратной совместимости: существующие импорты
``from ._nav_tree import build_nav_tree, ...`` продолжают работать.

Каноническое расположение утилит:
    ``multiprocess_framework.modules.frontend_module.widgets.tabs.nav_tree_utils``

Re-export CurrentPageStack из framework для удобства импорта.
"""

from __future__ import annotations

# Re-export для удобства: импортировать CurrentPageStack можно отсюда
from multiprocess_framework.modules.frontend_module.widgets.tabs import CurrentPageStack

# Реэкспорт утилит nav-дерева из framework
from multiprocess_framework.modules.frontend_module.widgets.tabs.nav_tree_utils import (
    build_nav_tree,
    collapse_other_branches,
    find_tree_item,
    select_tree_key,
)

__all__ = [
    "CurrentPageStack",
    "build_nav_tree",
    "collapse_other_branches",
    "find_tree_item",
    "select_tree_key",
]
