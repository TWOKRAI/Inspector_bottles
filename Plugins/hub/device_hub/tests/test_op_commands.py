"""Тесты автора SPI.c1: генерация команд ``robot_*`` / ``vfd_*`` из описаний операций (``install_op_commands``).

Purpose:
    Copy-on-write словарей ``commands`` / ``_op_commands`` (родитель не меняется), фабрика замыкания (каждый метод
    несёт свою операцию, Т4), ``__doc__`` (N6), отказ без частичной записи, маршрут тела ``_op_command`` по
    ``route`` / ``needs_link``, состав 55 команд и 21 описание. Ожидания — литералы.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin, install_op_commands
from Services.device_hub.spi import DEFAULT_SOURCES, OpSource, OpSpec, command_table

_DEVICE_AND_HIK = {
    "device_list",
    "device_describe",
    "device_upsert",
    "device_upsert_many",
    "device_sync_set",
    "device_remove",
    "device_protocols",
    "device_connect",
    "device_disconnect",
    "device_read",
    "device_write",
    "hik_enum",
    "hik_open",
    "hik_close",
    "hik_get_params",
    "hik_set_params",
    "hik_release",
}


def _source(prefix: str, *ops: OpSpec, route: str = "driver") -> OpSource:
    return OpSource(prefix=prefix, kind=f"{prefix}_kind", route=route, ops=ops)  # type: ignore[arg-type]


class _Recording(DeviceHubPlugin):
    """Подкласс, чьи пути исполнения пишут вызов вместо работы с менеджером."""

    def __init__(self) -> None:  # без configure: тесты зовут только сгенерированные методы
        self.calls: list[tuple[Any, ...]] = []

    def _kind_call(self, data: dict, expected_kind: str, op: str) -> dict:
        self.calls.append(("kind", expected_kind, op, data))
        return {"status": "ok"}

    def _driver_call(self, data: dict, expected_kind: str, op: str) -> dict:
        self.calls.append(("driver", expected_kind, op, data))
        return {"status": "ok"}

    def _robot_data(self, data: dict, op: str) -> dict:
        self.calls.append(("data", op, data))
        return {"status": "ok"}


def test_device_hub_plugin_has_72_commands_55_generated() -> None:
    names = set(DeviceHubPlugin.commands)
    assert len(names) == 72
    generated = names - _DEVICE_AND_HIK
    assert generated == set(command_table(DEFAULT_SOURCES)) and len(generated) == 55
    assert all(
        DeviceHubPlugin.commands[n] == f"cmd_{n}" and callable(getattr(DeviceHubPlugin, f"cmd_{n}")) for n in names
    )


def test_generated_docs_description_or_fallback() -> None:
    assert DeviceHubPlugin.cmd_robot_stop.__doc__ == "Робот v2: стоп {device_id, level: SOFT|HARD|HALT}"
    assert DeviceHubPlugin.cmd_robot_abort.__doc__ == "robot: abort"
    assert DeviceHubPlugin.cmd_vfd_run.__doc__ == "vfd: run"
    assert DeviceHubPlugin.cmd_robot_stop.__name__ == "cmd_robot_stop"


def test_copy_on_write_parent_unchanged() -> None:
    before_commands = dict(DeviceHubPlugin.commands)
    before_ops = dict(vars(DeviceHubPlugin)["_op_commands"])

    class Sub(DeviceHubPlugin):
        pass

    install_op_commands(Sub, [_source("cow", OpSpec(name="x"))])
    assert "cow_x" in Sub.commands and "cow_x" in vars(Sub)["_op_commands"]
    assert DeviceHubPlugin.commands == before_commands
    assert vars(DeviceHubPlugin)["_op_commands"] == before_ops
    assert not hasattr(DeviceHubPlugin, "cmd_cow_x")
    assert set(Sub.commands) == set(before_commands) | {"cow_x"}


def test_factory_binds_each_method_to_its_own_operation() -> None:
    """Т4: три операции одного источника — каждый метод зовёт свою (замыкание не над переменной цикла)."""

    class Sub(_Recording):
        pass

    install_op_commands(Sub, [_source("fac", OpSpec(name="a"), OpSpec(name="b"), OpSpec(name="c"))])
    plugin = Sub()
    for name in ("a", "b", "c"):
        assert getattr(plugin, f"cmd_fac_{name}")({"device_id": "d"}) == {"status": "ok"}
    assert [c[2] for c in plugin.calls] == ["a", "b", "c"]


def test_route_and_needs_link_choose_the_path() -> None:
    class Sub(_Recording):
        pass

    install_op_commands(
        Sub,
        [
            _source("rt", OpSpec(name="linked"), OpSpec(name="offline", needs_link=False)),
            _source("rd", OpSpec(name="store", needs_link=False), route="data"),
        ],
    )
    plugin = Sub()
    data = {"device_id": "d", "k": 1}
    plugin.cmd_rt_linked(data)
    plugin.cmd_rt_offline(data)
    plugin.cmd_rd_store(data)
    assert plugin.calls == [
        ("kind", "rt_kind", "linked", data),
        ("driver", "rt_kind", "offline", data),
        ("data", "store", data),
    ]


def test_taken_name_raises_without_partial_install() -> None:
    class Sub(DeviceHubPlugin):
        pass

    before = dict(Sub.commands)
    taken = _source("device", OpSpec(name="zzz_new"), OpSpec(name="list"))
    with pytest.raises(ValueError):
        install_op_commands(Sub, [taken])
    assert "commands" not in vars(Sub) and Sub.commands == before
    assert not hasattr(Sub, "cmd_device_zzz_new")


def test_existing_cmd_attribute_raises() -> None:
    class Sub(DeviceHubPlugin):
        def cmd_own_x(self, data: dict) -> dict:
            return {}

    with pytest.raises(ValueError):
        install_op_commands(Sub, [_source("own", OpSpec(name="x"))])


def test_op_commands_descriptions_are_the_21() -> None:
    described = {n for n, (_src, spec) in vars(DeviceHubPlugin)["_op_commands"].items() if spec.description}
    assert len(described) == 21
    assert all(n.startswith("robot_") for n in described)
