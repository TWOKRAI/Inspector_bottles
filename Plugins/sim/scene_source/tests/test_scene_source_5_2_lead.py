# -*- coding: utf-8 -*-
"""Task 5.2 — тесты лида после break-injection (стадия 3).

Инъекция I8 («движок не собран — исход в ledger не идёт») выжила против обоих наборов: ветку
`_spawner is None` в `_drain_jobs` не проверял никто, хотя контракт §2 её называет
(«движок не собран — команды работают, растёт только false_alarm»).
"""

from __future__ import annotations

import pytest

from Plugins.sim.scene_source.tests.test_acceptance_5_2 import _call, _make_plugin

pytestmark = pytest.mark.timeout(30)


def test_engine_unavailable_job_counts_false_alarm_only():
    plugin, _ctx, _sp = _make_plugin()  # без preset_path движок не собирается
    assert plugin._spawner is None  # предусловие: ветка «движок не собран»

    job = {"index": 1, "x_mm": 0.0, "y_mm": 20.0, "ecap": 1000, "t": 0.0}
    assert _call(plugin, "scene.job_done", job) == {"status": "ok"}
    plugin.produce()

    counters = _call(plugin, "truth.status")["counters"]
    assert counters["false_alarm"] == 1
    assert counters["caught"] == 0
    assert counters["dup_jobs"] == 0
    assert counters["missed"] == 0
    assert counters["on_belt"] == 0
