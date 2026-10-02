# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Task 5.3b (контракт лида §4.2.1/§4.2.4).

Что здесь проверяется: (б) каталожный инструмент отказывает на эталоне без альфа-канала, а не
молча портит спрайт; (в) `belt_direction` вне `{-1, 1}` отвергается. Hazard (а) — фоновый тайл при
развороте ленты едет в ТУ ЖЕ сторону, что и объекты — удалён в layer-render 1.3 вместе с параметром
одиночного тайла; то же свойство держит стек слоёв —
`test_acceptance_1_3_single_background.py::test_layers_tile_shifts_same_direction_as_objects`.

Файл лежит в ``Services/line_sim/tests/`` — импортирует только ``Services.line_sim.*``
(граница слоёв, правило 9 корневого CLAUDE.md), без ``Plugins.*``.
"""

from __future__ import annotations

import numpy as np
import pytest

from Services.line_sim.core.scene_compositor import SceneCompositor
from Services.line_sim.tools.make_letter_catalog import build_catalog


# --------------------------------------------------------------------------- #
# (b) §4.2.4 — инструмент отказывает на эталоне без альфа-канала              #
# --------------------------------------------------------------------------- #


def test_letter_catalog_tool_rejects_sprite_without_alpha(tmp_path) -> None:
    """§4.2.4: эталон без альфа-канала (RGB, не RGBA) -> `SystemExit`, называющий
    файл — движок сцены не должен получить эталон, который не умеет альфа-смешивать.

    Guard: проверка `sprite.ndim != 3 or sprite.shape[2] != 4` в
    `_resize_keep_alpha()` — убери её -> `cv2.resize` на 3-канальном массиве
    отработает молча (никакого `SystemExit`), тест красный.
    """
    from Services.dataset_gen.core.catalog import imwrite_unicode

    src = tmp_path / "manual_sprites" / "А"
    src.mkdir(parents=True)
    rgb_no_alpha = np.zeros((40, 40, 3), dtype=np.uint8)
    rgb_no_alpha[:, :, :] = 100
    bad_path = src / "sprite_no_alpha.png"
    imwrite_unicode(bad_path, rgb_no_alpha)

    with pytest.raises(SystemExit) as excinfo:
        build_catalog(tmp_path / "manual_sprites", "А", 60, tmp_path / "out")

    assert str(bad_path) in str(excinfo.value), (
        f"SystemExit не называет проблемный файл: {excinfo.value!r} (ожидался путь {bad_path})"
    )


# --------------------------------------------------------------------------- #
# Лид, после ревью 5.3b (итерация 1): находки 3 и 5.                          #
# --------------------------------------------------------------------------- #


class _NoObjects:
    def active_objects(self) -> list:
        return []


@pytest.mark.parametrize("bad", [True, 1.0, -1.0, "1"], ids=["bool", "float", "neg_float", "str"])
def test_compositor_rejects_non_int_direction(bad) -> None:
    """Находка 3: `True == 1` и `1.0 == 1` проходили проверку `in (1, -1)`."""
    with pytest.raises(ValueError):
        SceneCompositor(_NoObjects(), px_per_mm=1.0, belt_y_px=10.0, belt_direction=bad)


def _write_rgba(path, w: int, h: int) -> None:
    from Services.dataset_gen.core.catalog import imwrite_unicode

    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[:, :, 3] = 255
    imwrite_unicode(path, img)


def test_letter_catalog_tool_refuses_out_with_foreign_letters(tmp_path) -> None:
    """Находка 5: сборка «Б» в --out, где уже лежит «А», смешивала наборы молча."""
    for letter in ("А", "Б"):
        (tmp_path / "src" / letter).mkdir(parents=True)
        _write_rgba(tmp_path / "src" / letter / "000.png", 40, 40)
    build_catalog(tmp_path / "src", "А", 60, tmp_path / "out")
    with pytest.raises(SystemExit) as excinfo:
        build_catalog(tmp_path / "src", "Б", 60, tmp_path / "out")
    assert "А" in str(excinfo.value)
    # Пересборка того же набора в тот же --out — законна.
    build_catalog(tmp_path / "src", "А", 60, tmp_path / "out")


def test_letter_catalog_tool_refuses_non_square_sprite(tmp_path) -> None:
    """Находка 5: 320×400 молча сплющивался в 300×300."""
    (tmp_path / "src" / "А").mkdir(parents=True)
    bad = tmp_path / "src" / "А" / "000.png"
    _write_rgba(bad, 32, 40)
    with pytest.raises(SystemExit) as excinfo:
        build_catalog(tmp_path / "src", "А", 60, tmp_path / "out")
    assert str(bad) in str(excinfo.value)


def test_letter_catalog_tool_broken_png_is_system_exit(tmp_path) -> None:
    """Находка 5: битый PNG давал traceback ValueError вместо сообщения с именем файла."""
    (tmp_path / "src" / "А").mkdir(parents=True)
    bad = tmp_path / "src" / "А" / "000.png"
    bad.write_bytes(b"not a png")
    with pytest.raises(SystemExit) as excinfo:
        build_catalog(tmp_path / "src", "А", 60, tmp_path / "out")
    assert str(bad) in str(excinfo.value)
