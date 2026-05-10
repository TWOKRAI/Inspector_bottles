# multiprocess_prototype/frontend/managers/theme_manager.py
"""ThemeManager — доменный менеджер тем с темой Innotech для Inspector Bottles.

Тонкий subclass ThemeManager из фреймворка с:
- дефолтным путём к styles/ относительно корня прототипа
- провайдером переменных по умолчанию из registers/theme/schemas.py
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.frontend_module.managers import ThemeManager as _ThemeManagerBase
from multiprocess_prototype.registers.theme.schemas import get_default_variables

_STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"


class ThemeManager(_ThemeManagerBase):
    """Менеджер тем с темой Innotech для Inspector Bottles."""

    def __init__(self, styles_dir: Path | None = None) -> None:
        super().__init__(
            styles_dir or _STYLES_DIR,
            default_variables_provider=get_default_variables,
        )
