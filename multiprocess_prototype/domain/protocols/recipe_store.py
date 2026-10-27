# -*- coding: utf-8 -*-
"""
domain/protocols/recipe_store.py — Protocol для доступа к рецептам.

RecipeStore предоставляет ДВА уровня доступа:
  1. Recipe entity (денормализованный вид) — read/write для domain-логики.
  2. Raw dict (исходная YAML-структура) — read_raw/save_raw для blueprint-persistence,
     где presenter'ам нужна полная YAML-структура (data/blueprint/display_bindings/
     gui_positions/version/name/description).

Phase C создал адаптер RecipeStoreFromManager поверх существующего RecipeManager.
Phase F расширил Protocol: + read_raw/save_raw/duplicate/deactivate, set_active -> bool.
C-30 (Task 1.7): оптимистичная ревизия — чтения возвращают ``(тело, rev)``, записи принимают
``expected_rev`` и возвращают новый ``rev``; ``RecipeConflict`` (framework ``recipe``) пробрасывается.
"""

from __future__ import annotations

from typing import Protocol

from ..entities.recipe import Recipe


class RecipeStore(Protocol):
    """Контракт доступа к рецептам (entity + raw dict).

    Реализации: RecipeStoreFromManager (adapter), FakeRecipeStore (тесты).
    """

    def list(self) -> tuple[str, ...]:
        """Вернуть список slug'ов всех доступных рецептов."""
        ...

    def read(self, slug: str) -> Recipe | None:
        """Прочитать рецепт по slug как Recipe entity. Возвращает None если не найден."""
        ...

    def write(self, slug: str, recipe: Recipe, *, expected_rev: str | None = None) -> str:
        """Сохранить рецепт по slug (создать или перезаписать) — денормализованный формат.

        Pre: ``expected_rev`` — ``rev`` чтения, на котором основано изменение; ``None`` — стор берёт
        ``rev`` своего чтения внутри операции (для нового рецепта: ``(None, None)`` → создание).
        Post: возвращает новый ``rev``, если рецепт изменился; холостая запись (тело не изменилось) —
        прежний ``rev``, без новой версии. Raises: ``RecipeConflict`` при ``expected_rev`` ≠ ``rev`` рецепта
        (рецепт изменён с момента чтения; запись не выполнена).
        """
        ...

    def delete(self, slug: str) -> None:
        """Удалить рецепт по slug."""
        ...

    def get_active(self) -> str | None:
        """Вернуть slug активного рецепта или None."""
        ...

    def set_active(self, slug: str | None) -> bool:
        """Установить активный рецепт. slug=None сбрасывает (через deactivate). Вернуть True при успехе."""
        ...

    def deactivate(self) -> None:
        """Сбросить активный рецепт."""
        ...

    def duplicate(self, slug: str, new_slug: str) -> bool:
        """Дублировать рецепт. True если успех, False при ошибке."""
        ...

    def read_raw(self, slug: str) -> dict | None:
        """Прочитать raw YAML dict (полная структура). None если не найден."""
        ...

    def read_raw_with_rev(self, slug: str) -> tuple[dict | None, str | None]:
        """Прочитать raw dict и ``rev`` одного чтения.

        Post: ``(тело, rev)``; рецепта нет — ``(None, None)``. ``rev`` передаётся в ``expected_rev`` записи.
        """
        ...

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        """Прочитать рецепт в канонической форме (design.md §10) и ``rev`` того же чтения.

        Post: ``(doc, rev)``; рецепта нет — ``(None, None)``. Тело и ``rev`` — одно чтение.
        """
        ...

    def save_raw(
        self,
        slug: str,
        data: dict,
        *,
        expected_rev: str | None = None,
        layout: tuple[dict[str, list[float]], list[str]] | None = None,
    ) -> str:
        """Записать raw dict в файл рецепта (минимальная правка, не перезапись).

        Pre: ``expected_rev`` — ``rev`` чтения-основания; ``None`` — стор берёт ``rev`` своего чтения
        внутри операции (новый рецепт: ``(None, None)`` → создание). ``layout`` = ``(positions,
        locked_nodes)`` — раскладка пишется той же записью, что и топология (design.md §9.5).
        Post: возвращает новый ``rev``, если тело изменилось; холостая запись — прежний ``rev``. Топология и
        раскладка — одна версия. Пустая коллекция раскладки, которой не было в рецепте, не создаётся.
        Raises: ``RecipeConflict`` при ``expected_rev`` ≠ ``rev`` рецепта (запись не выполнена);
        ``ValueError`` — ``layout`` задан, а в ``data`` нет ``blueprint``-mapping.
        """
        ...

    def save_layout(
        self,
        slug: str,
        positions: dict[str, list[float]],
        locked_nodes: list[str],
        *,
        expected_rev: str | None = None,
    ) -> str | None:
        """Точечно сохранить GUI-layout (positions + locked_nodes) в blueprint.metadata.

        В отличие от save_raw, НЕ перезаписывает весь blueprint — сохраняет комментарии
        рецепта (per-node ``# --- ... ---`` и т.п.). Для авто-персиста layout при
        перетаскивании/фиксации нод (free-layout): частый тихий вызов не должен портить
        документ.

        Pre: ``expected_rev`` как у ``save_raw``. Post (как у ``RecipeManager.save_layout``):
          - рецепта нет, ``expected_rev=None`` -> ``None`` (писать нечего);
          - рецепта нет, ``expected_rev`` задан -> ``RecipeConflict`` (current_rev ``None``);
          - ``expected_rev`` ≠ ``rev`` рецепта -> ``RecipeConflict`` (в том числе у рецепта без blueprint);
          - нет вложенного blueprint-mapping -> записи нет, текущий ``rev``;
          - раскладка не изменилась -> записи нет, прежний ``rev``; иначе новый ``rev``.
        Пустая коллекция, которой не было в рецепте, не создаётся.
        """
        ...


__all__ = [
    "RecipeStore",
]
