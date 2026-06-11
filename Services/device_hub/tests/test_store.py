"""Тесты RegistryStore: load/save roundtrip, atomic, пустой файл, незнакомая версия."""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.device_hub.errors import DeviceHubError
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.registry.store import RegistryStore


class TestRegistryStore:
    """Тесты персистентности реестра устройств."""

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        """save -> load возвращает эквивалентные записи."""
        store = RegistryStore(tmp_path / "devices.yaml")
        entries = [
            DeviceEntry(
                id="robot_main",
                name="Робот Delta",
                kind="robot",
                protocol="delta_universal3",
                transport={"type": "tcp", "host": "192.168.1.7", "port": 502},
                params={"word_order": "little"},
            ),
            DeviceEntry(
                id="vfd_belt",
                name="ПЧ лента",
                kind="vfd",
                protocol="gd20_bridge",
                transport={"type": "bridge", "bridge": "robot_main"},
            ),
        ]
        store.save(entries)
        loaded = store.load()
        assert len(loaded) == 2
        assert loaded[0].id == "robot_main"
        assert loaded[0].transport["host"] == "192.168.1.7"
        assert loaded[1].id == "vfd_belt"
        assert loaded[1].transport["bridge"] == "robot_main"

    def test_load_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        """Несуществующий файл -> пустой список."""
        store = RegistryStore(tmp_path / "nonexistent.yaml")
        assert store.load() == []

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Пустой файл -> пустой список."""
        path = tmp_path / "devices.yaml"
        path.write_text("", encoding="utf-8")
        store = RegistryStore(path)
        assert store.load() == []

    def test_load_empty_devices_list(self, tmp_path: Path) -> None:
        """Файл с пустым devices -> пустой список."""
        path = tmp_path / "devices.yaml"
        path.write_text("version: 1\ndevices: []\n", encoding="utf-8")
        store = RegistryStore(path)
        assert store.load() == []

    def test_unknown_version_raises(self, tmp_path: Path) -> None:
        """Незнакомая версия -> ошибка с подсказкой."""
        path = tmp_path / "devices.yaml"
        path.write_text("version: 99\ndevices: []\n", encoding="utf-8")
        store = RegistryStore(path)
        with pytest.raises(DeviceHubError, match="Незнакомая версия"):
            store.load()

    def test_corrupted_not_dict(self, tmp_path: Path) -> None:
        """Не dict в корне -> ошибка."""
        path = tmp_path / "devices.yaml"
        path.write_text("- item1\n- item2\n", encoding="utf-8")
        store = RegistryStore(path)
        with pytest.raises(DeviceHubError, match="повреждён"):
            store.load()

    def test_atomic_write_no_partial(self, tmp_path: Path) -> None:
        """При успешной записи файл полный и корректный."""
        store = RegistryStore(tmp_path / "devices.yaml")
        entries = [
            DeviceEntry(id="dev_1", name="Test", kind="robot"),
        ]
        store.save(entries)
        # Файл существует и парсится
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].id == "dev_1"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save создаёт родительские директории."""
        store = RegistryStore(tmp_path / "subdir" / "deep" / "devices.yaml")
        store.save([DeviceEntry(id="dev_1", name="Test", kind="robot")])
        assert store.path.exists()

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        """Повторный save перезаписывает файл."""
        store = RegistryStore(tmp_path / "devices.yaml")
        store.save([DeviceEntry(id="dev_1", name="Old", kind="robot")])
        store.save([DeviceEntry(id="dev_2", name="New", kind="vfd")])
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].id == "dev_2"
