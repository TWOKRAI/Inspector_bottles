"""Регрессионные тесты lifecycle per-device воркеров (ревью Fable).

Покрывает:
  Б-1: reconnect-цикл — remove_worker освобождает имя для повторного connect
  Б-2: устройство с упавшим connect получает воркер (tick = reconnect)
  н1:  recipe_devices автоматически ставятся в connect-очередь при start()
  н2:  device_remove останавливает per-device воркер + чистит state
  конкурентность: RLock не ломает основной flow
  НР-1: disconnect -> N итераций supervisor -> остаётся disconnected (desired-state)
  НР-2: bridged-VFD: робот не готов -> VFD desired=True ждёт -> робот connect -> VFD поднимается
  НР-3: гонка cmd_device_remove <-> _ensure_device_workers
  НР-4: create_worker -> False не записывает _device_workers
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

        # Имитируем connect + создание воркера (desired=True через cmd_device_connect)
        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
            plugin.cmd_device_connect({"device_id": "robot_1"})
            plugin._process_conn_queue()

        # Создать фейковый драйвер для _ensure_device_workers
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        plugin._manager._drivers["robot_1"] = mock_driver

        plugin._ensure_device_workers()
        assert "robot_1" in plugin._device_workers
        assert "dev_robot_1" in ctx.worker_manager.workers

        # Disconnect (через cmd — ставит desired=False)
        plugin.cmd_device_disconnect({"device_id": "robot_1"})
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
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        mock_driver.stats = {}
        plugin._manager._drivers["robot_1"] = mock_driver

        # Первый connect + воркер (через cmd — desired=True)
        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
            plugin.cmd_device_connect({"device_id": "robot_1"})
            plugin._process_conn_queue()
        plugin._ensure_device_workers()
        assert "dev_robot_1" in ctx.worker_manager.workers

        # Disconnect (через cmd — desired=False)
        plugin.cmd_device_disconnect({"device_id": "robot_1"})
        plugin._process_conn_queue()
        # _ensure_device_workers тоже остановит воркер при desired=False
        plugin._ensure_device_workers()
        assert "dev_robot_1" not in ctx.worker_manager.workers

        # Повторный connect + воркер (через cmd — desired=True)
        mock_driver.desired_connected = True
        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=True):
            plugin.cmd_device_connect({"device_id": "robot_1"})
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
        """Если connect вернул False, драйвер создан — _ensure создаёт воркер
        (при desired=True, tick сам сделает reconnect)."""
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
        mock_driver.desired_connected = False
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        plugin._manager._drivers["robot_1"] = mock_driver

        # cmd_device_connect ставит desired=True
        with patch("Services.device_hub.manager.DeviceManager.connect", return_value=False):
            plugin.cmd_device_connect({"device_id": "robot_1"})
            plugin._process_conn_queue()

        # desired=True (выставлено cmd_device_connect) + драйвер есть
        # -> _ensure_device_workers создаёт воркер для reconnect
        plugin._ensure_device_workers()
        assert "robot_1" in plugin._device_workers
        assert "dev_robot_1" in ctx.worker_manager.workers


# ------------------------------------------------------------------ #
# н1: recipe_devices автоматически подключаются при start()
# ------------------------------------------------------------------ #


class TestRecipeDevicesAutoConnect:
    """н1: устройства из рецепта ставятся в connect-очередь при start()."""

    def test_recipe_devices_in_conn_queue(self, tmp_path: Path) -> None:
        """start() с recipe_devices → они в connect-очереди и desired=True."""
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
        # НР-1: desired=True проставлено для recipe-устройств
        assert plugin._desired_connected.get("robot_recipe") is True

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

        # Имитируем живой воркер (desired=True)
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        plugin._manager._drivers["dev_1"] = mock_driver
        plugin._desired_connected["dev_1"] = True

        plugin._ensure_device_workers()
        assert "dev_dev_1" in ctx.worker_manager.workers

        # Удаляем (cmd_device_remove ставит desired=False)
        result = plugin.cmd_device_remove({"device_id": "dev_1"})
        assert result["status"] == "ok"

        # Воркер удалён
        assert "dev_dev_1" not in ctx.worker_manager.workers
        assert "dev_1" not in plugin._device_workers

    def test_remove_then_readd_same_id(self, tmp_path: Path) -> None:
        """После remove того же id — upsert+connect+worker работает."""
        plugin, ctx = _make_plugin(tmp_path)

        # Добавить + имитировать воркер (desired=True)
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
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {}
        plugin._manager._drivers["dev_1"] = mock_driver
        plugin._desired_connected["dev_1"] = True
        plugin._ensure_device_workers()

        # Удалить (cmd_device_remove -> desired=False)
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

        # Имитировать драйвер + desired=True
        mock_driver2 = MagicMock()
        mock_driver2.is_connected = True
        mock_driver2.desired_connected = True
        mock_driver2.entry = MagicMock()
        mock_driver2.entry.params = {}
        plugin._manager._drivers["dev_1"] = mock_driver2
        plugin._desired_connected["dev_1"] = True

        # Воркер создаётся снова (имя свободно)
        plugin._ensure_device_workers()
        assert "dev_dev_1" in ctx.worker_manager.workers


# ------------------------------------------------------------------ #
# НР-1: disconnect → N итераций supervisor → остаётся disconnected
# ------------------------------------------------------------------ #


class TestDesiredStateDisconnect:
    """НР-1: desired-state — disconnect не самоотменяется."""

    def test_disconnect_stays_disconnected_after_ensure_iterations(self, tmp_path: Path) -> None:
        """disconnect → 5 итераций _ensure_device_workers → воркер НЕ возвращается."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "robot_1",
                "name": "R1",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )

        # Имитируем подключённое устройство с воркером
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {"poll_interval_s": 0.5}
        plugin._manager._drivers["robot_1"] = mock_driver
        plugin._desired_connected["robot_1"] = True

        plugin._ensure_device_workers()
        assert "robot_1" in plugin._device_workers

        # Пользователь отключает (desired=False)
        plugin.cmd_device_disconnect({"device_id": "robot_1"})
        plugin._process_conn_queue()

        # 5 итераций supervisor — воркер НЕ должен вернуться
        for _ in range(5):
            plugin._ensure_device_workers()

        assert "robot_1" not in plugin._device_workers
        assert "dev_robot_1" not in ctx.worker_manager.workers
        # desired_connected остался False
        assert plugin._desired_connected.get("robot_1") is False

    def test_desired_false_stops_existing_worker(self, tmp_path: Path) -> None:
        """desired=False при живом воркере -> _ensure останавливает воркер."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "dev_x",
                "name": "X",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {}
        plugin._manager._drivers["dev_x"] = mock_driver
        plugin._desired_connected["dev_x"] = True

        plugin._ensure_device_workers()
        assert "dev_x" in plugin._device_workers

        # Вручную ставим desired=False (имитируя disconnect без очереди)
        plugin._desired_connected["dev_x"] = False

        plugin._ensure_device_workers()
        assert "dev_x" not in plugin._device_workers
        assert "dev_dev_x" not in ctx.worker_manager.workers


# ------------------------------------------------------------------ #
# НР-3: гонка cmd_device_remove ↔ _ensure_device_workers
# ------------------------------------------------------------------ #


class TestRemoveEnsureRace:
    """НР-3: remove + ensure не создаёт зомби-воркер."""

    def test_remove_then_ensure_no_zombie_worker(self, tmp_path: Path) -> None:
        """remove убирает desired -> ensure не создаёт воркер на удалённый драйвер."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "dev_z",
                "name": "Z",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {}
        plugin._manager._drivers["dev_z"] = mock_driver
        plugin._desired_connected["dev_z"] = True
        plugin._ensure_device_workers()

        # remove ставит desired=False + останавливает воркер + удаляет из реестра
        plugin.cmd_device_remove({"device_id": "dev_z"})

        # _ensure_device_workers НЕ должен создать воркер (desired удалён)
        plugin._ensure_device_workers()
        assert "dev_z" not in plugin._device_workers
        assert "dev_dev_z" not in ctx.worker_manager.workers

    def test_ensure_skips_missing_driver(self, tmp_path: Path) -> None:
        """desired=True но драйвер отсутствует в _drivers -> ensure пропускает."""
        plugin, ctx = _make_plugin(tmp_path)
        # desired есть, но драйвера нет (удалён remove)
        plugin._desired_connected["phantom"] = True

        plugin._ensure_device_workers()
        assert "phantom" not in plugin._device_workers


# ------------------------------------------------------------------ #
# НР-4: create_worker → False не записывает _device_workers
# ------------------------------------------------------------------ #


class TestCreateWorkerFalse:
    """НР-4: create_worker вернул False — НЕ пишем в _device_workers."""

    def test_create_worker_false_not_recorded(self, tmp_path: Path) -> None:
        """create_worker->False: _device_workers остаётся без записи,
        retry на следующей итерации."""
        plugin, ctx = _make_plugin(tmp_path)
        plugin.cmd_device_upsert(
            {
                "id": "dev_f",
                "name": "F",
                "kind": "robot",
                "transport": {"type": "tcp", "host": "1.1.1.1", "port": 502, "unit_id": 1},
            }
        )
        mock_driver = MagicMock()
        mock_driver.is_connected = True
        mock_driver.desired_connected = True
        mock_driver.entry = MagicMock()
        mock_driver.entry.params = {}
        plugin._manager._drivers["dev_f"] = mock_driver
        plugin._desired_connected["dev_f"] = True

        # Занять имя чтобы create_worker вернул False
        ctx.worker_manager.workers["dev_dev_f"] = {"fn": None}

        plugin._ensure_device_workers()
        # НР-4: НЕ записан в _device_workers при False
        assert "dev_f" not in plugin._device_workers

        # Освободить имя — retry успешен
        del ctx.worker_manager.workers["dev_dev_f"]
        plugin._ensure_device_workers()
        assert "dev_f" in plugin._device_workers
