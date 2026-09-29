"""Дедлайн dead-man jog — на точных часах (раунд 4, sim-win).

Сторож гасит jog по дедлайну. Дедлайн на грубых часах (Windows: ``time.monotonic``, шаг 15.625 мс)
не видит истёкший срок: 52 мс сна укладываются в 3 тика = 46.9 мс < 50 мс. Тест зовёт сторож ОДИН раз
после сна, заведомо длиннее таймаута по точным часам, и требует, чтобы jog был погашен.
"""

from __future__ import annotations

import time

from Plugins.sim.robot_host.tests.test_hazards import _make_bare_plugin

_TIMEOUT_MS = 50
_SLEEP_S = 0.052
_ROUNDS = 60


def test_watchdog_sees_expired_deadline_after_sleep_longer_than_timeout() -> None:
    plugin, _core = _make_bare_plugin(jog_timeout_ms=_TIMEOUT_MS)
    missed: list[int] = []
    for i in range(_ROUNDS):
        assert plugin.cmd_belt_jog({"direction": 1, "freq_hz": 10})["ok"] is True
        started = time.perf_counter()
        time.sleep(_SLEEP_S)
        assert time.perf_counter() - started >= _TIMEOUT_MS / 1000.0
        plugin._check_jog_watchdog()
        if plugin._jog_deadline is not None:
            missed.append(i)
            plugin._check_jog_watchdog()  # добить, чтобы следующий круг начал с чистого состояния
            time.sleep(0.02)
            plugin._check_jog_watchdog()
        time.sleep(0.0011 * (i % 7))  # сбить фазу относительно сетки тиков грубых часов
    assert missed == [], f"сторож не увидел истёкший дедлайн в {len(missed)} из {_ROUNDS} кругов: {missed[:10]}"
