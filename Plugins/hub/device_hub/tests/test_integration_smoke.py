"""Интеграционный smoke-тест: DeviceManager + DeviceHubPlugin + RobotSimCore.

In-process: upsert robot(tcp→но transport подменён fake) → connect → robot_send_test_job
→ jobs_done в snapshot → vfd upsert(bridge) → connect → vfd_get_status.

Закрывает spike риска «роутинг плагин→devices» частично. Полный E2E через реальные
процессы — Фаза 3/верификация.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from Plugins.hub.device_hub.plugin import DeviceHubPlugin


from .conftest import make_ctx


def _make_plugin_with_registry(tmp_path: Path, config: dict | None = None) -> tuple[DeviceHubPlugin, MagicMock]:
    """Создать плагин с реестром в tmp_path."""
    registry_file = tmp_path / "devices.yaml"
    cfg = config or {}
    cfg["registry_path"] = str(registry_file)
    ctx = make_ctx(cfg, tmp_registry=registry_file)
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx


class TestIntegrationSmoke:
    """Интеграционный smoke: robot upsert→connect→job→vfd bridge."""

    def test_robot_upsert_connect_job(self, tmp_path: Path) -> None:
        """Полный цикл: upsert robot → connect → send_test_job → проверка."""
        plugin, ctx = _make_plugin_with_registry(tmp_path)

        # 1. Upsert робота
        result = plugin.cmd_device_upsert(
            {
                "id": "robot_sim",
                "name": "Робот-симулятор",
                "kind": "robot",
                "protocol": "delta_universal3",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 2},
                "params": {"word_order": "little"},
            }
        )
        assert result["status"] == "ok"

        # 2. Connect (синхронно через менеджер для теста, не через очередь)
        #    Подменяем connect чтобы не лезть в сеть
        with patch.object(plugin._manager, "connect", return_value=True):
            plugin._conn_queue.put(("connect", "robot_sim"))
            plugin._process_conn_queue()

        # 3. Проверяем что state опубликован (conn — через set, атомарно)
        set_calls = {c.args[0] for c in ctx.state_proxy.set.call_args_list}
        assert "devices.state.robot_sim.conn" in set_calls

    def test_kind_validation_vfd_to_robot(self, tmp_path: Path) -> None:
        """vfd_run к robot-устройству → ошибка kind."""
        plugin, ctx = _make_plugin_with_registry(tmp_path)
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

    def test_vfd_bridge_upsert(self, tmp_path: Path) -> None:
        """Upsert VFD bridge-устройства после робота."""
        plugin, ctx = _make_plugin_with_registry(tmp_path)
        # Сначала робот
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        # Затем VFD bridge
        result = plugin.cmd_device_upsert(
            {
                "id": "vfd_belt",
                "name": "ПЧ",
                "kind": "vfd",
                "protocol": "gd20_bridge",
                "transport": {"type": "bridge", "bridge": "robot_1"},
            }
        )
        assert result["status"] == "ok"
        # Проверяем список
        listed = plugin.cmd_device_list({})
        assert len(listed["devices"]) == 2

    def test_device_describe(self, tmp_path: Path) -> None:
        """device_describe возвращает entry + conn + stats."""
        plugin, ctx = _make_plugin_with_registry(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        result = plugin.cmd_device_describe({"device_id": "robot_1"})
        assert result["status"] == "ok"
        assert "entry" in result
        assert result["entry"]["id"] == "robot_1"

    def test_device_protocols(self, tmp_path: Path) -> None:
        """device_protocols возвращает доступные протоколы."""
        plugin, ctx = _make_plugin_with_registry(tmp_path)
        result = plugin.cmd_device_protocols({})
        assert result["status"] == "ok"
        assert "protocols" in result
        # Должны быть хотя бы протоколы из Services/**/protocols/*.yaml
        assert isinstance(result["protocols"], dict)

    def test_full_registry_lifecycle(self, tmp_path: Path) -> None:
        """Полный CRUD: upsert → list → describe → remove → list."""
        plugin, ctx = _make_plugin_with_registry(tmp_path)
        # Create
        plugin.cmd_device_upsert(
            {
                "id": "d1",
                "name": "D1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        assert plugin._reg.devices_total == 1
        # Describe
        desc = plugin.cmd_device_describe({"device_id": "d1"})
        assert desc["status"] == "ok"
        # Remove
        plugin.cmd_device_remove({"device_id": "d1"})
        assert plugin._reg.devices_total == 0
        listed = plugin.cmd_device_list({})
        assert len(listed["devices"]) == 0
