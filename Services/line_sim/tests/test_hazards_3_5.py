"""Hazard-тесты автора Task 3.5 — job↔object matching (`Services/line_sim/core/matching.py`)
и `ObjectSpawner.remove()` (`Services/line_sim/core/spawner.py`).

Независимый тестер уже принял основной контракт (`test_acceptance_3_5.py`, RED до
реализации). Эти тесты — внутренние опасности механизма, которые видны только автору:

1. Два задания подряд на один и тот же объект: первое снимает объект (`matched`),
   второе на уже снятый объект — `match_job` должен получить его в `removed`, иначе
   робот «поймает» уже не существующий объект второй раз молча.
2. `ecap`, далеко обгоняющий момент спавна объекта — точная арифметика оффсета
   (`encoder_to_offset_mm`), без исключений на больших значениях энкодера.
3. Round-trip `JobDone`/`BeltGeometry` (`to_dict`/`from_dict`) — контракт модуля
   («Post: round-trip», см. docstring `matching.py`), явно вне области тестера
   (сказано в докстринге `test_acceptance_3_5.py`).
4. `remove()` не трогает расписание `ObjectSpawner` в режиме `interval_s` — если бы
   `remove()` задевал `_deadline`, снятие объекта посреди интервала сдвигало бы момент
   следующего спавна (регрессия из §3 контракта: "счёт шага спавна... не трогает").

Своя фикстура-фабрика (тот же паттерн, что в `test_spawner.py`/`test_acceptance_3_5.py`) —
файл не импортирует их.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset
from Services.line_sim.core.belt import FACTOR_MM
from Services.line_sim.core.matching import BeltGeometry, JobDone, match_job
from Services.line_sim.interfaces import ObjectPassport


def _make_factory(tmp_path: Path, defect_probability: float = 0.0) -> ObjectFactory:
    class_dir = tmp_path / "catalog" / "only_class"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))

    preset_path = tmp_path / "preset.yaml"
    preset_path.write_text(
        yaml.safe_dump(
            {"catalog_dir": "catalog", "layers": [], "defect_probability": defect_probability},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    preset = ScenePreset.from_yaml(preset_path)
    return ObjectFactory(preset)


def _passport(object_id: str, spawn_encoder: float) -> ObjectPassport:
    return ObjectPassport(
        object_id=object_id,
        class_name="only_class",
        angle_deg=0.0,
        defect=None,
        spawn_encoder=spawn_encoder,
    )


def test_second_job_on_already_removed_object_is_dup_not_silent_match():
    """Первое задание снимает объект (matched); второе на тот же object_id, переданный
    в removed, — dup, а не тихое повторное matched (объекта уже нет в active)."""
    geometry = BeltGeometry()
    passport = _passport("obj-1", spawn_encoder=0.0)

    first_job = JobDone(index=1, x_mm=0.0, y_mm=144.473, ecap=1000, t=0.0)
    first_result = match_job([passport], first_job, geometry)
    assert first_result.outcome == "matched"
    assert first_result.object_id == "obj-1"

    # объект снят из active (плагин сцены вызвал бы spawner.remove() здесь) -> второе
    # задание на тот же ecap видит его только в removed.
    second_job = JobDone(index=2, x_mm=0.0, y_mm=144.473, ecap=1000, t=1.0)
    second_result = match_job([], second_job, geometry, removed=[passport])

    assert second_result.outcome == "dup"
    assert second_result.object_id == "obj-1"


def test_ecap_far_ahead_of_spawn_no_exception_exact_arithmetic():
    """ecap на порядки больше spawn_encoder — точная линейная арифметика
    (`encoder_to_offset_mm`), никакого исключения на больших числах."""
    geometry = BeltGeometry()
    spawn_encoder = 10.0
    ecap = 10_000_000.0  # далеко впереди момента спавна объекта
    passport = _passport("obj-far", spawn_encoder=spawn_encoder)

    expected_offset = (ecap - spawn_encoder) * FACTOR_MM
    job = JobDone(index=1, x_mm=0.0, y_mm=expected_offset, ecap=int(ecap), t=0.0)

    result = match_job([passport], job, geometry, match_radius_mm=1.0)

    assert result.outcome == "matched"
    assert result.residual_mm is not None
    assert result.residual_mm < 1e-6


def test_jobdone_and_beltgeometry_roundtrip():
    """`from_dict(x.to_dict()) == x` — контракт модуля, вне области независимого тестера."""
    job = JobDone(index=7, x_mm=12.3, y_mm=-45.6, ecap=106016, t=123.456)
    assert JobDone.from_dict(job.to_dict()) == job

    geometry = BeltGeometry(origin_x_mm=100.0, origin_y_mm=-50.0)
    assert BeltGeometry.from_dict(geometry.to_dict()) == geometry


def test_remove_does_not_disturb_interval_deadline(tmp_path):
    """`remove()` в режиме `interval_s` не трогает `_deadline` — снятие объекта
    посреди интервала не сдвигает момент следующего спавна вперёд или назад."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(5.0, 5.0), scene_length_mm=1e9)
    rng = np.random.default_rng(3)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взводит deadline=5.0, без спавна
    assert spawner.active_objects() == []

    spawner.tick(now_encoder=0.0, now_wall_s=5.0, rng=rng)  # deadline достигнут -> spawn obj-1
    active = spawner.active_objects()
    assert len(active) == 1
    object_id = active[0].passport.object_id

    removed = spawner.remove(object_id)
    assert removed is not None
    assert spawner.active_objects() == []

    # следующий deadline = 5.0 + 5.0 = 10.0 — remove() не должен был его тронуть.
    spawner.tick(now_encoder=0.0, now_wall_s=6.0, rng=rng)
    assert spawner.active_objects() == [], (
        "спавн на 6.0 при deadline=10.0 означал бы, что remove() задел _deadline "
        "(регрессия) — расписание должно идти от исходного 5.0+5.0"
    )

    spawner.tick(now_encoder=0.0, now_wall_s=10.0, rng=rng)
    assert len(spawner.active_objects()) == 1


def test_residual_exactly_at_radius_is_no_object():
    """Лид, после break-injection I5: граница радиуса строгая (`<`, контракт §2).
    Замена на `<=` проходила весь набор зелёным."""
    from Services.line_sim.core.matching import BeltGeometry, JobDone, match_job
    from Services.line_sim.interfaces import ObjectPassport

    obj = ObjectPassport(object_id="obj-1", class_name="A", angle_deg=0.0, defect=None, spawn_encoder=0.0)
    at_radius = JobDone(index=1, x_mm=5.0, y_mm=0.0, ecap=0, t=0.0)
    inside = JobDone(index=2, x_mm=4.99, y_mm=0.0, ecap=0, t=0.0)

    assert match_job([obj], at_radius, BeltGeometry()).outcome == "no_object"
    assert match_job([obj], inside, BeltGeometry()).outcome == "matched"
