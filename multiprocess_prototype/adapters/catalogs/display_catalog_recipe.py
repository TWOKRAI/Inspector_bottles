# -*- coding: utf-8 -*-
"""
adapters/catalogs/display_catalog_recipe.py — recipe-scoped адаптер реестра дисплеев.

DisplayCatalogFromRecipe реализует domain Protocol DisplayCatalog, но источником
истины является АКТИВНЫЙ РЕЦЕПТ (через RecipeStore), а НЕ глобальный displays.yaml.

Архитектура (Task 5.1, ADR-130):
  - Источник истины для вкладки «Дисплеи» — секция ``displays`` активного рецепта.
  - list_displays() / resolve() читают recipe.displays активного рецепта.
  - register() / unregister() / persist() мутируют активный рецепт и пишут
    через recipe_store.write(slug, recipe).
  - DisplayRegistry (framework singleton) остаётся для runtime/preview SHM-метаданных
    (наполняется backend'ом в apply_topology — Task 2.2).
  - Render-поля (position/fit/scale/rotate/flip/crop) живут в DisplaySpec/DisplayDefinition
    (domain слой), НЕ в DisplayEntry (framework, generic).

Границы импортов:
    - Разрешено: domain.protocols, domain.entities, adapters.stores
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from pydantic import ValidationError

from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.protocols.display_catalog import (
    DisplayCatalog,
    DisplaySpec,
    definition_to_spec,
    spec_to_definition_dict,
)

if TYPE_CHECKING:
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager

logger = logging.getLogger(__name__)


class DisplayCatalogFromRecipe:
    """Adapter: RecipeStore (активный рецепт) -> DisplayCatalog Protocol.

    Источник истины — секция ``displays`` активного рецепта.
    Persist пишет определения обратно в файл рецепта (через RecipeStore.write),
    НЕ в глобальный displays.yaml.

    DI-зависимости (через конструктор / AppServices):
      - recipe_store: RecipeStoreFromManager — CRUD рецептов (read/write).
      - get_active_slug: Callable[[], str | None] — возвращает slug активного рецепта.
        Реализация: lambda: recipe_store.get_active() или state.recipes.active.

    Edge cases:
      - Нет активного рецепта → list пуст, resolve → None, register → ValueError.
      - Рецепт без секции displays → пустой tuple (создаётся при первом register).

    Пример использования:
        catalog = DisplayCatalogFromRecipe(
            recipe_store=recipes,
            get_active_slug=lambda: recipes.get_active(),
        )
        displays = catalog.list_displays()
        catalog.register(DisplaySpec(display_id="cam1", display_name="Камера 1"))
        catalog.persist()  # Пишет в файл активного рецепта
    """

    def __init__(
        self,
        recipe_store: "RecipeStoreFromManager",
        get_active_slug: Callable[[], str | None],
    ) -> None:
        """Инициализировать recipe-scoped адаптер.

        Args:
            recipe_store: RecipeStore adapter для CRUD рецептов.
            get_active_slug: Callable, возвращающий slug активного рецепта (или None).
        """
        self._store = recipe_store
        self._get_active_slug = get_active_slug

    # ------------------------------------------------------------------ #
    #  Внутренние хелперы                                                  #
    # ------------------------------------------------------------------ #

    def _get_active_displays(self) -> tuple[DisplayDefinition, ...]:
        """Прочитать displays активного рецепта.

        RS-5 (A-7): мягкая деградация — легаси-рецепт со старыми top-level ключами
        (``data:``/``meta:``, не входящими в схему ``Recipe``/``RecipeMeta``,
        ``extra="forbid"``) роняет ``Recipe.from_dict()`` в ``ValidationError``.
        Раньше это всплывало необработанным до Qt-слота ``DisplaysPresenter.load()``
        и ронял вкладку Дисплеи. Теперь — предупреждение в лог модуля, displays
        считаются отсутствующими (как и при отсутствии активного рецепта/секции
        displays), остальная вкладка продолжает работать.

        Returns:
            tuple[DisplayDefinition, ...] — определения дисплеев; () если рецепта
            нет или он не прошёл валидацию.
        """
        slug = self._get_active_slug()
        if slug is None:
            return ()
        try:
            recipe = self._store.read(slug)
        except ValidationError as exc:
            logger.warning(
                "Активный рецепт '%s' не прошёл валидацию (легаси data:/meta:?) — дисплеи не показаны: %s",
                slug,
                exc,
            )
            return ()
        if recipe is None:
            return ()
        return recipe.displays

    # ------------------------------------------------------------------ #
    #  Read (DisplayCatalog Protocol)                                      #
    # ------------------------------------------------------------------ #

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        """Вернуть все дисплеи активного рецепта как DisplaySpec.

        Если активного рецепта нет — возвращает пустой tuple.

        Returns:
            Tuple DisplaySpec для всех определений дисплеев рецепта.
        """
        definitions = self._get_active_displays()
        return tuple(definition_to_spec(d) for d in definitions)

    def resolve(self, display_id: str) -> DisplaySpec | None:
        """Найти дисплей по id в активном рецепте.

        Args:
            display_id: Уникальный идентификатор дисплея.

        Returns:
            DisplaySpec если дисплей найден в активном рецепте, иначе None.
        """
        definitions = self._get_active_displays()
        for d in definitions:
            if d.id == display_id:
                return definition_to_spec(d)
        return None

    # ------------------------------------------------------------------ #
    #  Write (DisplayCatalog Protocol)                                     #
    # ------------------------------------------------------------------ #

    def register(self, spec: DisplaySpec) -> None:
        """Зарегистрировать дисплей в активном рецепте.

        Добавляет DisplayDefinition в секцию displays рецепта и сохраняет.

        Args:
            spec: Domain-спецификация дисплея для регистрации.

        Raises:
            ValueError: если нет активного рецепта или дисплей с таким id уже существует.
        """
        slug = self._get_active_slug()
        if slug is None:
            raise ValueError(
                "Нет активного рецепта — невозможно зарегистрировать дисплей. "
                "Активируйте рецепт перед добавлением дисплеев."
            )
        recipe = self._store.read(slug)
        if recipe is None:
            raise ValueError(f"Активный рецепт '{slug}' не найден в хранилище.")

        # Проверка дубликата id
        existing_ids = {d.id for d in recipe.displays}
        if spec.display_id in existing_ids:
            raise ValueError(f"Display '{spec.display_id}' already registered в рецепте '{slug}'")

        # Создать DisplayDefinition из spec
        defn_dict = spec_to_definition_dict(spec)
        new_defn = DisplayDefinition.from_dict(defn_dict)

        # Обновить рецепт (frozen → пересобрать)
        new_displays = list(recipe.displays) + [new_defn]
        updated = recipe.model_copy(update={"displays": tuple(new_displays)})
        self._store.write(slug, updated)

    def update(self, spec: DisplaySpec) -> bool:
        """Обновить существующее определение дисплея in-place (по display_id).

        В отличие от unregister+register, СОХРАНЯЕТ привязки
        ``blueprint.displays`` (node_id->display_id) и порядок определений —
        важно для toggle enabled и редактирования полей без потери маршрутизации.

        Args:
            spec: новое определение (display_id должен существовать в рецепте).

        Returns:
            True если обновлено, False если рецепта/дисплея нет.
        """
        slug = self._get_active_slug()
        if slug is None:
            return False
        recipe = self._store.read(slug)
        if recipe is None:
            return False

        defn_dict = spec_to_definition_dict(spec)
        new_defn = DisplayDefinition.from_dict(defn_dict)

        found = False
        new_displays: list[DisplayDefinition] = []
        for d in recipe.displays:
            if d.id == spec.display_id:
                new_displays.append(new_defn)
                found = True
            else:
                new_displays.append(d)
        if not found:
            return False

        updated = recipe.model_copy(update={"displays": tuple(new_displays)})
        self._store.write(slug, updated)
        return True

    def unregister(self, display_id: str) -> bool:
        """Удалить дисплей по id из активного рецепта.

        Args:
            display_id: Идентификатор дисплея для удаления.

        Returns:
            True если дисплей удалён, False если не найден или нет рецепта.
        """
        slug = self._get_active_slug()
        if slug is None:
            return False
        recipe = self._store.read(slug)
        if recipe is None:
            return False

        new_displays = [d for d in recipe.displays if d.id != display_id]
        if len(new_displays) == len(recipe.displays):
            return False  # Не найден

        # Также удалить привязки, ссылающиеся на этот display_id
        # (чтобы не нарушить инвариант recipe model_validator)
        new_bindings = [b for b in recipe.blueprint.displays if b.display_id != display_id]
        new_blueprint = recipe.blueprint.model_copy(update={"displays": tuple(new_bindings)})

        updated = recipe.model_copy(
            update={
                "displays": tuple(new_displays),
                "blueprint": new_blueprint,
            }
        )
        self._store.write(slug, updated)
        return True

    def has(self, display_id: str) -> bool:
        """Проверить наличие дисплея по id в активном рецепте.

        Args:
            display_id: Идентификатор дисплея.

        Returns:
            True если дисплей найден в активном рецепте.
        """
        definitions = self._get_active_displays()
        return any(d.id == display_id for d in definitions)

    def persist(self) -> None:
        """Сохранить текущее состояние в файл активного рецепта.

        Recipe-scoped: перечитывает рецепт и пересохраняет (через recipe_store.write).
        Фактически no-op, т.к. register/unregister уже пишут в рецепт.
        Семантика сохранена для совместимости с DisplayCatalog Protocol.

        При отсутствии активного рецепта — no-op с лог-предупреждением.
        """
        slug = self._get_active_slug()
        if slug is None:
            logger.warning("persist() вызван без активного рецепта — no-op")
            return
        recipe = self._store.read(slug)
        if recipe is None:
            logger.warning("persist() — рецепт '%s' не найден — no-op", slug)
            return
        # Перезаписать (сохранить текущее состояние displays в YAML)
        self._store.write(slug, recipe)


# Проверка structural subtyping (import-time)
_: DisplayCatalog = DisplayCatalogFromRecipe.__new__(DisplayCatalogFromRecipe)  # type: ignore[assignment]

__all__ = [
    "DisplayCatalogFromRecipe",
]
