# -*- coding: utf-8 -*-
"""RecipesPresenter — бизнес-логика таба рецептов (MVP).

Pure Python, без Qt-импортов. Управляет CRUD через RecipeStore Protocol:
- load() / on_select() / on_create() / on_duplicate()
- on_delete() / on_set_active() / on_open_in_pipeline()

Task F.4: перешёл с RecipeManager на RecipeStore Protocol.
Presenter больше не трогает файловую систему — вся I/O через store.

«Dict at Boundary»: replace_blueprint_fn принимает и возвращает dict.
Логирование: if self._logger: self._logger.log_info(...) — silent при logger=None.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.6
      plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md Task F.4
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

from multiprocess_prototype.domain.commands import ActivateRecipe
from multiprocess_prototype.domain.errors import DomainError

if TYPE_CHECKING:
    from multiprocess_prototype.domain.protocols.command_dispatcher import CommandDispatcher
    from multiprocess_prototype.domain.protocols.recipe_store import RecipeStore

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

    Task F.4: работает через RecipeStore Protocol (не RecipeManager напрямую).

    Attributes:
        _store: RecipeStore Protocol (CRUD + raw dict + duplicate).
        _view: реализация IRecipesView (Qt-виджет или mock в тестах).
        _replace_blueprint_fn: callback replace_blueprint -> dict result.
                               None -> set_active работает без перезапуска процессов.
        _logger: опциональный логгер (LoggerManager или совместимый).
        _selected_slug: текущий выбранный slug в nav-списке.
    """

    def __init__(
        self,
        store: "RecipeStore",
        view: "IRecipesView",
        replace_blueprint_fn: Callable[[dict], dict] | None = None,
        logger: Any | None = None,
        commands: "CommandDispatcher | None" = None,
    ) -> None:
        """Инициализировать presenter.

        Args:
            store: RecipeStore Protocol с доступом к CRUD и raw-dict I/O.
            view: реализация IRecipesView.
            replace_blueprint_fn: опциональный callback для замены blueprint
                при set_active (ProcessManager.replace_blueprint). None ->
                только state обновляется без перезапуска процессов.
            logger: опциональный менеджер логирования (silent при None).
            commands: domain CommandDispatcher (G.6.5). При наличии активация
                рецепта идёт через dispatch(ActivateRecipe) — валидирует blueprint,
                загружает топологию рецепта в editor (Pipeline reload) и эмитит
                RecipeActivated (cross-tab linking, G.6.6). None → legacy-путь
                (только set_active, без загрузки в editor).
        """
        self._store = store
        self._view = view
        self._replace_blueprint_fn = replace_blueprint_fn
        self._logger = logger
        self._commands = commands
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

        Сбрасывает выбор (set_buttons_state -> False, False).
        """
        slugs = list(self._store.list())
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

        # Читаем raw YAML через RecipeStore Protocol
        data = self._store.read_raw(slug)
        if data is None:
            self._view.show_recipe(slug, None)
            self._view.show_error("Рецепт не найден")
            self._log_warning(f"RecipesPresenter.on_select: '{slug}' не найден или нечитаем")
            return

        active = self._store.get_active()
        self._view.show_recipe(slug, data)
        self._view.set_buttons_state(True, slug == active)
        self._log_info(f"RecipesPresenter.on_select: выбран '{slug}', active='{active}'")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def on_create(self, name: str, description: str) -> None:
        """Создать новый рецепт из имени и описания.

        Генерирует slug из name (slugify), создаёт raw dict с пустым blueprint,
        записывает через store.save_raw(), затем вызывает load() для обновления.

        Args:
            name: человекочитаемое имя рецепта.
            description: описание рецепта.
        """
        slug = _slugify(name)
        if not slug:
            self._view.show_error("Имя рецепта содержит только недопустимые символы")
            self._log_warning(f"RecipesPresenter.on_create: пустой slug из name='{name}'")
            return

        # Проверяем существование через read_raw
        if self._store.read_raw(slug) is not None:
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
            self._store.save_raw(slug, recipe_data)
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
        if self._store.read_raw(base_copy) is None:
            new_slug = base_copy
        else:
            for n in range(2, 100):
                candidate = f"{target_slug}_copy_{n}"
                if self._store.read_raw(candidate) is None:
                    new_slug = candidate
                    break

        if new_slug is None:
            self._view.show_error("Слишком много копий рецепта")
            self._log_warning(f"RecipesPresenter.on_duplicate: все суффиксы заняты для '{target_slug}'")
            return

        result = self._store.duplicate(target_slug, new_slug)

        if result:
            self._log_info(f"RecipesPresenter.on_duplicate: '{target_slug}' -> '{new_slug}'")
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

        self._store.delete(target_slug)

        # Сбрасываем выбор если удалили выбранный
        if self._selected_slug == target_slug:
            self._selected_slug = None

        self._log_info(f"RecipesPresenter.on_delete: удалён '{target_slug}'")
        self.load()

    def on_set_active(self, slug: str | None = None) -> None:
        """Сделать рецепт активным и вызвать replace_blueprint если задан.

        Порядок:
        1. store.set_active(slug) -> bool.
        2. Если _replace_blueprint_fn задан — читает blueprint из raw dict и вызывает его.
        3. Если result["success"] -> load() + set_buttons_state(True, True).
        4. Если ошибка -> view.show_error.

        Args:
            slug: slug для активации. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_set_active: нет выбранного рецепта")
            return

        # G.6.5 (Вариант A): domain dispatch ДО persist — валидирует blueprint
        # рецепта (плагины/дисплеи/циклы), загружает топологию рецепта в editor
        # (Pipeline scene reload через TopologyReplaced) и эмитит RecipeActivated
        # (cross-tab linking, G.6.6). undoable=False — переключение рецепта это
        # смена контекста, а не правка топологии (не попадает в Ctrl+Z-историю).
        # DomainError (рецепт ссылается на неизвестный плагин и т.п.) → graceful.
        if self._commands is not None:
            try:
                self._commands.dispatch(ActivateRecipe(slug=target_slug), undoable=False)
            except DomainError as exc:
                self._view.show_error(f"Не удалось активировать рецепт: {exc}")
                self._log_error(f"RecipesPresenter.on_set_active: ActivateRecipe отклонён: {exc}")
                return

        # Активируем через RecipeStore Protocol
        success = self._store.set_active(target_slug)
        if not success:
            self._view.show_error(f"Рецепт '{target_slug}' не найден")
            self._log_warning(f"RecipesPresenter.on_set_active: set_active=False для '{target_slug}'")
            return

        self._log_info(f"RecipesPresenter.on_set_active: активирован '{target_slug}'")

        # Если задан replace_blueprint_fn — выполняем горячую замену
        if self._replace_blueprint_fn is not None:
            # Читаем raw YAML через RecipeStore Protocol
            recipe_data = self._store.read_raw(target_slug)
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
