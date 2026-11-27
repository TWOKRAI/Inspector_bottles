"""Слепые приёмочные тесты 2.11, часть A: метка ``paused_by`` в ``PluginRunner.call_process``, пункты F1-F11.

Написаны по задаче 2.11 (DESIGN, REDS) до реализации. Настоящий ``PluginRunner``, плагины — двойники
с ``name`` / ``state`` / ``enabled`` / ``process``. Ожидаемые значения — литералы.

Тесты ``test_design_*`` сверх списка REDS: они держат строки DESIGN §2 и §3, которые F1-F11 не различают
(каждый item пачки; маркер в смешанной пачке; позиционный донор 1:1; ПЕРВЫЙ помеченный вход).
"""

from __future__ import annotations

from collections.abc import Callable

from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.base import PluginState
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import is_marker


class _Plugin:
    """Плагин-двойник: ``process`` отдаёт результат ``fn(items)``; по умолчанию — новый dict на каждый item."""

    def __init__(
        self,
        name: str,
        state: PluginState = PluginState.RUNNING,
        enabled: bool = True,
        fn: Callable[[list[dict]], list[dict]] | None = None,
    ) -> None:
        self.name = name
        self.state = state
        self.enabled = enabled
        self._fn = fn or (lambda items: [{"mask": 1} for _ in items])

    def process(self, items: list[dict]) -> list[dict]:
        return self._fn(items)


def _run(plugin: _Plugin, items: list[dict]) -> list[dict]:
    return PluginRunner(validate_ports=False).call_process(plugin, items)


# ---------------------------------------------------------------------------
# F1, F2, F7, F8: кто ставит метку (bypass)
# ---------------------------------------------------------------------------


def test_f1_paused_plugin_marks_passed_item() -> None:
    items = [{"frame": 1}]

    out = _run(_Plugin("p1", PluginState.PAUSED), items)

    assert out is items
    assert out[0]["paused_by"] == "p1"
    assert out[0]["frame"] == 1


def test_f2_disabled_running_plugin_sets_no_mark() -> None:
    out = _run(_Plugin("p1", PluginState.RUNNING, enabled=False), [{"frame": 1}])

    assert "paused_by" not in out[0]


def test_f2b_disabled_and_paused_plugin_marks_item() -> None:
    out = _run(_Plugin("p1", PluginState.PAUSED, enabled=False), [{"frame": 1}])

    assert out[0].get("paused_by") == "p1"


def test_f7_first_paused_plugin_keeps_its_name() -> None:
    runner = PluginRunner(validate_ports=False)

    middle = runner.call_process(_Plugin("p1", PluginState.PAUSED), [{"frame": 1}])
    out = runner.call_process(_Plugin("p2", PluginState.PAUSED), middle)

    assert out[0].get("paused_by") == "p1"


def test_f8_overflow_marker_passes_paused_plugin_without_mark() -> None:
    """Контроль."""
    marker = {"overflow_marker": True, "inspection_status": "not_inspected"}
    assert is_marker(marker) is True  # предусловие: это действительно маркер

    out = _run(_Plugin("p1", PluginState.PAUSED), [marker])

    assert "paused_by" not in out[0]


def test_design_every_item_of_a_batch_is_marked_by_paused_plugin() -> None:
    out = _run(_Plugin("p1", PluginState.PAUSED), [{"frame": 1}, {"frame": 2}, {"frame": 3}])

    assert [item.get("paused_by") for item in out] == ["p1", "p1", "p1"]


def test_design_marker_in_mixed_batch_stays_unmarked_and_neighbour_is_marked() -> None:
    marker = {"overflow_marker": True, "inspection_status": "not_inspected"}

    out = _run(_Plugin("p1", PluginState.PAUSED), [marker, {"frame": 1}])

    assert "paused_by" not in out[0]
    assert out[1].get("paused_by") == "p1"


# ---------------------------------------------------------------------------
# F3-F6, F9-F11: перенос метки через работающий плагин
# ---------------------------------------------------------------------------


def test_f3_running_plugin_adds_no_mark_to_unmarked_input() -> None:
    """Контроль."""
    out = _run(_Plugin("p1"), [{"frame": 1}])

    assert out == [{"mask": 1}]
    assert "paused_by" not in out[0]


def test_f4_new_dict_inherits_mark_from_input() -> None:
    out = _run(_Plugin("p1"), [{"frame": 1, "paused_by": "p0"}])

    assert out[0].get("paused_by") == "p0"


def test_f5_fan_out_marks_every_output() -> None:
    plugin = _Plugin("p1", fn=lambda items: [{"crop": 0}, {"crop": 1}, {"crop": 2}])

    out = _run(plugin, [{"frame": 1, "paused_by": "p0"}])

    assert [item.get("paused_by") for item in out] == ["p0", "p0", "p0"]


def test_f6_fan_in_takes_mark_of_second_input() -> None:
    plugin = _Plugin("p1", fn=lambda items: [{"joined": True}])

    out = _run(plugin, [{"a": 1}, {"b": 2, "paused_by": "p0"}])

    assert out[0].get("paused_by") == "p0"


def test_f9_mutated_same_dict_keeps_mark() -> None:
    """Контроль."""

    def _mutate(items: list[dict]) -> list[dict]:
        items[0]["mask"] = 1
        return items

    items = [{"frame": 1, "paused_by": "p0"}]

    out = _run(_Plugin("p1", fn=_mutate), items)

    assert out[0] is items[0]
    assert out[0]["mask"] == 1
    assert out[0]["paused_by"] == "p0"


def test_f10_key_set_by_plugin_is_not_overwritten() -> None:
    plugin = _Plugin("p1", fn=lambda items: [{"mask": 1, "paused_by": "x"}])

    out = _run(plugin, [{"frame": 1, "paused_by": "p0"}])

    assert out[0]["paused_by"] == "x"


def test_f11_input_object_returned_from_not_one_to_one_gets_mark_of_other_input() -> None:
    items = [{"a": 1}, {"b": 2, "paused_by": "p0"}]

    out = _run(_Plugin("p1", fn=lambda batch: batch[:1]), items)

    assert out[0] is items[0]
    assert out[0].get("paused_by") == "p0"


def test_design_one_to_one_takes_mark_by_position() -> None:
    out = _run(_Plugin("p1"), [{"a": 1}, {"b": 2, "paused_by": "p0"}])

    assert [item.get("paused_by") for item in out] == [None, "p0"]


def test_design_fan_in_takes_first_marked_input() -> None:
    plugin = _Plugin("p1", fn=lambda items: [{"joined": True}])

    out = _run(plugin, [{"a": 1}, {"b": 2, "paused_by": "p0"}, {"c": 3, "paused_by": "p9"}])

    assert out[0].get("paused_by") == "p0"
