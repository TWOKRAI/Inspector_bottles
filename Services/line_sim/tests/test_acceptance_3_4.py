"""Независимые acceptance-тесты Task 3.4 (ред. 2) — `SceneCompositor` +
`ObjectPassport.to_dict/from_dict`, написаны ДО реализации по контракту из
`plans/line-sim/phase-3-object-engine.md` (§ "Task 3.4 (ред. 2)" + уточнение лида
2026-09-23). Никакого доступа к Steps/реализации не было — только раздел плана,
`Services/line_sim/README.md`, `interfaces.py`, `core/belt.py`,
`Services/dataset_gen/core/catalog.py` и уже смёрженные (Task 3.1-3.3) `preset.py`,
`factory.py`, `spawner.py`, `catalog_bridge.py`, `layered_object.py` — эти пять читались
только как готовая зависимость для сборки fixture, не как то, что тестируется здесь.

СИГНАТУРЫ, ПРЕДПОЛАГАЕМЫЕ (ещё не реализованы — источник: раздел плана "Уточнено лидом
2026-09-23 перед тестером"), проверить при имплементации:
  - `from Services.line_sim import SceneCompositor`
  - `SceneCompositor(spawner: ObjectSpawner, px_per_mm: float, belt_y_px: float,
     background_bgr: tuple[int, int, int] = (60, 60, 60))`
  - `SceneCompositor.render(now_encoder: float,
     camera_rect: tuple[float, float, float, float]) ->
     tuple[np.ndarray, list[ObjectPassport]]`
    где `camera_rect = (x_px, y_px, w_px, h_px)`; кадр — RGB uint8 `(h_px, w_px, 3)`.
  - Центр объекта в кадре: `cx = encoder_to_offset_mm(now_encoder, spawn_encoder) *
    px_per_mm - x_px`, `cy = belt_y_px - y_px` (см. план, п. "Уточнено лидом").
  - `SceneCompositor` НЕ вызывает `spawner.tick()` — тик делает вызывающий (плагин).
  - `ObjectPassport.to_dict(self) -> dict` (только JSON-совместимые типы, numpy-скаляры
    -> float) / `ObjectPassport.from_dict(d: dict) -> ObjectPassport` (round-trip).

Fixture-каталог классов строится в `tmp_path`: одна листовая папка-класс со спрайтом
16x16 RGBA, полностью непрозрачным и одноканальным по цвету (только R либо только B
ненулевой) — так R/B-swap в кадре виден напрямую по пикселю, без интерполяции на углах
(во всех тестах `angle_range_deg=(0.0, 0.0)` — объект не поворачивается).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import (
    FACTOR_MM,
    ObjectFactory,
    ObjectPassport,
    ObjectSpawner,
    SceneCompositor,
    ScenePreset,
)

BACKGROUND_BGR = (60, 60, 60)  # серый: одинаков в RGB и BGR — не участвует в R/B-проверке


# --------------------------------------------------------------------------------------
# Fixture-хелперы (не тестируют ничего сами — готовят детерминированный офлайн-мир)
# --------------------------------------------------------------------------------------


def _make_fixture_catalog(tmp_path: Path, color_bgr: tuple[int, int, int]) -> Path:
    """Каталог из одного класса `square` с непрозрачным 16x16 спрайтом.

    `color_bgr` пишется на диск как есть (BGRA, конвенция `imwrite_unicode`/cv2);
    `SpriteCatalog._load_sprite` сам переведёт в RGBA при загрузке.
    """
    classes_dir = tmp_path / "classes"
    class_dir = classes_dir / "square"
    class_dir.mkdir(parents=True)
    b, g, r = color_bgr
    sprite_bgra = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite_bgra[:, :, 0] = b
    sprite_bgra[:, :, 1] = g
    sprite_bgra[:, :, 2] = r
    sprite_bgra[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", sprite_bgra)
    return classes_dir


def _make_spawner(tmp_path: Path, color_bgr: tuple[int, int, int], **spawner_kwargs) -> ObjectSpawner:
    classes_dir = _make_fixture_catalog(tmp_path, color_bgr)
    preset = ScenePreset(catalog_dir=str(classes_dir), angle_range_deg=(0.0, 0.0), defect_probability=0.0)
    factory = ObjectFactory(preset)
    kwargs = {"interval_s": (1000.0, 1000.0), "scene_length_mm": 1_000_000.0, "max_active": 200}
    kwargs.update(spawner_kwargs)
    return ObjectSpawner(factory, **kwargs)


def _spawn_one_at(spawner: ObjectSpawner, spawn_encoder: float, seed: int = 0):
    """Ровно один объект, `passport.spawn_encoder == spawn_encoder` (см. `ObjectSpawner.tick`
    докстринг: первый `tick()` только взводит срок, второй — спавнит с `spawn_encoder =
    now_encoder` ЭТОГО тика)."""
    rng = np.random.default_rng(seed)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=2000.0, rng=rng)
    objs = spawner.active_objects()
    assert len(objs) == 1, "setup sanity: ожидался ровно один заспавненный объект"
    return objs[0]


def _assert_uniform_background(frame: np.ndarray, bg: tuple[int, int, int] = BACKGROUND_BGR) -> None:
    expected = np.empty_like(frame)
    expected[:, :, 0], expected[:, :, 1], expected[:, :, 2] = bg
    assert np.array_equal(frame, expected)


def _dominant_channel_present(
    frame: np.ndarray, cx: float, cy: float, hi: int, lo_a: int, lo_b: int, radius: int = 3
) -> bool:
    """Окно ±radius px вокруг (cx, cy) содержит пиксель, где канал `hi` доминирует
    (>200) и остальные два (`lo_a`, `lo_b`) низкие (<50) — допуск на округление центра."""
    cy_i, cx_i = int(round(cy)), int(round(cx))
    y0, y1 = max(0, cy_i - radius), min(frame.shape[0], cy_i + radius + 1)
    x0, x1 = max(0, cx_i - radius), min(frame.shape[1], cx_i + radius + 1)
    window = frame[y0:y1, x0:x1]
    if window.size == 0:
        return False
    mask = (window[:, :, hi] > 200) & (window[:, :, lo_a] < 50) & (window[:, :, lo_b] < 50)
    return bool(np.any(mask))


# --------------------------------------------------------------------------------------
# SceneCompositor.render
# --------------------------------------------------------------------------------------


def test_empty_spawner_renders_background_only(tmp_path):
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=BACKGROUND_BGR)

    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 300.0, 150.0))

    assert frame.dtype == np.uint8
    assert frame.shape == (150, 300, 3)
    _assert_uniform_background(frame)
    assert passports == []


def test_object_centre_matches_encoder_offset(tmp_path):
    # спрайт — чистый красный канал (RGB): BGR на диске (0, 0, 255) -> R=255,G=0,B=0
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    obj = _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=BACKGROUND_BGR)

    delta_ticks = 1000.0  # литерал; смещение в мм считаем из FACTOR_MM, не хардкодим дважды
    now_encoder = 0.0 + delta_ticks
    expected_offset_mm = delta_ticks * FACTOR_MM
    expected_cx = expected_offset_mm * 1.0 - 0.0  # px_per_mm=1.0, x_px=0.0
    expected_cy = 75.0 - 0.0  # belt_y_px - y_px

    frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 300.0, 150.0))

    assert frame.dtype == np.uint8
    assert frame.shape == (150, 300, 3)
    assert len(passports) == 1
    assert passports[0].object_id == obj.passport.object_id
    # R доминирует, G/B — низкие: подтверждает и позицию (±2px), и порядок RGB-каналов
    assert _dominant_channel_present(frame, expected_cx, expected_cy, hi=0, lo_a=1, lo_b=2)
    # фон нетронут в стороне от объекта (объект 16x16, далёкие точки вне его bbox)
    assert tuple(int(v) for v in frame[5, 5]) == BACKGROUND_BGR
    assert tuple(int(v) for v in frame[140, 5]) == BACKGROUND_BGR


def test_object_outside_camera_rect_absent(tmp_path):
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=BACKGROUND_BGR)

    # смещение заведомо за пределами кадра (300 px шириной, объект 16x16)
    now_encoder = 0.0 + 100_000.0

    frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 300.0, 150.0))

    assert passports == []
    _assert_uniform_background(frame)


def test_partially_visible_object_is_listed_and_clipped(tmp_path):
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    obj = _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=BACKGROUND_BGR)

    # кадр 100 px шириной; центр объекта в 96 px -> объект (16x16, половина=8) занимает
    # x в [88, 104) — правая часть [100, 104) уже за краем кадра, объект частично виден
    expected_offset_mm = 96.0  # px_per_mm=1.0, x_px=0.0 -> expected_cx = 96.0
    now_encoder = 0.0 + expected_offset_mm / FACTOR_MM

    frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 100.0, 150.0))

    assert frame.shape == (150, 100, 3)
    assert len(passports) == 1
    assert passports[0].object_id == obj.passport.object_id
    # видимая (левая) часть объекта нарисована: точка x=95 гарантированно внутри bbox и внутри кадра
    assert tuple(int(v) for v in frame[75, 95]) == (255, 0, 0)


def test_frame_is_rgb_uint8(tmp_path):
    # спрайт — чистый синий канал: BGR на диске (255, 0, 0) -> R=0,G=0,B=255
    spawner = _make_spawner(tmp_path, color_bgr=(255, 0, 0))
    _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=BACKGROUND_BGR)

    delta_ticks = 1000.0
    now_encoder = 0.0 + delta_ticks
    expected_cx = delta_ticks * FACTOR_MM * 1.0 - 0.0
    expected_cy = 75.0

    frame, _passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 300.0, 150.0))

    assert frame.dtype == np.uint8
    assert frame.shape == (150, 300, 3)
    # B доминирует, R/G — низкие (индексы канала: R=0, G=1, B=2 в RGB-массиве)
    assert _dominant_channel_present(frame, expected_cx, expected_cy, hi=2, lo_a=0, lo_b=1)


def test_passports_are_in_spawn_order(tmp_path):
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255), interval_s=(1.0, 1.0), max_active=10)
    rng = np.random.default_rng(0)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взводит срок (deadline=1.0)
    spawner.tick(now_encoder=0.0, now_wall_s=2.0, rng=rng)  # spawns obj-1, deadline=3.0
    spawner.tick(now_encoder=0.0, now_wall_s=4.0, rng=rng)  # spawns obj-2, deadline=5.0
    spawner.tick(now_encoder=0.0, now_wall_s=6.0, rng=rng)  # spawns obj-3, deadline=7.0
    ids = [o.passport.object_id for o in spawner.active_objects()]
    assert ids == ["obj-1", "obj-2", "obj-3"]  # setup sanity: порядок спавна известен

    # все три объекта на одной позиции (spawn_encoder=0.0) -> все в кадре одновременно
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=BACKGROUND_BGR)
    _frame, passports = compositor.render(now_encoder=0.0, camera_rect=(-50.0, 0.0, 100.0, 150.0))

    assert [p.object_id for p in passports] == ["obj-1", "obj-2", "obj-3"]


def test_render_does_not_tick_the_spawner(tmp_path):
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255), interval_s=(1e-6, 2e-6), max_active=50)
    rng = np.random.default_rng(0)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взводит срок (~1e-6)
    spawner.tick(now_encoder=0.0, now_wall_s=1.0, rng=rng)  # 1.0 >= deadline -> спавнит, deadline~=1.000001
    assert len(spawner.active_objects()) == 1  # setup sanity

    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=BACKGROUND_BGR)
    compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 300.0, 150.0))
    compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 300.0, 150.0))

    # interval_s настолько мал, что ЛЮБОЙ реальный wall-clock тик спавнера (время.time()
    # эпохи всегда >> взведённый срок ~1.000001) заспавнил бы ещё один объект -- список
    # не изменился, значит render() не звал spawner.tick()
    assert len(spawner.active_objects()) == 1


# --------------------------------------------------------------------------------------
# ObjectPassport.to_dict / from_dict
# --------------------------------------------------------------------------------------


def test_passport_dict_round_trip_json_safe():
    passport = ObjectPassport(
        object_id="obj-7",
        class_name="square",
        angle_deg=37.5,
        defect="damaged",
        spawn_encoder=12345.0,
        layer_params={
            "augmented_layer": {
                "offset_x_px": 1.5,
                "offset_y_px": -2.0,
                "angle_deg": np.float32(10.0),  # numpy-скаляр -> to_dict должен привести к float
                "scale": 1.1,
                "hue_shift_deg": 5.0,
            },
            "damaged": {"active": True},
        },
    )

    as_dict = passport.to_dict()

    # только JSON-совместимые типы на границе (numpy-скаляр не проходит json.dumps)
    json.dumps(as_dict)
    assert isinstance(as_dict["angle_deg"], float)
    assert isinstance(as_dict["spawn_encoder"], float)
    assert as_dict["object_id"] == "obj-7"
    assert as_dict["defect"] == "damaged"
    nested_angle = as_dict["layer_params"]["augmented_layer"]["angle_deg"]
    assert isinstance(nested_angle, float)
    assert nested_angle == pytest.approx(10.0)

    round_tripped = ObjectPassport.from_dict(as_dict)

    assert round_tripped == passport


def test_passport_dict_round_trip_none_defect_and_empty_layer_params():
    passport = ObjectPassport(
        object_id="obj-1",
        class_name="square",
        angle_deg=0.0,
        defect=None,
        spawn_encoder=0.0,
        layer_params={},
    )

    round_tripped = ObjectPassport.from_dict(passport.to_dict())

    assert round_tripped == passport
    assert round_tripped.defect is None
