# -*- coding: utf-8 -*-
"""
adapters/stores/recipe_store.py — RecipeStoreFromManager: domain RecipeStore adapter.

Реализует Protocol RecipeStore из domain/protocols/recipe_store.py
поверх существующего RecipeManager.

Решение Q2 (Variant A): при write() денормализует meta → top-level
для backward-compat с live YAML reader'ами (legacy формат v2).

Write обходит RecipeManager.save() намеренно — тот выполняет snapshot
config-store ветвей через TreeStore, что неприменимо для domain entity write.
Вместо этого YAML записывается напрямую в recipe_dir / f"{slug}.yaml".

Read делегирует RecipeManager.read_recipe(), который уже читает YAML
и возвращает raw dict. Recipe.from_dict() понимает оба формата
(с meta: и без — top-level name/version/...).

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.5)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from multiprocess_prototype.domain.entities.recipe import Recipe

if TYPE_CHECKING:
    from multiprocess_prototype.recipes.manager import RecipeManager


class RecipeStoreFromManager:
    """Adapter поверх RecipeManager для domain RecipeStore Protocol.

    Q2 (Variant A): при write денормализует meta → top-level
    для backward-compat с live YAML reader'ами.

    Read использует RecipeManager.read_recipe() (он уже понимает оба формата).
    Write обходит RecipeManager.save() — пишет YAML напрямую.

    set_active(None): RecipeManager.set_active() не поддерживает None (только str).
    Adapter обращается к engine._active_name напрямую и обновляет state_proxy
    через RecipeManager._update_active_in_state(None). Это осознанный компромисс
    Phase C — adapter является bridge и знает реализацию RecipeManager.
    В Phase F RecipeManager будет расширен методом deactivate().
    """

    def __init__(self, recipe_manager: RecipeManager, recipe_dir: Path) -> None:
        self._rm = recipe_manager
        self._dir = Path(recipe_dir)

    # ------------------------------------------------------------------
    # CRUD
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
        """Записать рецепт в YAML, денормализуя meta → top-level (Q2 Variant A).

        Обходит RecipeManager.save() — тот делает snapshot config-store,
        а нам нужно записать domain entity как есть.
        """
        data = self._denormalize(recipe.to_dict())
        target = self._dir / f"{slug}.yaml"
        # Убеждаемся что директория существует
        self._dir.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def delete(self, slug: str) -> None:
        """Удалить файл рецепта. Если файла нет — молча игнорировать."""
        path = self._dir / f"{slug}.yaml"
        path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Active recipe
    # ------------------------------------------------------------------

    def get_active(self) -> str | None:
        """Вернуть slug активного рецепта через RecipeManager.get_active()."""
        return self._rm.get_active()

    def set_active(self, slug: str | None) -> None:
        """Установить активный рецепт.

        slug != None: делегирует RecipeManager.set_active(slug) (вызывает load + state).
        slug == None: сбрасывает active напрямую через engine._active_name + state_proxy.

        Компромисс Phase C: RecipeManager не имеет deactivate().
        Adapter обращается к protected attrs engine. Phase F добавит deactivate().
        """
        if slug is not None:
            self._rm.set_active(slug)
        else:
            # Сброс активного рецепта — RecipeManager не поддерживает deactivate(),
            # поэтому обращаемся к engine напрямую (bridge-компромисс Phase C)
            self._rm._engine._active_name = None
            self._rm._update_active_in_state(None)

    # ------------------------------------------------------------------
    # Денормализация (Q2 Variant A)
    # ------------------------------------------------------------------

    @staticmethod
    def _denormalize(data: dict[str, Any]) -> dict[str, Any]:
        """Денормализовать meta → top-level для backward-compat с live YAML.

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
