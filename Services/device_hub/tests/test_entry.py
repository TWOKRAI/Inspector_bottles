"""Тесты DeviceEntry: to_dict/from_dict, валидация id/kind/transport.type."""

from __future__ import annotations

import pytest

from Services.device_hub.registry.entry import DeviceEntry


class TestDeviceEntry:
    """Тесты создания и сериализации DeviceEntry."""

    def test_create_valid(self) -> None:
        """Валидная запись создаётся без ошибок."""
        entry = DeviceEntry(
            id="robot_main",
            name="Робот Delta",
            kind="robot",
            transport={"type": "tcp", "host": "192.168.1.7"},
        )
        assert entry.id == "robot_main"
        assert entry.kind == "robot"
        assert entry.enabled is True
        assert entry.origin == "manual"

    def test_to_dict_roundtrip(self) -> None:
        """to_dict -> from_dict -> тот же объект."""
        entry = DeviceEntry(
            id="vfd_belt",
            name="ПЧ лента",
            kind="vfd",
            protocol="gd20_bridge",
            transport={"type": "bridge", "bridge": "robot_main"},
            params={"freq_max_hz": 50.0},
            enabled=True,
            auto_connect=True,
            origin="recipe:demo",
        )
        d = entry.to_dict()
        restored = DeviceEntry.from_dict(d)
        assert restored.id == entry.id
        assert restored.kind == entry.kind
        assert restored.protocol == entry.protocol
        assert restored.transport == entry.transport
        assert restored.params == entry.params
        assert restored.auto_connect is True
        assert restored.origin == "recipe:demo"

    def test_from_dict_ignores_extra_keys(self) -> None:
        """from_dict игнорирует посторонние ключи."""
        d = {"id": "test_1", "name": "Test", "kind": "robot", "extra": 42}
        entry = DeviceEntry.from_dict(d)
        assert entry.id == "test_1"
        assert not hasattr(entry, "extra")

    def test_all_valid_kinds(self) -> None:
        """Все допустимые kind принимаются."""
        for kind in ("robot", "vfd", "hikvision", "generic_modbus"):
            entry = DeviceEntry(id=f"dev_{kind}", name="Test", kind=kind)
            assert entry.kind == kind

    def test_all_valid_transport_types(self) -> None:
        """Все допустимые transport.type принимаются."""
        for t_type in ("tcp", "rtu", "bridge"):
            entry = DeviceEntry(
                id="dev_1",
                name="Test",
                kind="robot",
                transport={"type": t_type},
            )
            assert entry.transport["type"] == t_type

    def test_empty_transport_ok(self) -> None:
        """Пустой transport (без type) допустим."""
        entry = DeviceEntry(id="dev_1", name="Test", kind="robot")
        assert entry.transport == {}


class TestDeviceEntryValidation:
    """Тесты валидации DeviceEntry."""

    def test_invalid_id_uppercase(self) -> None:
        """Uppercase в id — ошибка."""
        with pytest.raises(ValueError, match="slug"):
            DeviceEntry(id="Robot_Main", name="Test", kind="robot")

    def test_invalid_id_spaces(self) -> None:
        """Пробелы в id — ошибка."""
        with pytest.raises(ValueError, match="slug"):
            DeviceEntry(id="robot main", name="Test", kind="robot")

    def test_invalid_id_dash(self) -> None:
        """Дефис в id — ошибка (только подчёркивание)."""
        with pytest.raises(ValueError, match="slug"):
            DeviceEntry(id="robot-main", name="Test", kind="robot")

    def test_invalid_id_empty(self) -> None:
        """Пустой id — ошибка."""
        with pytest.raises(ValueError, match="slug"):
            DeviceEntry(id="", name="Test", kind="robot")

    def test_invalid_kind(self) -> None:
        """Неизвестный kind — ошибка."""
        with pytest.raises(ValueError, match="kind"):
            DeviceEntry(id="dev_1", name="Test", kind="unknown")

    def test_invalid_transport_type(self) -> None:
        """Неизвестный transport.type — ошибка."""
        with pytest.raises(ValueError, match="transport.type"):
            DeviceEntry(
                id="dev_1",
                name="Test",
                kind="robot",
                transport={"type": "serial"},
            )
