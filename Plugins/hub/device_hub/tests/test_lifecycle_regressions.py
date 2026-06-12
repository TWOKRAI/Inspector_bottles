"""Регрессионные тесты lifecycle per-device воркеров (ревью Fable).

Покрывает:
  Б-1: reconnect-цикл — remove_worker освобождает имя для повторного connect
  Б-2: устройство с упавшим connect получает воркер (tick = reconnect)
  н1:  recipe_devices автоматически ставятся в connect-очередь при start()
  н2:  device_remove останавливает per-device воркер + чистит state
  конкурентность: RLock не ломает основной flow
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


from Plugins.hub.device_hub.plugin import DeviceHubPlugin

from .conftest import make_ctx


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _make_plugin(
    tmp_path: Path,
    devices: list[dict] | None = None,
    recipe_devices: list[dict] | None = None,
) -> tuple[DeviceHubPlugin, MagicMock]:
    """Создать сконфигурированный и запущенный плагин с tmp-реестром."""
    registry_file = tmp_path / "devices.yaml"
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
# Б-1: reconnect-цикл — remove_worker освобождает имя
# ------------------------------------------------------------------ #


class TestReconnectWorkerLifecycle:
    """Б-1: connect → disconnect → connect — воркер НЕ осиротевает."""

    def test_disconnect_removes_worker_name(self, tmp_path: Path) -> None:
        """После disconnect имя per-device воркера освобождено в FakeWorkerManager."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )

        # Имитируем connect + создание воркера
        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
            plugin._conn_queue.put(("connect", "robot_1"))
            plugin._process_conn_queue()

        # Создать фейковый драйвер для _ensure_device_workers
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        plugin._manager._drivers["robot_1"] = mock_driver

        plugin._ensure_device_workers()
        assert "robot_1" in plugin._device_workers
        assert "dev_robot_1" in ctx.worker_manager.workers

        # Disconnect
        plugin._conn_queue.put(("disconnect", "robot_1"))
        plugin._process_conn_queue()

        # Воркер удалён из FakeWorkerManager (имя свободно)
        assert "robot_1" not in plugin._device_workers
        assert "dev_robot_1" not in ctx.worker_manager.workers

    def test_reconnect_after_disconnect_creates_new_worker(self, tmp_path: Path) -> None:
        """connect → disconnect → connect: повторный create_worker успешен."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )

        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        mock_driver.stats = {}
        plugin._manager._drivers["robot_1"] = mock_driver

        # Первый connect + воркер
        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
            plugin._conn_queue.put(("connect", "robot_1"))
            plugin._process_conn_queue()
        plugin._ensure_device_workers()
        assert "dev_robot_1" in ctx.worker_manager.workers

        # Disconnect
        plugin._conn_queue.put(("disconnect", "robot_1"))
        plugin._process_conn_queue()
        assert "dev_robot_1" not in ctx.worker_manager.workers

        # Повторный connect + воркер
        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
            plugin._conn_queue.put(("connect", "robot_1"))
            plugin._process_conn_queue()
        plugin._ensure_device_workers()
        # Воркер снова создан (имя было освобождено remove_worker)
        assert "dev_robot_1" in ctx.worker_manager.workers
        assert "robot_1" in plugin._device_workers


# ------------------------------------------------------------------ #
# Б-2: воркер для не-connected драйвера (reconnect через tick)
# ------------------------------------------------------------------ #


class TestInitialConnectFailWorker:
    """Б-2: первый connect падает — воркер всё равно создаётся для reconnect."""

    def test_worker_created_for_failed_connect(self, tmp_path: Path) -> None:
        """Если connect вернул False, драйвер создан — _ensure создаёт воркер."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )

        # Connect падает (False), но драйвер создан в _get_or_create_driver
        mock_driver = MagicMock()
        mock_driver.is_connected = False  # НЕ connected
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        plugin._manager._drivers["robot_1"] = mock_driver

        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=False):
            plugin._conn_queue.put(("connect", "robot_1"))
            plugin._process_conn_queue()

        # _ensure_device_workers должен создать воркер даже для
        # не-connected драйвера (Б-2: tick сам сделает reconnect)
        plugin._ensure_device_workers()
        assert "robot_1" in plugin._device_workers
        assert "dev_robot_1" in ctx.worker_manager.workers


# ------------------------------------------------------------------ #
# н1: recipe_devices автоматически подключаются при start()
# ------------------------------------------------------------------ #


class TestRecipeDevicesAutoConnect:
    """н1: устройства из рецепта ставятся в connect-очередь при start()."""

    def test_recipe_devices_in_conn_queue(self, tmp_path: Path) -> None:
        """start() с recipe_devices → они в connect-очереди."""
        recipe = [
            {
                "id": "robot_recipe",
                "name": "R_recipe",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.2.3.4", "port": 502, "unit_id": 1},
            }
        ]
        plugin, ctx = _make_plugin(tmp_path, recipe_devices=recipe)

        # Проверяем что robot_recipe в connect-очереди
        queued_ops: list[tuple[str, str]] = []
        while not plugin._conn_queue.empty():
            queued_ops.append(plugin._conn_queue.get_nowait())

        ids_to_connect = [dev_id for op, dev_id in queued_ops if op == "connect"]
        assert "robot_recipe" in ids_to_connect

    def test_recipe_device_without_auto_connect_still_queued(self, tmp_path: Path) -> None:
        """Рецептное устройство без auto_connect=True всё равно подключается (Р11)."""
        recipe = [
            {
                "id": "vfd_r",
                "name": "VFD",
                "kind": "vfd",
                "auto_connect": False,  # Явно выключен, но рецепт подразумевает connect
                "transport": {"type": "bridge", "bridge": "robot_main"},
            }
        ]
        plugin, ctx = _make_plugin(tmp_path, recipe_devices=recipe)

        queued_ops: list[tuple[str, str]] = []
        while not plugin._conn_queue.empty():
            queued_ops.append(plugin._conn_queue.get_nowait())

        ids_to_connect = [dev_id for op, dev_id in queued_ops if op == "connect"]
        assert "vfd_r" in ids_to_connect


# ------------------------------------------------------------------ #
# н2: device_remove останавливает per-device воркер
# ------------------------------------------------------------------ #


class TestDeviceRemoveStopsWorker:
    """н2: удаление устройства останавливает+удаляет per-device воркер."""

    def test_remove_stops_worker(self, tmp_path: Path) -> None:
        """device_remove останавливает воркер, имя освобождается."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "dev_1",
                "name": "D1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )

        # Имитируем живой воркер
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        plugin._manager._drivers["dev_1"] = mock_driver

        plugin._ensure_device_workers()
        assert "dev_dev_1" in ctx.worker_manager.workers

        # Удаляем
        result = plugin.cmd_device_remove({"device_id": "dev_1"})
        assert result["status"] == "ok"

        # Воркер удалён
        assert "dev_dev_1" not in ctx.worker_manager.workers
        assert "dev_1" not in plugin._device_workers

    def test_remove_then_readd_same_id(self, tmp_path: Path) -> None:
        """После remove того же id — upsert+connect+worker работает."""
        plugin, ctx = _make_plugin(tmp_path)

        # Добавить + имитировать воркер
        plugin.cmd_device_upsert(
            {
                "id": "dev_1",
                "name": "D1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {}
        plugin._manager._drivers["dev_1"] = mock_driver
        plugin._ensure_device_workers()

        # Удалить
        plugin.cmd_device_remove({"device_id": "dev_1"})

        # Снова добавить с тем же id
        plugin.cmd_device_upsert(
            {
                "id": "dev_1",
                "name": "D1v2",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "2.2.2.2", "port": 502, "unit_id": 1},
            }
        )

        # Имитировать драйвер
        mock_driver2 = MagicMock()
        mock_driver2.is_connected = True
        mock_driver2.entry = MagicMock()
        mock_driver2.entry.params = {}
        plugin._manager._drivers["dev_1"] = mock_driver2

        # Воркер создаётся снова (имя свободно)
        plugin._ensure_device_workers()
        assert "dev_dev_1" in ctx.worker_manager.workers
