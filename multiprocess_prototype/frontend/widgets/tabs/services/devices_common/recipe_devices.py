# -*- coding: utf-8 -*-
"""RecipeDevicesStore — устройства как top-level секция активного рецепта.

Источник истины набора зарегистрированных устройств — секция ``devices:`` YAML
активного рецепта (решение владельца, план device-tree-recipe, Фаза B). GUI CRUD
редактирует рецепт через этот хелпер; процесс ``devices`` (hub) — runtime-отражение.

Хелпер БЕЗ Qt — чистая обёртка над RecipeStore Protocol (read_canonical/save_raw/get_active),
тестируется на tmp-рецепте. Запись — ``save_raw(…, expected_rev)`` с базой ревизии ``TopologySession``
(если сессия передана): ручная правка файла до записи — конфликт, а своя запись двигает базу, и Save
редактора не видит ложного конфликта (C-30, Task 1.9). Чтение списка при отсутствии активного рецепта возвращает
``[]``; модификация (upsert/remove) без активного рецепта — ``RecipeDevicesError``
(GUI показывает подсказку и блокирует добавление).

Refs: plans/device-tree-recipe.md Фаза B
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from multiprocess_framework.modules.recipe import RecipeConflict, RecipeFormatError

logger = logging.getLogger(__name__)


class RecipeDevicesError(Exception):
    """Операция требует активного рецепта, которого нет (или иной recipe-сбой)."""


class RecipeDevicesStore:
    """CRUD устройств в секции ``devices:`` активного рецепта.

    Args:
        recipe_store:    объект с ``read_canonical(slug)``, ``save_raw(slug, data, *, expected_rev)``
                         и ``get_active() -> str | None`` (RecipeStore Protocol,
                         напр. ``services.recipes``).
        active_provider: опциональный override провайдера активного slug'а
                         (по умолчанию ``recipe_store.get_active``). Удобно для
                         тестов и для случаев, когда активный рецепт берётся не из
                         store напрямую.
        session:         опционально ``TopologySession`` (duck: ``base_rev_for(slug)`` и
                         ``rebase(slug, rev)``). Запись идёт с базой сессии и двигает её;
                         ``None`` — запись с ``rev`` собственного чтения (тесты, нет сессии).
    """

    def __init__(
        self,
        recipe_store: Any,
        *,
        active_provider: Callable[[], str | None] | None = None,
        session: Any = None,
    ) -> None:
        self._store = recipe_store
        self._session = session
        self._active_provider = active_provider or recipe_store.get_active

    # ------------------------------------------------------------------ #
    # Активный рецепт
    # ------------------------------------------------------------------ #

    def has_active(self) -> bool:
        """Есть ли активный рецепт (можно ли добавлять устройства)."""
        return bool(self._active_provider())

    def active_slug(self) -> str | None:
        """Slug активного рецепта (для origin-тега ``recipe:<slug>``) или None."""
        return self._active_provider()

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
        ``save_raw`` (минимальная дельта — комментарии рецепта сохраняются).

        Raises:
            RecipeDevicesError: нет активного рецепта, у ``entry`` пустой ``id``
                или файл рецепта изменён снаружи (конфликт ревизии).
        """
        slug = self._require_active()
        dev_id = entry.get("id")
        if not dev_id:
            raise RecipeDevicesError("у устройства пустой id — upsert невозможен")

        devices, read_rev = self._read_canonical_devices(slug)
        replaced = False
        for i, existing in enumerate(devices):
            if existing.get("id") == dev_id:
                devices[i] = {**existing, **entry}
                replaced = True
                break
        if not replaced:
            devices.append(dict(entry))

        self._write_devices(slug, devices, read_rev)

    def remove(self, device_id: str) -> None:
        """Удалить устройство из секции ``devices:`` рецепта.

        No-op по содержимому, если id не найден (список просто перезаписывается).

        Raises:
            RecipeDevicesError: нет активного рецепта или файл рецепта изменён снаружи.
        """
        slug = self._require_active()
        devices, read_rev = self._read_canonical_devices(slug)
        devices = [d for d in devices if d.get("id") != device_id]
        self._write_devices(slug, devices, read_rev)

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _read_canonical_devices(self, slug: str) -> tuple[list[dict], str | None]:
        """Список устройств (только валидные dict) и ``rev`` одного чтения канона рецепта.

        Файла нет → ``([], None)``. ``RecipeFormatError`` не перехватывается.
        """
        doc, rev = self._store.read_canonical(slug)
        devices_raw = (doc or {}).get("devices")
        if not isinstance(devices_raw, list):
            return [], rev
        return [d for d in devices_raw if isinstance(d, dict)], rev

    def _read_devices(self, slug: str) -> list[dict]:
        """Список устройств для UI. Битый рецепт → предупреждение (без содержимого файла) и ``[]``.

        ``rev`` не сохраняется: чтение базу не двигает.
        """
        try:
            return self._read_canonical_devices(slug)[0]
        except RecipeFormatError as exc:
            logger.warning("Рецепт '%s' не читается, список устройств пуст: %s", slug, type(exc).__name__)
            return []

    def _write_devices(self, slug: str, devices: list[dict], read_rev: str | None) -> None:
        """Записать ``devices`` с базой сессии (иначе — с ``rev`` своего чтения); базу двигать только если она была."""
        base = self._session.base_rev_for(slug) if self._session is not None else None
        expected = base if base is not None else read_rev
        try:
            new_rev = self._store.save_raw(slug, {"devices": devices}, expected_rev=expected)
        except RecipeConflict as exc:
            raise RecipeDevicesError("Рецепт изменён снаружи — перезагрузите его") from exc
        if base is not None:
            self._session.rebase(slug, new_rev)


__all__ = ["RecipeDevicesStore", "RecipeDevicesError"]
