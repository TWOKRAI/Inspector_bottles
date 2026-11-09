# -*- coding: utf-8 -*-
"""Task R1, A10 — слепой acceptance-тест минимального интервала между дисками списка (уровень сервиса).

Контракт — ТОЛЬКО пункт A10 раздела ACCEPTANCE задачи R1 (``plans/line-sim/tasks/R1.md``) и строка
публичного интерфейса: ``from Services.line_sim.core.spawner import DiscSequence, ObjectSpawner``;
``ObjectSpawner(..., sequence=DiscSequence())``, ``tick(now_encoder=, now_wall_s=, rng=)``,
``active_objects()``, ``DiscSequence().load(...)``. DESIGN тестеру не показывался. Worktree на коммите до
реализации: ``DiscSequence`` не существует — ожидаемый красный
``ImportError: cannot import name 'DiscSequence' from 'Services.line_sim.core.spawner'``.

НЕОДНОЗНАЧНОСТЬ (вынесена в отчёт, не угадана глубже): точная сигнатура ``DiscSequence.load`` в ACCEPTANCE
не дана (``load(...)``). Тест зовёт ``sequence.load(discs)`` с ``discs`` = список пар ``[буква, угол]`` — как
в команде ``scene.sequence``. Если сигнатура другая — красный будет ``TypeError`` на ``load``, а не про
интервал; тогда правится только вызов в ``_loaded_sequence``.

Время — целочисленный счётчик шагов x 0,05 с (без накопления ошибки float); окно допуска 1e-9 на границу 1,0 с
вынесено в ``_EPS`` и объяснено у проверки. Каталог классов — временный (``tmp_path``), ``data/`` не читается.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset

_LETTERS = ["А", "Е", "Р"]  # А Е Р
_DT = 0.05
_EPS = 1e-9  # t = k * 0.05 в float: разность соседних t может отличаться от 1.0 на ~1e-16, не на смысл


def _factory(root: Path) -> ObjectFactory:
    catalog = root / "cat"
    for index, letter in enumerate(_LETTERS):
        folder = catalog / letter
        folder.mkdir(parents=True)
        sprite = np.zeros((16, 16, 4), dtype=np.uint8)
        sprite[:, :, :3] = 60 + 30 * index
        sprite[:, :, 3] = 255
        imwrite_unicode(folder / "0.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    preset = ScenePreset(catalog_dir=str(catalog), angle_range_deg=(0.0, 360.0), defect_probability=0.0, layers=[])
    return ObjectFactory(preset)


def _new_sequence():
    from Services.line_sim.core.spawner import DiscSequence

    return DiscSequence()


def _loaded_sequence(discs: list[list]):
    sequence = _new_sequence()
    sequence.load(discs)
    return sequence


def _spawn_times(spawner: ObjectSpawner, *, seconds: float) -> list[float]:
    """Тикать с шагом 0,05 с на живом энкодере; вернуть ``now_wall_s`` каждого появления нового объекта."""
    rng = np.random.default_rng(0)
    times: list[float] = []
    seen = 0
    for k in range(int(round(seconds / _DT)) + 1):
        now = k * _DT
        spawner.tick(now_encoder=float(k), now_wall_s=now, rng=rng)
        count = len(spawner.active_objects())
        if count > seen:
            times.extend([now] * (count - seen))
            seen = count
    return times


@pytest.mark.timeout(60)
def test_min_interval_one_second(tmp_path):
    """A10: поток ``interval_s (0.1, 0.1)``, список из 5, шаг времени 0,05 с -> разность ``now_wall_s`` между
    появлениями соседних объектов списка >= 1,0 с, все 5 поданы не позже 5,2 с.
    Ловит: подачу по интервалу потока (0,1 с) вместо минимума 1,0 с; интервал, считаемый от неверной точки."""
    discs = [[_LETTERS[0], 0], [_LETTERS[1], 10], [_LETTERS[2], 20], [_LETTERS[0], 30], [_LETTERS[1], 40]]
    spawner = ObjectSpawner(
        _factory(tmp_path),
        interval_s=(0.1, 0.1),
        scene_length_mm=1e9,
        sequence=_loaded_sequence(discs),
    )

    times = _spawn_times(spawner, seconds=8.0)

    assert len(times) == 5, times
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap >= 1.0 - _EPS for gap in gaps), (times, gaps)
    assert times[-1] <= 5.2 + _EPS, times


@pytest.mark.timeout(60)
def test_random_mode_interval_unchanged(tmp_path):
    """A10 (вторая часть): в режиме ``random`` (``DiscSequence()`` без ``load``) с тем же потоком
    ``(0.1, 0.1)`` интервал прежний, 0,1 с: за 4 с не меньше 20 появлений, ни одного зазора больше 0,15 с
    (шаг 0,05 с). Ловит: минимум 1,0 с, протёкший в обычный случайный режим."""
    spawner = ObjectSpawner(
        _factory(tmp_path),
        interval_s=(0.1, 0.1),
        scene_length_mm=1e9,
        sequence=_new_sequence(),
    )

    times = _spawn_times(spawner, seconds=4.0)

    assert len(times) >= 20, times
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap <= 0.15 + _EPS for gap in gaps), (max(gaps), gaps)
