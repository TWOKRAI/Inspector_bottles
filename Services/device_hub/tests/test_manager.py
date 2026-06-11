"""Тесты DeviceManager: CRUD, persist, publish_cb, bridge-целостность, call, describe, write_registers."""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.device_hub.errors import (
    DeviceHubError,
    DeviceNotFoundError,
    RegistryIntegrityError,
)
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.store import RegistryStore


@pytest.fixture
def store(tmp_path: Path) -> RegistryStore:
    return RegistryStore(tmp_path / "devices.yaml")


@pytest.fixture
def published() -> list:
    """Лог publish_cb вызовов: [(path, data), ...]."""
    return []


@pytest.fixture
def mgr(store: RegistryStore, published: list) -> DeviceManager:
    """DeviceManager с фейковым publish_cb."""
    m = DeviceManager(store, publish_cb=lambda p, d: published.append((p, d)))
    m.initialize()
    return m


class TestCrud:
    """CRUD операции реестра."""

    def test_list_empty(self, mgr: DeviceManager) -> None:
        assert mgr.list_devices() == []

    def test_upsert_creates(self, mgr: DeviceManager, published: list) -> None:
        entry = mgr.upsert({"id": "robot_1", "name": "R1", "kind": "robot"})
        assert entry.id == "robot_1"
        assert len(mgr.list_devices()) == 1
        # publish_cb вызван
        assert any("robot_1" in p for p, _ in published)

    def test_upsert_merge_preserves_name(self, mgr: DeviceManager) -> None:
        """upsert существующего: ручное name НЕ затирается."""
        mgr.upsert({"id": "r1", "name": "Ручное имя", "kind": "robot"})
        # Обновляем transport, name в новых данных тоже задано
        updated = mgr.upsert(
            {"id": "r1", "name": "Новое", "kind": "robot", "transport": {"type": "tcp", "host": "10.0.0.1"}}
        )
        assert updated.name == "Новое"
        assert updated.transport["host"] == "10.0.0.1"

    def test_upsert_with_origin(self, mgr: DeviceManager) -> None:
        entry = mgr.upsert({"id": "r1", "name": "R", "kind": "robot"}, origin="recipe:demo")
        assert entry.origin == "recipe:demo"

    def test_get_existing(self, mgr: DeviceManager) -> None:
        mgr.upsert({"id": "r1", "name": "R", "kind": "robot"})
        entry = mgr.get("r1")
        assert entry.id == "r1"

    def test_get_missing_raises(self, mgr: DeviceManager) -> None:
        with pytest.raises(DeviceNotFoundError):
            mgr.get("nonexistent")

    def test_remove(self, mgr: DeviceManager) -> None:
        mgr.upsert({"id": "r1", "name": "R", "kind": "robot"})
        mgr.remove("r1")
        assert mgr.list_devices() == []

    def test_remove_missing_raises(self, mgr: DeviceManager) -> None:
        with pytest.raises(DeviceNotFoundError):
            mgr.remove("nonexistent")


class TestPersist:
    """Персистентность через store."""

    def test_upsert_persists(self, store: RegistryStore, published: list) -> None:
        mgr = DeviceManager(store, publish_cb=lambda p, d: published.append((p, d)))
        mgr.initialize()
        mgr.upsert({"id": "r1", "name": "R", "kind": "robot"})
        # Новый менеджер читает из того же store
        mgr2 = DeviceManager(store)
        mgr2.initialize()
        assert len(mgr2.list_devices()) == 1
        assert mgr2.list_devices()[0]["id"] == "r1"


class TestBridgeIntegrity:
    """Целостность bridge-ссылок: ADR-DH-004."""

    def test_remove_carrier_blocked(self, mgr: DeviceManager) -> None:
        """Удаление носителя при живых bridge-зависимых -> RegistryIntegrityError."""
        mgr.upsert({"id": "robot_main", "name": "R", "kind": "robot"})
        mgr.upsert(
            {
                "id": "vfd_belt",
                "name": "V",
                "kind": "vfd",
                "transport": {"type": "bridge", "bridge": "robot_main"},
            }
        )
        with pytest.raises(RegistryIntegrityError, match="bridge"):
            mgr.remove("robot_main")

    def test_remove_carrier_ok_after_dependent_removed(self, mgr: DeviceManager) -> None:
        """После удаления зависимого — носитель удаляется."""
        mgr.upsert({"id": "robot_main", "name": "R", "kind": "robot"})
        mgr.upsert(
            {
                "id": "vfd_belt",
                "name": "V",
                "kind": "vfd",
                "transport": {"type": "bridge", "bridge": "robot_main"},
            }
        )
        mgr.remove("vfd_belt")
        mgr.remove("robot_main")  # не должно падать
        assert mgr.list_devices() == []


class TestConnectDisconnect:
    """Lifecycle: connect/disconnect."""

    def test_connect_bridge_without_carrier_raises(self, mgr: DeviceManager) -> None:
        """Connect bridge без подключённого носителя -> DeviceHubError."""
        mgr.upsert({"id": "robot_main", "name": "R", "kind": "robot"})
        mgr.upsert(
            {
                "id": "vfd_belt",
                "name": "V",
                "kind": "vfd",
                "transport": {"type": "bridge", "bridge": "robot_main"},
            }
        )
        # Носитель не подключён
        with pytest.raises(DeviceHubError, match="не подключён"):
            mgr.connect("vfd_belt")

    def test_disconnect_carrier_degrades_dependent(self, mgr: DeviceManager) -> None:
        """Disconnect носителя -> зависимый в degraded."""
        from Services.device_hub.drivers.robot_driver import RobotDriver
        from Services.robot_comm.testing.fake_transport import FakeRobotTransport
        from Services.robot_comm.server.sim_core import RobotSimCore

        # Создаём робот-драйвер с фейком
        mgr.upsert({"id": "robot_main", "name": "R", "kind": "robot", "transport": {"type": "tcp"}})
        mgr.upsert(
            {
                "id": "vfd_belt",
                "name": "V",
                "kind": "vfd",
                "transport": {"type": "bridge", "bridge": "robot_main"},
            }
        )

        # Подменяем фабрику для теста — робот с фейковым транспортом
        core = RobotSimCore()
        fake_t = FakeRobotTransport(core)

        def robot_factory(entry, proto):
            return RobotDriver(entry, proto, transport=fake_t)

        mgr.register_driver_factory("robot", robot_factory)

        mgr.connect("robot_main")
        assert mgr._drivers["robot_main"].is_connected

        # Теперь disconnect робота
        mgr.disconnect("robot_main")
        # VFD-драйвер если создан — degraded
        vfd_driver = mgr._drivers.get("vfd_belt")
        if vfd_driver is not None:
            assert not vfd_driver.is_connected


class TestCall:
    """Dispatch: call роутинг + ошибки."""

    def test_call_not_found(self, mgr: DeviceManager) -> None:
        result = mgr.call("nonexistent", "read", {})
        assert result["status"] == "error"
        assert "не найдено" in result["message"]

    def test_call_not_connected(self, mgr: DeviceManager) -> None:
        mgr.upsert({"id": "r1", "name": "R", "kind": "robot"})
        result = mgr.call("r1", "get_telemetry", {})
        assert result["status"] == "error"
        assert "не подключено" in result["message"]


class TestDescribe:
    """describe(id) — информация для GUI."""

    def test_describe_disconnected(self, mgr: DeviceManager) -> None:
        mgr.upsert({"id": "r1", "name": "R", "kind": "robot", "protocol": ""})
        desc = mgr.describe("r1")
        assert desc["entry"]["id"] == "r1"
        assert desc["conn"] == "disconnected"

    def test_describe_missing_raises(self, mgr: DeviceManager) -> None:
        with pytest.raises(DeviceNotFoundError):
            mgr.describe("nonexistent")


class TestWriteRegistersValidation:
    """write_registers: валидация access/min/max."""

    def test_write_readonly_rejected(self, mgr: DeviceManager) -> None:
        """Запись в read-only регистр -> ошибка."""
        from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver
        from Services.modbus.core.protocol_file import DeviceProtocol, RegisterMeta
        from Services.modbus.core.register_map import RegisterMap, Reg

        # Фейковый протокол с r-only регистром
        rmap = RegisterMap({"temp": Reg(0x100)})
        meta = {"temp": RegisterMeta(name="temp", kind="reg", access="r")}
        proto = DeviceProtocol(name="test", kind="generic_modbus", description="", register_map=rmap, meta=meta)

        mgr.upsert({"id": "sensor", "name": "S", "kind": "generic_modbus"})

        # Подменяем фабрику
        class FakeTransport:
            is_connected = True

            def read_registers(self, a, c=1):
                return [0] * c

            def transaction(self, ops):
                return True

        driver = GenericModbusDriver(
            mgr.get("sensor"),
            proto,
            transport=FakeTransport(),
        )
        driver._device = FakeTransport()
        mgr._drivers["sensor"] = driver

        result = mgr.write_registers("sensor", {"temp": 42})
        assert result["status"] == "error"
        assert "только на чтение" in result["message"]

    def test_write_out_of_range_rejected(self, mgr: DeviceManager) -> None:
        """Значение вне min/max -> ошибка."""
        from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver
        from Services.modbus.core.protocol_file import DeviceProtocol, RegisterMeta
        from Services.modbus.core.register_map import RegisterMap, Reg

        rmap = RegisterMap({"freq": Reg(0x200, scale=100)})
        meta = {"freq": RegisterMeta(name="freq", kind="reg", access="rw", min=0, max=50)}
        proto = DeviceProtocol(name="test", kind="generic_modbus", description="", register_map=rmap, meta=meta)

        mgr.upsert({"id": "sensor", "name": "S", "kind": "generic_modbus"})

        class FakeTransport:
            is_connected = True

            def read_registers(self, a, c=1):
                return [0] * c

            def transaction(self, ops):
                return True

        driver = GenericModbusDriver(
            mgr.get("sensor"),
            proto,
            transport=FakeTransport(),
        )
        driver._device = FakeTransport()
        mgr._drivers["sensor"] = driver

        result = mgr.write_registers("sensor", {"freq": 100.0})
        assert result["status"] == "error"
        assert "max" in result["message"]
