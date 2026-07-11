"""manager.py — доменный шим над generic-RecipeManager из модуля `recipe`.

Generic-реализация — `multiprocess_framework.modules.recipe.manager`
(консолидация C1, ADR-RCP-001/002). Здесь — тонкий шим, сохраняющий путь импорта
`multiprocess_prototype.recipes.manager` и инжектирующий прикладной
comment-preserving writer (`yaml_io.update_yaml_preserving`, ruamel round-trip) в
duplicate(). Без инъекции generic-менеджер использует plain-PyYAML (без комментариев);
прототип комментарии сохраняет.

Consolidation `yaml_io`/duplicate во фреймворк — задача C3.
"""

from __future__ import annotations

from typing import Any, Callable
from pathlib import Path

from multiprocess_framework.modules.recipe.manager import RecipeManager as _RecipeManager
from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving


class RecipeManager(_RecipeManager):
    """Доменный шим: инжектирует comment-preserving yaml_updater по умолчанию."""

    def __init__(
        self,
        engine: Any,
        state_proxy: Any | None = None,
        logger: Any | None = None,
        yaml_updater: Callable[[str | Path, dict], None] | None = None,
    ) -> None:
        if yaml_updater is None:
            yaml_updater = update_yaml_preserving
        super().__init__(
            engine,
            state_proxy=state_proxy,
            logger=logger,
            yaml_updater=yaml_updater,
        )


__all__ = ["RecipeManager"]
