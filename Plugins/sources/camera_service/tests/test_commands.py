"""Тесты команд CameraServicePlugin: 14 команд, switch, passthrough."""

from __future__ import annotations

from unittest.mock import MagicMock


from Plugins.sources.camera_service.plugin import CameraServicePlugin


def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _configure_with_commands(plugin: CameraServicePlugin, ctx: MagicMock) -> dict:
    """configure() + авторегистрация команд → dict зарегистрированных команд."""
    plugin.configure(ctx)
    plugin._auto_register_commands(ctx)
    commands = {}
    for c in ctx.command_manager.register_command.call_args_list:
        name, handler = c[0]
        commands[name] = handler
    return commands


class TestStartStopCapture:
    """Тесты команд start_capture / stop_capture."""

    def test_start_stop_capture(self):
        """Команды start_capture и stop_capture работают."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})
        commands = _configure_with_commands(plugin, ctx)
        assert "start_capture" in commands
        assert "stop_capture" in commands

        # Запуск
        result = commands["start_capture"]({})
        assert result["status"] == "ok"
        assert plugin._is_capturing is True

        # Остановка
        result = commands["stop_capture"]({})
        assert result["status"] == "ok"
        assert plugin._is_capturing is False

        plugin.shutdown(ctx)


class TestSetCameraType:
    """Тесты команды set_camera_type."""

    def test_set_camera_type(self):
        """switch simulator → simulator (проверка механизма переключения)."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})
        commands = _configure_with_commands(plugin, ctx)

        # Запустить захват
        commands["start_capture"]({})
        assert plugin._is_capturing is True

        # Переключить тип (simulator → simulator, но через полный цикл)
        result = commands["set_camera_type"]({"camera_type": "simulator"})
        assert result["status"] == "ok"
        assert result["camera_type"] == "simulator"
        # После переключения захват должен продолжиться (был активен)
        assert plugin._is_capturing is True

        plugin.shutdown(ctx)

    def test_set_camera_type_invalid(self):
        """Неизвестный тип → error."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})
        commands = _configure_with_commands(plugin, ctx)
        result = commands["set_camera_type"]({"camera_type": "invalid_type"})
        assert result["status"] == "error"

        plugin.shutdown(ctx)


class TestSetFps:
    """Тесты команды set_fps."""

    def test_set_fps(self):
        """clamp 1-120."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})
        commands = _configure_with_commands(plugin, ctx)

        # Нормальное значение
        result = commands["set_fps"]({"fps": 30})
        assert result["fps"] == 30

        # Ниже минимума → 1
        result = commands["set_fps"]({"fps": 0})
        assert result["fps"] == 1

        # Выше максимума → 120
        result = commands["set_fps"]({"fps": 999})
        assert result["fps"] == 120

        plugin.shutdown(ctx)


class TestHikPassthrough:
    """Тесты hik_* passthrough команд."""

    def test_hik_passthrough_error(self):
        """hik_* при camera_type != 'hikvision' → error."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})
        commands = _configure_with_commands(plugin, ctx)

        # Все hik_* команды должны вернуть ошибку для не-hikvision backend
        hik_commands = [
            "hik_open",
            "hik_close",
            "hik_start_grabbing",
            "hik_stop_grabbing",
            "hik_get_parameters",
            "hik_set_parameters",
        ]

        for cmd_name in hik_commands:
            assert cmd_name in commands, f"Команда {cmd_name} не зарегистрирована"
            result = commands[cmd_name]({})
            assert result["status"] == "error", f"Команда {cmd_name} должна вернуть error для simulator backend"

        plugin.shutdown(ctx)


class TestAllCommandsRegistered:
    """Проверка что все команды зарегистрированы (14 базовых + 4 live-параметра)."""

    def test_all_commands_registered(self):
        """Все 18 команд зарегистрированы в command_manager."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})
        commands = _configure_with_commands(plugin, ctx)

        expected = {
            "start_capture",
            "stop_capture",
            "set_camera_type",
            "set_fps",
            "set_resolution",
            "set_device_id",
            "set_camera_index",
            "enum_devices",
            "hik_open",
            "hik_close",
            "hik_start_grabbing",
            "hik_stop_grabbing",
            "hik_get_parameters",
            "hik_set_parameters",
            # Phase 2 — live-управление параметрами
            "set_config",
            "set_param",
            "set_mjpg",
            "get_actual",
        }

        assert set(commands.keys()) == expected, (
            f"Ожидалось {len(expected)} команд, получено {len(commands)}: "
            f"лишние={set(commands.keys()) - expected}, "
            f"отсутствуют={expected - set(commands.keys())}"
        )

        plugin.shutdown(ctx)


class _FakeWebcamBackend:
    """Фейк webcam-backend для тестов live-параметров (без cv2)."""

    def __init__(self) -> None:
        self.params: dict = {}
        self.fps: int | None = None
        self.mjpg: bool | None = None

    def set_param(self, name: str, value) -> bool:
        self.params[name] = value
        return True

    def set_fps(self, fps: int) -> bool:
        self.fps = int(fps)
        return True

    def set_mjpg(self, on: bool) -> bool:
        self.mjpg = bool(on)
        return True

    def get_actual(self, names=None) -> dict:
        return {"width": 1280, "height": 720, "fps": 30, "gain": 50}


class TestLiveParams:
    """Phase 2: live-управление параметрами через команды."""

    def _plugin_with_fake_webcam(self):
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "webcam"})
        commands = _configure_with_commands(plugin, ctx)
        plugin._camera_type = "webcam"
        plugin._backend = _FakeWebcamBackend()
        return plugin, ctx, commands

    def test_set_param_applies_to_backend(self):
        plugin, ctx, commands = self._plugin_with_fake_webcam()
        result = commands["set_param"]({"name": "gain", "value": 100})
        assert result["status"] == "ok"
        assert plugin._backend.params["gain"] == 100
        assert plugin._params["gain"] == 100  # desired сохранён

    def test_set_config_updates_register_and_backend(self):
        plugin, ctx, commands = self._plugin_with_fake_webcam()
        commands["set_config"]({"exposure": -4, "fps": 30})
        assert plugin._reg.exposure == -4
        assert plugin._reg.fps == 30
        assert plugin._backend.params["exposure"] == -4
        assert plugin._backend.fps == 30

    def test_set_mjpg(self):
        plugin, ctx, commands = self._plugin_with_fake_webcam()
        commands["set_mjpg"]({"on": True})
        assert plugin._backend.mjpg is True
        assert plugin._reg.mjpg is True

    def test_get_actual(self):
        plugin, ctx, commands = self._plugin_with_fake_webcam()
        result = commands["get_actual"]({})
        assert result["status"] == "ok"
        assert result["actual"]["width"] == 1280

    def test_param_remembered_when_no_backend(self):
        """Без открытого webcam — desired запоминается, применится при open."""
        plugin = CameraServicePlugin()
        ctx = _make_mock_ctx({"camera_type": "simulator"})
        commands = _configure_with_commands(plugin, ctx)
        commands["set_param"]({"name": "gain", "value": 77})
        assert plugin._params["gain"] == 77

    def test_publish_actual_merges_state(self):
        plugin, ctx, commands = self._plugin_with_fake_webcam()
        plugin._state_proxy = MagicMock()
        plugin._ctx.process_name = "camera_0"
        plugin._publish_actual()
        plugin._state_proxy.merge.assert_called_once()
        path, data = plugin._state_proxy.merge.call_args[0]
        assert path == "processes.camera_0.state.cam.actual"
        assert data["width"] == 1280
