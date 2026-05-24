"""recipe_adapter.py — Утилитный wrapper: RecipeManagerProtocol → RecipeEngine.

НЕ является StateAdapter — не подписывается на StateProxy, не наследует StateAdapterBase.
Это тонкий адаптер старого API виджетов (list_slots/get_slot/save_slot/delete_slot)
поверх RecipeEngine из framework.

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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml

from multiprocess_prototype.backend.state.recipes.recipe_engine import RecipeEngine


class RecipeAdapter:
    """Утилитный wrapper: адаптер RecipeManagerProtocol → RecipeEngine.

    Не является StateAdapter (не подписывается на StateProxy).
    Виджеты вызывают старый API, данные идут через StateStore.

    Args:
        recipe_engine: готовый RecipeEngine с подключённым TreeStore.
        logger: менеджер логирования (LoggerManager или совместимый).
                Если None — методы логирования ничего не делают (silent fallback).
    """

    def __init__(self, recipe_engine: RecipeEngine, logger: Any | None = None) -> None:
        self._engine = recipe_engine
        self._logger = logger

    # ------------------------------------------------------------------
    # Вспомогательные методы логирования (silent fallback)
    # ------------------------------------------------------------------

    def _log_info(self, msg: str) -> None:
        """Логировать info через инжектированный logger. Если None — молча."""
        if self._logger is not None:
            self._logger.log_info(msg)

    def _log_warning(self, msg: str) -> None:
        """Логировать warning через инжектированный logger. Если None — молча."""
        if self._logger is not None:
            self._logger.log_warning(msg)

    def _log_error(self, msg: str) -> None:
        """Логировать error через инжектированный logger. Если None — молча."""
        if self._logger is not None:
            self._logger.log_error(msg)

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
            self._log_warning(f"Ошибка чтения рецепта '{name}': {exc}")
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
            self._log_info(f"RecipeAdapter: snapshot store → рецепт '{name}'")
            return

        # Записываем переданные данные напрямую в YAML,
        # сохраняя формат, совместимый с RecipeEngine.
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
            self._log_info(f"RecipeAdapter: сохранён рецепт '{name}' (data-режим)")
        except OSError as exc:
            self._log_error(f"RecipeAdapter: ошибка записи рецепта '{name}': {exc}")

    def delete_slot(self, name: str) -> bool:
        """Удалить рецепт по имени.

        Делегирует в recipe_engine.delete().

        Args:
            name: имя слота.

        Returns:
            True если удалён, False если не существовал.
        """
        return self._engine.delete(name)


__all__ = ["RecipeAdapter"]
