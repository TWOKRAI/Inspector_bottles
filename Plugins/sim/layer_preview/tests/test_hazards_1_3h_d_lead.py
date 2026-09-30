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


@pytest.mark.parametrize("corrupt", ["signature", "pixel_cap"])
def test_g_rejected_bytes_never_reach_the_decoder(world, monkeypatch: pytest.MonkeyPatch, corrupt: str) -> None:
    """Ревью 1.3h-d F1/F3: сигнатура и IHDR-потолок — ДО любого декодера OpenCV. Инъекция J1 (без проверки
    сигнатуры) была зелёной: WebP/TIFF отсекает проверка IHDR, а PNG с битой сигнатурой отсекал сам декодер —
    исход `invalid` тот же, но байты из сети уже побывали в декодере. Здесь свойство и есть «декодер не вызван»."""
    plugin, sprites_dir = world
    png = bytearray(_rgba_png())
    if corrupt == "signature":
        png[1:4] = b"XNG"  # IHDR на месте, сигнатура битая
    else:
        png[16:24] = (5000).to_bytes(4, "big") + (5000).to_bytes(4, "big")  # IHDR 5000x5000 > 4096²
    reached: list[str] = []
    monkeypatch.setattr(f"{_PLUGIN}.load_image_rgba", lambda path: reached.append(str(path)))
    res = _put(plugin, "up.png", base64.b64encode(bytes(png)).decode("ascii"))
    assert res.get("code") == "invalid", res
    assert reached == [], f"декодер вызван на отвергнутых байтах: {reached}"
    assert not any(sprites_dir.iterdir()) or all(p.suffix != ".uploading" for p in sprites_dir.iterdir())


def test_h_sixteen_bit_png_is_invalid_it_would_never_build_a_layer(world) -> None:
    """Ревью 1.3h-d ит.2: RGBA 16 бит сохранялся с `ok`, а `preset.layout` на нём падал (`uint16`) — файл лежит,
    слоя нет, повтор под тем же именем даёт 409. Отказ — до диска."""
    import cv2
    import numpy as np

    plugin, sprites_dir = world
    rgba16 = np.full((8, 8, 4), 30000, np.uint16)
    png = cv2.imencode(".png", rgba16)[1].tobytes()
    assert png[24] == 16, "контроль: закодирован 16-битный PNG"
    res = _put(plugin, "deep.png", base64.b64encode(png).decode("ascii"))
    assert res.get("code") == "invalid", res
    assert not (sprites_dir / "deep.png").exists()


def test_i_exactly_the_pixel_cap_is_accepted(world) -> None:
    """Граница `SPRITE_PUT_MAX_PIXELS` = 4096² включительно (ревью ит.2: `>` → `>=` оставался зелёным)."""
    import cv2
    import numpy as np

    plugin, sprites_dir = world
    png = cv2.imencode(".png", np.zeros((4096, 4096, 4), np.uint8))[1].tobytes()
    res = _put(plugin, "cap.png", base64.b64encode(png).decode("ascii"))
    assert res.get("status") == "ok", res
    assert (sprites_dir / "cap.png").read_bytes() == png
