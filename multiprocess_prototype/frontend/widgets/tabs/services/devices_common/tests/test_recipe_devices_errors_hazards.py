# -*- coding: utf-8 -*-
"""Охранные тесты F3 (Task 1.1): строка ``OSError`` таблицы ``_WRITE_FAILURES`` без chmod и без root-skip.

``test_recipe_devices_errors.py::test_r10`` держит строку ``OSError`` на одном chmod 0o444 и под root
пропускается (``pytest.skip``). Здесь та же строка закреплена двумя тестами, не зависящими от прав файла:

* (а) реальная цепочка: ``os.replace`` бросает ``OSError(ENOSPC)`` посреди атомарной записи;
* (б) подкласс ``PermissionError``, брошенный из ``save_raw``, попадает в строку ``OSError`` (``isinstance``, а не
  ``type(exc) is``).

Ожидаемый текст — литерал, не из кода под тестом.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.recipe import service as _service_module
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
    RecipeDevicesError,
    RecipeDevicesStore,
)

LITERAL_OSERROR = (
    "Не удалось прочитать или записать файл рецепта (например, нет доступа или места на диске) — устройства не изменены"
)
_SLUG = "demo"
_RECIPE_TEXT = (
    "name: Demo\n"
    "version: 1\n"
    "devices:\n"
    "  - id: r1\n"
    "    name: R1\n"
    "    kind: robot\n"
    "blueprint:\n"
    "  processes: []\n"
    "  wires: []\n"
)
_NEW_DEVICE = {"id": "r2", "name": "R2", "kind": "robot"}


class _FakeEngine:
    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir

    def get_active(self) -> str | None:
        return _SLUG


def _build_chain_store(recipes_dir: Path) -> RecipeDevicesStore:
    """Настоящие RecipeManager + RecipeStoreFromManager + RecipeDevicesStore над ``recipes_dir``."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager

    manager = RecipeManager(engine=_FakeEngine(recipes_dir), state_proxy=None, logger=None)
    chain = RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)
    return RecipeDevicesStore(chain, active_provider=lambda: _SLUG)


class _SaveRaisesStore:
    """Фейк RecipeStore: чтение работает, ``save_raw`` бросает заданное исключение."""

    def __init__(self, save_exc: BaseException) -> None:
        self._save_exc = save_exc

    def get_active(self) -> str | None:
        return _SLUG

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        return {"devices": [{"id": "r1", "name": "R1", "kind": "robot"}]}, "0"

    def save_raw(self, slug: str, data: dict, **kwargs: Any) -> str:
        raise self._save_exc


def test_r10b_enospc_from_os_replace_translated_to_oserror_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / f"{_SLUG}.yaml"
    path.write_bytes(_RECIPE_TEXT.encode("utf-8"))
    before = path.read_bytes()
    store = _build_chain_store(tmp_path)
    real_replace = os.replace

    def failing_replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        if Path(dst).name == path.name:
            raise OSError(errno.ENOSPC, "No space left")
        real_replace(src, dst, *args, **kwargs)

    # os.replace зовёт service._atomic_write (tmp + fsync + replace); патч модульного os — только на время теста
    monkeypatch.setattr(_service_module.os, "replace", failing_replace)

    with pytest.raises(RecipeDevicesError) as info:
        store.upsert(dict(_NEW_DEVICE))

    assert str(info.value) == LITERAL_OSERROR
    assert str(tmp_path) not in str(info.value)
    assert path.read_bytes() == before


def test_r10b_permission_error_subclass_from_save_raw_translated_to_oserror_literal() -> None:
    store = RecipeDevicesStore(_SaveRaisesStore(PermissionError("нет прав")), active_provider=lambda: _SLUG)

    with pytest.raises(RecipeDevicesError) as info:
        store.upsert(dict(_NEW_DEVICE))

    assert str(info.value) == LITERAL_OSERROR
