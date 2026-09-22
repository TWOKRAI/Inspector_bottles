"""Тесты автора (hazard) — Task 3.4, `SceneCompositor` (`core/scene_compositor.py`).

Про что acceptance-тесты тестера (`test_acceptance_3_4.py`) НЕ проверяют, а механизм
может сломаться именно тут: `camera_rect` со смещённым началом координат (все тесты
тестера держат `x_px=y_px=0.0`), порядок отрисовки при перекрытии двух объектов
(z-order), отсутствие альясинга кадра между вызовами `render()` и точная граница
bbox-пересечения (касание края ровно).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import FACTOR_MM, ObjectFactory, ObjectSpawner, SceneCompositor, ScenePreset


def _make_fixture_catalog(tmp_path: Path, name: str, color_bgr: tuple[int, int, int]) -> Path:
    classes_dir = tmp_path / f"classes_{name}"
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


def _make_spawner(tmp_path: Path, name: str, color_bgr: tuple[int, int, int], **spawner_kwargs) -> ObjectSpawner:
    classes_dir = _make_fixture_catalog(tmp_path, name, color_bgr)
    preset = ScenePreset(catalog_dir=str(classes_dir), angle_range_deg=(0.0, 0.0), defect_probability=0.0)
    factory = ObjectFactory(preset)
    kwargs = {"interval_s": (1000.0, 1000.0), "scene_length_mm": 1_000_000.0, "max_active": 200}
    kwargs.update(spawner_kwargs)
    return ObjectSpawner(factory, **kwargs)


def _spawn_one_at(spawner: ObjectSpawner, spawn_encoder: float, seed: int = 0):
    rng = np.random.default_rng(seed)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=2000.0, rng=rng)
    objs = spawner.active_objects()
    assert len(objs) == 1, "setup sanity: ожидался ровно один заспавненный объект"
    return objs[0]


# --------------------------------------------------------------------------------------
# (a) camera_rect со смещённым x_px/y_px — тестер держит их нулевыми во всех тестах
# --------------------------------------------------------------------------------------


def test_camera_rect_offset_shifts_object_position(tmp_path):
    """`x_px`/`y_px` != 0 вычитаются из позиции объекта (та же формула, что для фона):
    объект в мировых координатах на месте, кадр — это окно `camera_rect` в мир."""
    spawner = _make_spawner(tmp_path, "a", color_bgr=(0, 0, 255))
    _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=(60, 60, 60))

    # x_px=50 -> объект (offset_mm=0, cx_world=0) виден в кадре на cx = 0 - 50 = -50 —
    # ПОЛНОСТЬЮ за левым краем кадра 100x150 -> отсутствует.
    frame_shifted_out, passports_out = compositor.render(now_encoder=0.0, camera_rect=(50.0, 0.0, 100.0, 150.0))
    assert passports_out == []

    # x_px=-50 -> cx = 0 - (-50) = 50, объект (16x16) целиком внутри кадра 100x150.
    frame_shifted_in, passports_in = compositor.render(now_encoder=0.0, camera_rect=(-50.0, 0.0, 100.0, 150.0))
    assert len(passports_in) == 1
    assert tuple(int(v) for v in frame_shifted_in[75, 50]) == (255, 0, 0)
    del frame_shifted_out


def test_camera_rect_y_offset_shifts_belt_line(tmp_path):
    """`y_px` != 0 сдвигает видимую линию ленты: `cy = belt_y_px - y_px`."""
    spawner = _make_spawner(tmp_path, "a", color_bgr=(0, 0, 255))
    _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=(60, 60, 60))

    # y_px=25 -> cy = 75 - 25 = 50 (не 75) -> объект виден на строке 50, не 75.
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(-50.0, 25.0, 100.0, 150.0))
    assert len(passports) == 1
    assert tuple(int(v) for v in frame[50, 50]) == (255, 0, 0)
    assert tuple(int(v) for v in frame[75, 50]) == (60, 60, 60), "на старой (без сдвига) линии — фон, объект уехал"


# --------------------------------------------------------------------------------------
# (b) Порядок отрисовки при перекрытии — z-order = порядок спавна
# --------------------------------------------------------------------------------------


def test_overlapping_objects_passports_follow_spawn_order(tmp_path):
    """Два объекта в одной точке ленты (одинаковый `spawn_encoder`) — `render()` рисует
    (и возвращает паспорта) СТРОГО в порядке `spawner.active_objects()`, то есть в порядке
    спавна: поздний объект композитится ПОСЛЕ раннего и потому визуально перекрывает его
    (реализация `render()` не переупорядочивает список по какому-то отдельному z-ключу —
    закрепляем это явным сравнением порядка id, а не полагаемся на то, что тестер этого
    не проверил случайно)."""
    spawner = _make_spawner(tmp_path, "a", color_bgr=(0, 0, 255), interval_s=(1.0, 1.0), max_active=10)
    rng = np.random.default_rng(0)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взводит срок
    spawner.tick(now_encoder=0.0, now_wall_s=2.0, rng=rng)  # спавнит obj-1
    spawner.tick(now_encoder=0.0, now_wall_s=4.0, rng=rng)  # спавнит obj-2 (позже obj-1)
    ids = [o.passport.object_id for o in spawner.active_objects()]
    assert ids == ["obj-1", "obj-2"], "setup sanity: порядок спавна"

    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=(60, 60, 60))
    _frame, passports = compositor.render(now_encoder=0.0, camera_rect=(-50.0, 0.0, 100.0, 150.0))
    assert [p.object_id for p in passports] == ["obj-1", "obj-2"]


# --------------------------------------------------------------------------------------
# (c) render() не расшаривает буфер кадра между вызовами
# --------------------------------------------------------------------------------------


def test_render_returns_independent_frame_each_call(tmp_path):
    """Два последовательных `render()` возвращают РАЗНЫЕ объекты `np.ndarray` — правка
    одного не должна протечь во второй (защита от будущей оптимизации "кэшировать фон
    и рисовать поверх одного и того же буфера")."""
    spawner = _make_spawner(tmp_path, "a", color_bgr=(0, 0, 255))
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=(60, 60, 60))

    frame_1, _p1 = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 50.0, 50.0))
    frame_1[0, 0] = (1, 2, 3)
    frame_2, _p2 = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 50.0, 50.0))

    assert frame_1 is not frame_2
    assert tuple(int(v) for v in frame_2[0, 0]) == (60, 60, 60), "мутация первого кадра протекла во второй"


# --------------------------------------------------------------------------------------
# (d) Граница bbox: касание края РОВНО (нулевая полоса пересечения) — невидим
# --------------------------------------------------------------------------------------


def test_object_touching_frame_edge_exactly_is_absent(tmp_path):
    """bbox объекта касается правого края кадра РОВНО (`x0 == w`, не `<`) — ноль видимых
    пикселей, объект не должен попасть в `passports` (закрепляет строгое неравенство
    в `_bbox_intersects`, не проверено тестером явно на этой точной границе)."""
    spawner = _make_spawner(tmp_path, "a", color_bgr=(0, 0, 255))
    obj = _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=75.0, background_bgr=(60, 60, 60))

    # объект 16x16, половина=8; камера шириной 92 px -> x0 объекта == w кадра ровно при
    # cx=100 (x0 = 100-8 = 92 = w). px_per_mm=1.0, x_px=0.0 -> now_encoder = 100 / FACTOR_MM.
    now_encoder = 100.0 / FACTOR_MM
    frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 92.0, 150.0))

    assert passports == [], f"объект {obj.passport.object_id}: bbox касается края ровно — ожидали отсутствие"
    expected = np.empty_like(frame)
    expected[:, :, 0], expected[:, :, 1], expected[:, :, 2] = (60, 60, 60)
    assert np.array_equal(frame, expected)


# --------------------------------------------------------------------------------------
# (e) Заглушка литерала FACTOR_MM — не даёт файлу остаться неиспользуемым импортом,
#     подтверждает, что смещение в тестах этого файла считается из того же инварианта
# --------------------------------------------------------------------------------------


def test_offset_formula_uses_shared_factor_mm(tmp_path):
    spawner = _make_spawner(tmp_path, "a", color_bgr=(0, 0, 255))
    _spawn_one_at(spawner, spawn_encoder=0.0)
    compositor = SceneCompositor(spawner, px_per_mm=2.0, belt_y_px=75.0, background_bgr=(60, 60, 60))

    delta_ticks = 500.0
    expected_cx = delta_ticks * FACTOR_MM * 2.0
    frame, passports = compositor.render(now_encoder=delta_ticks, camera_rect=(0.0, 0.0, 400.0, 150.0))

    assert len(passports) == 1
    cx_i = int(round(expected_cx))
    assert tuple(int(v) for v in frame[75, cx_i]) == (255, 0, 0)
