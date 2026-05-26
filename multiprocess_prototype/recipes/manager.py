"""manager.py — RecipeManager: тонкая application-обёртка над RecipeEngine.

RecipeManager предоставляет CRUD-операции над рецептами и интегрируется
с StateProxy для синхронизации state.recipes.active.

Паттерн логирования: if self._logger: self._logger.log_info(...)
(аналогично RecipeAdapter из Phase 0 — silent fallback при logger=None).

Dict at Boundary: RecipeManager работает с dict (YAML-данные),
не с Pydantic-моделями на границе компонентов.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


class RecipeManager:
    """Тонкая application-обёртка над RecipeEngine.

    Добавляет к базовому RecipeEngine:
    - обновление state.recipes.active через StateProxy при load/set_active
    - метод duplicate (не реализован в RecipeEngine)
    - единое место логирования мутирующих операций

    Args:
        engine: экземпляр RecipeEngine (generic из framework или доменный wrapper).
        state_proxy: опциональный StateProxy для синхронизации state.recipes.active.
                     Если None — state не обновляется.
        logger: опциональный менеджер логирования (LoggerManager или совместимый).
                Если None — логирование отключено (silent fallback).
    """

    def __init__(
        self,
        engine: Any,
        state_proxy: Any | None = None,
        logger: Any | None = None,
    ) -> None:
        self._engine = engine
        self._state_proxy = state_proxy
        self._logger = logger

    # ------------------------------------------------------------------
    # Вспомогательные методы логирования (silent fallback)
    # ------------------------------------------------------------------

    def _log_info(self, msg: str) -> None:
        """Логировать info. Если logger=None — молча."""
        if self._logger is not None:
            self._logger.log_info(msg)

    def _log_warning(self, msg: str) -> None:
        """Логировать warning. Если logger=None — молча."""
        if self._logger is not None:
            self._logger.log_warning(msg)

    def _log_error(self, msg: str) -> None:
        """Логировать error. Если logger=None — молча."""
        if self._logger is not None:
            self._logger.log_error(msg)

    # ------------------------------------------------------------------
    # Вспомогательные методы для state_proxy
    # ------------------------------------------------------------------

    def _update_active_in_state(self, slug: str | None) -> None:
        """Обновить state.recipes.active через StateProxy если доступен."""
        if self._state_proxy is not None:
            self._state_proxy.set("recipes.active", slug)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def list(self) -> list[str]:
        """Список имён доступных рецептов (файлов без .yaml).

        Делегирует в engine.list().

        Returns:
            Сортированный список slug'ов.
        """
        return self._engine.list()

    def load(
        self,
        slug: str,
        remap: dict[str, str] | None = None,
    ) -> list:
        """Загрузить рецепт и обновить state.recipes.active.

        Делегирует в engine.load(slug, remap).
        После успешной загрузки обновляет state_proxy если доступен.

        Args:
            slug: имя рецепта (без .yaml).
            remap: опциональный remap путей.

        Returns:
            Список Delta из engine.load().

        Raises:
            FileNotFoundError: если рецепт не найден.
        """
        deltas = self._engine.load(slug, remap)
        self._update_active_in_state(slug)
        self._log_info(f"RecipeManager: загружен рецепт '{slug}'")
        return deltas

    def save(
        self,
        slug: str,
        paths: list[str] | None = None,
    ) -> None:
        """Сохранить рецепт.

        Делегирует в engine.save(slug, paths).

        Args:
            slug: имя рецепта (без .yaml).
            paths: список config-путей для snapshot. None → DEFAULT_CONFIG_PATHS.
        """
        self._engine.save(slug, paths)
        self._log_info(f"RecipeManager: сохранён рецепт '{slug}'")

    def delete(self, slug: str) -> bool:
        """Удалить рецепт.

        Делегирует в engine.delete(slug).
        Если удалён активный рецепт — сбрасывает state.recipes.active = None.

        Args:
            slug: имя рецепта (без .yaml).

        Returns:
            True если рецепт удалён, False если не существовал.
        """
        was_active = self._engine.get_active() == slug
        result = self._engine.delete(slug)

        if result:
            self._log_info(f"RecipeManager: удалён рецепт '{slug}'")
            if was_active:
                self._update_active_in_state(None)

        return result

    def duplicate(self, source_slug: str, new_slug: str) -> bool:
        """Дублировать рецепт под новым именем.

        Читает YAML source_slug, записывает под new_slug с обновлённым meta.name.

        Edge cases:
        - source_slug пустой → False без исключений
        - source_slug не существует → False
        - new_slug уже занят → False

        Args:
            source_slug: имя исходного рецепта.
            new_slug: имя нового рецепта.

        Returns:
            True если дублирование выполнено успешно, False при ошибке.
        """
        # Проверяем пустые аргументы
        if not source_slug or not new_slug:
            self._log_warning(f"RecipeManager.duplicate: пустой slug (source='{source_slug}', new='{new_slug}')")
            return False

        recipes_dir: Path = self._engine.recipes_dir
        source_path = recipes_dir / f"{source_slug}.yaml"
        target_path = recipes_dir / f"{new_slug}.yaml"

        # Проверяем что source существует
        if not source_path.exists():
            self._log_warning(f"RecipeManager.duplicate: source '{source_slug}' не найден")
            return False

        # Проверяем что target не занят
        if target_path.exists():
            self._log_warning(f"RecipeManager.duplicate: target '{new_slug}' уже существует")
            return False

        # Читаем source
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                recipe_data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as exc:
            self._log_error(f"RecipeManager.duplicate: ошибка чтения '{source_slug}': {exc}")
            return False

        if not isinstance(recipe_data, dict):
            self._log_error(f"RecipeManager.duplicate: некорректный формат рецепта '{source_slug}'")
            return False

        # Создаём копию с обновлённым meta.name
        new_recipe = copy.deepcopy(recipe_data)

        # Обновляем meta.name если поле существует
        if "meta" in new_recipe and isinstance(new_recipe["meta"], dict):
            new_recipe["meta"]["name"] = new_slug
        else:
            # Для v2-формата рецептов: top-level поле name
            new_recipe["name"] = new_slug

        # Записываем под новым именем
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                yaml.dump(new_recipe, f, default_flow_style=False, allow_unicode=True)
        except OSError as exc:
            self._log_error(f"RecipeManager.duplicate: ошибка записи '{new_slug}': {exc}")
            return False

        self._log_info(f"RecipeManager: дублирован рецепт '{source_slug}' → '{new_slug}'")
        return True

    def set_active(self, slug: str) -> bool:
        """Установить рецепт активным.

        Вызывает load(slug) и уведомляет state_proxy.
        Возвращает False если рецепт не найден.

        Args:
            slug: имя рецепта для активации.

        Returns:
            True если успешно, False если рецепт не найден.
        """
        recipes_dir: Path = self._engine.recipes_dir
        recipe_path = recipes_dir / f"{slug}.yaml"

        if not recipe_path.exists():
            self._log_warning(f"RecipeManager.set_active: рецепт '{slug}' не найден")
            return False

        self.load(slug)
        self._log_info(f"RecipeManager: активирован рецепт '{slug}'")
        return True

    def get_active(self) -> str | None:
        """Имя текущего активного рецепта (или None).

        Делегирует в engine.get_active().

        Returns:
            slug активного рецепта или None.
        """
        return self._engine.get_active()

    def is_dirty(self) -> bool:
        """True если config изменился после загрузки рецепта.

        Делегирует в engine.is_dirty().

        Returns:
            True если есть несохранённые изменения.
        """
        return self._engine.is_dirty()

    @property
    def recipes_dir(self) -> Path:
        """Директория с YAML-файлами рецептов.

        Делегирует в engine.recipes_dir.

        Returns:
            Path к директории рецептов.
        """
        return self._engine.recipes_dir

    def read_recipe(self, slug: str) -> dict | None:
        """Прочитать YAML рецепта по slug.

        Инкапсулирует чтение файла — presenter не работает с путями напрямую.

        Args:
            slug: имя рецепта (без .yaml).

        Returns:
            dict с данными рецепта или None если файл не найден / невалиден.
        """
        import yaml  # noqa: PLC0415

        recipe_path = self._engine.recipes_dir / f"{slug}.yaml"
        if not recipe_path.exists():
            return None
        try:
            with open(recipe_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, dict) else None
        except (yaml.YAMLError, OSError) as exc:
            self._log_error(f"RecipeManager.read_recipe: ошибка чтения '{slug}': {exc}")
            return None


__all__ = ["RecipeManager"]
