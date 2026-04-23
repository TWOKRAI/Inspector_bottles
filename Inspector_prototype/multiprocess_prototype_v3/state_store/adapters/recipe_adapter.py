"""RecipeAdapter — тонкий адаптер RecipeManagerProtocol → RecipeEngine.

Виджеты вызывают старый API (list_slots/get_slot/save_slot/delete_slot),
данные идут через StateStore (RecipeEngine → TreeStore → YAML).

Адаптер не хранит собственного состояния рецептов:
- list_slots()    → recipe_engine.list()
- save_slot()     → данные кладутся во временный TreeStore → recipe_engine.save()
- get_slot()      → читает YAML-файл напрямую через recipe_engine
- delete_slot()   → recipe_engine.delete()
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from state_store.recipes.recipe_engine import RecipeEngine

logger = logging.getLogger(__name__)


class RecipeAdapter:
    """Адаптер RecipeManagerProtocol → RecipeEngine.

    Виджеты вызывают старый API, данные идут через StateStore.

    Args:
        recipe_engine: готовый RecipeEngine с подключённым TreeStore.
    """

    def __init__(self, recipe_engine: RecipeEngine) -> None:
        self._engine = recipe_engine

    # ------------------------------------------------------------------
    # RecipeManagerProtocol-совместимый API
    # ------------------------------------------------------------------

    def list_slots(self) -> List[str]:
        """Список имён доступных рецептов.

        Делегирует в recipe_engine.list() → файлы *.yaml в recipes_dir.
        """
        return self._engine.list()

    def get_slot(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить данные рецепта по имени.

        Читает YAML-файл рецепта напрямую и возвращает секцию 'data'.
        Возвращает None если рецепт не найден.

        Args:
            name: имя рецепта (без расширения .yaml).

        Returns:
            dict с данными рецепта, или None если не найден.
        """
        file_path = self._engine._recipes_dir / f"{name}.yaml"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                recipe = yaml.safe_load(f)
            data = recipe.get("data", {}) if isinstance(recipe, dict) else {}
            return copy.deepcopy(data)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Ошибка чтения рецепта '%s': %s", name, exc)
            return None

    def save_slot(self, name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Сохранить рецепт под именем name.

        Если data передана — она записывается как YAML напрямую (без TreeStore),
        чтобы не перетирать текущее состояние store.
        Если data=None — делает snapshot текущего store через recipe_engine.save().

        Args:
            name: имя слота (имя файла без .yaml).
            data: словарь данных рецепта, или None для snapshot из store.
        """
        if data is None:
            # Snapshot текущего состояния store
            self._engine.save(name)
            logger.info("RecipeAdapter: snapshot store → рецепт '%s'", name)
            return

        # Записываем переданные данные напрямую в YAML,
        # сохраняя формат, совместимый с RecipeEngine.
        from datetime import datetime, timezone

        recipe = {
            "meta": {
                "name": name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "description": "",
            },
            "data": copy.deepcopy(data),
        }
        file_path = self._engine._recipes_dir / f"{name}.yaml"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(recipe, f, default_flow_style=False, allow_unicode=True)
            logger.info("RecipeAdapter: сохранён рецепт '%s' (data-режим)", name)
        except OSError as exc:
            logger.error("RecipeAdapter: ошибка записи рецепта '%s': %s", name, exc)

    def delete_slot(self, name: str) -> bool:
        """Удалить рецепт по имени.

        Делегирует в recipe_engine.delete().

        Args:
            name: имя слота.

        Returns:
            True если удалён, False если не существовал.
        """
        return self._engine.delete(name)
