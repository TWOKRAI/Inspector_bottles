# -*- coding: utf-8 -*-
"""
adapters/stores/recipe_store.py — RecipeStoreFromManager: domain RecipeStore adapter.

Реализует Protocol RecipeStore из domain/protocols/recipe_store.py
поверх существующего RecipeManager.

Решение Q2 (Variant A): при write() денормализует meta -> top-level
для backward-compat с live YAML reader'ами (legacy формат v2).

Write обходит RecipeManager.save() намеренно — тот выполняет snapshot
config-store ветвей через TreeStore, что неприменимо для domain entity write.

Read делегирует RecipeManager.read_recipe(), который уже читает YAML
и возвращает raw dict. Recipe.from_dict() понимает оба формата
(с meta: и без — top-level name/version/...).

Phase F: + read_raw/save_raw/duplicate/deactivate, set_active -> bool.
Прямой доступ к engine._active_name убран — через RecipeManager.deactivate().

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.5)
      plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md (Task F.4)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from multiprocess_prototype.domain.entities.recipe import Recipe

if TYPE_CHECKING:
    from multiprocess_prototype.recipes.manager import RecipeManager


class RecipeStoreFromManager:
    """Adapter поверх RecipeManager для domain RecipeStore Protocol.

    Q2 (Variant A): при write денормализует meta -> top-level
    для backward-compat с live YAML reader'ами.

    Read использует RecipeManager.read_recipe() (он уже понимает оба формата).
    Write обходит RecipeManager.save() — пишет YAML напрямую.

    Phase F: set_active(None) делегирует в RecipeManager.deactivate() (публичный API).
    """

    def __init__(self, recipe_manager: RecipeManager, recipe_dir: Path) -> None:
        self._rm = recipe_manager
        self._dir = Path(recipe_dir)

    # ------------------------------------------------------------------
    # CRUD (Recipe entity)
    # ------------------------------------------------------------------

    def list(self) -> tuple[str, ...]:
        """Вернуть отсортированный tuple slug'ов всех доступных рецептов."""
        return tuple(sorted(p.stem for p in self._dir.glob("*.yaml")))

    def read(self, slug: str) -> Recipe | None:
        """Прочитать рецепт по slug через RecipeManager.read_recipe().

        RecipeManager.read_recipe() возвращает dict | None.
        Recipe.from_dict() понимает оба формата (meta: и top-level).
        """
        raw = self._rm.read_recipe(slug)
        if raw is None:
            return None
        return Recipe.from_dict(raw)

    def write(self, slug: str, recipe: Recipe) -> None:
        """Записать рецепт в YAML, денормализуя meta -> top-level (Q2 Variant A).

        Обходит RecipeManager.save() — тот делает snapshot config-store,
        а нам нужно записать domain entity как есть. Запись через
        update_yaml_preserving (ruamel) — сохраняет комментарии существующего файла.
        """
        from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving

        data = self._denormalize(recipe.to_dict())
        self._dir.mkdir(parents=True, exist_ok=True)
        update_yaml_preserving(self._dir / f"{slug}.yaml", data)

    def delete(self, slug: str) -> None:
        """Удалить файл рецепта. Если файла нет — молча игнорировать."""
        path = self._dir / f"{slug}.yaml"
        path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Raw dict I/O (Phase F)
    # ------------------------------------------------------------------

    def read_raw(self, slug: str) -> dict | None:
        """Прочитать raw YAML dict (полная структура) через RecipeManager.read_recipe()."""
        return self._rm.read_recipe(slug)

    def save_raw(self, slug: str, data: dict) -> None:
        """Записать top-level ключи рецепта, СОХРАНИВ комментарии (ruamel round-trip).

        merge-семантика: обновляются только переданные top-level ключи (blueprint,
        gui_positions, ...); остальные (name/version/description) и комментарии файла
        не тронуты. Новый файл создаётся из ``data``. Используется presenter'ами для
        сохранения живого графа в рецепт без порчи документа.
        """
        from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving

        self._dir.mkdir(parents=True, exist_ok=True)
        update_yaml_preserving(self._dir / f"{slug}.yaml", data)

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
        """
        result = dict(data)
        meta = result.pop("meta", {})
        if isinstance(meta, dict):
            # Распаковываем все meta-поля на верхний уровень.
            # Порядок: meta-поля идут первыми для читаемости YAML
            denormalized: dict[str, Any] = {}
            for key in ("name", "version", "description", "created_at"):
                if key in meta:
                    denormalized[key] = meta[key]
            # Оставшиеся meta-поля (если появятся в будущем)
            for key, value in meta.items():
                if key not in denormalized:
                    denormalized[key] = value
            # Добавляем остальные поля Recipe (blueprint, active_services, ...)
            denormalized.update(result)
            return denormalized
        return result


__all__ = [
    "RecipeStoreFromManager",
]
