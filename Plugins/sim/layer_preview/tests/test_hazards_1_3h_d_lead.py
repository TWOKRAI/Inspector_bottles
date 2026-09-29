# -*- coding: utf-8 -*-
"""Hazard лида к `preset.sprite_put` (Task 1.3h-d): «файл опубликован — ответ потерян».

Найдено чтением кода разработчика, до правки:
(e) `sprite_entry` считался ПОСЛЕ `os.link`: `relpath` между дисками (`sprites_dir` и каталог пресета на
    разных дисках) бросал `ValueError` из команды — файл уже лежит в каталоге, оператор получает ошибку
    транспорта. Теперь запись считается до записи файла: отказ `bad_request`, на диске ничего.
(f) `finally` ловил только `FileNotFoundError`: `PermissionError` при удалении временного (на Windows его
    держит антивирус) вылетал ПОСЛЕ успешной публикации. Теперь ответ `ok` с `file`, файл опубликован.
Отказы вызываются monkeypatch в пространстве имён плагина; проверяются коды и содержимое каталога.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from Plugins.sim.layer_preview.tests.test_acceptance_1_3h_d_sprite_put import (
    _make_world,
    _new_preview,
    _put,
    _rgba_png,
)

_PLUGIN = "Plugins.sim.layer_preview.plugin"


@pytest.fixture
def world(tmp_path: Path):
    preset_path, sprites_dir = _make_world(tmp_path)
    return _new_preview(preset_path, sprites_dir=str(sprites_dir)), sprites_dir


def _png_b64() -> str:
    return base64.b64encode(_rgba_png()).decode("ascii")


def test_e_entry_that_cannot_be_built_refuses_before_writing(world, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin, sprites_dir = world
    before = sorted(p.name for p in sprites_dir.iterdir())

    def cross_drive(*_args, **_kwargs):
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    monkeypatch.setattr(f"{_PLUGIN}.sprite_entry", cross_drive)
    res = _put(plugin, "up.png", _png_b64())
    assert res.get("status") == "error" and res.get("code") == "bad_request", res
    assert sorted(p.name for p in sprites_dir.iterdir()) == before, "на диске ничего не появилось"


def test_f_tmp_unlink_failure_after_publish_keeps_the_ok_reply(world, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin, sprites_dir = world
    png = _rgba_png()

    def locked(_path):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(f"{_PLUGIN}.os.unlink", locked)
    res = _put(plugin, "up.png", base64.b64encode(png).decode("ascii"))
    monkeypatch.undo()
    assert res.get("status") == "ok" and res.get("file", {}).get("path") == "up.png", res
    assert (sprites_dir / "up.png").read_bytes() == png
