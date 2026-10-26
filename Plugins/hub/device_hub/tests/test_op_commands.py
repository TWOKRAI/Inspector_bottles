"""Тесты автора SPI.c1: генерация команд ``robot_*`` / ``vfd_*`` из описаний операций (``install_op_commands``).

Purpose:
    Copy-on-write словарей ``commands`` / ``_op_commands`` (родитель не меняется), фабрика замыкания (каждый метод
    несёт свою операцию, Т4), ``__doc__`` (N6), отказ без частичной записи, маршрут тела ``_op_command`` по
    ``route`` / ``needs_link``, состав 55 команд и 55 описаний. Ожидания — литералы.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin, install_op_commands
from Services.device_hub.kinds import DEFAULT_SOURCES
from Services.device_hub.spi import OpSource, OpSpec, command_table

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
    assert DeviceHubPlugin.cmd_robot_abort.__doc__ == "Стоп робота: {device_id, mode: 1|2|3}."
    assert DeviceHubPlugin.cmd_vfd_run.__doc__ == "Пуск ПЧ: {device_id, direction?, freq_hz?}."
    assert DeviceHubPlugin.cmd_robot_stop.__name__ == "cmd_robot_stop"

    class Sub(DeviceHubPlugin):
        pass

    install_op_commands(Sub, [_source("fake", OpSpec(name="ping"))])  # без описания: запасной текст «вид: операция»
    assert Sub.cmd_fake_ping.__doc__ == "fake: ping"


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


def test_op_commands_descriptions_are_the_55() -> None:
    described = {n for n, (_src, spec) in vars(DeviceHubPlugin)["_op_commands"].items() if spec.description}
    assert len(described) == 55
    assert all(n.startswith(("robot_", "vfd_")) for n in described)
    assert sum(n.startswith("vfd_") for n in described) == 5


# --- SPI.d2: command_options хаба ---


def test_command_options_data_command_has_executor_key_and_description() -> None:
    assert DeviceHubPlugin().command_options("robot_point_list") == {
        "metadata": {"description": "Робот v2: список точек {device_id} -> points, rev"},
        "executor": "device_io",
        "key_from": "device_id",
    }


def test_command_options_driver_command_description_only_and_plain_commands_empty() -> None:
    plugin = DeviceHubPlugin()
    assert plugin.command_options("robot_stop") == {
        "metadata": {"description": "Робот v2: стоп {device_id, level: SOFT|HARD|HALT}", "args": ["level"]}
    }
    assert plugin.command_options("robot_abort") == {
        "metadata": {"description": "Стоп робота: {device_id, mode: 1|2|3}.", "args": ["mode?"]}
    }
    assert plugin.command_options("robot_get_telemetry") == {"metadata": {"description": "Телеметрия робота."}}
    assert plugin.command_options("device_list") == {}
    assert plugin.command_options("hik_enum") == {}


def test_command_options_executor_exactly_on_ten_data_commands() -> None:
    plugin = DeviceHubPlugin()
    with_executor = sorted(n for n in DeviceHubPlugin.commands if plugin.command_options(n).get("executor"))
    assert with_executor == sorted(
        f"robot_{op}"
        for op in (
            "param_get_all",
            "point_list",
            "point_save",
            "point_delete",
            "frame_list",
            "frame_teach",
            "program_list",
            "program_get",
            "program_save",
            "program_delete",
        )
    )


def test_command_options_args_from_schema() -> None:
    class Sub(DeviceHubPlugin):
        pass

    install_op_commands(Sub, [_source("arg", OpSpec(name="x", args_schema=("a", "b?")))])
    assert Sub().command_options("arg_x") == {"metadata": {"args": ["a", "b?"]}}


# --- SPI.d2 / D6: счётчики команд под _counters_lock (свойство 27, проверка детерминированная) ---


class _LockCheckingReg:
    """Регистр-заглушка: запись счётчика проверяет удержание замка и уступает поток между чтением и записью."""

    def __init__(self, lock: Any) -> None:
        object.__setattr__(self, "_lock", lock)
        object.__setattr__(self, "unlocked_writes", [])
        object.__setattr__(self, "commands_ok", 0)
        object.__setattr__(self, "commands_err", 0)
        object.__setattr__(self, "last_error", "")

    def __setattr__(self, name: str, value: Any) -> None:
        if not self._lock.locked():
            self.unlocked_writes.append(name)
        time.sleep(0)  # уступить поток: без замка соседняя запись потеряла бы инкремент
        object.__setattr__(self, name, value)


def _counting_plugin() -> tuple[DeviceHubPlugin, _LockCheckingReg]:
    plugin = DeviceHubPlugin()
    plugin._counters_lock = threading.Lock()
    reg = _LockCheckingReg(plugin._counters_lock)
    plugin._reg = reg  # type: ignore[assignment]
    return plugin, reg


def test_safe_call_counters_written_under_lock() -> None:
    plugin, reg = _counting_plugin()

    def boom() -> dict:
        raise RuntimeError("сбой")

    assert plugin._safe_call(lambda: {"x": 1}) == {"x": 1, "status": "ok"}
    assert plugin._safe_call(boom) == {"status": "error", "message": "сбой", "error": "сбой"}
    assert (reg.commands_ok, reg.commands_err, reg.last_error) == (1, 1, "сбой")
    assert reg.unlocked_writes == []


def test_safe_call_counters_exact_under_parallel_calls() -> None:
    plugin, reg = _counting_plugin()
    start = threading.Event()

    def worker() -> None:
        start.wait(5.0)
        for _ in range(50):
            plugin._safe_call(lambda: {})

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(10.0)
    assert not any(t.is_alive() for t in threads)
    assert reg.commands_ok == 400
    assert reg.unlocked_writes == []
