# -*- coding: utf-8 -*-
"""Tab layouts — колоночные layout'ы для вкладок.

Реэкспорт:
- ``_AbstractColumnarTabLayout`` — общая база (action-колонка, undo/redo, nav-слот).
- ``DiffScrollTabLayout`` — дифференциальный скролл + мастер-скроллбар.
- ``StandardTabLayout`` — стандартный layout с sub-nav и QScrollArea.

См. ADR-127.
"""

from ._abstract_columnar import _AbstractColumnarTabLayout
from .diff_scroll_layout import DiffScrollTabLayout
from .standard_layout import StandardTabLayout

__all__ = [
    "_AbstractColumnarTabLayout",
    "DiffScrollTabLayout",
    "StandardTabLayout",
]
