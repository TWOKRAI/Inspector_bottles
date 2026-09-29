# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.3h-d — механизм записи `preset.sprite_put`: что в НЁМ может сломаться.

Механизм: `mkstemp` в `sprites_dir` -> запись + `fsync` -> `load_image_rgba(tmp)` -> `os.link(tmp, final)`
-> `unlink(tmp)` в `finally`. Приёмка независимого tester смотрит на исходы по контракту; здесь — то, что видно
только зная устройство:

(a) Гонка. Проверка «файл уже есть» и публикация — два разных момента; между ними (окно — проверка RGBA)
    внешний писатель может создать целевой файл. `os.replace` тут молча перезаписал бы чужой файл; контракт —
    `conflict`, чужие байты целы, `.uploading` не остаётся. Окно открываем инъекцией: `load_image_rgba` в
    пространстве имён плагина создаёт целевой файл как побочный эффект.
(b) Сбой записи. `fsync` падает `OSError` -> `io_error`, ни `.uploading`, ни итогового файла (временный файл
    уже создан `mkstemp` — его должен убрать `finally`, а не только успешный путь).
(c) Отказ невидим в списке. После неудачной загрузки `preset.sprites` не показывает ничего нового — ни
    `.uploading`, ни итоговое имя (полузаписанный файл не должен светиться оператору).
(d) Сбой публикации не оставляет мусора и не маскируется под `conflict`: `os.link` падает не `FileExistsError`,
    а другим `OSError` -> `io_error`, временный убран.

Инъекция отказов — monkeypatch; число вызовов API-имён не считается: проверяются содержимое каталога и коды.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from Plugins.sim.layer_preview.tests.test_acceptance_1_3h_d_sprite_put import (
    _make_world,
    _new_preview,
    _put,
    _rgba_png,
)

_PLUGIN = "Plugins.sim.layer_preview.plugin"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _listing(sprites_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(sprites_dir.iterdir())}


@pytest.fixture
def world(tmp_path: Path):
    preset_path, sprites_dir = _make_world(tmp_path)
    return _new_preview(preset_path, sprites_dir=str(sprites_dir)), sprites_dir


def test_a_external_writer_between_check_and_link_is_conflict_and_not_overwritten(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Внешний писатель создаёт `up.png` в окне между проверкой существования и `os.link` -> `conflict`,
    его байты целы, временный файл убран."""
    plugin, sprites_dir = world
    external = b"EXTERNAL-WRITER-BYTES"
    real_load = __import__(_PLUGIN, fromlist=["load_image_rgba"]).load_image_rgba

    def load_and_race(path):
        (sprites_dir / "up.png").write_bytes(external)  # гонка: файл появился после проверки «нет»
        return real_load(path)

    monkeypatch.setattr(f"{_PLUGIN}.load_image_rgba", load_and_race)
    reply = _put(plugin, "up.png", _b64(_rgba_png()))
    assert reply["status"] == "error" and reply["code"] == "conflict", reply
    assert _listing(sprites_dir) == {"up.png": external}, "чужой файл цел, ничего лишнего (.uploading) не осталось"


def test_b_fsync_failure_is_io_error_and_leaves_nothing(world, monkeypatch: pytest.MonkeyPatch) -> None:
    """`fsync` -> `OSError` (диск полон/сбой) -> `io_error`; `mkstemp` уже создал файл — он убран, итогового нет."""
    plugin, sprites_dir = world

    def broken_fsync(fd):
        raise OSError("диск отказал")

    monkeypatch.setattr(f"{_PLUGIN}.os.fsync", broken_fsync)
    reply = _put(plugin, "up.png", _b64(_rgba_png()))
    assert reply["status"] == "error" and reply["code"] == "io_error", reply
    assert _listing(sprites_dir) == {}, "после сбоя записи каталог пуст"


def test_c_failed_put_is_invisible_in_sprites_listing(world, monkeypatch: pytest.MonkeyPatch) -> None:
    """После неудачной загрузки `preset.sprites` не видит ничего нового (ни `.uploading`, ни целевого имени)."""
    plugin, sprites_dir = world
    assert _put(plugin, "old.png", _b64(_rgba_png(fill=10)))["status"] == "ok"
    before = plugin.cmd_preset_sprites({})["files"]
    assert [f["path"] for f in before] == ["old.png"]

    monkeypatch.setattr(f"{_PLUGIN}.os.fsync", lambda fd: (_ for _ in ()).throw(OSError("сбой")))
    assert _put(plugin, "new.png", _b64(_rgba_png(fill=20)))["code"] == "io_error"
    monkeypatch.undo()
    assert _put(plugin, "bad.png", _b64(b"not a png"))["code"] == "invalid"

    assert plugin.cmd_preset_sprites({})["files"] == before
    assert sorted(_listing(sprites_dir)) == ["old.png"], "и на диске только прежний файл"


def test_d_link_oserror_other_than_exists_is_io_error_not_conflict(world, monkeypatch: pytest.MonkeyPatch) -> None:
    """`os.link` падает НЕ `FileExistsError` (ФС без жёстких ссылок и т.п.) -> `io_error`, временный убран,
    итогового нет: «не смогли опубликовать» не выдаём за «имя занято»."""
    plugin, sprites_dir = world

    def no_links(src, dst):
        raise OSError("жёсткие ссылки не поддерживаются")

    monkeypatch.setattr(f"{_PLUGIN}.os.link", no_links)
    reply = _put(plugin, "up.png", _b64(_rgba_png()))
    assert reply["status"] == "error" and reply["code"] == "io_error", reply
    assert _listing(sprites_dir) == {}
    assert not any(name.endswith(".uploading") for name in os.listdir(sprites_dir))
