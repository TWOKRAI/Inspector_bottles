# -*- coding: utf-8 -*-
"""Тесты автора (hazard) — Task 2.2 плана line-sim, ``SceneSourcePlugin``.

Про что acceptance-тесты тестера НЕ проверяют, а механизм ломается ровно тут:
гонка старта процессов (сцена поднялась раньше робота), обе формы дельт в
ОДНОЙ последовательности (не по отдельности), де-дублирование предупреждения о
протухшем значении (не спам на каждый кадр) и конкурентность колбэка подписки
против ``produce()`` (два разных потока пишут/читают ``self._world`` под
одним ``Lock``).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.sim.scene_source.plugin import SPRITE_BGR, SceneSourcePlugin

pytestmark = pytest.mark.timeout(30)


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — см. ``tests/test_scene_source_acceptance.py``."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)


def _make_plugin(cfg_overrides: dict | None = None):
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        "stale_ms": 200,
        **(cfg_overrides or {}),
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, state_proxy


# --------------------------------------------------------------------------- #
# (a) Сцена поднялась раньше робота — гонка старта процессов                  #
# --------------------------------------------------------------------------- #


def test_scene_up_before_robot_multiple_produce_no_exception() -> None:
    """Мир пуст на протяжении НЕСКОЛЬКИХ подряд кадров (не одного, как у
    тестера) — реалистичная гонка: `robot` поднимается на несколько тактов
    позже `camera`. Ни один `produce()` не должен бросить, и кадр остаётся
    валидным на каждом тике."""
    plugin, _ctx, _sp = _make_plugin()
    for _ in range(20):
        items = plugin.produce()
        assert isinstance(items, list) and items
        frame = items[0]["frame"]
        assert frame.shape == (480, 640, 3)


# --------------------------------------------------------------------------- #
# (b) Обе формы дельт В ОДНОЙ последовательности — частичная полистовая       #
#     дельта не должна затирать поля, пришедшие дельтой создания             #
# --------------------------------------------------------------------------- #


def test_creation_then_partial_leaf_update_preserves_untouched_fields() -> None:
    """Дельта-целиком кладёт {value, mm_s, t}; следующая полистовая дельта
    обновляет ТОЛЬКО value/t. Исправлено ревью Task 2.2: полистовая форма НЕ
    приходит от повторного вызова живого паблишера (``state_proxy.set()``
    шлёт словарь целиком КАЖДЫЙ раз — см. докстринг ``plugin.py``); в реальном
    процессе она приходит от РЕПЛЕЯ начального состояния при (пере)подписке
    (``_replay_initial_state``). Тест бьёт по самому объединению в
    ``_on_deltas`` независимо от того, кто прислал полистовую форму: mm_s из
    дельты-целиком не должен пропасть из накопителя после частичного
    полистового апдейта."""
    plugin, ctx, sp = _make_plugin()
    t0 = time.monotonic()
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": 0, "mm_s": 50.0, "t": t0},
                source="robot",
            )
        ]
    )
    with plugin._lock:
        assert plugin._world.get("mm_s") == 50.0

    # Полистовая дельта только по value/t — синтетическая имитация формы РЕПЛЕЯ
    # подписки (``_replay_initial_state``), НЕ повторного вызова паблишера
    # (тот шлёт словарь целиком каждый раз, см. докстринг ``plugin.py``).
    sp.emit(
        [
            Delta(path="sim.belt.encoder.value", old_value=0, new_value=100, source="robot"),
            Delta(path="sim.belt.encoder.t", old_value=t0, new_value=t0 + 0.05, source="robot"),
        ]
    )
    with plugin._lock:
        assert plugin._world.get("value") == 100
        assert plugin._world.get("mm_s") == 50.0, "mm_s из дельты создания пропал после частичного полистового апдейта"


# --------------------------------------------------------------------------- #
# (c) Де-дублирование предупреждения — не спам на каждый кадр                #
# --------------------------------------------------------------------------- #


def test_stale_warning_deduplicated_by_t_not_spammed_every_frame() -> None:
    """Одно и то же протухшее ``t`` не должно порождать новое предупреждение
    на КАЖДЫЙ ``produce()`` — иначе лог сима зальётся тысячами строк в
    секунду на длинной паузе публикации. Новое (другое) протухшее ``t`` —
    новое предупреждение."""
    plugin, ctx, sp = _make_plugin()
    stale_t = time.monotonic() - 10.0
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": 0, "mm_s": 0.0, "t": stale_t},
                source="robot",
            )
        ]
    )

    for _ in range(5):
        plugin.produce()
    assert ctx.log_warning.call_count == 1, (
        f"ожидалось ровно 1 предупреждение на неизменном t, получено {ctx.log_warning.call_count}"
    )

    stale_t_2 = stale_t - 1.0
    sp.emit([Delta(path="sim.belt.encoder.t", old_value=stale_t, new_value=stale_t_2, source="robot")])
    plugin.produce()
    assert ctx.log_warning.call_count == 2, "новое протухшее значение должно дать новое предупреждение"


# --------------------------------------------------------------------------- #
# (d) Конкурентность: колбэк подписки (чужой поток) против produce()          #
# --------------------------------------------------------------------------- #


def test_callback_vs_produce_concurrency_no_exception() -> None:
    """``_on_deltas`` в реальном процессе зовётся с потока роутера/подписки,
    ``produce()`` — с потока ``SourceProducer``. Гоняем оба конкурентно на
    ``Lock`` и проверяем отсутствие исключений/дедлока (join с дедлайном —
    зависший поток не должен повесить тест, см. project-rules про hangs)."""
    plugin, _ctx, sp = _make_plugin()
    stop = threading.Event()
    errors: list[BaseException] = []

    def _writer() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            t = time.monotonic()
            try:
                sp.emit(
                    [
                        Delta(path="sim.belt.encoder.value", old_value=None, new_value=i, source="robot"),
                        Delta(path="sim.belt.encoder.t", old_value=None, new_value=t, source="robot"),
                    ]
                )
            except BaseException as exc:  # noqa: BLE001 — хотим увидеть ЛЮБОЙ сбой гонки
                errors.append(exc)
                return

    writer = threading.Thread(target=_writer, daemon=True)
    writer.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                plugin.produce()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                break
    finally:
        stop.set()
        writer.join(timeout=5.0)
        assert not writer.is_alive(), "writer-поток не завершился за 5с — подозрение на дедлок"

    assert not errors, f"конкурентный доступ дал исключение: {errors!r}"


# --------------------------------------------------------------------------- #
# (e) Бесконечная лента — спрайт за правым краем въезжает слева, не паркуется  #
# --------------------------------------------------------------------------- #


def test_sprite_wraps_past_right_edge_instead_of_parking() -> None:
    """Живой дефект первого захода Task 2.2: спрайт упирался в правый край за ~6 с и
    стоял там, пока лента ехала. Энкодер 5122 при px_per_mm=1.0 → x_px ≈ 740 (> 640):
    период 640 + 32 = 672, центр = ((740 + 16) % 672) − 16 = 68 px от левого края.
    Сторож инъекции «зажим у края вместо модуля» (K2 матрицы ведущего, 2026-09-22 —
    без этого теста она проходила зелёной)."""
    import numpy as np

    plugin, _ctx, sp = _make_plugin({"stale_ms": 10_000})
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": 5122, "mm_s": 100.0, "t": time.monotonic()},
                source="robot",
            )
        ]
    )
    frame = plugin.produce()[0]["frame"]
    mask = np.all(np.abs(frame.astype(int) - np.array(SPRITE_BGR)) <= 40, axis=2)
    cols = np.flatnonzero(mask.any(axis=0))
    assert cols.size > 0, "спрайт исчез из кадра вместо переноса на левый край"
    centre = float(cols.mean())
    assert centre == pytest.approx(68.0, abs=2.0), f"центр спрайта {centre} — ожидали 68 после переноса"
    assert cols.max() < 640 - 32, "спрайт припаркован у правого края — лента не бесконечна"
