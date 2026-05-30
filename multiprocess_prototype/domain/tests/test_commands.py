# -*- coding: utf-8 -*-
"""
Тесты для domain/commands.py (Task B.3).

Покрывает:
1. test_command_immutable         — frozen dataclass бросает FrozenInstanceError при мутации.
2. test_command_slots             — slots=True означает отсутствие __dict__.
3. test_command_type_discriminator — ClassVar command_type содержит имя класса.
4. test_exhaustiveness_match      — match-expression покрывает все 14 вариантов ProjectCommand.
5. test_commands_carry_entities   — payload хранит типизированные entity (Topology, PluginInstance).
6. test_default_values            — AddProcess.plugins=(), InsertPlugin.index=None.
7. test_all_14_commands_covered   — len(get_args(ProjectCommand)) == 14.
"""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from multiprocess_prototype.domain import (
    ActivateRecipe,
    AddProcess,
    AssignTargetProcess,
    BindDisplay,
    ConnectWire,
    DeactivateRecipe,
    DisconnectWire,
    InsertPlugin,
    MovePlugin,
    PluginInstance,
    ProjectCommand,
    RemovePlugin,
    RemoveProcess,
    RenameProcess,
    ReplaceTopology,
    SetPluginConfig,
    Topology,
    UnbindDisplay,
)


# ==============================================================================
# Вспомогательные фабрики
# ==============================================================================


def _make_plugin(name: str = "blur") -> PluginInstance:
    """Минимальный PluginInstance для тестов."""
    return PluginInstance(plugin_name=name)


def _make_topology() -> Topology:
    """Минимальная Topology для тестов."""
    return Topology()


# ==============================================================================
# 1. Frozen — FrozenInstanceError при попытке мутации
# ==============================================================================


class TestCommandImmutable:
    """frozen=True → попытка изменить поле бросает FrozenInstanceError."""

    def test_add_process_immutable(self) -> None:
        """AddProcess.process_name нельзя изменить."""
        cmd = AddProcess(process_name="proc")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.process_name = "mutated"  # type: ignore[misc]

    def test_remove_process_immutable(self) -> None:
        """RemoveProcess.process_name нельзя изменить."""
        cmd = RemoveProcess(process_name="proc")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.process_name = "mutated"  # type: ignore[misc]

    def test_rename_process_immutable(self) -> None:
        """RenameProcess.old_name нельзя изменить."""
        cmd = RenameProcess(old_name="a", new_name="b")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.old_name = "mutated"  # type: ignore[misc]

    def test_insert_plugin_immutable(self) -> None:
        """InsertPlugin.process_name нельзя изменить."""
        cmd = InsertPlugin(process_name="proc", plugin=_make_plugin())
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.process_name = "mutated"  # type: ignore[misc]

    def test_connect_wire_immutable(self) -> None:
        """ConnectWire.source нельзя изменить."""
        cmd = ConnectWire(source="a", target="b")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.source = "mutated"  # type: ignore[misc]

    def test_replace_topology_immutable(self) -> None:
        """ReplaceTopology.reason нельзя изменить."""
        cmd = ReplaceTopology(topology=_make_topology(), reason="test")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.reason = "mutated"  # type: ignore[misc]

    def test_deactivate_recipe_is_frozen(self) -> None:
        """DeactivateRecipe (без полей) — frozen=True зафиксировано в метаданных."""
        cmd = DeactivateRecipe()
        fields = dataclasses.fields(cmd)
        assert len(fields) == 0, "DeactivateRecipe не должен иметь полей"
        assert cmd.__dataclass_params__.frozen is True  # type: ignore[attr-defined]


# ==============================================================================
# 2. Slots — нет __dict__
# ==============================================================================


class TestCommandSlots:
    """slots=True → у экземпляра нет __dict__."""

    @pytest.mark.parametrize(
        "cmd",
        [
            AddProcess(process_name="p"),
            RemoveProcess(process_name="p"),
            RenameProcess(old_name="a", new_name="b"),
            InsertPlugin(process_name="p", plugin=PluginInstance(plugin_name="blur")),
            RemovePlugin(process_name="p", index=0),
            SetPluginConfig(process_name="p", plugin_index=0, field="k", value=1),
            ConnectWire(source="a", target="b"),
            DisconnectWire(source="a", target="b"),
            BindDisplay(node_id="n", display_id="d"),
            UnbindDisplay(node_id="n", display_id="d"),
            AssignTargetProcess(process_name="p", target=None),
            ActivateRecipe(slug="r"),
            DeactivateRecipe(),
            ReplaceTopology(topology=Topology(), reason="test"),
        ],
        ids=[
            "AddProcess",
            "RemoveProcess",
            "RenameProcess",
            "InsertPlugin",
            "RemovePlugin",
            "SetPluginConfig",
            "ConnectWire",
            "DisconnectWire",
            "BindDisplay",
            "UnbindDisplay",
            "AssignTargetProcess",
            "ActivateRecipe",
            "DeactivateRecipe",
            "ReplaceTopology",
        ],
    )
    def test_no_dict(self, cmd: object) -> None:
        """У dataclass с slots=True нет __dict__."""
        assert not hasattr(cmd, "__dict__"), (
            f"{type(cmd).__name__}: ожидается slots=True (нет __dict__), но __dict__ существует"
        )


# ==============================================================================
# 3. ClassVar command_type — дискриминатор
# ==============================================================================


class TestCommandTypeDiscriminator:
    """command_type ClassVar содержит имя класса (PascalCase)."""

    @pytest.mark.parametrize(
        ("cmd_cls", "expected"),
        [
            (AddProcess, "AddProcess"),
            (RemoveProcess, "RemoveProcess"),
            (RenameProcess, "RenameProcess"),
            (InsertPlugin, "InsertPlugin"),
            (RemovePlugin, "RemovePlugin"),
            (SetPluginConfig, "SetPluginConfig"),
            (ConnectWire, "ConnectWire"),
            (DisconnectWire, "DisconnectWire"),
            (BindDisplay, "BindDisplay"),
            (UnbindDisplay, "UnbindDisplay"),
            (AssignTargetProcess, "AssignTargetProcess"),
            (ActivateRecipe, "ActivateRecipe"),
            (DeactivateRecipe, "DeactivateRecipe"),
            (ReplaceTopology, "ReplaceTopology"),
        ],
    )
    def test_command_type_equals_class_name(self, cmd_cls: type, expected: str) -> None:
        """command_type на классе совпадает с именем класса (PascalCase)."""
        assert cmd_cls.command_type == expected  # type: ignore[attr-defined]

    def test_command_type_not_instance_field(self) -> None:
        """command_type — ClassVar, не instance-поле (не попадает в dataclass fields)."""
        fields = {f.name for f in dataclasses.fields(AddProcess)}
        assert "command_type" not in fields, "command_type должен быть ClassVar, не instance-полем"


# ==============================================================================
# 4. Exhaustiveness match — все 14 вариантов покрыты
# ==============================================================================


def _dispatch(cmd: ProjectCommand) -> str:
    """Demo-обработчик для проверки exhaustiveness match.

    Покрывает все 14 вариантов ProjectCommand без default-ветки.
    Pyright в strict-режиме подтвердит, что match исчерпывающий.
    """
    match cmd:
        case AddProcess():
            return "AddProcess"
        case RemoveProcess():
            return "RemoveProcess"
        case RenameProcess():
            return "RenameProcess"
        case InsertPlugin():
            return "InsertPlugin"
        case RemovePlugin():
            return "RemovePlugin"
        case SetPluginConfig():
            return "SetPluginConfig"
        case MovePlugin():
            return "MovePlugin"
        case ConnectWire():
            return "ConnectWire"
        case DisconnectWire():
            return "DisconnectWire"
        case BindDisplay():
            return "BindDisplay"
        case UnbindDisplay():
            return "UnbindDisplay"
        case AssignTargetProcess():
            return "AssignTargetProcess"
        case ActivateRecipe():
            return "ActivateRecipe"
        case DeactivateRecipe():
            return "DeactivateRecipe"
        case ReplaceTopology():
            return "ReplaceTopology"


class TestExhaustivenessMatch:
    """match покрывает все 14 вариантов ProjectCommand."""

    @pytest.mark.parametrize(
        ("cmd", "expected_label"),
        [
            (AddProcess(process_name="p"), "AddProcess"),
            (RemoveProcess(process_name="p"), "RemoveProcess"),
            (RenameProcess(old_name="a", new_name="b"), "RenameProcess"),
            (
                InsertPlugin(process_name="p", plugin=PluginInstance(plugin_name="blur")),
                "InsertPlugin",
            ),
            (RemovePlugin(process_name="p", index=0), "RemovePlugin"),
            (
                SetPluginConfig(process_name="p", plugin_index=0, field="k", value=42),
                "SetPluginConfig",
            ),
            (MovePlugin(from_process="p", from_index=0, to_process="q"), "MovePlugin"),
            (ConnectWire(source="a", target="b"), "ConnectWire"),
            (DisconnectWire(source="a", target="b"), "DisconnectWire"),
            (BindDisplay(node_id="n", display_id="d"), "BindDisplay"),
            (UnbindDisplay(node_id="n", display_id="d"), "UnbindDisplay"),
            (AssignTargetProcess(process_name="p", target="q"), "AssignTargetProcess"),
            (ActivateRecipe(slug="my_recipe"), "ActivateRecipe"),
            (DeactivateRecipe(), "DeactivateRecipe"),
            (ReplaceTopology(topology=Topology(), reason="blueprint reload"), "ReplaceTopology"),
        ],
        ids=[
            "AddProcess",
            "RemoveProcess",
            "RenameProcess",
            "InsertPlugin",
            "RemovePlugin",
            "SetPluginConfig",
            "MovePlugin",
            "ConnectWire",
            "DisconnectWire",
            "BindDisplay",
            "UnbindDisplay",
            "AssignTargetProcess",
            "ActivateRecipe",
            "DeactivateRecipe",
            "ReplaceTopology",
        ],
    )
    def test_dispatch_returns_label(self, cmd: ProjectCommand, expected_label: str) -> None:
        """_dispatch(cmd) возвращает строку-метку для каждой из 14 команд."""
        result = _dispatch(cmd)
        assert result == expected_label


# ==============================================================================
# 5. Commands carry entities — payload хранит типизированные объекты
# ==============================================================================


class TestCommandsCarryEntities:
    """Payload команд хранит entity-объекты, а не dict."""

    def test_replace_topology_carries_topology_entity(self) -> None:
        """ReplaceTopology.topology — экземпляр Topology, не dict."""
        from multiprocess_prototype.domain import Process, Wire

        topology = Topology(
            processes=(Process(process_name="cam", plugins=()),),
            wires=(Wire(source="cam.out", target="display.in"),),
        )
        cmd = ReplaceTopology(topology=topology, reason="recipe:demo")
        assert isinstance(cmd.topology, Topology)
        assert len(cmd.topology.processes) == 1
        assert cmd.topology.processes[0].process_name == "cam"
        assert len(cmd.topology.wires) == 1

    def test_insert_plugin_carries_plugin_entity(self) -> None:
        """InsertPlugin.plugin — экземпляр PluginInstance, не dict."""
        plugin = PluginInstance(plugin_name="resize", config={"width": 640})
        cmd = InsertPlugin(process_name="proc", plugin=plugin, index=1)
        assert isinstance(cmd.plugin, PluginInstance)
        assert cmd.plugin.plugin_name == "resize"
        assert cmd.plugin.config == {"width": 640}

    def test_assign_target_process_none(self) -> None:
        """AssignTargetProcess.target допускает None (сброс привязки)."""
        cmd = AssignTargetProcess(process_name="p", target=None)
        assert cmd.target is None

    def test_assign_target_process_string(self) -> None:
        """AssignTargetProcess.target допускает строку."""
        cmd = AssignTargetProcess(process_name="p", target="output_proc")
        assert cmd.target == "output_proc"

    def test_set_plugin_config_any_value(self) -> None:
        """SetPluginConfig.value принимает любой тип (int, str, list, None)."""
        cmd_int = SetPluginConfig(process_name="p", plugin_index=0, field="k", value=42)
        cmd_list = SetPluginConfig(process_name="p", plugin_index=0, field="k", value=[1, 2])
        cmd_none = SetPluginConfig(process_name="p", plugin_index=0, field="k", value=None)
        assert cmd_int.value == 42
        assert cmd_list.value == [1, 2]
        assert cmd_none.value is None

    def test_connect_wire_optional_dtypes(self) -> None:
        """ConnectWire поддерживает src_dtype и tgt_dtype."""
        cmd = ConnectWire(source="a.out", target="b.in", src_dtype="image", tgt_dtype="image")
        assert cmd.src_dtype == "image"
        assert cmd.tgt_dtype == "image"


# ==============================================================================
# 6. Default values — значения по умолчанию
# ==============================================================================


class TestDefaultValues:
    """Команды с опциональными полями имеют ожидаемые defaults."""

    def test_add_process_default_plugins(self) -> None:
        """AddProcess(process_name='p') имеет plugins=()."""
        cmd = AddProcess(process_name="p")
        assert cmd.plugins == ()

    def test_insert_plugin_default_index(self) -> None:
        """InsertPlugin без index имеет index=None (append)."""
        cmd = InsertPlugin(process_name="p", plugin=_make_plugin("x"))
        assert cmd.index is None

    def test_connect_wire_default_dtypes(self) -> None:
        """ConnectWire без dtype-аргументов имеет src_dtype=None, tgt_dtype=None."""
        cmd = ConnectWire(source="a", target="b")
        assert cmd.src_dtype is None
        assert cmd.tgt_dtype is None


# ==============================================================================
# 7. All 14 commands covered — ProjectCommand Union содержит 14 типов
# ==============================================================================


class TestAll14CommandsCovered:
    """ProjectCommand Union содержит ровно 15 типов (14 + MovePlugin, Phase B)."""

    def test_project_command_union_size(self) -> None:
        """len(get_args(ProjectCommand)) == 15."""
        union_args = get_args(ProjectCommand)
        assert len(union_args) == 15, (
            f"ProjectCommand должен содержать 15 типов, найдено {len(union_args)}: {[t.__name__ for t in union_args]}"
        )
