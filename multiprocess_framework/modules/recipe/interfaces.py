"""Публичный контракт recipe-модуля.

Единственный файл, от которого разрешено зависеть другим модулям.

Модуль `recipe` — крыша над управлением рецептами (snapshot config-ветвей,
detect формата, миграции через callbacks, CRUD-менеджер). Он НЕ знает о доменных
схемах приложения (cameras/robot/…): доменные пути и миграции инжектируются
(ADR-SS-003, ADR-SS-011, ADR-RCP-001).

Контракты здесь описаны в стиле Design-by-Contract (Pre/Post/Invariants в
докстрингах) — исполняемо проверяются в `tests/test_contract.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ContextManager, Protocol, runtime_checkable


@runtime_checkable
class StoreProtocol(Protocol):
    """Контракт реактивного config-store, к которому применяются рецепты.

    Доменно-нейтральный срез `TreeStore` (state_store_module), достаточный для
    RecipeEngine. Модуль `recipe` типизирует store через этот Protocol и НЕ
    импортирует state_store_module — так избегается цикл recipe ↔ state_store.
    """

    def has(self, path: str) -> bool:
        """True если по dot-пути есть значение."""
        ...

    def get(self, path: str, default: Any = None) -> Any:
        """Значение по dot-пути (или default)."""
        ...

    def transaction(self, label: str = "") -> ContextManager[Any]:
        """Контекст-менеджер батча: yield tx с `.set(path, value)` и `.deltas`."""
        ...


@runtime_checkable
class RecipeEngineProtocol(Protocol):
    """Контракт движка рецептов — snapshot/restore config-ветвей.

    Рецепт = snapshot config-ветвей в YAML. load() применяет через одну
    Transaction (батч дельт подписчикам).
    """

    def save(self, name: str, paths: list[str] | None = None) -> None:
        """Сохранить рецепт (snapshot путей).

        Pre:
          - name — непустое имя файла (без .yaml).
        Post:
          - файл recipes_dir/{name}.yaml создан с секциями meta+data.
          - paths=None → snapshot default_paths движка (может быть пустым).
        """
        ...

    def load(self, name: str, remap: dict[str, str] | None = None) -> list:
        """Загрузить рецепт и применить к store.

        Pre:
          - рецепт recipes_dir/{name}.yaml существует (иначе FileNotFoundError).
        Post:
          - config-snapshot v1/v2: значения применены к store, get_active()==name.
          - v3-blueprint (top-level `blueprint`): помечен active БЕЗ replay/migrate/
            перезаписи файла, возвращён пустой список дельт.
        """
        ...

    def list(self) -> list[str]:
        """Отсортированный список имён рецептов."""
        ...

    def delete(self, name: str) -> bool:
        """Удалить рецепт. True если удалён (сбрасывает active при совпадении)."""
        ...

    def get_active(self) -> str | None:
        """Имя последнего загруженного/активированного рецепта (или None)."""
        ...

    def set_active(self, name: str) -> bool:
        """Пометить рецепт активным — чистый указатель, БЕЗ применения к store."""
        ...

    def deactivate(self) -> None:
        """Сбросить активный рецепт (is_dirty()→False)."""
        ...

    def is_dirty(self) -> bool:
        """True если config изменился после load()."""
        ...

    @property
    def recipes_dir(self) -> Path:
        """Каталог хранения рецептов."""
        ...

    @property
    def doc_type(self) -> str | None:
        """Namespace реестра миграций для дефолтного run_chain (или None).

        Если задан и migration_fn не инжектирован — load() мигрирует устаревший
        рецепт через зарегистрированные шаги (ADR-RCP-003, C3). None → дефолтная
        миграция из реестра отключена (работает только явная инъекция callbacks).
        """
        ...


@runtime_checkable
class RecipeManagerProtocol(Protocol):
    """Контракт CRUD-менеджера рецептов поверх RecipeEngine.

    Добавляет к движку: синхронизацию state.recipes.active через StateProxy,
    duplicate(), логирование мутаций, read_recipe().
    """

    def list(self) -> list[str]:
        """Список slug'ов рецептов."""
        ...

    def load(self, slug: str, remap: dict[str, str] | None = None) -> list:
        """Загрузить рецепт и обновить state.recipes.active."""
        ...

    def save(self, slug: str, paths: list[str] | None = None) -> None:
        """Сохранить рецепт."""
        ...

    def delete(self, slug: str) -> bool:
        """Удалить рецепт (сброс active в state при удалении активного)."""
        ...

    def duplicate(self, source_slug: str, new_slug: str) -> bool:
        """Дублировать рецепт под новым именем.

        Pre:
          - source_slug и new_slug непустые.
          - source существует, target свободен.
        Post:
          - target — копия source с обновлённым именем (meta.name или top-level name).
          - при нарушении Pre → False без исключения.
        """
        ...

    def set_active(self, slug: str) -> bool:
        """Пометить активным (без topology/config side-effect)."""
        ...

    def deactivate(self) -> None:
        """Сбросить активный рецепт + state.recipes.active=None."""
        ...

    def get_active(self) -> str | None:
        """Slug активного рецепта или None."""
        ...

    def is_dirty(self) -> bool:
        """True если есть несохранённые изменения config."""
        ...

    def read_recipe(self, slug: str) -> dict | None:
        """Прочитать YAML рецепта (dict) или None."""
        ...

    @property
    def recipes_dir(self) -> Path:
        """Каталог хранения рецептов."""
        ...


__all__ = [
    "StoreProtocol",
    "RecipeEngineProtocol",
    "RecipeManagerProtocol",
]
