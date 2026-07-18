# -*- coding: utf-8 -*-
"""C.0 live-якорь сплита god-file (Phase C).

Характеризационный тест через РЕАЛЬНЫЕ сокеты: доказывает, что реконнект-механика
(durable-подписки + watch-контур) работает end-to-end, а не только на fake-транспорте
unit-тестов. Прогоняется ДО распила driver.py (baseline) и ПОСЛЕ (доказательство
«бит-в-бит»): если сплит по transport/events/subscriptions/watch что-то сломает,
именно этот тест — сетка, которую unit на фейках поймать не могут.

Сценарий = приёмный профиль GUI → телеметрия наполняется → разрыв соединения →
replay durable-намерений + resume watch-контура на новом соединении → телеметрия
возобновляется. Одно соединение за раз (close ДО нового driver) — без ловушки двух
клиентов на одном порту (session-isolation ещё нет, D.1a).

Свой headless-бэкенд на уникальном порту (≥8770) — изоляция от общих фикстур
(project_concurrent_backends_trap, backend_ctl/AGENTS.md).
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness

_PORT = 8776  # уникальный порт этого модуля (≥8770)


def _wait_nonempty_snapshot(drv: BackendDriver, deadline: float) -> dict:
    """Дождаться, пока read-model телеметрии наполнится (count>0) до дедлайна."""
    snap = drv.telemetry_snapshot()
    while time.time() < deadline:
        snap = drv.telemetry_snapshot()
        if snap.get("count", 0) > 0:
            return snap
        time.sleep(0.2)
    return snap


@pytest.mark.harness_smoke
def test_reconnect_replays_watch_and_telemetry_resumes() -> None:
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    drv2: BackendDriver | None = None
    try:
        # 1. Приёмный профиль GUI одной командой: state + obs-хвост + авто-resub.
        res = drv.watch_like_gui()
        assert res.get("success") is True

        # 2. Под активным watch телеметрия наполняется через state.changed → read-model.
        snap1 = _wait_nonempty_snapshot(drv, time.time() + 15.0)
        assert snap1["count"] > 0, "телеметрия должна наполниться под активным watch"

        # Снимок durable-намерений + watch-манифеста ДО разрыва (как DriverSession.reset).
        intents = drv.export_subscriptions()
        manifest = drv.watch_manifest()
        assert intents, "watch должен оставить durable-намерения в реестре"
        assert manifest.get("active") is True, "watch-манифест должен быть активен"

        # 3. Разрыв соединения (одно соединение за раз — без двух клиентов на порту).
        drv.close()

        # 4. Новый driver на том же порту → replay намерений + resume watch-контура.
        drv2 = BackendDriver(port=_PORT)
        drv2.connect()
        drv2.import_subscriptions(intents)
        replayed = drv2.replay_subscriptions()
        assert replayed, "replay должен переподписать durable-намерения на новом соединении"
        wr = drv2.resume_watch(manifest)
        assert wr.get("resumed") is True, "watch-контур должен подняться после реконнекта"

        # 5. Tail продолжается: телеметрия снова наполняется на новом соединении.
        snap2 = _wait_nonempty_snapshot(drv2, time.time() + 15.0)
        assert snap2["count"] > 0, "после реконнекта телеметрия должна возобновиться"
    finally:
        if drv2 is not None:
            drv2.close()
        harness.stop()
