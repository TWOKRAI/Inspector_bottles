"""Тесты команд CameraServicePlugin: 14 команд, switch, passthrough."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from multiprocess_prototype_2.plugins.camera_service.plugin import CameraServicePlugin


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
            assert result["status"] == "error", (
                f"Команда {cmd_name} должна вернуть error для simulator backend"
            )

        plugin.shutdown(ctx)


class TestAllCommandsRegistered:
    """Проверка что все 14 команд зарегистрированы."""

    def test_all_14_commands_registered(self):
        """Все 14 команд зарегистрированы в command_manager."""
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
        }

        assert set(commands.keys()) == expected, (
            f"Ожидалось 14 команд, получено {len(commands)}: "
            f"лишние={set(commands.keys()) - expected}, "
            f"отсутствуют={expected - set(commands.keys())}"
        )

        plugin.shutdown(ctx)
