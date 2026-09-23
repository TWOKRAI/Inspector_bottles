# -*- coding: utf-8 -*-
"""Тесты автора (hazard) — Task 3.5 (часть B) плана line-sim: задания робота в сцене.

Про что приёмка тестера (``test_scene_source_task_3_5.py``) не проверяет, а механизм
ломается именно тут:

1. **Передача между потоками.** ``cmd_job_done`` зовётся из потока команд, ``produce()`` —
   из воркера; единственная передача — ``collections.deque`` (``append`` / ``popleft``).
   Если разбор сделать «снимок очереди -> обработать -> ``clear()``», задание, пришедшее
   между снимком и ``clear()``, теряется молча; если читать ``_recent`` без замка во время
   ``append`` — ``RuntimeError: deque mutated during iteration`` в потоке команд.
   Проверка — по СЧЁТУ исходов (строки ``log_info``), не по ``recent`` (он ограничен 32).
   **Сторож слабый, вероятностный** (break-injection автора, 2026-09-23, при
   ``setswitchinterval(1e-6)``): «``recent`` без замка» — красный 2 прогона из 5;
   «снимок -> ``clear()``» с окном ``sleep(0.001)`` — красный, без окна — 0 из 5 (окно в пару
   байткодов под GIL не попадает). Зелёный H1 не доказывает дисциплину передачи — доказывает
   только, что в обычном режиме ни одно задание не потерялось и ни один поток не упал.
2. **Энкодер задания, а не мира.** Сопоставление считает положение объекта от ``job.ecap``;
   мир сцены может отставать (задание завершилось, а дельта энкодера ещё не пришла). Задание
   с ``ecap`` далеко впереди энкодера мира обязано сводиться арифметикой.
3. **Два задания на один объект в ОДНОМ разборе.** Первое снимает объект, второе обязано
   увидеть его среди снятых (``dup``), а не ``no_object`` — то есть запись в ``_removed``
   должна случиться ДО разбора следующего задания той же пачки.

Харнесс — своя копия (как в остальных файлах этого каталога — файл самодостаточен).
"""

from __future__ import annotations

import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Services.dataset_gen.core.catalog import imwrite_unicode
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

pytestmark = pytest.mark.timeout(30)

#: Литералы контракта (§2/§4 «Контракт лида 3.5»), не импорт из matching.py.
_FACTOR_MM = 0.144473
_JOIN_DEADLINE_S = 10.0
_OUTCOME_RE = re.compile(r"задание #(\d+) .* -> (matched|dup|no_object)")


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, object]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        self.set_calls.append((path, value))


def _make_plugin_with_engine(tmp_path: Path):
    classes_dir = tmp_path / f"classes_{uuid.uuid4().hex}"
    (classes_dir / "square").mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(classes_dir / "square" / "sprite.png", sprite)

    sp = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = sp
    ctx.config = {
        "resolution_width": 64,
        "resolution_height": 48,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        "stale_ms": 1e9,
        "preset_path": str(classes_dir),
        "spawn_spacing_mm": [1e9, 1e9],  # ровно один объект на первом tick()
        "scene_length_mm": 1e9,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, sp


def _push_encoder(sp: _FakeStateProxy, value: float) -> None:
    new_value = {"value": value, "mm_s": 0.0, "t": 0.0}
    sp.emit([Delta(path="sim.belt.encoder", old_value=object(), new_value=new_value, source="robot")])


def _job(index: int, spawn_encoder: float, ecap: float) -> dict:
    offset_mm = (ecap - spawn_encoder) * _FACTOR_MM
    return {"index": index, "x_mm": 0.0, "y_mm": offset_mm, "ecap": int(ecap), "t": 0.0}


def _outcomes(ctx: MagicMock) -> list[tuple[int, str]]:
    found = []
    for call in ctx.log_info.call_args_list:
        m = _OUTCOME_RE.search(str(call.args[0]) if call.args else "")
        if m:
            found.append((int(m.group(1)), m.group(2)))
    return found


def _spawn_one(tmp_path: Path, world_encoder: float = 1000.0):
    plugin, ctx, sp = _make_plugin_with_engine(tmp_path)
    _push_encoder(sp, world_encoder)
    plugin.produce()
    active = plugin._spawner.active_objects()
    assert len(active) == 1, "фикстура должна заспавнить ровно один объект"
    return plugin, ctx, sp, active[0].passport


# --------------------------------------------------------------------------- #
# H1 — 200 заданий из 4 потоков во время produce() в цикле: у каждого ровно   #
#      один исход, ни одного исключения ни в одном потоке                      #
# --------------------------------------------------------------------------- #


def test_concurrent_job_done_during_produce_each_job_exactly_one_outcome(tmp_path):
    plugin, ctx, _sp, _passport = _spawn_one(tmp_path)
    n_threads, per_thread = 4, 50
    errors: list[BaseException] = []
    senders_done = threading.Event()

    def producer() -> None:
        try:
            while not senders_done.is_set():
                plugin.produce()
        except BaseException as exc:  # noqa: BLE001 — фиксируем для assert
            errors.append(exc)

    def sender(base: int) -> None:
        try:
            for i in range(per_thread):
                # Далеко от объекта -> no_object: объект не снимается, у всех 200 один путь.
                job = {"index": base + i, "x_mm": 1e6, "y_mm": 1e6, "ecap": 0, "t": 0.0}
                assert plugin.cmd_job_done(job) == {"status": "ok"}
                plugin.cmd_status(None)  # чтение recent из «потока команд» во время записи
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    prod = threading.Thread(target=producer, daemon=True)
    senders = [threading.Thread(target=sender, args=(t * per_thread,), daemon=True) for t in range(n_threads)]
    # Частое переключение GIL: без него окно «снимок очереди -> clear()» почти не попадает
    # под переключение потоков (замер автора: такая поломка без этого зелёная 3 из 3).
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        prod.start()
        for s in senders:
            s.start()
        for s in senders:
            s.join(_JOIN_DEADLINE_S)
            assert not s.is_alive(), "поток команд завис"
        senders_done.set()
        prod.join(_JOIN_DEADLINE_S)
        assert not prod.is_alive(), "produce() завис"
    finally:
        senders_done.set()
        sys.setswitchinterval(old_interval)
    plugin.produce()  # добрать хвост очереди, пришедший после последнего кадра

    assert errors == []
    outcomes = _outcomes(ctx)
    indices = sorted(index for index, _ in outcomes)
    assert indices == list(range(n_threads * per_thread)), "каждое задание — ровно один исход"
    assert {o for _, o in outcomes} == {"no_object"}
    assert len(plugin._jobs) == 0


# --------------------------------------------------------------------------- #
# H2 — ecap задания далеко впереди энкодера мира сцены: сводится арифметикой  #
# --------------------------------------------------------------------------- #


def test_job_far_ahead_of_world_encoder_still_matches(tmp_path):
    plugin, ctx, sp, passport = _spawn_one(tmp_path, world_encoder=1000.0)
    far_ecap = passport.spawn_encoder + 1_000_000  # ~144 м ленты; мир стоит на 1000

    assert plugin.cmd_job_done(_job(1, passport.spawn_encoder, far_ecap)) == {"status": "ok"}
    plugin.produce()

    assert _outcomes(ctx) == [(1, "matched")]
    assert plugin._spawner.active_objects() == []
    assert sp.set_calls[-1] == ("sim.objects", {})


# --------------------------------------------------------------------------- #
# H3 — два задания на один объект в ОДНОМ разборе -> matched, затем dup       #
# --------------------------------------------------------------------------- #


def test_two_jobs_for_one_object_in_same_drain_matched_then_dup(tmp_path):
    plugin, ctx, _sp, passport = _spawn_one(tmp_path)
    job = _job(1, passport.spawn_encoder, 2000)

    assert plugin.cmd_job_done(job) == {"status": "ok"}
    assert plugin.cmd_job_done({**job, "index": 2}) == {"status": "ok"}
    plugin.produce()  # обе в очереди до кадра — один разбор

    assert _outcomes(ctx) == [(1, "matched"), (2, "dup")]
    recent = plugin.cmd_status(None)["recent"]
    assert [(e["index"], e["outcome"], e["object_id"]) for e in recent] == [
        (1, "matched", passport.object_id),
        (2, "dup", passport.object_id),
    ]
