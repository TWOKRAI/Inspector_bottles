# -*- coding: utf-8 -*-
"""
adapters/stores/recipe_store.py — RecipeStoreFromManager: domain RecipeStore adapter.

Реализует Protocol RecipeStore из domain/protocols/recipe_store.py
поверх существующего RecipeManager.

Решение Q2 (Variant A): при создании рецепта денормализует meta -> top-level
для backward-compat с live YAML reader'ами (legacy формат v2).

C-30 (Task 1.1c): стор работает только по slug, весь IO — через RecipeManager (design.md §9.1, §10).
Операция «прочитал -> записал»: ``(doc, rev) = read_canonical(slug)``, правка переносится на ``doc``
(каноническая форма ``N(файл)``), запись — ``patch_recipe(slug, after, expected_rev=...)``; движок
правит файл минимальной дельтой, без шума (комментарии, flow-стиль, порядок ключей, EOL). ``RecipeConflict``
не глотается. Каталог рецептов владеет RecipeManager: ``recipe_dir`` конструктора для IO не используется.

Phase F: + read_raw/save_raw/duplicate/deactivate, set_active -> bool.
Прямой доступ к engine._active_name убран — через RecipeManager.deactivate().

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.5)
      plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md (Task F.4)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.logger_module import get_std_logger
from multiprocess_framework.modules.recipe import RecipeFormatError
from multiprocess_framework.modules.recipe.detect import has_top_level_blueprint
from multiprocess_prototype.domain.entities.recipe import Recipe

if TYPE_CHECKING:
    from multiprocess_prototype.recipes.manager import RecipeManager

logger = get_std_logger(__name__)


class RecipeStoreFromManager:
    """Adapter поверх RecipeManager для domain RecipeStore Protocol (только slug, IO через менеджер).

    Чтения: ``read_raw_with_rev`` / ``read_canonical`` возвращают ``(тело, rev)`` одного чтения.
    Записи: принимают ``expected_rev`` (``None`` — стор берёт ``rev`` своего чтения внутри операции),
    возвращают новый ``rev`` (холостая запись — прежний). ``RecipeConflict`` пробрасывается.

    Phase F: set_active(None) делегирует в RecipeManager.deactivate() (публичный API).
    """

    def __init__(self, recipe_manager: RecipeManager, recipe_dir: Path) -> None:
        self._rm = recipe_manager
        # FREEZE: каталог рецептов владеет RecipeManager; ``_dir`` для IO не используется.
        self._dir = Path(recipe_dir)

    # ------------------------------------------------------------------
    # CRUD (Recipe entity)
    # ------------------------------------------------------------------

    def list(self) -> tuple[str, ...]:
        """Вернуть отсортированный tuple slug'ов всех доступных рецептов (RecipeManager.list())."""
        return tuple(self._rm.list())

    def read(self, slug: str) -> Recipe | None:
        """Прочитать рецепт по slug из канонической формы (``read_canonical``, не из raw).

        Битый файл (не разбирается, корень не mapping, хук отверг тело) -> ``None`` и ``error`` в лог:
        контракт до 1.1c («None если не найден»), потребители (каталог дисплеев, ``ActivateRecipe``)
        не знают ``RecipeFormatError``.
        """
        from multiprocess_prototype.adapters.recipe_canonical import recipe_from_canonical

        try:
            doc, _rev = self._rm.read_canonical(slug)
        except RecipeFormatError as exc:
            logger.error("RecipeStoreFromManager.read: рецепт '%s' не читается: %s", slug, exc)
            return None
        if doc is None:
            return None
        return recipe_from_canonical(doc)

    def write(self, slug: str, recipe: Recipe, *, expected_rev: str | None = None) -> str:
        """Записать рецепт: правка модели переносится на канон файла дельтой (1.1g), одна запись.

        Рецепта нет — создание из ``_denormalize(recipe.to_dict())`` (meta -> top-level, Q2 Variant A),
        верхние ключи проходят ``minimize`` (как вставка в ``recipe_to_canonical``: умолчания модели не пишутся).
        Возвращает новый ``rev`` (холостая запись — прежний). Raises: ``RecipeConflict``.
        """
        from multiprocess_prototype.adapters.recipe_canonical import minimize, recipe_to_canonical

        doc, rev = self._rm.read_canonical(slug)
        if doc is None:
            after = {key: minimize((key,), value) for key, value in self._denormalize(recipe.to_dict()).items()}
        else:
            after = recipe_to_canonical(recipe, doc)
        return self._rm.patch_recipe(slug, after, expected_rev=expected_rev if expected_rev is not None else rev)

    def delete(self, slug: str) -> None:
        """Удалить рецепт через RecipeManager.delete(). Если файла нет — молча игнорировать.

        Побочный эффект менеджера: удаление активного рецепта сбрасывает ``state.recipes.active``.
        """
        self._rm.delete(slug)

    # ------------------------------------------------------------------
    # Raw dict I/O (Phase F)
    # ------------------------------------------------------------------

    def read_raw(self, slug: str) -> dict | None:
        """Прочитать raw YAML dict (полная структура) через RecipeManager.read_recipe()."""
        return self._rm.read_recipe(slug)

    def read_raw_with_rev(self, slug: str) -> tuple[dict | None, str | None]:
        """Raw dict и ``rev`` одного чтения (``RecipeManager.read_recipe_rev``); нет файла — ``(None, None)``."""
        return self._rm.read_recipe_rev(slug)

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        """Каноническое тело ``N(файл)`` и ``rev`` одного чтения (``RecipeManager.read_canonical``)."""
        return self._rm.read_canonical(slug)

    def save_raw(
        self,
        slug: str,
        data: dict,
        *,
        expected_rev: str | None = None,
        layout: tuple[dict[str, list[float]], list[str]] | None = None,
    ) -> str:
        """Записать top-level ключи ``data`` в рецепт минимальной дельтой; вернуть новый ``rev``.

        merge-семантика: ``after = {**канон файла, **data}`` — переданные top-level ключи заменяются,
        остальные не тронуты. Файла нет — создание из ``data``. ``layout`` пишется той же записью.
        Raises: ``RecipeConflict`` (``expected_rev`` не совпал), ``ValueError`` (``layout`` без blueprint).
        """
        doc, rev = self._rm.read_canonical(slug)
        after = {**(doc or {}), **data}
        return self._rm.patch_recipe(
            slug, after, expected_rev=expected_rev if expected_rev is not None else rev, layout=layout
        )

    def save_layout(
        self,
        slug: str,
        positions: dict[str, list[float]],
        locked_nodes: list[str],
        *,
        expected_rev: str | None = None,
    ) -> str | None:
        """Точечно сохранить ``blueprint.metadata.{gui_positions,locked_nodes}`` (RecipeManager.save_layout).

        Комментарии и стиль файла сохраняются. ``expected_rev=None`` — rev своего чтения внутри операции;
        рецепта нет и ``expected_rev=None`` — ``None``.
        Raises: ``RecipeConflict``, ``RecipeFormatError`` (файл устаревшей формы).
        """
        if expected_rev is None:
            # Менеджер запрещает запись по существующему файлу без базовой ревизии: берём rev своего чтения.
            _body, expected_rev = self._rm.read_recipe_rev(slug)
        return self._rm.save_layout(slug, positions, locked_nodes, expected_rev=expected_rev)

    # ------------------------------------------------------------------
    # Active recipe
    # ------------------------------------------------------------------

    def get_active(self) -> str | None:
        """Вернуть slug активного рецепта через RecipeManager.get_active()."""
        return self._rm.get_active()

    def set_active(self, slug: str | None) -> bool:
        """Установить активный рецепт.

        slug != None: делегирует RecipeManager.set_active(slug) -> bool.
        slug == None: делегирует RecipeManager.deactivate() -> True.
        """
        if slug is not None:
            return self._rm.set_active(slug)
        self._rm.deactivate()
        return True

    def deactivate(self) -> None:
        """Сбросить активный рецепт через RecipeManager.deactivate()."""
        self._rm.deactivate()

    # ------------------------------------------------------------------
    # Duplicate (Phase F)
    # ------------------------------------------------------------------

    def duplicate(self, slug: str, new_slug: str) -> bool:
        """Дублировать рецепт через RecipeManager.duplicate()."""
        return self._rm.duplicate(slug, new_slug)

    # ------------------------------------------------------------------
    # Денормализация (Q2 Variant A)
    # ------------------------------------------------------------------

    @staticmethod
    def _denormalize(data: dict[str, Any]) -> dict[str, Any]:
        """Денормализовать meta -> top-level для backward-compat с live YAML.

        Recipe.to_dict() выдаёт: {"meta": {"name": ..., "version": ..., ...}, "blueprint": ..., ...}
        Live YAML формат (v2):   {"name": ..., "version": ..., "blueprint": ..., ...}

        Решение Q2 Variant A: извлечь все поля из meta на верхний уровень,
        удалить ключ meta. Это сохраняет совместимость с:
        - RecipeManager.read_recipe() (raw YAML reader)
        - Recipe.from_dict() (понимает оба формата)
        - Legacy GUI reader'ы (ожидают top-level name/version)

        Порядок ключей в результирующем YAML для читаемости (Task 1.3):
            1. meta-поля (name, version, description, created_at)
            2. displays — определения дисплеев (DisplayDefinition, top-level секция)
            3. blueprint — топология рецепта
            4. остальные поля (active_services, display_bindings, gui_positions, ...)

        Поле ``displays`` (tuple[DisplayDefinition,...]) сохраняется автоматически
        через denormalized.update(result) — оно НЕ входит в meta и не требует
        специальной обработки. Явное позиционирование перед blueprint — только
        для читаемости итогового YAML файла.
        """
        result = dict(data)
        meta = result.pop("meta", {})
        if isinstance(meta, dict):
            # 1. Сначала meta-поля (верхний уровень, читаемость YAML)
            denormalized: dict[str, Any] = {}
            for key in ("name", "version", "description", "created_at"):
                if key in meta:
                    denormalized[key] = meta[key]
            # Оставшиеся meta-поля (если появятся в будущем)
            for key, value in meta.items():
                if key not in denormalized:
                    denormalized[key] = value

            # 2. displays — определения дисплеев рецепта (перед blueprint для читаемости).
            #    Сохраняется как top-level секция, НЕ внутри blueprint.
            #    (blueprint.displays = привязки node_id→display_id — другая секция)
            if "displays" in result:
                denormalized["displays"] = result.pop("displays")

            # 3. blueprint — топология (процессы, провода, привязки дисплеев)
            if has_top_level_blueprint(result):
                denormalized["blueprint"] = result.pop("blueprint")

            # 4. Остальные поля Recipe (active_services, display_bindings, gui_positions, ...)
            denormalized.update(result)
            return denormalized
        return result


__all__ = [
    "RecipeStoreFromManager",
]
