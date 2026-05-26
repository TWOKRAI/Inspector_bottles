# -*- coding: utf-8 -*-
"""RecipesPresenter — бизнес-логика таба рецептов (MVP).

Pure Python, без Qt-импортов. Управляет CRUD над RecipeManager:
- load() / on_select() / on_create() / on_duplicate()
- on_delete() / on_set_active() / on_open_in_pipeline()

«Dict at Boundary»: replace_blueprint_fn принимает и возвращает dict.
Логирование: if self._logger: self._logger.log_info(...) — silent при logger=None.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.6
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from multiprocess_prototype.recipes.manager import RecipeManager

if TYPE_CHECKING:
    from .view import IRecipesView


def _slugify(name: str) -> str:
    """Преобразовать произвольное имя в безопасный slug.

    Правила:
    - Перевести в нижний регистр.
    - Заменить пробелы и специальные символы на '_'.
    - Оставить только [a-z0-9_-].
    - Убрать дублирующиеся '_' и '-'.
    - Обрезать до 80 символов.

    Args:
        name: произвольная строка имени.

    Returns:
        Безопасный slug или пустую строку если имя содержит только спецсимволы.
    """
    slug = name.lower()
    # Пробелы → '_'
    slug = slug.replace(" ", "_")
    # Убрать все символы не из [a-z0-9_-]
    slug = re.sub(r"[^a-z0-9_\-]", "_", slug)
    # Схлопнуть множественные '_' и '-'
    slug = re.sub(r"[_\-]{2,}", "_", slug)
    # Убрать ведущие/хвостовые '_' и '-'
    slug = slug.strip("_-")
    return slug[:80]


class RecipesPresenter:
    """Presenter для RecipesTab.

    Содержит всю бизнес-логику работы с рецептами v2 (blueprint-based CRUD).
    View получает обновления только через методы IRecipesView.
    Qt-зависимостей нет — presenter полностью тестируется без QApplication.

    Attributes:
        _recipe_manager: RecipeManager (CRUD поверх RecipeEngine).
        _view: реализация IRecipesView (Qt-виджет или mock в тестах).
        _replace_blueprint_fn: callback replace_blueprint → dict result.
                               None → set_active работает без перезапуска процессов.
        _logger: опциональный логгер (LoggerManager или совместимый).
        _selected_slug: текущий выбранный slug в nav-списке.
    """

    def __init__(
        self,
        recipe_manager: RecipeManager,
        view: "IRecipesView",
        replace_blueprint_fn: Callable[[dict], dict] | None = None,
        logger: Any | None = None,
    ) -> None:
        """Инициализировать presenter.

        Args:
            recipe_manager: RecipeManager с доступом к CRUD и engine.
            view: реализация IRecipesView.
            replace_blueprint_fn: опциональный callback для замены blueprint
                при set_active (ProcessManager.replace_blueprint). None →
                только state обновляется без перезапуска процессов.
            logger: опциональный менеджер логирования (silent при None).
        """
        self._recipe_manager = recipe_manager
        self._view = view
        self._replace_blueprint_fn = replace_blueprint_fn
        self._logger = logger
        self._selected_slug: str | None = None

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
    # Загрузка списка
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Загрузить список рецептов и обновить nav в view.

        Сбрасывает выбор (set_buttons_state → False, False).
        """
        slugs = self._recipe_manager.list()
        self._view.refresh_list(slugs)
        self._view.set_buttons_state(False, False)
        self._log_info(f"RecipesPresenter.load: {len(slugs)} рецептов")

    # ------------------------------------------------------------------
    # Выбор рецепта
    # ------------------------------------------------------------------

    def on_select(self, slug: str | None) -> None:
        """Обработать выбор slug'а в nav-списке.

        Args:
            slug: slug выбранного рецепта или None при снятии выбора.
        """
        if slug is None:
            self._selected_slug = None
            self._view.show_recipe(None, None)
            self._view.set_buttons_state(False, False)
            return

        self._selected_slug = slug

        # Читаем YAML через публичный API RecipeManager (не трогаем _engine)
        data = self._recipe_manager.read_recipe(slug)
        if data is None:
            self._view.show_recipe(slug, None)
            self._view.show_error("Рецепт не найден")
            self._log_warning(f"RecipesPresenter.on_select: '{slug}' не найден или нечитаем")
            return

        active = self._recipe_manager.get_active()
        self._view.show_recipe(slug, data)
        self._view.set_buttons_state(True, slug == active)
        self._log_info(f"RecipesPresenter.on_select: выбран '{slug}', active='{active}'")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def on_create(self, name: str, description: str) -> None:
        """Создать новый рецепт из имени и описания.

        Генерирует slug из name (slugify), создаёт YAML с пустым blueprint,
        затем вызывает load() для обновления списка.

        Args:
            name: человекочитаемое имя рецепта.
            description: описание рецепта.
        """
        slug = _slugify(name)
        if not slug:
            self._view.show_error("Имя рецепта содержит только недопустимые символы")
            self._log_warning(f"RecipesPresenter.on_create: пустой slug из name='{name}'")
            return

        # Используем публичное свойство recipes_dir (не _engine)
        recipes_dir: Path = self._recipe_manager.recipes_dir
        target_path = recipes_dir / f"{slug}.yaml"

        if target_path.exists():
            self._view.show_error(f"Рецепт '{slug}' уже существует")
            self._log_warning(f"RecipesPresenter.on_create: '{slug}' уже существует")
            return

        # Создаём пустой рецепт v2 с заглушечным blueprint
        recipe_data = {
            "version": 2,
            "name": name,
            "description": description,
            "blueprint": {
                "processes": [],
                "wires": [],
            },
            "active_services": [],
            "display_bindings": [],
        }

        try:
            with open(target_path, "w", encoding="utf-8") as f:
                yaml.dump(recipe_data, f, default_flow_style=False, allow_unicode=True)
        except OSError as exc:
            self._view.show_error(f"Ошибка создания рецепта: {exc}")
            self._log_error(f"RecipesPresenter.on_create: ошибка записи '{slug}': {exc}")
            return

        self._log_info(f"RecipesPresenter.on_create: создан '{slug}' (name='{name}')")
        self.load()

    def on_duplicate(self, slug: str | None = None) -> None:
        """Дублировать рецепт с суффиксом _copy.

        Args:
            slug: slug для дублирования. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_duplicate: нет выбранного рецепта")
            return

        # Auto-increment: пробуем _copy, _copy_2 ... _copy_99
        new_slug: str | None = None
        base_copy = f"{target_slug}_copy"
        if self._recipe_manager.read_recipe(base_copy) is None:
            new_slug = base_copy
        else:
            for n in range(2, 100):
                candidate = f"{target_slug}_copy_{n}"
                if self._recipe_manager.read_recipe(candidate) is None:
                    new_slug = candidate
                    break

        if new_slug is None:
            self._view.show_error("Слишком много копий рецепта")
            self._log_warning(f"RecipesPresenter.on_duplicate: все суффиксы заняты для '{target_slug}'")
            return

        result = self._recipe_manager.duplicate(target_slug, new_slug)

        if result:
            self._log_info(f"RecipesPresenter.on_duplicate: '{target_slug}' → '{new_slug}'")
            self.load()
        else:
            self._view.show_error(f"Не удалось дублировать рецепт '{target_slug}'")
            self._log_warning(f"RecipesPresenter.on_duplicate: дублирование '{target_slug}' не удалось")

    def on_delete(self, slug: str | None = None) -> None:
        """Удалить рецепт после подтверждения пользователем.

        Args:
            slug: slug для удаления. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_delete: нет выбранного рецепта")
            return

        confirmed = self._view.confirm_delete(target_slug)
        if not confirmed:
            self._log_info(f"RecipesPresenter.on_delete: '{target_slug}' — удаление отменено")
            return

        self._recipe_manager.delete(target_slug)

        # Сбрасываем выбор если удалили выбранный
        if self._selected_slug == target_slug:
            self._selected_slug = None

        self._log_info(f"RecipesPresenter.on_delete: удалён '{target_slug}'")
        self.load()

    def on_set_active(self, slug: str | None = None) -> None:
        """Сделать рецепт активным и вызвать replace_blueprint если задан.

        Порядок:
        1. recipe_manager.set_active(slug).
        2. Если _replace_blueprint_fn задан — читает blueprint из YAML и вызывает его.
        3. Если result["success"] → load() + set_buttons_state(True, True).
        4. Если ошибка → view.show_error.

        Args:
            slug: slug для активации. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_set_active: нет выбранного рецепта")
            return

        # Активируем через RecipeManager
        success = self._recipe_manager.set_active(target_slug)
        if not success:
            self._view.show_error(f"Рецепт '{target_slug}' не найден")
            self._log_warning(f"RecipesPresenter.on_set_active: set_active=False для '{target_slug}'")
            return

        self._log_info(f"RecipesPresenter.on_set_active: активирован '{target_slug}'")

        # Если задан replace_blueprint_fn — выполняем горячую замену
        if self._replace_blueprint_fn is not None:
            # Читаем через публичный API RecipeManager (не _engine)
            recipe_data = self._recipe_manager.read_recipe(target_slug)
            if recipe_data is None:
                self._view.show_error(f"Ошибка чтения blueprint рецепта '{target_slug}'")
                self._log_error(f"RecipesPresenter.on_set_active: не удалось прочитать '{target_slug}'")
                return

            # Dict at Boundary: передаём dict, не Pydantic-модель
            blueprint_dict: dict = recipe_data.get("blueprint", {})

            try:
                result = self._replace_blueprint_fn(blueprint_dict)
            except Exception as exc:  # noqa: BLE001
                self._view.show_error(f"Ошибка replace_blueprint: {exc}")
                self._log_error(f"RecipesPresenter.on_set_active: исключение replace_blueprint: {exc}")
                return

            if not isinstance(result, dict) or not result.get("success"):
                error_msg = (
                    result.get("error", "Ошибка replace_blueprint")
                    if isinstance(result, dict)
                    else "Ошибка replace_blueprint"
                )
                self._view.show_error(error_msg)
                self._log_error(f"RecipesPresenter.on_set_active: replace_blueprint failed: {error_msg}")
                return

            self._log_info(f"RecipesPresenter.on_set_active: replace_blueprint успешен для '{target_slug}'")

        self.load()
        self._view.set_buttons_state(True, True)

    def on_open_in_pipeline(self, slug: str | None = None) -> None:
        """Открыть рецепт в Pipeline (заглушка — Task 7a).

        Args:
            slug: slug для открытия. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        # TODO: Task 7a — реализовать открытие в PipelineTab
        self._log_info(f"RecipesPresenter.on_open_in_pipeline: TBD (slug='{target_slug}')")
