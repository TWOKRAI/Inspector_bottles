"""Hazard-тесты автора для `ObjectSpawner` (Task 3.3) — ловушки самого механизма:
копия `active_objects()`, устойчивость к исключению `factory.make()` внутри `tick()`,
джиттер интервала в границах, деспавн по СОБСТВЕННОМУ `spawn_encoder` объекта.

Не переиспользует и не расширяет `test_acceptance_3_3.py` (независимые acceptance-тесты
тестера) — своя фикстура-фабрика (тот же паттерн из `test_acceptance_3_2.py`).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset


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


def test_active_objects_copy_survives_mutation_and_later_despawn(tmp_path):
    """`active_objects()` — копия: `.clear()`/`.pop()` результата не трогают внутренний
    список, и деспавн следующим `tick()` по-прежнему видит объект и снимает его."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=100.0)
    rng = np.random.default_rng(101)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)
    snapshot = spawner.active_objects()
    assert len(snapshot) == 1
    snapshot.pop()  # мутация копии — не должна тронуть внутренний список спавнера
    snapshot.append("посторонний объект")  # даже подмена элемента копии — изолирована

    assert len(spawner.active_objects()) == 1  # спавнер не заметил мутацию копии

    # despawn всё ещё работает после мутации возвращённой копии (693 * FACTOR_MM > 100)
    spawner.tick(now_encoder=693.0, now_wall_s=0.5, rng=rng)
    assert spawner.active_objects() == []


def test_tick_survives_factory_make_exception_no_lost_deadline_no_double_spawn(tmp_path, monkeypatch):
    """`factory.make()` падает на одном тике — `tick()` не портит состояние: срок не
    теряется (следующий тик на просроченном сроке повторяет попытку РОВНО один раз,
    не два) и спавнер остаётся рабочим (следующий успешный `make()` спавнит нормально)."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(102)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод срока = 0.5

    real_make = factory.make
    calls = {"n": 0}

    def _flaky_make(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("транзитный сбой каталога")
        return real_make(*args, **kwargs)

    monkeypatch.setattr(factory, "make", _flaky_make)

    with pytest.raises(RuntimeError, match="транзитный сбой"):
        spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)
    assert spawner.active_objects() == []  # ничего не добавлено при сбое

    # следующий тик на ТОМ ЖЕ (не потерянном) сроке — ровно ОДИН успешный спавн, не два
    spawner.tick(now_encoder=0.0, now_wall_s=0.6, rng=rng)
    assert len(spawner.active_objects()) == 1
    assert calls["n"] == 2  # ровно одна повторная попытка, не бесконечный ретрай в одном tick()


def test_interval_jitter_stays_within_bounds_over_200_spawns(tmp_path):
    """Джиттер `rng.uniform(lo, hi)` с lo != hi — каждый интервал между последовательными
    спавнами лежит строго в [lo, hi] (реальный `np.random.default_rng`, не мок)."""
    lo, hi = 0.2, 0.8
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(lo, hi), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(103)

    now_wall = 0.0
    spawner.tick(now_encoder=0.0, now_wall_s=now_wall, rng=rng)  # взвод

    spawn_times: list[float] = []
    step = 0.01  # мельче нижней границы интервала — не пропустим момент спавна
    prev_count = 0
    while len(spawn_times) < 200:
        now_wall += step
        spawner.tick(now_encoder=0.0, now_wall_s=now_wall, rng=rng)
        count = len(spawner.active_objects())
        if count > prev_count:
            spawn_times.append(now_wall)
            prev_count = count

    gaps = [b - a for a, b in zip(spawn_times, spawn_times[1:])]
    assert len(gaps) == 199
    # допуск на дискретность шага сканирования (step) сверх точной границы rng.uniform
    for gap in gaps:
        assert lo - step <= gap <= hi + step, gap


def test_despawn_uses_each_objects_own_spawn_encoder(tmp_path):
    """Два объекта, заспавненные на РАЗНЫХ энкодерах, уезжают со сцены в РАЗНОЕ время —
    деспавн считает смещение от `passport.spawn_encoder` каждого объекта, не от общего
    начала отсчёта спавнера."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(1.0, 1.0), scene_length_mm=100.0)
    rng = np.random.default_rng(104)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод
    spawner.tick(now_encoder=0.0, now_wall_s=1.0, rng=rng)  # spawn A: spawn_encoder=0.0
    spawner.tick(now_encoder=500.0, now_wall_s=2.0, rng=rng)  # spawn B: spawn_encoder=500.0
    assert len(spawner.active_objects()) == 2

    # 693 * FACTOR_MM (0.144473) = 100.119789 > 100 -> A (spawn_encoder=0) уехал,
    # B (spawn_encoder=500) на энкодере 693 прошёл только 193 тика от своего спавна
    # (193 * 0.144473 = 27.883 мм) — всё ещё на сцене.
    spawner.tick(now_encoder=693.0, now_wall_s=2.1, rng=rng)
    remaining = spawner.active_objects()
    assert len(remaining) == 1
    assert remaining[0].passport.spawn_encoder == 500.0
