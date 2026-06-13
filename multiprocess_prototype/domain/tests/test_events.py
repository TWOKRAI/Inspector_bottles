# -*- coding: utf-8 -*-
"""
Тесты для domain/events.py (Task B.2).

Покрывает:
1. test_event_immutable      — frozen dataclass бросает FrozenInstanceError при мутации.
2. test_event_slots          — slots=True означает отсутствие __dict__.
3. test_event_type_discriminator — ClassVar event_type содержит имя класса.
4. test_exhaustiveness_match — match-expression покрывает все 14 вариантов ProjectEvent.
5. test_events_carry_entities — payload хранит типизированные entity, не dict.
"""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from multiprocess_prototype.domain import (
    DisplayBound,
    DisplayInstance,
    DisplayUnbound,
    DisplaysChanged,
    PluginConfigChanged,
    PluginInserted,
    PluginMoved,
    PluginInstance,
    PluginRemoved,
    Process,
    ProcessAdded,
    ProcessRemoved,
    ProcessRenamed,
    ProjectEvent,
    RecipeActivated,
    RecipeDeactivated,
    TargetProcessAssigned,
    TopologyReplaced,
    Wire,
    WireConnected,
    WireDisconnected,
)


# ==============================================================================
# Вспомогательные фикстуры
# ==============================================================================


def _make_process(name: str = "proc") -> Process:
    """Минимальный Process для тестов."""
    return Process(process_name=name, plugins=())


def _make_plugin(name: str = "blur") -> PluginInstance:
    """Минимальный PluginInstance для тестов."""
    return PluginInstance(plugin_name=name)


def _make_wire() -> Wire:
    """Минимальный Wire для тестов."""
    return Wire(source="proc_a.plug.out", target="proc_b.plug.in")


def _make_display() -> DisplayInstance:
    """Минимальный DisplayInstance для тестов."""
    return DisplayInstance(node_id="proc.plug.out", display_id="main_output")


# ==============================================================================
# 1. Frozen — FrozenInstanceError при попытке мутации
# ==============================================================================


class TestEventImmutable:
    """frozen=True → попытка изменить поле бросает FrozenInstanceError."""

    def test_process_added_immutable(self) -> None:
        """ProcessAdded.process_name нельзя изменить."""
        evt = ProcessAdded(process_name="p", process=_make_process("p"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            evt.process_name = "mutated"  # type: ignore[misc]

    def test_process_removed_immutable(self) -> None:
        """ProcessRemoved.process_name нельзя изменить."""
        evt = ProcessRemoved(process_name="p")
        with pytest.raises(dataclasses.FrozenInstanceError):
            evt.process_name = "mutated"  # type: ignore[misc]

    def test_wire_connected_immutable(self) -> None:
        """WireConnected.wire нельзя изменить."""
        evt = WireConnected(wire=_make_wire())
        with pytest.raises(dataclasses.FrozenInstanceError):
            evt.wire = _make_wire()  # type: ignore[misc]

    def test_recipe_activated_immutable(self) -> None:
        """RecipeActivated.slug нельзя изменить."""
        evt = RecipeActivated(slug="my_recipe")
        with pytest.raises(dataclasses.FrozenInstanceError):
            evt.slug = "other"  # type: ignore[misc]

    def test_topology_replaced_immutable(self) -> None:
        """TopologyReplaced.reason нельзя изменить."""
        evt = TopologyReplaced(reason="blueprint reload")
        with pytest.raises(dataclasses.FrozenInstanceError):
            evt.reason = "other"  # type: ignore[misc]

    def test_recipe_deactivated_immutable(self) -> None:
        """RecipeDeactivated (без полей) тоже frozen — dataclass frozen=True задокументировано."""
        evt = RecipeDeactivated()
        # У dataclass без полей нет полей для мутации.
        # Проверяем frozen через dataclass метаданные.
        params = dataclasses.fields(evt)
        assert len(params) == 0, "RecipeDeactivated не должен иметь полей"
        # frozen=True зафиксирован в конфигурации dataclass
        assert evt.__dataclass_params__.frozen is True  # type: ignore[attr-defined]


# ==============================================================================
# 2. Slots — нет __dict__
# ==============================================================================


class TestEventSlots:
    """slots=True → у экземпляра нет __dict__."""

    @pytest.mark.parametrize(
        "evt",
        [
            ProcessAdded(process_name="p", process=Process(process_name="p", plugins=())),
            ProcessRemoved(process_name="p"),
            ProcessRenamed(old_name="a", new_name="b"),
            PluginInserted(process_name="p", plugin=PluginInstance(plugin_name="blur"), index=0),
            PluginRemoved(process_name="p", plugin_name="blur", index=0),
            PluginConfigChanged(process_name="p", plugin_index=0, field="k", value=1),
            WireConnected(wire=Wire(source="a", target="b")),
            WireDisconnected(source="a", target="b"),
            DisplayBound(display=DisplayInstance(node_id="n", display_id="d")),
            DisplayUnbound(node_id="n", display_id="d"),
            TargetProcessAssigned(process_name="p", target=None),
            RecipeActivated(slug="r"),
            RecipeDeactivated(),
            TopologyReplaced(reason="test"),
        ],
        ids=[
            "ProcessAdded",
            "ProcessRemoved",
            "ProcessRenamed",
            "PluginInserted",
            "PluginRemoved",
            "PluginConfigChanged",
            "WireConnected",
            "WireDisconnected",
            "DisplayBound",
            "DisplayUnbound",
            "TargetProcessAssigned",
            "RecipeActivated",
            "RecipeDeactivated",
            "TopologyReplaced",
        ],
    )
    def test_no_dict(self, evt: object) -> None:
        """У dataclass с slots=True нет __dict__."""
        assert not hasattr(evt, "__dict__"), (
            f"{type(evt).__name__}: ожидается slots=True (нет __dict__), но __dict__ существует"
        )


# ==============================================================================
# 3. ClassVar event_type — дискриминатор
# ==============================================================================


class TestEventTypeDiscriminator:
    """event_type ClassVar содержит имя класса (PascalCase)."""

    @pytest.mark.parametrize(
        ("event_cls", "expected"),
        [
            (ProcessAdded, "ProcessAdded"),
            (ProcessRemoved, "ProcessRemoved"),
            (ProcessRenamed, "ProcessRenamed"),
            (PluginInserted, "PluginInserted"),
            (PluginRemoved, "PluginRemoved"),
            (PluginConfigChanged, "PluginConfigChanged"),
            (WireConnected, "WireConnected"),
            (WireDisconnected, "WireDisconnected"),
            (DisplayBound, "DisplayBound"),
            (DisplayUnbound, "DisplayUnbound"),
            (TargetProcessAssigned, "TargetProcessAssigned"),
            (RecipeActivated, "RecipeActivated"),
            (RecipeDeactivated, "RecipeDeactivated"),
            (TopologyReplaced, "TopologyReplaced"),
        ],
    )
    def test_event_type_equals_class_name(self, event_cls: type, expected: str) -> None:
        """event_type на классе совпадает с именем класса (PascalCase)."""
        assert event_cls.event_type == expected  # type: ignore[attr-defined]

    def test_event_type_not_instance_field(self) -> None:
        """event_type — ClassVar, не instance-поле (не попадает в dataclass fields)."""
        fields = {f.name for f in dataclasses.fields(ProcessAdded)}
        assert "event_type" not in fields, "event_type должен быть ClassVar, не instance-полем"


# ==============================================================================
# 4. Exhaustiveness match — все 14 вариантов покрыты
# ==============================================================================


def _handle(evt: ProjectEvent) -> str:
    """Demo-обработчик для проверки exhaustiveness match.

    Покрывает все 14 вариантов ProjectEvent без default-ветки.
    Pyright в strict-режиме подтвердит, что match исчерпывающий.
    """
    match evt:
        case ProcessAdded():
            return "ProcessAdded"
        case ProcessRemoved():
            return "ProcessRemoved"
        case ProcessRenamed():
            return "ProcessRenamed"
        case PluginInserted():
            return "PluginInserted"
        case PluginRemoved():
            return "PluginRemoved"
        case PluginConfigChanged():
            return "PluginConfigChanged"
        case PluginMoved():
            return "PluginMoved"
        case WireConnected():
            return "WireConnected"
        case WireDisconnected():
            return "WireDisconnected"
        case DisplayBound():
            return "DisplayBound"
        case DisplayUnbound():
            return "DisplayUnbound"
        case DisplaysChanged():
            return "DisplaysChanged"
        case TargetProcessAssigned():
            return "TargetProcessAssigned"
        case RecipeActivated():
            return "RecipeActivated"
        case RecipeDeactivated():
            return "RecipeDeactivated"
        case TopologyReplaced():
            return "TopologyReplaced"


class TestExhaustivenessMatch:
    """match покрывает все 14 вариантов ProjectEvent."""

    @pytest.mark.parametrize(
        ("evt", "expected_label"),
        [
            (
                ProcessAdded(process_name="p", process=Process(process_name="p", plugins=())),
                "ProcessAdded",
            ),
            (ProcessRemoved(process_name="p"), "ProcessRemoved"),
            (ProcessRenamed(old_name="a", new_name="b"), "ProcessRenamed"),
            (
                PluginInserted(
                    process_name="p",
                    plugin=PluginInstance(plugin_name="blur"),
                    index=0,
                ),
                "PluginInserted",
            ),
            (PluginRemoved(process_name="p", plugin_name="blur", index=0), "PluginRemoved"),
            (
                PluginConfigChanged(process_name="p", plugin_index=0, field="k", value=42),
                "PluginConfigChanged",
            ),
            (
                PluginMoved(
                    from_process="a",
                    from_index=0,
                    to_process="b",
                    to_index=0,
                    plugin=PluginInstance(plugin_name="blur"),
                ),
                "PluginMoved",
            ),
            (WireConnected(wire=Wire(source="a", target="b")), "WireConnected"),
            (WireDisconnected(source="a", target="b"), "WireDisconnected"),
            (
                DisplayBound(display=DisplayInstance(node_id="n", display_id="d")),
                "DisplayBound",
            ),
            (DisplayUnbound(node_id="n", display_id="d"), "DisplayUnbound"),
            (DisplaysChanged(slug="my_recipe"), "DisplaysChanged"),
            (TargetProcessAssigned(process_name="p", target="q"), "TargetProcessAssigned"),
            (RecipeActivated(slug="my_recipe"), "RecipeActivated"),
            (RecipeDeactivated(), "RecipeDeactivated"),
            (TopologyReplaced(reason="blueprint reload"), "TopologyReplaced"),
        ],
        ids=[
            "ProcessAdded",
            "ProcessRemoved",
            "ProcessRenamed",
            "PluginInserted",
            "PluginRemoved",
            "PluginConfigChanged",
            "PluginMoved",
            "WireConnected",
            "WireDisconnected",
            "DisplayBound",
            "DisplayUnbound",
            "DisplaysChanged",
            "TargetProcessAssigned",
            "RecipeActivated",
            "RecipeDeactivated",
            "TopologyReplaced",
        ],
    )
    def test_handle_returns_label(self, evt: ProjectEvent, expected_label: str) -> None:
        """_handle(evt) возвращает строку-метку для каждого события."""
        result = _handle(evt)
        assert result == expected_label

    def test_all_14_events_covered(self) -> None:
        """ProjectEvent Union содержит ровно 16 типов (+ DisplaysChanged, мульти-дисплей)."""
        union_args = get_args(ProjectEvent)
        assert len(union_args) == 16, (
            f"ProjectEvent должен содержать 16 типов, найдено {len(union_args)}: {[t.__name__ for t in union_args]}"
        )


# ==============================================================================
# 5. Events carry entities — payload хранит типизированные объекты
# ==============================================================================


class TestEventsCarryEntities:
    """Payload событий хранит entity-объекты, а не dict."""

    def test_process_added_carries_process_entity(self) -> None:
        """ProcessAdded.process — экземпляр Process, не dict."""
        process = _make_process("my_proc")
        evt = ProcessAdded(process_name="my_proc", process=process)
        assert isinstance(evt.process, Process)
        assert evt.process.process_name == "my_proc"

    def test_plugin_inserted_carries_plugin_entity(self) -> None:
        """PluginInserted.plugin — экземпляр PluginInstance, не dict."""
        plugin = _make_plugin("resize")
        evt = PluginInserted(process_name="p", plugin=plugin, index=2)
        assert isinstance(evt.plugin, PluginInstance)
        assert evt.plugin.plugin_name == "resize"

    def test_wire_connected_carries_wire_entity(self) -> None:
        """WireConnected.wire — экземпляр Wire, не dict."""
        wire = _make_wire()
        evt = WireConnected(wire=wire)
        assert isinstance(evt.wire, Wire)
        assert evt.wire.source == wire.source
        assert evt.wire.target == wire.target

    def test_display_bound_carries_display_entity(self) -> None:
        """DisplayBound.display — экземпляр DisplayInstance, не dict."""
        display = _make_display()
        evt = DisplayBound(display=display)
        assert isinstance(evt.display, DisplayInstance)
        assert evt.display.node_id == display.node_id
        assert evt.display.display_id == display.display_id

    def test_target_process_assigned_none_target(self) -> None:
        """TargetProcessAssigned.target допускает None (сброс привязки)."""
        evt = TargetProcessAssigned(process_name="p", target=None)
        assert evt.target is None

    def test_target_process_assigned_string_target(self) -> None:
        """TargetProcessAssigned.target допускает строку."""
        evt = TargetProcessAssigned(process_name="p", target="output_proc")
        assert evt.target == "output_proc"

    def test_plugin_config_changed_any_value(self) -> None:
        """PluginConfigChanged.value принимает любой тип (int, str, list, None)."""
        evt_int = PluginConfigChanged(process_name="p", plugin_index=0, field="k", value=42)
        evt_list = PluginConfigChanged(process_name="p", plugin_index=0, field="k", value=[1, 2])
        evt_none = PluginConfigChanged(process_name="p", plugin_index=0, field="k", value=None)

        assert evt_int.value == 42
        assert evt_list.value == [1, 2]
        assert evt_none.value is None

    def test_process_added_process_has_topology_context(self) -> None:
        """ProcessAdded содержит полноценный Process с plugins."""
        plugin = PluginInstance(plugin_name="blur", config={"kernel_size": 5})
        process = Process(
            process_name="blur_proc",
            plugins=(plugin,),
            category="processing",
        )
        evt = ProcessAdded(process_name="blur_proc", process=process)
        assert isinstance(evt.process, Process)
        assert len(evt.process.plugins) == 1
        assert evt.process.plugins[0].plugin_name == "blur"
        assert evt.process.plugins[0].config == {"kernel_size": 5}
