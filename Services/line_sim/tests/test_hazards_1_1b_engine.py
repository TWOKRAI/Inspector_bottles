# -*- coding: utf-8 -*-
"""Hazard-тесты автора для Task 1.1b (блок A — слой класса `class://`, блок B — заливка
`color_rgb`) — что может сломаться именно в ЭТОМ механизме, а не в общей приёмке
(`test_acceptance_1_1b_class_layer.py`, `test_acceptance_1_1b_layer_color.py`).

Что проверяется и почему:
    H1. Слой `class://` в СЕРЕДИНЕ трёх слоёв не сдвигает rng-поток соседних слоёв —
        `rng.spawn(len(layers))` раздаёт под-генераторы по ИНДЕКСУ; если бы `make()`
        как-то по-другому строил список (скажем, добавлял class-слой в конец вместо
        замены на месте), позиции всех слоёв после него сдвинулись бы.
    H2. `force_defect_next()` + слой класса — объект N+1 (обычный, без форса) получает
        класс/угол/спрайт из ТОЙ ЖЕ позиции общего `rng`, что и legacy-путь без слоя
        класса: подстановка `class://` не добавляет и не убирает rng-поток по сравнению
        с "base", который она заменяет.
    H3. `color_rgb` на `defect`-слое красит АКТИВНОЕ пятно дефекта (не только static/
        augmented, которые проверяет приёмка).
    H4. `color_rgb` + `scale != 1` (антиалиасинг при ресайзе) — альфа побитово та же,
        что без заливки: заливка не трогает альфа-канал ДО ресайза (порядок из спеки —
        заливка -> scale -> поворот -> тон), а не после.
    H5. `layer_params[...]["color_rgb"]` — список ПРОСТЫХ `int` (не `np.uint8`/`np.int64`),
        JSON-safe уже на выходе `LayeredObject`, не только после `_json_safe()` в
        `ObjectPassport.to_dict()`.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.line_sim import (
    CLASS_SPRITE_SOURCE,
    LayerAugment,
    LayerSpec,
    LayeredObject,
    ObjectFactory,
    ObjectPassport,
    ScenePreset,
)

pytestmark = pytest.mark.timeout(30)


# --------------------------------------------------------------------------
# Фикстуры-помощники (тот же паттерн, что в test_acceptance_1_1b_*.py — не тестируют
# ничего сами)
# --------------------------------------------------------------------------


def _solid_rgba(h: int, w: int, rgb: tuple[int, int, int], alpha: int = 255) -> np.ndarray:
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[:, :, 0], img[:, :, 1], img[:, :, 2] = rgb
    img[:, :, 3] = alpha
    return img


def _antialiased_disk(diameter: int) -> np.ndarray:
    """Диск с мягким (не 0/255) краем альфы — иначе `cv2.resize` края не интерполирует
    заметно и H4 ничего не проверяет."""
    img = np.zeros((diameter, diameter, 4), dtype=np.uint8)
    r = diameter / 2.0
    yy, xx = np.mgrid[0:diameter, 0:diameter].astype(np.float32) + 0.5
    dist = np.sqrt((yy - r) ** 2 + (xx - r) ** 2)
    alpha = np.clip((r - dist) * 40.0, 0.0, 255.0)
    img[:, :, 0:3] = 200
    img[:, :, 3] = alpha.astype(np.uint8)
    return img


def _write_rgba_png(path: Path, rgba: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok = cv2.imwrite(str(path), bgra)
    assert ok, f"cv2.imwrite не смог записать {path}"


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    """cat/A -> один класс, красный квадрат 20x20 непрозрачный."""
    root = tmp_path / "cat"
    _write_rgba_png(root / "A" / "sprite.png", _solid_rgba(20, 20, (255, 0, 0)))
    return root


def _passport(defect: str | None = None) -> ObjectPassport:
    return ObjectPassport(object_id="o1", class_name="x", angle_deg=0.0, defect=defect, spawn_encoder=0.0)


# --------------------------------------------------------------------------
# H1 — class:// в середине не сдвигает rng соседей
# --------------------------------------------------------------------------


def test_class_layer_in_middle_keeps_sibling_rng_streams(catalog_dir: Path, tmp_path: Path) -> None:
    """Слой class:// в позиции 1 из 3 заменён на файловый static-слой того же размера —
    augmented-слой НАД ним должен разыграть ТЕ ЖЕ значения (тот же seed, та же длина
    списка слоёв): rng.spawn() раздаёт потоки по индексу, а не по содержимому слоя.

    ЛОВУШКА, найденная при первом прогоне (не догадка из спеки): наивное сравнение
    "пресет с class:// в позиции 1" против "тот же список, но class:// заменён на
    самый обычный файловый слой" — НЕ сравнение слоёв одного размера списка. Фабрика
    добавляет "base" САМА, но только когда в пресете НЕТ ни одного слоя class:// —
    поэтому пресет без class:// получает 4 слоя (base, top, mid, bottom) + damaged,
    а пресет с class:// — 3 (top, mid-как-класс, bottom) + damaged: "top" оказывается
    на РАЗНЫХ индексах (1 и 0), и сравнение как раз и ловит этот сдвиг, а не искомое
    свойство. Настоящий сиблинг того же размера списка — пресет БЕЗ catalog_dir (Task
    1.1b, блок B): "base" туда тоже не добавляется (см. ObjectFactory.make(), ветка
    `self._catalog is None`), так что оба пресета дают одинаковые 3+1=4 слоя и "top"
    остаётся на индексе 0 в обоих."""
    top_sprite = tmp_path / "top.png"
    _write_rgba_png(top_sprite, _solid_rgba(10, 10, (0, 255, 0)))
    bottom_sprite = tmp_path / "bottom.png"
    _write_rgba_png(bottom_sprite, _solid_rgba(10, 10, (255, 255, 0)))
    dummy_path = tmp_path / "dummy.png"
    _write_rgba_png(dummy_path, _solid_rgba(20, 20, (0, 0, 255)))

    top = LayerSpec(
        name="top",
        mode="augmented",
        sprite_source=str(top_sprite),
        augment=LayerAugment(hue_shift_deg=(10.0, 350.0), offset_x_px=(-5.0, 5.0)),
    )
    bottom = LayerSpec(name="bottom", mode="static", sprite_source=str(bottom_sprite))
    class_layer = LayerSpec(name="mid", mode="static", sprite_source=CLASS_SPRITE_SOURCE)
    dummy_layer = LayerSpec(name="mid", mode="static", sprite_source=str(dummy_path))

    preset_class = ScenePreset(
        catalog_dir=str(catalog_dir),
        layers=[top, class_layer, bottom],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )
    preset_dummy = ScenePreset(
        catalog_dir=None,
        layers=[top, dummy_layer, bottom],
        defect_probability=0.0,
        angle_range_deg=(0.0, 0.0),
    )

    obj_class = ObjectFactory(preset_class).make("o1", 0.0, np.random.default_rng(42))
    obj_dummy = ObjectFactory(preset_dummy).make("o1", 0.0, np.random.default_rng(42))

    assert obj_class.passport.layer_params["top"] == obj_dummy.passport.layer_params["top"]


# --------------------------------------------------------------------------
# H2 — force_defect_next() + class:// не сдвигает rng для объекта N+1
# --------------------------------------------------------------------------


def test_forced_defect_then_next_object_matches_legacy_rng_position(catalog_dir: Path) -> None:
    """Объект N — форсированный дефект; объект N+1 (обычный) на ОБЩЕМ rng должен выйти
    побитово одинаковым что в legacy-пресете (без слоя класса), что в пресете со слоем
    class:// — раз class:// подставляется НА МЕСТО "base", а не добавляется сверх него,
    число слоёв (и, значит, число rng-потоков на объект) не меняется."""
    legacy_preset = ScenePreset(
        catalog_dir=str(catalog_dir), layers=[], defect_probability=0.0, angle_range_deg=(0.0, 360.0)
    )
    class_layer = LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE)
    class_preset = ScenePreset(
        catalog_dir=str(catalog_dir), layers=[class_layer], defect_probability=0.0, angle_range_deg=(0.0, 360.0)
    )

    rng_legacy = np.random.default_rng(99)
    factory_legacy = ObjectFactory(legacy_preset)
    factory_legacy.force_defect_next()
    factory_legacy.make("o1", 0.0, rng_legacy)
    obj_legacy_next = factory_legacy.make("o2", 1.0, rng_legacy)

    rng_class = np.random.default_rng(99)
    factory_class = ObjectFactory(class_preset)
    factory_class.force_defect_next()
    factory_class.make("o1", 0.0, rng_class)
    obj_class_next = factory_class.make("o2", 1.0, rng_class)

    assert obj_legacy_next.passport.class_name == obj_class_next.passport.class_name
    assert obj_legacy_next.passport.angle_deg == obj_class_next.passport.angle_deg
    assert obj_legacy_next.passport.defect is None and obj_class_next.passport.defect is None
    assert np.array_equal(obj_legacy_next.render(), obj_class_next.render())


# --------------------------------------------------------------------------
# H3 — color_rgb на defect-слое
# --------------------------------------------------------------------------


def test_color_rgb_on_defect_layer_recolors_active_blob() -> None:
    """color_rgb на defect-слое красит АКТИВНОЕ пятно дефекта (RGB := цвет, альфа не
    трогается) — приёмка B1/B2 проверяет только static/augmented."""
    base = LayerSpec(name="base", mode="static", sprite_source=_solid_rgba(40, 40, (255, 255, 255)))
    defect = LayerSpec(
        name="damaged",
        mode="defect",
        sprite_source=_solid_rgba(40, 40, (60, 60, 60)),
        defect_probability=0.0,
        color_rgb=(0, 200, 0),
    )
    obj = LayeredObject(passport=_passport(defect="damaged"), layers=[base, defect], rng=np.random.default_rng(1))

    assert obj.passport.defect == "damaged"
    assert obj.passport.layer_params["damaged"] == {"active": True, "color_rgb": [0, 200, 0]}
    frame = obj.render()
    cy, cx = frame.shape[0] // 2, frame.shape[1] // 2
    assert tuple(int(v) for v in frame[cy, cx, 0:3]) == (0, 200, 0)
    assert int(frame[cy, cx, 3]) == 255


# --------------------------------------------------------------------------
# H4 — color_rgb + scale != 1 не трогает антиалиасинг альфы
# --------------------------------------------------------------------------


def test_color_rgb_with_scale_keeps_antialiased_alpha_bitwise() -> None:
    """Заливка идёт ПЕРЕД resize (заливка -> scale -> поворот -> тон) и меняет только RGB —
    альфа после resize (scale=1.7, интерполяция мягкого края) должна быть побитово
    одинаковой что с color_rgb, что без."""
    sprite = _antialiased_disk(30)
    plain = LayerSpec(name="d", mode="static", sprite_source=sprite, scale=1.7)
    colored = LayerSpec(name="d", mode="static", sprite_source=sprite, scale=1.7, color_rgb=(10, 20, 30))

    frame_plain = LayeredObject(passport=_passport(), layers=[plain], rng=np.random.default_rng(1)).render()
    frame_colored = LayeredObject(passport=_passport(), layers=[colored], rng=np.random.default_rng(1)).render()

    alpha_plain = frame_plain[:, :, 3]
    alpha_colored = frame_colored[:, :, 3]
    assert alpha_plain.sum() > 0
    assert len(np.unique(alpha_plain)) > 2, "тест ничего не проверяет, если край не сглажен (только 0/255)"
    assert np.array_equal(alpha_plain, alpha_colored)


# --------------------------------------------------------------------------
# H5 — layer_params цвета — простые int, JSON-safe
# --------------------------------------------------------------------------


def test_layer_params_color_values_are_plain_json_safe_ints() -> None:
    """layer_params[...]['color_rgb'] — список ПРОСТЫХ int (не np.uint8/np.int64) уже на
    выходе LayeredObject, а не только после ObjectPassport._json_safe()."""
    sprite = _solid_rgba(10, 10, (255, 255, 255))
    static_layer = LayerSpec(name="s", mode="static", sprite_source=sprite, color_rgb=(255, 0, 0))
    aug_layer = LayerSpec(
        name="a",
        mode="augmented",
        sprite_source=sprite,
        color_rgb=(0, 255, 0),
        augment=LayerAugment(hue_shift_deg=(45.0, 45.0)),
    )
    obj = LayeredObject(passport=_passport(), layers=[static_layer, aug_layer], rng=np.random.default_rng(3))

    for name in ("s", "a"):
        color = obj.passport.layer_params[name]["color_rgb"]
        assert all(type(v) is int for v in color), f"{name}: {[type(v) for v in color]}"

    dumped = json.dumps(obj.passport.to_dict())
    assert "color_rgb" in dumped
