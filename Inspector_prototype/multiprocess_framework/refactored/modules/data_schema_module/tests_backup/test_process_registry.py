# -*- coding: utf-8 -*-
"""
Тесты для ProcessRegistersRegistry и RegistersMeta.

Тестируемые сценарии:
    - Singleton: все вызовы возвращают тот же объект
    - register_process: добавление нового процесса
    - register_process: повторная регистрация → ValueError
    - update_process: обновление контейнера и/или метаданных
    - unregister_process: удаление, возврат True/False
    - get_container / get_meta / get_register
    - has_process / process_names / __contains__ / __len__
    - collect_routing_channels: собирает только не-пустые каналы
    - collect_field_routing: собирает routing из FieldMeta
    - collect_all_registers_meta: класс и поля
    - summary: структура сводки
    - export_state / to_json: полный дамп данных
    - thread-safety: параллельная регистрация нескольких процессов
"""
import sys
import types

if "multiprocess_framework" not in sys.modules:
    _mock_fw = types.ModuleType("multiprocess_framework")
    _mock_fw.__path__ = []
    sys.modules["multiprocess_framework"] = _mock_fw

import json
import threading
from typing import Annotated

import pytest

from data_schema_module.registry.process_registry import (
    ProcessRegistersRegistry,
    RegistersMeta,
)
from data_schema_module.utils.registers_container import RegistersContainer
from data_schema_module.fields.register_base import RegisterBase
from data_schema_module.fields.field_meta import FieldMeta
from data_schema_module.fields.field_routing import FieldRouting


# =============================================================================
# Вспомогательные классы
# =============================================================================

CTRL_ROUTING = FieldRouting(channel="ctrl_channel")


class AlphaRegisters(RegisterBase):
    value: Annotated[int, FieldMeta("Значение", min=0, max=100)] = 42


class BetaRegisters(RegisterBase):
    rate: Annotated[float, FieldMeta("Скорость", routing=CTRL_ROUTING, min=0.0)] = 1.0


def make_container(*classes) -> RegistersContainer:
    register_map = {cls.__name__.replace("Registers", "").lower(): cls for cls in classes}
    return RegistersContainer(register_map)


# =============================================================================
# Фикстура: сброс Singleton перед каждым тестом
# =============================================================================

@pytest.fixture(autouse=True)
def reset_registry():
    ProcessRegistersRegistry.reset()
    yield
    ProcessRegistersRegistry.reset()


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:
    def test_same_instance(self) -> None:
        r1 = ProcessRegistersRegistry()
        r2 = ProcessRegistersRegistry()
        assert r1 is r2

    def test_reset_creates_new(self) -> None:
        r1 = ProcessRegistersRegistry()
        ProcessRegistersRegistry.reset()
        r2 = ProcessRegistersRegistry()
        assert r1 is not r2

    def test_initial_empty(self) -> None:
        r = ProcessRegistersRegistry()
        assert len(r) == 0
        assert r.process_names == []


# =============================================================================
# register_process
# =============================================================================

class TestRegisterProcess:
    def test_register_basic(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        reg.register_process("proc_a", container)
        assert "proc_a" in reg
        assert len(reg) == 1

    def test_register_with_meta(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        meta = RegistersMeta(display_name="Альфа", routing_channel="alpha_ctrl")
        reg.register_process("proc_a", container, meta=meta)
        assert reg.get_meta("proc_a").display_name == "Альфа"
        assert reg.get_meta("proc_a").routing_channel == "alpha_ctrl"

    def test_register_duplicate_raises(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        reg.register_process("proc_a", container)
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            reg.register_process("proc_a", container)

    def test_default_meta_display_name(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        reg.register_process("my_process", container)
        assert reg.get_meta("my_process").display_name == "my_process"

    def test_register_multiple(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc_a", make_container(AlphaRegisters))
        reg.register_process("proc_b", make_container(BetaRegisters))
        assert len(reg) == 2
        assert set(reg.process_names) == {"proc_a", "proc_b"}


# =============================================================================
# update_process
# =============================================================================

class TestUpdateProcess:
    def test_update_container(self) -> None:
        reg = ProcessRegistersRegistry()
        c1 = make_container(AlphaRegisters)
        reg.register_process("proc", c1)

        c2 = make_container(BetaRegisters)
        reg.update_process("proc", container=c2)
        assert reg.get_container("proc") is c2

    def test_update_meta_only(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        meta = RegistersMeta(display_name="Старое")
        reg.register_process("proc", container, meta=meta)

        new_meta = RegistersMeta(display_name="Новое", version="2.0.0")
        reg.update_process("proc", meta=new_meta)
        assert reg.get_meta("proc").display_name == "Новое"
        assert reg.get_meta("proc").version == "2.0.0"

    def test_update_nonexistent_creates(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        reg.update_process("new_proc", container=container)
        assert "new_proc" in reg


# =============================================================================
# unregister_process
# =============================================================================

class TestUnregisterProcess:
    def test_unregister_existing(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc", make_container(AlphaRegisters))
        result = reg.unregister_process("proc")
        assert result is True
        assert "proc" not in reg

    def test_unregister_nonexistent(self) -> None:
        reg = ProcessRegistersRegistry()
        result = reg.unregister_process("ghost")
        assert result is False


# =============================================================================
# Доступ к данным
# =============================================================================

class TestDataAccess:
    def test_get_container(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        reg.register_process("proc", container)
        assert reg.get_container("proc") is container

    def test_get_container_missing(self) -> None:
        assert ProcessRegistersRegistry().get_container("ghost") is None

    def test_get_meta_missing(self) -> None:
        assert ProcessRegistersRegistry().get_meta("ghost") is None

    def test_get_register(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        reg.register_process("proc", container)
        alpha_reg = reg.get_register("proc", "alpha")
        assert alpha_reg is not None
        assert isinstance(alpha_reg, AlphaRegisters)

    def test_get_register_missing_process(self) -> None:
        assert ProcessRegistersRegistry().get_register("ghost", "alpha") is None

    def test_has_process(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc", make_container(AlphaRegisters))
        assert reg.has_process("proc") is True
        assert reg.has_process("ghost") is False

    def test_contains(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc", make_container(AlphaRegisters))
        assert "proc" in reg
        assert "ghost" not in reg


# =============================================================================
# Агрегация метаданных
# =============================================================================

class TestAggregation:
    def test_collect_routing_channels(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process(
            "proc_a", make_container(AlphaRegisters),
            meta=RegistersMeta(routing_channel="channel_a")
        )
        reg.register_process(
            "proc_b", make_container(BetaRegisters),
            meta=RegistersMeta(routing_channel="")  # пустой → не должен войти
        )
        channels = reg.collect_routing_channels()
        assert "proc_a" in channels
        assert channels["proc_a"] == "channel_a"
        assert "proc_b" not in channels

    def test_collect_field_routing(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc_b", make_container(BetaRegisters))
        routing = reg.collect_field_routing()
        assert "proc_b" in routing
        assert "beta.rate" in routing["proc_b"]
        assert routing["proc_b"]["beta.rate"]["channel"] == "ctrl_channel"

    def test_collect_all_registers_meta_class_name(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc_a", make_container(AlphaRegisters))
        meta = reg.collect_all_registers_meta()
        assert "proc_a" in meta
        assert "alpha" in meta["proc_a"]
        assert meta["proc_a"]["alpha"]["class"] == "AlphaRegisters"

    def test_collect_all_registers_meta_has_fields(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc_a", make_container(AlphaRegisters))
        meta = reg.collect_all_registers_meta()
        assert "value" in meta["proc_a"]["alpha"]["fields"]


# =============================================================================
# Сводка и экспорт
# =============================================================================

class TestSummaryAndExport:
    def test_summary_structure(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process(
            "proc_a", make_container(AlphaRegisters),
            meta=RegistersMeta(display_name="Альфа", version="1.2.0", tags=["ui"])
        )
        s = reg.summary()
        assert s["total_processes"] == 1
        assert "proc_a" in s["processes"]
        p = s["processes"]["proc_a"]
        assert p["display_name"] == "Альфа"
        assert p["version"] == "1.2.0"
        assert "alpha" in p["registers"]
        assert p["total_registers"] == 1

    def test_export_state(self) -> None:
        reg = ProcessRegistersRegistry()
        container = make_container(AlphaRegisters)
        reg.register_process("proc_a", container)
        state = reg.export_state()
        assert "proc_a" in state
        assert "alpha" in state["proc_a"]
        assert state["proc_a"]["alpha"]["value"] == 42

    def test_to_json(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc_a", make_container(AlphaRegisters))
        j = reg.to_json()
        data = json.loads(j)
        assert "proc_a" in data

    def test_repr(self) -> None:
        reg = ProcessRegistersRegistry()
        reg.register_process("proc_a", make_container(AlphaRegisters))
        r = repr(reg)
        assert "proc_a" in r


# =============================================================================
# RegistersMeta
# =============================================================================

class TestRegistersMeta:
    def test_defaults(self) -> None:
        m = RegistersMeta()
        assert m.display_name == ""
        assert m.process_type == "worker"
        assert m.routing_channel == ""
        assert m.version == "1.0.0"
        assert m.tags == []
        assert m.extra == {}

    def test_to_dict(self) -> None:
        m = RegistersMeta(display_name="Test", tags=["a", "b"], extra={"x": 1})
        d = m.to_dict()
        assert d["display_name"] == "Test"
        assert d["tags"] == ["a", "b"]
        assert d["extra"] == {"x": 1}


# =============================================================================
# Thread-safety
# =============================================================================

class TestThreadSafety:
    def test_parallel_registration(self) -> None:
        reg = ProcessRegistersRegistry()
        errors: list[Exception] = []

        def register(name: str) -> None:
            try:
                reg.register_process(name, make_container(AlphaRegisters))
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register, args=(f"proc_{i}",))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Ошибки при параллельной регистрации: {errors}"
        assert len(reg) == 20
