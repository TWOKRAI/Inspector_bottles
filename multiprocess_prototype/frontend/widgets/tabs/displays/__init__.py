"""displays — таб управления дисплеями v2 (MVP pattern).

Публичный API:
    - DisplaysTab      — основной виджет (BaseListNavTab + IDisplaysView)
    - DisplaysPresenter — бизнес-логика (pure Python, без Qt)
    - IDisplaysView    — Protocol для structural subtyping
"""

from .presenter import DisplaysPresenter
from .tab import DisplaysTab
from .view import IDisplaysView

__all__ = [
    "DisplaysTab",
    "DisplaysPresenter",
    "IDisplaysView",
]
