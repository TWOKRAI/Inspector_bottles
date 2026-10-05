"""Авторские hazard-тесты Task 5.9a: имя, пришедшее проводом на ДРУГОЙ плагин процесса.

Механизм: ``SystemBlueprint.check()`` передаёт в ``validate_chain_detailed`` и в
``_is_covered_by_auto_wiring`` имена портов, пришедших проводами в процесс
(``wired_names_by_process``). Рантайм несёт между плагинами один dict, поэтому вход
``frame`` узла 0 покрыт, если провод принёс ключ ``frame`` хотя бы на любой плагин
этого процесса — даже если по АДРЕСУ узла 0 провода нет.

Что может сломаться именно здесь (рецепты разведены по адресу, а адресные входы
``check()`` исключает отдельно, поэтому рецепты эту ветку не видят):
* имена проводов не дошли до ``validate_chain_detailed`` -> ложная ошибка цепочки;
* имена проводов не дошли до ``_is_covered_by_auto_wiring`` -> ложная ошибка
  «не подключен» из цикла обязательных входов, хотя цепочка вход покрыла.
  Этот путь достижим независимо: цикл доходит до ``_is_covered_by_auto_wiring``
  только для входов, которых цепочка НЕ назвала ошибкой, — то есть как раз тогда,
  когда цепочка (с именами) вход покрыла, а второй вызов (без имён) — нет.

Ожидания — литералы; контроль-негатив подтверждает, что провод — единственная причина.
"""

from __future__ import annotations

import pytest

from ...process_manager_module.topology.blueprint import SystemBlueprint
from ...process_module.plugins.base import ProcessModulePlugin
from ...process_module.plugins.port import Port
from ...process_module.plugins.registry import PluginRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = PluginRegistry.snapshot()
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(saved)


class _FrameSource(ProcessModulePlugin):
    name = "frame_source"
    category = "source"
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _FirstNeedsFrame(ProcessModulePlugin):
    """Узел 0 процесса: обязательный ``frame``; выдаёт только ``mask``."""

    name = "first_needs_frame"
    category = "processing"
    inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]
    outputs = [Port(name="mask", dtype="image/gray", shape="(H, W)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _SecondNeedsFrame(ProcessModulePlugin):
    """Узел 1 процесса: ``frame`` (optional) — на него приходит провод; сам ошибок не даёт."""

    name = "second_needs_frame"
    category = "processing"
    inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True)]
    outputs = [Port(name="out", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


def _blueprint(*, wire_to_second: bool) -> SystemBlueprint:
    PluginRegistry.register(name=_FrameSource.name, plugin_class=_FrameSource, category=_FrameSource.category)
    PluginRegistry.register(name=_FirstNeedsFrame.name, plugin_class=_FirstNeedsFrame, category="processing")
    PluginRegistry.register(name=_SecondNeedsFrame.name, plugin_class=_SecondNeedsFrame, category="processing")
    wires = [{"source": "src.frame_source.frame", "target": "proc.second_needs_frame.frame"}] if wire_to_second else []
    return SystemBlueprint.model_validate(
        {
            "name": "wired_name_other_plugin",
            "processes": [
                {"process_name": "src", "plugins": [{"plugin_name": "frame_source", "plugin_class": ""}]},
                {
                    "process_name": "proc",
                    "plugins": [
                        {"plugin_name": "first_needs_frame", "plugin_class": ""},
                        {"plugin_name": "second_needs_frame", "plugin_class": ""},
                    ],
                },
            ],
            "wires": wires,
        }
    )


def test_name_wired_to_another_plugin_of_the_process_covers_node_zero_input() -> None:
    """Провод на ``proc.second_needs_frame.frame`` покрывает ``frame`` узла 0 (по имени): ошибок нет."""
    errors = _blueprint(wire_to_second=True).check()
    assert errors == [], errors


def test_without_the_wire_node_zero_input_is_exactly_one_error() -> None:
    """Контроль: тот же чертёж без провода — ровно одна ошибка на адрес узла 0 (ни две, ни ноль)."""
    errors = _blueprint(wire_to_second=False).check()
    assert len(errors) == 1, errors
    assert "proc.first_needs_frame.frame" in errors[0], errors[0]
