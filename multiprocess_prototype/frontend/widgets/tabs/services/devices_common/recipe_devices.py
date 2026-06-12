# -*- coding: utf-8 -*-
"""RecipeDevicesStore — устройства как top-level секция активного рецепта.

Источник истины набора зарегистрированных устройств — секция ``devices:`` YAML
активного рецепта (решение владельца, план device-tree-recipe, Фаза B). GUI CRUD
редактирует рецепт через этот хелпер; процесс ``devices`` (hub) — runtime-отражение.

Хелпер БЕЗ Qt — чистая обёртка над RecipeStore Protocol (read_raw/save_raw/get_active),
тестируется на tmp-рецепте. Чтение списка при отсутствии активного рецепта возвращает
``[]``; модификация (upsert/remove) без активного рецепта — ``RecipeDevicesError``
(GUI показывает подсказку и блокирует добавление).

Refs: plans/device-tree-recipe.md Фаза B
"""

from __future__ import annotations

from typing import Any, Callable


class RecipeDevicesError(Exception):
    """Операция требует активного рецепта, которого нет (или иной recipe-сбой)."""


class RecipeDevicesStore:
    """CRUD устройств в секции ``devices:`` активного рецепта.

    Args:
        recipe_store:    объект с ``read_raw(slug)``, ``save_raw(slug, data)`` и
                         ``get_active() -> str | None`` (RecipeStore Protocol,
                         напр. ``services.recipes``).
        active_provider: опциональный override провайдера активного slug'а
                         (по умолчанию ``recipe_store.get_active``). Удобно для
                         тестов и для случаев, когда активный рецепт берётся не из
                         store напрямую.
    """

    def __init__(
        self,
        recipe_store: Any,
        *,
        active_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._store = recipe_store
        self._active_provider = active_provider or recipe_store.get_active

    # ------------------------------------------------------------------ #
    # Активный рецепт
    # ------------------------------------------------------------------ #

    def has_active(self) -> bool:
        """Есть ли активный рецепт (можно ли добавлять устройства)."""
        return bool(self._active_provider())

    def _require_active(self) -> str:
        slug = self._active_provider()
        if not slug:
            raise RecipeDevicesError("нет активного рецепта")
        return slug

    # ------------------------------------------------------------------ #
    # Чтение
    # ------------------------------------------------------------------ #

    def list(self, kind: str | None = None) -> list[dict]:
        """Устройства из активного рецепта (опц. фильтр по ``kind``).

        Нет активного рецепта → ``[]`` (не ошибка — список просто пуст).
        """
        slug = self._active_provider()
        if not slug:
            return []
        devices = self._read_devices(slug)
        if kind is not None:
            return [d for d in devices if d.get("kind") == kind]
        return devices

    def get(self, device_id: str) -> dict | None:
        """Одно устройство по id из активного рецепта (или ``None``)."""
        for entry in self.list():
            if entry.get("id") == device_id:
                return entry
        return None

    # ------------------------------------------------------------------ #
    # Запись
    # ------------------------------------------------------------------ #

    def upsert(self, entry: dict) -> None:
        """Добавить или обновить устройство в секции ``devices:`` рецепта.

        Merge по ключу ``id``: существующая запись обновляется поверх (новые поля
        перекрывают старые), новая — добавляется в конец. Запись через
        ``save_raw`` (ruamel round-trip — комментарии рецепта сохраняются).

        Raises:
            RecipeDevicesError: нет активного рецепта или у ``entry`` пустой ``id``.
        """
        slug = self._require_active()
        dev_id = entry.get("id")
        if not dev_id:
            raise RecipeDevicesError("у устройства пустой id — upsert невозможен")

        devices = self._read_devices(slug)
        replaced = False
        for i, existing in enumerate(devices):
            if existing.get("id") == dev_id:
                devices[i] = {**existing, **entry}
                replaced = True
                break
        if not replaced:
            devices.append(dict(entry))

        self._store.save_raw(slug, {"devices": devices})

    def remove(self, device_id: str) -> None:
        """Удалить устройство из секции ``devices:`` рецепта.

        No-op по содержимому, если id не найден (список просто перезаписывается).

        Raises:
            RecipeDevicesError: нет активного рецепта.
        """
        slug = self._require_active()
        devices = [d for d in self._read_devices(slug) if d.get("id") != device_id]
        self._store.save_raw(slug, {"devices": devices})

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _read_devices(self, slug: str) -> list[dict]:
        """Прочитать список устройств из raw рецепта (только валидные dict)."""
        raw = self._store.read_raw(slug) or {}
        devices_raw = raw.get("devices")
        if not isinstance(devices_raw, list):
            return []
        return [d for d in devices_raw if isinstance(d, dict)]


__all__ = ["RecipeDevicesStore", "RecipeDevicesError"]
