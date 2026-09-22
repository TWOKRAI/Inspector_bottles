"""Hazard-тесты автора для `ObjectSpawner` — режим `spacing_mm` (Task 3.3a, LS-010).

Независимого тестера на этой задаче НЕТ намеренно (`ObjectSpawner` уже принят тестером
на Task 3.3, повторная приёмка одного и того же механизма запрещена правилом проекта,
`.claude/CLAUDE.md` — «Stage 1 refined 2026-08-20»). Эти тесты несут двойной вес: сначала
пять литеральных критериев приёмки из плана (раздел Task 3.3a), затем hazard-тесты автора
на сам механизм нового режима (по аналогии с review fix F1/F2 режима `interval_s`,
`test_hazards_3_3.py`, LS-008).

Своя фикстура-фабрика (тот же паттерн, что в `test_hazards_3_3.py`/`test_acceptance_3_3.py`) —
файл не расширяет и не импортирует их.
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
from Services.line_sim.core.belt import FACTOR_MM, encoder_to_offset_mm


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


# --------------------------------------------------------------------------
# Acceptance criteria из плана (Task 3.3a) — литеральные числа, не выведенные из кода
# --------------------------------------------------------------------------


def test_uniform_spacing_144mm_matches_within_one_tick(tmp_path):
    """spacing_mm=(144, 144), лента едет: расстояния между соседними `spawn_encoder` —
    ровно 144 мм ± допуск одного тика, счёт через `FACTOR_MM` импортом (не хардкод)."""
    spacing = 144.0
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(spacing, spacing), scene_length_mm=1e9)
    rng = np.random.default_rng(200)

    tick_step = 1.0
    now_encoder = 0.0
    spawn_encoders: list[float] = []
    prev_count = 0
    max_ticks = int(spacing / (tick_step * FACTOR_MM)) * 6 + 100
    for _ in range(max_ticks):
        now_encoder += tick_step
        spawner.tick(now_encoder=now_encoder, now_wall_s=0.0, rng=rng)
        count = len(spawner.active_objects())
        if count > prev_count:
            spawn_encoders.append(now_encoder)
            prev_count = count
        if len(spawn_encoders) >= 5:
            break

    assert len(spawn_encoders) == 5
    tick_mm = tick_step * FACTOR_MM
    for a, b in zip(spawn_encoders, spawn_encoders[1:]):
        gap_mm = encoder_to_offset_mm(b, a)
        assert spacing <= gap_mm <= spacing + tick_mm + 1e-9, gap_mm


def test_range_100_200mm_all_within_bounds_and_not_all_equal(tmp_path):
    """spacing_mm=(100, 200): 50 спавнов, все расстояния внутри [100, 200], и не все
    равны (литеральные границы из плана, не значения из кода)."""
    lo, hi = 100.0, 200.0
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(lo, hi), scene_length_mm=1e9)
    rng = np.random.default_rng(201)

    tick_step = 5.0
    now_encoder = 0.0
    spawn_encoders: list[float] = []
    prev_count = 0
    max_ticks = int(hi / (tick_step * FACTOR_MM)) * 60
    for _ in range(max_ticks):
        now_encoder += tick_step
        spawner.tick(now_encoder=now_encoder, now_wall_s=0.0, rng=rng)
        count = len(spawner.active_objects())
        if count > prev_count:
            spawn_encoders.append(now_encoder)
            prev_count = count
        if len(spawn_encoders) >= 51:
            break

    assert len(spawn_encoders) == 51
    tick_mm = tick_step * FACTOR_MM
    gaps_mm = [encoder_to_offset_mm(b, a) for a, b in zip(spawn_encoders, spawn_encoders[1:])]
    assert len(gaps_mm) == 50
    for gap_mm in gaps_mm:
        assert lo <= gap_mm <= hi + tick_mm + 1e-9, gap_mm
    assert len(set(gaps_mm)) > 1, "джиттер lo!=hi обязан давать разные шаги, не константу"


def test_frozen_encoder_spawns_no_new_objects_over_200_ticks(tmp_path):
    """Замерший энкодер + 200 тиков в режиме `spacing_mm` -> число объектов не изменилось."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(50.0, 50.0), scene_length_mm=1e9)
    rng = np.random.default_rng(202)

    spawner.tick(now_encoder=1000.0, now_wall_s=0.0, rng=rng)  # первый спавн — сразу
    count_before = len(spawner.active_objects())
    assert count_before == 1

    for _ in range(200):
        spawner.tick(now_encoder=1000.0, now_wall_s=0.0, rng=rng)  # энкодер не растёт

    assert len(spawner.active_objects()) == count_before


def test_constructor_requires_exactly_one_of_interval_or_spacing(tmp_path):
    """Заданы оба параметра или ни одного -> `ValueError`, в тексте оба имени."""
    factory = _make_factory(tmp_path)

    with pytest.raises(ValueError) as exc_none:
        ObjectSpawner(factory, scene_length_mm=100.0)
    assert "interval_s" in str(exc_none.value)
    assert "spacing_mm" in str(exc_none.value)

    with pytest.raises(ValueError) as exc_both:
        ObjectSpawner(factory, interval_s=(0.5, 0.5), spacing_mm=(100.0, 100.0), scene_length_mm=100.0)
    assert "interval_s" in str(exc_both.value)
    assert "spacing_mm" in str(exc_both.value)


def test_interval_mode_unaffected_by_keyword_only_signature(tmp_path):
    """Режим `interval_s` ведёт себя ровно как до задачи — сигнатура конструктора
    сменилась на keyword-only, поведение режима не тронуто (Task 3.3 остаётся эталоном)."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(203)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)
    assert len(spawner.active_objects()) == 1


# --------------------------------------------------------------------------
# Валидация spacing_mm (edge cases контракта, симметрично interval_s)
# --------------------------------------------------------------------------


def test_constructor_rejects_spacing_lo_greater_than_hi(tmp_path):
    factory = _make_factory(tmp_path)
    with pytest.raises(ValueError, match="spacing_mm"):
        ObjectSpawner(factory, spacing_mm=(200.0, 100.0), scene_length_mm=100.0)


def test_constructor_rejects_nonpositive_spacing_lo(tmp_path):
    factory = _make_factory(tmp_path)
    with pytest.raises(ValueError, match="spacing_mm"):
        ObjectSpawner(factory, spacing_mm=(0.0, 100.0), scene_length_mm=100.0)


# --------------------------------------------------------------------------
# Hazard-тесты автора на сам механизм spacing_mm (аналоги review fix F1/F2, LS-008)
# --------------------------------------------------------------------------


def test_first_spawn_happens_on_first_tick_no_waiting(tmp_path):
    """Первый объект создаётся на первом же `tick()` — часов ждать не нужно, лента уже
    едет (в отличие от `interval_s`, где первый `tick()` только взводит срок)."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(50.0, 50.0), scene_length_mm=1e9)
    rng = np.random.default_rng(207)

    spawner.tick(now_encoder=123.0, now_wall_s=0.0, rng=rng)
    active = spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.spawn_encoder == 123.0


def test_pause_blocks_even_the_first_spawn_in_spacing_mode(tmp_path):
    """Пауза останавливает НОВЫЙ спавн, включая самый первый (симметрично `interval_s`,
    где спавн на паузе тоже не создаёт объект вообще)."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(50.0, 50.0), scene_length_mm=1e9)
    rng = np.random.default_rng(208)

    spawner.set_paused(True)
    spawner.tick(now_encoder=1000.0, now_wall_s=0.0, rng=rng)
    assert spawner.active_objects() == []

    spawner.set_paused(False)
    spawner.tick(now_encoder=1000.0, now_wall_s=0.0, rng=rng)
    assert len(spawner.active_objects()) == 1


def test_permanent_factory_failure_in_spacing_mode_raises_once_per_window(tmp_path, monkeypatch):
    """Аналог review fix F1 (LS-008) для `spacing_mm`: `_last_spawn_encoder`/
    `_next_spacing_mm` обновляются ДО вызова `factory.make()`, поэтому постоянный сбой
    роняет исключение раз в ШАГ (при непрерывно едущей ленте), не на каждом тике — без
    этого фикса падающая фабрика заливала бы исключениями каждый тик продюсера, как это
    было у `interval_s` до review fix F1."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(50.0, 50.0), scene_length_mm=1e9)
    rng = np.random.default_rng(209)

    def _always_fails(*args, **kwargs):
        raise RuntimeError("постоянный сбой каталога")

    monkeypatch.setattr(factory, "make", _always_fails)

    tick_step = 5.0
    window_ticks = math.ceil(50.0 / (tick_step * FACTOR_MM))
    total_ticks = window_ticks * 3  # три полных окна -> ровно три исключения

    exceptions = 0
    now_encoder = 0.0
    for _ in range(total_ticks):
        now_encoder += tick_step
        try:
            spawner.tick(now_encoder=now_encoder, now_wall_s=0.0, rng=rng)
        except RuntimeError:
            exceptions += 1

    assert exceptions == 3, "исключение на частоте ШАГА, не на каждом из total_ticks тиков"
    assert spawner.active_objects() == []


def test_spacing_ceiling_does_not_move_threshold_and_resumes_after_despawn(tmp_path):
    """Аналог review fix F2 (LS-008): потолок `max_active` не трогает порог `spacing_mm` —
    как только деспавн освобождает место, спавн на давно просроченном пороге срабатывает
    на БЛИЖАЙШЕМ тике, не ждёт нового шага."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, spacing_mm=(50.0, 50.0), scene_length_mm=100.0, max_active=1)
    rng = np.random.default_rng(210)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # первый спавн сразу, spawn_encoder=0.0
    assert len(spawner.active_objects()) == 1

    # Порог (50мм) давно превышен, но потолок max_active=1 блокирует; деспавн ещё не
    # сработал (600 * FACTOR_MM = 86.68мм <= 100мм — объект ещё на сцене).
    for enc in (400.0, 500.0, 600.0):
        spawner.tick(now_encoder=enc, now_wall_s=0.0, rng=rng)
    assert len(spawner.active_objects()) == 1

    # Лента уезжает далеко -- первый объект деспавнится, потолок освобождается; порог
    # давно превышен, поэтому спавн происходит НА ЭТОМ ЖЕ тике.
    far = 10_000.0
    spawner.tick(now_encoder=far, now_wall_s=0.0, rng=rng)
    active = spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.spawn_encoder == far
