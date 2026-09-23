# -*- coding: utf-8 -*-
"""Task 5.1b — тесты лида после ревью (итерация 1, п.2 и п.3).

W1 («движок не собран — в on_match идёт job=None») и W2 («уровень frozen_xy публикует
false_alarm») выжили против всех наборов: проверялось только имя уровня, а ветку `_spawner is
None` с двумя заданиями в одной точке не слал никто.
"""

from __future__ import annotations

import pytest

from Plugins.sim.scene_source.tests.test_acceptance_5_2 import _call, _make_plugin

pytestmark = pytest.mark.timeout(30)


def test_engine_unavailable_frozen_xy_counted_and_published():
    plugin, ctx, _sp = _make_plugin()  # без preset_path движок не собирается
    assert plugin._spawner is None

    _call(plugin, "scene.job_done", {"index": 1, "x_mm": 0.0, "y_mm": 20.0, "ecap": 1000, "t": 0.0})
    _call(plugin, "scene.job_done", {"index": 2, "x_mm": 0.0, "y_mm": 20.0, "ecap": 1362, "t": 0.5})
    ctx.publish_metric.reset_mock()
    plugin.produce()  # первый produce публикует без ожидания такта

    counters = _call(plugin, "truth.status")["counters"]
    assert counters["false_alarm"] == 2
    assert counters["false_alarm_frozen_xy"] == 1

    levels = {call.args[0]: call.args[1] for call in ctx.publish_metric.call_args_list}
    assert levels["truth_false_alarm"] == 2
    assert levels["truth_false_alarm_frozen_xy"] == 1
