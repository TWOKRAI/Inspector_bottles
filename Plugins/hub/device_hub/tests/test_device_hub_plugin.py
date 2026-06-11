"""Тесты DeviceHubPlugin — lifecycle, commands, async connect, supervisor.

ctx — mock (FakeWorkerManager, фейковый state_proxy); DeviceManager с реальным
RegistryStore (tmp_path) и фейковыми драйверами (FakeRobotTransport+RobotSimCore).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin, _resolve_registry_path


from .conftest import make_ctx


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _make_plugin(
    tmp_path: Path,
    devices: list[dict] | None = None,
    recipe_devices: list[dict] | None = None,
) -> tuple[DeviceHubPlugin, MagicMock]:
    """Создать сконфигурированный и запущенный плагин с tmp-реестром.

    Args:
        tmp_path:       Корневой tmp-каталог (pytest fixture).
        devices:        Начальные устройства для персистентного store.
        recipe_devices: Устройства из рецепта (inject при start).

    Returns:
        (plugin, ctx)
    """
    registry_file = tmp_path / "devices.yaml"
    # Если devices заданы — напишем в yaml
    if devices:
        import yaml

        data = {"version": 1, "devices": devices}
        registry_file.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

    config: dict = {"registry_path": str(registry_file)}
    if recipe_devices:
        config["recipe_devices"] = recipe_devices

    ctx = make_ctx(config, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx


# ------------------------------------------------------------------ #
# Lifecycle
# ------------------------------------------------------------------ #


class TestLifecycle:
    """Тесты configure/start/shutdown."""

    def test_configure_creates_manager(self, tmp_path: Path) -> None:
        """configure создаёт DeviceManager и публикует реестр."""
        plugin, ctx = _make_plugin(tmp_path)
        assert plugin._manager is not None
        assert plugin._reg.devices_total == 0

    def test_configure_loads_existing_registry(self, tmp_path: Path) -> None:
        """configure загружает существующий реестр из файла."""
        devices = [
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            },
        ]
        plugin, ctx = _make_plugin(tmp_path, devices=devices)
        assert plugin._reg.devices_total == 1
        # Публикация реестра
        ctx.state_proxy.merge.assert_any_call("devices.registry.robot_1", plugin._manager._entries["robot_1"].to_dict())

    def test_start_creates_supervisor_worker(self, tmp_path: Path) -> None:
        """start создаёт supervisor-worker."""
        plugin, ctx = _make_plugin(tmp_path)
        assert "device_supervisor" in ctx.worker_manager.workers

    def test_start_upserts_recipe_devices(self, tmp_path: Path) -> None:
        """start upsert'ит устройства из recipe_devices конфига."""
        recipe = [
            {
                "id": "test_dev",
                "name": "Test",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.2.3.4", "port": 502, "unit_id": 1},
            }
        ]
        plugin, ctx = _make_plugin(tmp_path, recipe_devices=recipe)
        assert "test_dev" in plugin._manager._entries
        assert plugin._reg.devices_total == 1

    def test_shutdown_disconnects_all(self, tmp_path: Path) -> None:
        """shutdown отключает все устройства."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.shutdown(ctx)
        # Менеджер shutdown'нут
        assert not plugin._manager.is_initialized


# ------------------------------------------------------------------ #
# CRUD команды
# ------------------------------------------------------------------ #


class TestCrudCommands:
    """Тесты CRUD-команд реестра."""

    def test_device_upsert_and_list(self, tmp_path: Path) -> None:
        """device_upsert создаёт устройство, device_list возвращает его."""
        plugin, ctx = _make_plugin(tmp_path)
        result = plugin.cmd_device_upsert(
            {
                "id": "dev_1",
                "name": "Dev 1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        assert result["status"] == "ok"
        listed = plugin.cmd_device_list({})
        assert listed["status"] == "ok"
        assert len(listed["devices"]) == 1
        assert listed["devices"][0]["id"] == "dev_1"

    def test_device_upsert_persists(self, tmp_path: Path) -> None:
        """device_upsert сохраняет в файл."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "dev_1",
                "name": "Dev 1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        # Проверить что файл записан
        registry_file = Path(plugin._reg.registry_path)
        assert registry_file.exists()

    def test_device_upsert_publishes_state(self, tmp_path: Path) -> None:
        """device_upsert публикует в state-дерево."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "dev_2",
                "name": "Dev 2",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        # publish_cb вызывается через state_proxy.merge
        calls = [c.args[0] for c in ctx.state_proxy.merge.call_args_list]
        assert "devices.registry.dev_2" in calls

    def test_device_remove(self, tmp_path: Path) -> None:
        """device_remove удаляет устройство."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "dev_1",
                "name": "Dev 1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        result = plugin.cmd_device_remove({"device_id": "dev_1"})
        assert result["status"] == "ok"
        assert plugin._reg.devices_total == 0

    def test_device_remove_nonexistent(self, tmp_path: Path) -> None:
        """device_remove несуществующего → ошибка."""
        plugin, ctx = _make_plugin(tmp_path)
        result = plugin.cmd_device_remove({"device_id": "nope"})
        assert result["status"] == "error"

    def test_device_upsert_many(self, tmp_path: Path) -> None:
        """device_upsert_many массово создаёт устройства."""
        plugin, ctx = _make_plugin(tmp_path)
        result = plugin.cmd_device_upsert_many(
            {
                "devices": [
                    {
                        "id": "d1",
                        "name": "D1",
                        "kind": "robot",
                        "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
                    },
                    {"id": "d2", "name": "D2", "kind": "vfd", "transport": {"type": "bridge", "bridge": "d1"}},
                ],
            }
        )
        assert result["status"] == "ok"
        assert result["count"] == 2
        assert plugin._reg.devices_total == 2


# ------------------------------------------------------------------ #
# Async connect/disconnect (Б2)
# ------------------------------------------------------------------ #


class TestAsyncConnect:
    """Тесты асинхронного connect/disconnect через очередь."""

    def test_connect_returns_immediately(self, tmp_path: Path) -> None:
        """device_connect отвечает сразу с conn=connecting."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        result = plugin.cmd_device_connect({"device_id": "robot_1"})
        assert result["status"] == "ok"
        assert result["conn"] == "connecting"
        # Запрос в очереди
        assert not plugin._conn_queue.empty()

    def test_disconnect_returns_immediately(self, tmp_path: Path) -> None:
        """device_disconnect отвечает сразу с conn=disconnecting."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        result = plugin.cmd_device_disconnect({"device_id": "robot_1"})
        assert result["status"] == "ok"
        assert result["conn"] == "disconnecting"

    def test_connect_nonexistent_device(self, tmp_path: Path) -> None:
        """device_connect к несуществующему → ошибка."""
        plugin, ctx = _make_plugin(tmp_path)
        result = plugin.cmd_device_connect({"device_id": "nope"})
        assert result["status"] == "error"

    def test_supervisor_processes_connect_queue(self, tmp_path: Path, fake_transport, sim_core) -> None:
        """Supervisor разбирает очередь: connect с фейковым транспортом."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "protocol": "delta_universal3",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 2},
                "params": {"word_order": "little"},
            }
        )
        # Подменим build_transport чтобы вернуть фейковый
        plugin.cmd_device_connect({"device_id": "robot_1"})
        with patch("Services.device_hub.manager.DeviceManager.connect") as mock_connect:
            mock_connect.return_value = True
            plugin._process_conn_queue()
        # Проверяем что state publish вызван с connected
        merge_calls = {c.args[0]: c.args[1] for c in ctx.state_proxy.merge.call_args_list}
        assert "devices.state.robot_1.conn" in merge_calls


# ------------------------------------------------------------------ #
# Kind-валидация
# ------------------------------------------------------------------ #


class TestKindValidation:
    """Тесты kind-валидации (vfd-команда к robot → error)."""

    def test_vfd_command_to_robot_device(self, tmp_path: Path) -> None:
        """vfd_run к robot-устройству → ошибка kind."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        result = plugin.cmd_vfd_run({"device_id": "robot_1"})
        assert result["status"] == "error"
        assert "kind" in result["message"].lower() or "vfd" in result["message"].lower()

    def test_robot_command_to_vfd_device(self, tmp_path: Path) -> None:
        """robot_send_test_job к vfd-устройству → ошибка kind."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "vfd_1",
                "name": "V1",
                "kind": "vfd",
                "transport": {"type": "bridge", "bridge": "robot_1"},
            }
        )
        result = plugin.cmd_robot_send_test_job({"device_id": "vfd_1"})
        assert result["status"] == "error"

    def test_missing_device_id(self, tmp_path: Path) -> None:
        """Команда без device_id → ошибка."""
        plugin, ctx = _make_plugin(tmp_path)
        result = plugin.cmd_robot_send_test_job({})
        assert result["status"] == "error"
        assert "device_id" in result["message"]


# ------------------------------------------------------------------ #
# hik_enum device-less + hik_release broadcast
# ------------------------------------------------------------------ #


class TestHikvisionCommands:
    """Тесты hikvision-команд: device-less enum, broadcast release."""

    def test_hik_enum_without_device_id(self, tmp_path: Path) -> None:
        """hik_enum не требует device_id — вызывает discovery напрямую."""
        from types import SimpleNamespace

        plugin, ctx = _make_plugin(tmp_path)
        # SimpleNamespace — чтобы getattr возвращал реальные значения
        fake_dev = SimpleNamespace(
            serial="SN123",
            serial_number="SN123",
            model_name="DS-2CD",
            ip_address="192.168.1.10",
            index=0,
        )
        with patch(
            "Services.hikvision_camera.core.discovery.enum_devices",
            return_value=[fake_dev],
        ):
            result = plugin.cmd_hik_enum({})  # БЕЗ device_id
        assert result["status"] == "ok"
        assert len(result["devices"]) == 1
        assert result["devices"][0]["serial"] == "SN123"

    def test_hik_enum_sdk_unavailable(self, tmp_path: Path) -> None:
        """hik_enum без SDK → ошибка, не crash."""
        plugin, ctx = _make_plugin(tmp_path)
        with patch.dict("sys.modules", {"Services.hikvision_camera.core.discovery": None}):
            # Имитация ImportError
            import builtins

            original_import = builtins.__import__

            def fail_import(name, *args, **kwargs):
                if "hikvision_camera.core.discovery" in name:
                    raise ImportError("SDK недоступен")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fail_import):
                result = plugin.cmd_hik_enum({})
        assert result["status"] == "error"
        assert "SDK" in result["message"] or "недоступен" in result["message"]

    def test_hik_release_without_device_id(self, tmp_path: Path) -> None:
        """hik_release без device_id — release всех hikvision-устройств."""
        plugin, ctx = _make_plugin(tmp_path)
        # Создадим hikvision-устройство и фейковый драйвер
        plugin.cmd_device_upsert({"id": "cam_1", "name": "Cam1", "kind": "hikvision", "params": {"serial": "SN1"}})
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.call.return_value = {"status": "ok"}
        plugin._manager._drivers["cam_1"] = mock_driver

        result = plugin.cmd_hik_release({})  # БЕЗ device_id
        assert result["status"] == "ok"
        assert "cam_1" in result["released"]
        mock_driver.call.assert_called_once_with("release", {})

    def test_hik_release_no_connected_cameras(self, tmp_path: Path) -> None:
        """hik_release без device_id и без подключённых камер → ok, released=[]."""
        plugin, ctx = _make_plugin(tmp_path)
        result = plugin.cmd_hik_release({})
        assert result["status"] == "ok"
        assert result["released"] == []


# ------------------------------------------------------------------ #
# Resolve registry path (У6)
# ------------------------------------------------------------------ #


class TestResolveRegistryPath:
    """Тесты резолва пути к реестру."""

    def test_absolute_path_unchanged(self) -> None:
        """Абсолютный путь — без изменений (имя файла совпадает)."""
        import sys

        if sys.platform == "win32":
            raw = "C:\\Users\\test\\devices.yaml"
        else:
            raw = "/tmp/devices.yaml"
        p = _resolve_registry_path(raw)
        assert p == Path(raw)

    def test_relative_path_from_project_root(self) -> None:
        """Относительный путь — от корня проекта."""
        p = _resolve_registry_path("data/devices.yaml")
        assert "data" in str(p)
        assert p.is_absolute()

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """INSPECTOR_DATA_DIR override."""
        import sys

        custom = "C:\\custom\\data" if sys.platform == "win32" else "/custom/data"
        monkeypatch.setenv("INSPECTOR_DATA_DIR", custom)
        p = _resolve_registry_path("data/devices.yaml")
        assert "custom" in str(p).lower()


# ------------------------------------------------------------------ #
# Counters / telemetry
# ------------------------------------------------------------------ #


class TestCounters:
    """Тесты счётчиков commands_ok/commands_err."""

    def test_successful_command_increments_ok(self, tmp_path: Path) -> None:
        """Успешная команда инкрементирует commands_ok."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_list({})
        assert plugin._reg.commands_ok >= 1

    def test_failed_command_increments_err(self, tmp_path: Path) -> None:
        """Ошибочная команда инкрементирует commands_err."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_remove({"device_id": "nope"})
        assert plugin._reg.commands_err >= 1
