"""Независимые RED acceptance-тесты Task 3.5 (Services) — «робот забрал — объект исчез».

Контракт лида: секция "Контракт лида 3.5 (2026-09-23, до тестера)" в
plans/line-sim/phase-3-object-engine.md, §2 (новый Services/line_sim/core/matching.py) и
§3 (ObjectSpawner.remove()). Написано ДО реализации, в git worktree на коммите контракта —
тестер намеренно не видел implementation-файлы (см. FILES тестового задания).

Символы matching.py импортируются ВНУТРИ каждого теста — модуль ещё не существует,
падение каждого теста не должно зависеть от соседних тестов файла.

Округление: JobDone/BeltGeometry round-trip (to_dict/from_dict) — вне области, его
покрывает автор (hazard-тесты внутренней механики).
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset
from Services.line_sim.core.belt import FACTOR_MM
from Services.line_sim.interfaces import ObjectPassport


def _make_factory(tmp_path: Path, defect_probability: float = 0.0) -> ObjectFactory:
    """Фабрика-заглушка — тот же паттерн, что в test_spawner.py (файл не импортирует его)."""
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


# --------------------------------------------------------------------------
# §2 — Services/line_sim/core/matching.py (модуль НЕ существует до реализации)
# --------------------------------------------------------------------------


def test_identity_geometry_matches_at_ecap_1000():
    """Литерал приёмки: тождественная геометрия, spawn_encoder=0, ecap=1000,
    задание (0.0, 144.473) -> matched, residual_mm < 0.5."""
    from Services.line_sim.core.matching import BeltGeometry, JobDone, match_job

    geometry = BeltGeometry()
    passport = _passport("obj-1", spawn_encoder=0.0)
    job = JobDone(index=1, x_mm=0.0, y_mm=144.473, ecap=1000, t=0.0)

    result = match_job([passport], job, geometry)

    assert result.outcome == "matched"
    assert result.object_id == "obj-1"
    assert result.residual_mm is not None
    assert result.residual_mm < 0.5


def test_shift_20mm_x_is_no_object():
    """Тот же объект/задание, сдвиг +20 мм по X -> no_object, object_id=None."""
    from Services.line_sim.core.matching import BeltGeometry, JobDone, match_job

    geometry = BeltGeometry()
    passport = _passport("obj-1", spawn_encoder=0.0)
    job = JobDone(index=1, x_mm=20.0, y_mm=144.473, ecap=1000, t=0.0)

    result = match_job([passport], job, geometry)

    assert result.outcome == "no_object"
    assert result.object_id is None


def test_object_robot_xy_with_origin():
    """Геометрия origin=(100.0, -50.0), тот же объект и ecap -> объект в (100.0, 94.473)."""
    from Services.line_sim.core.matching import BeltGeometry, object_robot_xy

    geometry = BeltGeometry(origin_x_mm=100.0, origin_y_mm=-50.0)

    x, y = object_robot_xy(spawn_encoder=0.0, ecap=1000, geometry=geometry)

    assert x == pytest.approx(100.0, abs=1e-6)
    assert y == pytest.approx(94.473, abs=1e-6)


def test_removed_passport_gives_dup_with_its_id():
    """Тот же паспорт только в removed -> dup с его object_id."""
    from Services.line_sim.core.matching import BeltGeometry, JobDone, match_job

    geometry = BeltGeometry()
    passport = _passport("obj-ghost", spawn_encoder=0.0)
    job = JobDone(index=1, x_mm=0.0, y_mm=144.473, ecap=1000, t=0.0)

    result = match_job([], job, geometry, removed=[passport])

    assert result.outcome == "dup"
    assert result.object_id == "obj-ghost"


def test_nearest_active_wins_and_tie_goes_to_active():
    """Два активных объекта в 3 и 4 мм от точки -> matched с ближним (3 мм); при равной
    невязке active против removed -> matched (побеждает active)."""
    from Services.line_sim.core.matching import BeltGeometry, JobDone, match_job

    geometry = BeltGeometry()

    # Часть 1: identity-геометрия, BELT_UX=0 -> x объекта всегда 0. job.x=0, поэтому
    # невязка равна |job.y - object.y| ровно: 3мм и 4мм без округления смещения.
    job = JobDone(index=1, x_mm=0.0, y_mm=200.0, ecap=0, t=0.0)
    near = _passport("near", spawn_encoder=-197.0 / FACTOR_MM)  # offset=197 -> невязка 3
    far = _passport("far", spawn_encoder=-196.0 / FACTOR_MM)  # offset=196 -> невязка 4

    result = match_job([near, far], job, geometry)

    assert result.outcome == "matched"
    assert result.object_id == "near"

    # Часть 2: активный и снятый объект с одинаковым spawn_encoder -> одинаковая невязка
    # (0 у обоих) -> ничья разрешается в пользу active.
    tie_job = JobDone(index=2, x_mm=0.0, y_mm=0.0, ecap=0, t=0.0)
    live = _passport("live", spawn_encoder=0.0)
    ghost = _passport("ghost", spawn_encoder=0.0)

    tie_result = match_job([live], tie_job, geometry, removed=[ghost])

    assert tie_result.outcome == "matched"
    assert tie_result.object_id == "live"


def test_nonpositive_radius_raises_valueerror_naming_param():
    """match_radius_mm <= 0 -> ValueError с именем параметра в тексте."""
    from Services.line_sim.core.matching import BeltGeometry, JobDone, match_job

    geometry = BeltGeometry()
    job = JobDone(index=1, x_mm=0.0, y_mm=0.0, ecap=0, t=0.0)

    with pytest.raises(ValueError, match="match_radius_mm"):
        match_job([], job, geometry, match_radius_mm=0.0)


# --------------------------------------------------------------------------
# §3 — ObjectSpawner.remove() (Services/line_sim/core/spawner.py, extends-contract)
# --------------------------------------------------------------------------


def test_spawner_remove_returns_passport_unknown_is_none(tmp_path):
    """remove(id) снимает активный объект и возвращает его паспорт; неизвестный id -> None,
    без исключения."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(50.0, 50.0), scene_length_mm=1e9)
    rng = np.random.default_rng(1)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    active = spawner.active_objects()
    assert len(active) == 1
    object_id = active[0].passport.object_id

    removed = spawner.remove(object_id)

    assert removed is not None
    assert removed.object_id == object_id
    assert spawner.active_objects() == []
    assert spawner.remove("no-such-id") is None


def test_spawner_remove_keeps_spacing_and_numbering(tmp_path):
    """remove() не трогает счётчик шага спавна (_last_spawn_encoder) и нумерацию obj-N:
    следующий спавн наступает НА ТОМ ЖЕ шаге пути (не раньше — счётчик не сброшен) и
    получает следующий номер, не переиспользует снятый."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(50.0, 50.0), scene_length_mm=1e9)
    rng = np.random.default_rng(2)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    assert spawner.active_objects()[0].passport.object_id == "obj-1"
    spawner.remove("obj-1")
    assert spawner.active_objects() == []

    ticks = math.ceil(50.0 / FACTOR_MM)
    half_ticks = ticks // 2  # заведомо меньше порога 50мм

    spawner.tick(now_encoder=float(half_ticks), now_wall_s=0.0, rng=rng)
    assert spawner.active_objects() == [], (
        "спавн на полпути к порогу означал бы, что remove() сбросил "
        "_last_spawn_encoder (баг) — счётчик должен идти от исходной точки 0.0"
    )

    spawner.tick(now_encoder=float(ticks), now_wall_s=0.0, rng=rng)
    active_after = spawner.active_objects()
    assert len(active_after) == 1
    assert active_after[0].passport.object_id == "obj-2"
    assert active_after[0].passport.spawn_encoder == float(ticks)
