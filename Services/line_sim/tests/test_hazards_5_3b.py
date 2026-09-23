# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Task 5.3b (контракт лида §4.2.1/§4.2.4).

Что здесь проверяется — два опасных места, которые acceptance-тесты тестера не
покрывают напрямую: (а) фоновый тайл при развороте ленты обязан ехать в ТУ ЖЕ
сторону, что и объекты (иначе диски «едут по льду» относительно ленты — контракт
§3, п.3); (б) каталожный инструмент отказывает на эталоне без альфа-канала, а не
молча портит спрайт.

Файл лежит в ``Services/line_sim/tests/`` — импортирует только ``Services.line_sim.*``
(граница слоёв, правило 9 корневого CLAUDE.md), без ``Plugins.*``.
"""

from __future__ import annotations

import numpy as np
import pytest

from Services.line_sim.core.scene_compositor import SceneCompositor
from Services.line_sim.interfaces import ObjectPassport
from Services.line_sim.tools.make_letter_catalog import build_catalog

pytestmark = pytest.mark.timeout(30)


class _FakeObj:
    def __init__(self, passport: ObjectPassport, sprite: np.ndarray) -> None:
        self.passport = passport
        self._sprite = sprite

    def render(self) -> np.ndarray:
        return self._sprite


class _FakeSpawner:
    def __init__(self, obj: _FakeObj) -> None:
        self._obj = obj

    def active_objects(self) -> list[_FakeObj]:
        return [self._obj]


def _opaque_sprite(size_px: int = 10) -> np.ndarray:
    sprite = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    sprite[:, :, 0] = 200
    sprite[:, :, 3] = 255
    return sprite


def _make_marker_tile(tw: int = 200, th: int = 5) -> np.ndarray:
    """Тайл-фон с ОДНОЙ отмеченной колонкой (индекс `tw // 2`) — маркер-канал 2."""
    tile = np.full((th, tw, 3), 60, dtype=np.uint8)
    tile[:, tw // 2, 2] = 255
    return tile


def _find_marker_col(frame: np.ndarray, row: int) -> int:
    """Индекс колонки кадра, где найден маркер тайла (канал 2 > 200), в заданной строке."""
    cols = np.nonzero(frame[row, :, 2] > 200)[0]
    assert cols.size > 0, "маркер тайла не найден в кадре"
    return int(cols.mean())


# --------------------------------------------------------------------------- #
# (a) §4.2.1 — фоновый тайл при belt_direction=-1 едет в ту же сторону,       #
#     что и объекты (не в противоположную)                                    #
# --------------------------------------------------------------------------- #


def test_background_tile_shifts_same_direction_as_objects_when_reversed() -> None:
    """§4.2.1: при `belt_direction=-1` сдвиг фонового тайла использует ТОТ ЖЕ знак,
    что и объекты — иначе диски и лента расходятся визуально при развороте
    (контракт §3, п.3: "без разворота расхождение до ~8 мм при радиусе
    сопоставления 5 мм").

    Guard: `self._belt_direction * shift_px` в формуле `cols` (`render()`) — убери
    `self._belt_direction *` (голый `- shift_px`, старая формула) -> тайл и объект
    едут в ПРОТИВОПОЛОЖНЫЕ стороны при `belt_direction=-1`, тест красный.
    """
    px_per_mm = 1.0
    belt_y_px = 2.5
    tile = _make_marker_tile(tw=200, th=5)
    sprite = _opaque_sprite()
    spawner = _FakeSpawner(
        _FakeObj(ObjectPassport(object_id="o1", class_name="A", angle_deg=0.0, defect=None, spawn_encoder=0.0), sprite)
    )
    compositor = SceneCompositor(
        spawner,
        px_per_mm=px_per_mm,
        belt_y_px=belt_y_px,
        background_tile=tile,
        belt_direction=-1,
        entry_x_px=150.0,  # объект должен оставаться в кадре (0..200) на обоих замерах
    )
    camera_rect = (0.0, 0.0, 200.0, 5.0)

    from Services.line_sim.core.belt import encoder_to_offset_mm
    from Services.robot_comm.core.registers import FACTOR_MM

    def _cx_and_marker(now_encoder: float) -> tuple[float, int]:
        frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=camera_rect)
        assert passports
        obj_mask = np.nonzero(frame[2, :, 0] > 150)[0]  # спрайт-маркер: канал 0
        assert obj_mask.size > 0, "объект не найден в кадре"
        cx = float(obj_mask.mean())
        marker_col = _find_marker_col(frame, row=2)
        return cx, marker_col

    enc0 = 0.0
    enc1 = 50.0 / FACTOR_MM  # offset ~50мм — меньше половины ширины тайла (100), без wraparound
    assert encoder_to_offset_mm(enc1, 0.0) < 100.0

    cx0, marker0 = _cx_and_marker(enc0)
    cx1, marker1 = _cx_and_marker(enc1)

    obj_delta = cx1 - cx0
    marker_delta = marker1 - marker0
    assert obj_delta != 0, "объект не сдвинулся между замерами — увеличьте enc1"
    assert marker_delta != 0, "маркер тайла не сдвинулся между замерами"
    assert (obj_delta > 0) == (marker_delta > 0), (
        f"объект и фон едут в РАЗНЫЕ стороны при belt_direction=-1: "
        f"объект {cx0:.1f}->{cx1:.1f} (Δ={obj_delta:.1f}), тайл {marker0}->{marker1} (Δ={marker_delta})"
    )


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
