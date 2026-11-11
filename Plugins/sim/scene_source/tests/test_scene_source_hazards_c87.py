# -*- coding: utf-8 -*-
"""Hazard-тесты автора C-87 — досчёт энкодера в ``SceneSourcePlugin._read_world_encoder``.

(a) Гонка писатель/читатель: колбэк подписки (поток брокера) пишет value/mm_s/t, а
    ``produce()`` читает в другом потоке. Снимок берётся под одним ``Lock`` — читатель
    не должен увидеть «рваное» значение (value от одной дельты, t от другой).
(b) Де-дублирование предупреждения о протухании: одно предупреждение на ``t``, а не на
    каждое чтение (досчёт читает мир на каждом кадре).
"""

from __future__ import annotations

import threading
import uuid
from typing import Callable
from unittest.mock import MagicMock

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

_PATH = "sim.belt.encoder"
_FACTOR_MM = 0.144473
_NOW = 100.0
_JOIN_S = 10.0
_READS = 20000


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:  # не используется
        pass


def _make_plugin(stale_ms: float = 500) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy]:
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        "stale_ms": stale_ms,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    plugin._clock = lambda: _NOW  # C-87: шов часов — подменяется ПОСЛЕ configure()
    return plugin, ctx, state_proxy


def _leaf_batch(value: float, mm_s: float, t: float) -> list[Delta]:
    return [
        Delta(path=f"{_PATH}.value", old_value=None, new_value=value, source="robot"),
        Delta(path=f"{_PATH}.mm_s", old_value=None, new_value=mm_s, source="robot"),
        Delta(path=f"{_PATH}.t", old_value=None, new_value=t, source="robot"),
    ]


def test_concurrent_deltas_vs_read_no_torn_value() -> None:
    """Писатель чередует две дельты (листовая форма, три Delta в одном батче), читатель
    непрерывно читает. Каждое чтение обязано равняться ровно одному из двух легальных
    значений: смесь value одной дельты с t/mm_s другой дала бы третье число.

    Легальные (часы зафиксированы на 100.0, stale_ms=500):
      A: value=1000, mm_s=20, t=99.9 -> 1000 + 20*0.1/0.144473 = 1013.84...
      B: value=5000, mm_s=40, t=99.8 -> 5000 + 40*0.2/0.144473 = 5055.37..."""
    plugin, _ctx, sp = _make_plugin()
    legal_a = 1000 + 20 * 0.1 / _FACTOR_MM
    legal_b = 5000 + 40 * 0.2 / _FACTOR_MM
    sp.emit(_leaf_batch(1000, 20.0, 99.9))  # мир не пуст до старта потоков

    stop = threading.Event()
    readings: list[float] = []
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            i = 0
            while not stop.is_set():
                sp.emit(_leaf_batch(1000, 20.0, 99.9) if i % 2 == 0 else _leaf_batch(5000, 40.0, 99.8))
                i += 1
        except BaseException as exc:  # noqa: BLE001 - тест фиксирует любой сбой потока
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(_READS):
                readings.append(plugin._read_world_encoder())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            stop.set()

    threads = [threading.Thread(target=writer, daemon=True), threading.Thread(target=reader, daemon=True)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(_JOIN_S)
    stop.set()
    assert not any(th.is_alive() for th in threads), "потоки не завершились за дедлайн"
    assert not errors, f"исключение в потоке: {errors!r}"
    assert len(readings) == _READS
    torn = [r for r in readings if abs(r - legal_a) > 1e-6 and abs(r - legal_b) > 1e-6]
    assert not torn, f"рваные чтения (не A и не B): {torn[:5]!r}"


def test_stale_warning_dedup_per_t() -> None:
    """Одно протухшее ``t`` читается 3 раза -> 1 предупреждение; новое протухшее ``t`` -> второе."""
    plugin, ctx, sp = _make_plugin(stale_ms=200)
    sp.emit([Delta(path=_PATH, old_value=None, new_value={"value": 1000, "mm_s": 20.0, "t": 50.0}, source="robot")])
    for _ in range(3):
        plugin._read_world_encoder()
    assert ctx.log_warning.call_count == 1

    sp.emit([Delta(path=_PATH, old_value=None, new_value={"value": 1010, "mm_s": 20.0, "t": 60.0}, source="robot")])
    for _ in range(3):
        plugin._read_world_encoder()
    assert ctx.log_warning.call_count == 2
    assert "stale_ms" in ctx.log_warning.call_args.args[0]


def test_smaller_delta_after_a_reading_does_not_clamp_to_previous_reading() -> None:
    """Добавлено лидом после инъекции I4 (монотонный clamp по чтениям): слепой RED 5 читает
    только после второй дельты, поэтому clamp «не ниже прошлого чтения» его не краснит. Здесь
    чтение идёт и ДО меньшей дельты — как на стенде, где produce() читает мир каждый кадр.

    Литералы: чтение в 100.1 от (1000, 20, t=100.0) = 1000 + 20*0.1/0.144473 = 1013.84342;
    новая дельта (900, 20, t=100.2), чтение в 100.26 = 900 + 20*0.06/0.144473 = 908.30605."""
    plugin, _ctx, sp = _make_plugin()
    sp.emit(_leaf_batch(1000, 20.0, 100.0))
    plugin._clock = lambda: 100.1
    first = plugin._read_world_encoder()
    assert abs(first - 1013.84342) < 1e-4, first
    sp.emit(_leaf_batch(900, 20.0, 100.2))
    plugin._clock = lambda: 100.26
    second = plugin._read_world_encoder()
    assert abs(second - 908.30605) < 1e-4, f"чтение после меньшей дельты {second}, ждали 908.30605"
