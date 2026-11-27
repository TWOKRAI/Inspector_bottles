# -*- coding: utf-8 -*-
"""Опасности 2.11 (``paused_by``), тесты автора реализации: H2, H4 и уточнения лида к переносу.

Настоящий ``PluginRunner``, плагины-двойники. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.base import PluginState


class _Plugin:
    def __init__(self, name: str, state: PluginState = PluginState.RUNNING, make=lambda items: items) -> None:
        self.name = name
        self.enabled = True
        self.state = state
        self._make = make

    def process(self, items: list[dict]) -> list[dict]:
        return self._make(items)


def _call(plugin: _Plugin, items: list[dict]) -> list[dict]:
    return PluginRunner(validate_ports=False).call_process(plugin, items)


def _marker() -> dict:
    return {"overflow_marker": True, "inspection_status": "not_inspected"}


def test_h2_marked_second_item_marks_every_output_of_2_to_3() -> None:
    plugin = _Plugin("p1", make=lambda items: [{"n": 0}, {"n": 1}, {"n": 2}])

    out = _call(plugin, [{"a": 1}, {"b": 2, "paused_by": "p0"}])

    assert [item.get("paused_by") for item in out] == ["p0", "p0", "p0"]


def test_one_to_one_reordered_inputs_are_not_touched() -> None:
    clean, marked = {"a": 1}, {"b": 2, "paused_by": "p0"}

    out = _call(_Plugin("p1", make=lambda items: [items[1], items[0]]), [clean, marked])

    assert out[0] is marked
    assert out[1] is clean
    assert "paused_by" not in clean


def test_one_to_one_new_outputs_take_the_positional_donor() -> None:
    out = _call(_Plugin("p1", make=lambda items: [{"n": 0}, {"n": 1}]), [{"a": 1}, {"b": 2, "paused_by": "p0"}])

    assert ["paused_by" in item for item in out] == [False, True]


def test_not_a_string_mark_on_input_is_not_carried() -> None:
    plugin = _Plugin("p1", make=lambda items: [{"n": 0}])

    for value in ("", 1, None, True):
        out = _call(plugin, [{"a": 1, "paused_by": value}, {"b": 2}])
        assert "paused_by" not in out[0], value


def test_first_marked_input_skips_an_unusable_mark() -> None:
    plugin = _Plugin("p1", make=lambda items: [{"n": 0}])

    out = _call(plugin, [{"a": 1, "paused_by": ""}, {"b": 2, "paused_by": "p0"}])

    assert out[0]["paused_by"] == "p0"


def test_marker_in_outputs_gets_no_mark_on_carry() -> None:
    plugin = _Plugin("p1", make=lambda items: [_marker(), {"n": 1}, {"n": 2}])

    out = _call(plugin, [{"a": 1, "paused_by": "p0"}])

    assert [item.get("paused_by") for item in out] == [None, "p0", "p0"]


def test_marker_gets_no_mark_on_one_to_one_carry() -> None:
    out = _call(_Plugin("p1", make=lambda items: [_marker()]), [{"a": 1, "paused_by": "p0"}])

    assert "paused_by" not in out[0]


def test_non_dict_items_pass_the_paused_bypass() -> None:
    items = [1, {"a": 1}]

    out = _call(_Plugin("p1", PluginState.PAUSED), items)

    assert out is items
    assert out[0] == 1
    assert out[1]["paused_by"] == "p1"


class _ResumedBetweenReads:
    """``state`` отдаёт PAUSED один раз, дальше RUNNING: resume с потока наблюдателя посреди вызова."""

    name = "p1"
    enabled = True

    def __init__(self) -> None:
        self.reads = 0
        self.process_calls = 0

    @property
    def state(self) -> PluginState:
        self.reads += 1
        return PluginState.PAUSED if self.reads == 1 else PluginState.RUNNING

    def process(self, items: list[dict]) -> list[dict]:
        self.process_calls += 1
        return items


def test_resume_between_bypass_and_mark_still_marks_the_item() -> None:
    plugin = _ResumedBetweenReads()

    out = _call(plugin, [{"frame": 1}])

    assert out[0].get("paused_by") == "p1"
    assert plugin.reads == 1
    assert plugin.process_calls == 0


def test_h4_thousand_items_through_paused() -> None:
    """Время идёт в отчёт (``-s``); порог — только защита от квадратичной ошибки переноса."""
    plugin = _Plugin("p1", PluginState.PAUSED)
    runner = PluginRunner(validate_ports=False)
    items = [{"frame": i} for i in range(1000)]

    started = time.perf_counter()
    out = runner.call_process(plugin, items)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    print(f"H4: 1000 items через PAUSED за {elapsed_ms:.2f} мс")
    assert all(item["paused_by"] == "p1" for item in out)
    assert elapsed_ms < 1000.0
