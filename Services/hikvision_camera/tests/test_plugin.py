"""Тесты плагина HikvisionCameraPlugin.

Все тесты работают без реального SDK и без запуска multiprocess_framework.
HikvisionCamera и FrameConverter мокируются через patch.
"""
from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_ctx(config: dict | None = None) -> MagicMock:
    """Создать минимальный mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.registers = None          # без managed registers → fallback к defaults
    return ctx


def _make_plugin_configured(config: dict | None = None):
    """Создать и настроить HikvisionCameraPlugin с mock камерой.

    Returns:
        tuple(plugin, mock_camera) — плагин после configure() и mock HikvisionCamera.
    """
    from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin

    plugin = HikvisionCameraPlugin()
    ctx = _make_ctx(config)
    mock_cam = MagicMock()

    with patch(
        "hikvision_camera_module_2.plugin.plugin.HikvisionCamera",
        return_value=mock_cam,
    ):
        plugin.configure(ctx)

    return plugin, mock_cam


# ===========================================================================
# TestHikvisionCameraConfig
# ===========================================================================


class TestHikvisionCameraConfig:
    """Тесты конфигурации плагина."""

    def test_default_values(self):
        """Дефолтные значения конфига: camera_id=0, resolution=1920x1080, fps=25, auto_start=False."""
        from hikvision_camera_module_2.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig()
        assert cfg.camera_id == 0
        assert cfg.camera_index == 0
        assert cfg.resolution_width == 1920
        assert cfg.resolution_height == 1080
        assert cfg.fps == 25
        assert cfg.auto_start is False

    def test_memory_property(self):
        """memory возвращает dict с правильным slot_name и shape для camera_id=0."""
        from hikvision_camera_module_2.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig()
        mem = cfg.memory
        assert mem is not None
        # Ключ слота: hikvision_0_frame
        assert "hikvision_0_frame" in mem
        # Размерность: (height, width, 3)
        assert mem["hikvision_0_frame"] == (1080, 1920, 3)

    def test_memory_custom_camera_id(self):
        """SHM slot_name учитывает camera_id: camera_id=3 → hikvision_3_frame."""
        from hikvision_camera_module_2.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig(camera_id=3)
        mem = cfg.memory
        assert "hikvision_3_frame" in mem
        # Старый ключ не должен присутствовать
        assert "hikvision_0_frame" not in mem

    def test_memory_ring_buffer_size(self):
        """memory['coll'] равен ring_buffer_size."""
        from hikvision_camera_module_2.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig(ring_buffer_size=5)
        assert cfg.memory["coll"] == 5

    def test_plugin_class_path(self):
        """plugin_class указывает на правильный класс."""
        from hikvision_camera_module_2.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig()
        assert cfg.plugin_class == (
            "hikvision_camera_module_2.plugin.plugin.HikvisionCameraPlugin"
        )


# ===========================================================================
# TestHikvisionCameraRegisters
# ===========================================================================


class TestHikvisionCameraRegisters:
    """Тесты runtime-параметров."""

    def test_default_values(self):
        """Дефолтные значения: exposure_time=10000, gain=0, frame_rate=25."""
        from hikvision_camera_module_2.plugin.registers import HikvisionCameraRegisters

        reg = HikvisionCameraRegisters()
        assert reg.exposure_time == 10_000.0
        assert reg.gain == 0.0
        assert reg.frame_rate == 25.0

    def test_field_names(self):
        """Ожидаемые поля присутствуют в model_fields."""
        from hikvision_camera_module_2.plugin.registers import HikvisionCameraRegisters

        fields = set(HikvisionCameraRegisters.model_fields.keys())
        assert "exposure_time" in fields
        assert "gain" in fields
        assert "frame_rate" in fields

    def test_mutability(self):
        """Регистры можно менять (нужно для GUI-биндинга)."""
        from hikvision_camera_module_2.plugin.registers import HikvisionCameraRegisters

        reg = HikvisionCameraRegisters()
        reg.exposure_time = 50_000.0
        reg.gain = 5.0
        reg.frame_rate = 60.0

        assert reg.exposure_time == 50_000.0
        assert reg.gain == 5.0
        assert reg.frame_rate == 60.0


# ===========================================================================
# TestHikvisionCameraPlugin
# ===========================================================================


class TestHikvisionCameraPlugin:
    """Тесты source-плагина."""

    def test_plugin_meta(self):
        """name='hikvision_camera', category='source'."""
        from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        assert plugin.name == "hikvision_camera"
        assert plugin.category == "source"

    def test_outputs(self):
        """Один output: frame, dtype=image/bgr."""
        from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        assert len(plugin.outputs) == 1
        assert plugin.outputs[0].name == "frame"
        assert plugin.outputs[0].dtype == "image/bgr"

    def test_no_inputs(self):
        """Source plugin — нет inputs."""
        from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        assert plugin.inputs == []

    def test_commands_registered(self):
        """Все 11 команд зарегистрированы в commands dict."""
        from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        expected = {
            "open",
            "close",
            "start_capture",
            "stop_capture",
            "enum_devices",
            "get_parameters",
            "set_parameters",
            "set_exposure",
            "set_gain",
            "set_frame_rate",
            "set_resolution",
            "open_sdk_app",
            "close_sdk_app",
        }
        assert set(plugin.commands.keys()) == expected
        assert len(plugin.commands) == 13

    def test_configure_creates_camera(self):
        """configure() создаёт HikvisionCamera и сохраняет параметры из конфига."""
        from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        ctx = _make_ctx({"camera_id": 2, "camera_index": 1, "fps": 30})
        mock_cam = MagicMock()

        with patch(
            "hikvision_camera_module_2.plugin.plugin.HikvisionCamera",
            return_value=mock_cam,
        ) as cam_cls:
            plugin.configure(ctx)
            # Конструктор вызван один раз с колбэками
            cam_cls.assert_called_once()

        # Параметры из конфига применились
        assert plugin._camera_id == 2
        assert plugin._camera_index == 1
        assert plugin._fps == 30
        # _camera проставлен
        assert plugin._camera is mock_cam

    def test_configure_defaults(self):
        """configure() с пустым config использует дефолты плагина."""
        plugin, _ = _make_plugin_configured()
        assert plugin._camera_id == 0
        assert plugin._width == 1920
        assert plugin._height == 1080
        assert plugin._auto_start is False

    # --- produce ---

    def test_produce_not_capturing(self):
        """produce() без активного захвата возвращает пустой список."""
        plugin, _ = _make_plugin_configured()
        # _is_capturing по умолчанию False
        assert plugin.produce() == []

    def test_produce_camera_none(self):
        """produce() без камеры (None) возвращает пустой список."""
        plugin, _ = _make_plugin_configured()
        plugin._is_capturing = True
        plugin._camera = None
        assert plugin.produce() == []

    def test_produce_with_frame(self):
        """produce() с mock-камерой возвращает список с dict-кадром."""
        plugin, mock_cam = _make_plugin_configured({"camera_id": 1})
        plugin._is_capturing = True

        # Фейковый RAW-кадр от SDK
        raw_frame = np.zeros((1080, 1920), dtype=np.uint8)
        pixel_type = "BayerRG8"
        mock_cam.capture_frame.return_value = (raw_frame, pixel_type)

        # Mock FrameConverter
        bgr_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch(
            "hikvision_camera_module_2.plugin.plugin.FrameConverter"
        ) as mock_fc:
            mock_fc.to_bgr.return_value = bgr_frame
            mock_fc.resize.return_value = bgr_frame

            result = plugin.produce()

        assert len(result) == 1
        item = result[0]
        assert item["camera_id"] == 1
        assert item["camera_type"] == "hikvision"
        assert item["width"] == 1920
        assert item["height"] == 1080
        assert item["channels"] == 3
        assert item["dtype"] == "uint8"
        assert "timestamp" in item
        assert "seq_id" in item
        assert "frame_id" in item
        assert isinstance(item["frame"], np.ndarray)

    def test_produce_frame_none(self):
        """produce() когда камера возвращает None → пустой список."""
        plugin, mock_cam = _make_plugin_configured()
        plugin._is_capturing = True
        mock_cam.capture_frame.return_value = (None, None)

        assert plugin.produce() == []

    def test_produce_converter_returns_none(self):
        """produce() когда FrameConverter.to_bgr возвращает None → пустой список."""
        plugin, mock_cam = _make_plugin_configured()
        plugin._is_capturing = True

        raw_frame = np.zeros((1080, 1920), dtype=np.uint8)
        mock_cam.capture_frame.return_value = (raw_frame, "BayerRG8")

        with patch(
            "hikvision_camera_module_2.plugin.plugin.FrameConverter"
        ) as mock_fc:
            mock_fc.to_bgr.return_value = None  # конвертер не справился

            result = plugin.produce()

        assert result == []
        # Должна быть залогирована ошибка
        plugin._ctx.log_error.assert_called_once()

    def test_produce_seq_id_increments(self):
        """seq_id увеличивается с каждым кадром."""
        plugin, mock_cam = _make_plugin_configured()
        plugin._is_capturing = True

        raw_frame = np.zeros((100, 100), dtype=np.uint8)
        bgr_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        mock_cam.capture_frame.return_value = (raw_frame, "BayerRG8")

        with patch(
            "hikvision_camera_module_2.plugin.plugin.FrameConverter"
        ) as mock_fc:
            mock_fc.to_bgr.return_value = bgr_frame
            mock_fc.resize.return_value = bgr_frame

            r1 = plugin.produce()
            r2 = plugin.produce()

        assert r2[0]["seq_id"] == r1[0]["seq_id"] + 1

    # --- shutdown ---

    def test_shutdown(self):
        """shutdown() закрывает камеру и сбрасывает захват."""
        plugin, mock_cam = _make_plugin_configured()
        plugin._is_capturing = True

        ctx = _make_ctx()
        plugin.shutdown(ctx)

        # close() вызван
        mock_cam.close.assert_called_once()
        # _camera обнулён
        assert plugin._camera is None
        assert plugin._is_capturing is False

    # --- cmd_enum_devices ---

    def test_cmd_enum_devices(self):
        """cmd_enum_devices возвращает {'status': 'ok', 'devices': [...]}."""
        plugin, _ = _make_plugin_configured()

        # Мок-устройство с to_dict()
        fake_device = MagicMock()
        fake_device.to_dict.return_value = {"index": 0, "name": "Hikvision MV-CS050"}

        # enum_devices импортируется внутри cmd_enum_devices (late import),
        # поэтому патчим по месту определения в core.discovery
        with patch(
            "hikvision_camera_module_2.core.discovery.enum_devices",
            return_value=[fake_device],
        ):
            result = plugin.cmd_enum_devices({})

        assert result["status"] == "ok"
        assert result["devices"] == [{"index": 0, "name": "Hikvision MV-CS050"}]

    def test_cmd_enum_devices_empty(self):
        """cmd_enum_devices без устройств → пустой список."""
        plugin, _ = _make_plugin_configured()

        with patch(
            "hikvision_camera_module_2.core.discovery.enum_devices",
            return_value=[],
        ):
            result = plugin.cmd_enum_devices({})

        assert result == {"status": "ok", "devices": []}

    # --- cmd_start_capture ---

    def test_cmd_start_capture(self):
        """cmd_start_capture открывает и запускает захват."""
        plugin, mock_cam = _make_plugin_configured()
        mock_cam.open.return_value = True
        mock_cam.start_grabbing.return_value = True

        result = plugin.cmd_start_capture({})

        mock_cam.open.assert_called_once_with(plugin._camera_index)
        mock_cam.start_grabbing.assert_called_once()
        assert result["status"] == "ok"
        assert plugin._is_capturing is True

    def test_cmd_start_capture_with_index(self):
        """cmd_start_capture принимает camera_index из payload."""
        plugin, mock_cam = _make_plugin_configured()
        mock_cam.open.return_value = True
        mock_cam.start_grabbing.return_value = True

        plugin.cmd_start_capture({"camera_index": 2})

        # Индекс обновился и использован при открытии
        assert plugin._camera_index == 2
        mock_cam.open.assert_called_once_with(2)

    def test_cmd_start_capture_open_fails(self):
        """cmd_start_capture → error если open() вернул False."""
        plugin, mock_cam = _make_plugin_configured()
        mock_cam.open.return_value = False

        result = plugin.cmd_start_capture({})

        assert result["status"] == "error"
        assert plugin._is_capturing is False

    # --- cmd_stop_capture ---

    def test_cmd_stop_capture(self):
        """cmd_stop_capture останавливает захват."""
        plugin, mock_cam = _make_plugin_configured()
        plugin._is_capturing = True

        result = plugin.cmd_stop_capture({})

        mock_cam.stop_grabbing.assert_called_once()
        assert result["status"] == "ok"
        assert plugin._is_capturing is False

    # --- cmd_set_resolution ---

    def test_cmd_set_resolution(self):
        """cmd_set_resolution меняет _width и _height."""
        plugin, _ = _make_plugin_configured()

        result = plugin.cmd_set_resolution({"width": 640, "height": 480})

        assert plugin._width == 640
        assert plugin._height == 480
        assert result == {"status": "ok", "width": 640, "height": 480}

    def test_cmd_set_resolution_partial(self):
        """cmd_set_resolution сохраняет текущее значение если параметр не указан."""
        plugin, _ = _make_plugin_configured({"resolution_width": 1920, "resolution_height": 1080})

        # Передаём только width
        plugin.cmd_set_resolution({"width": 1280})

        assert plugin._width == 1280
        assert plugin._height == 1080  # не изменилась

    # --- cmd_set_exposure ---

    def test_cmd_set_exposure(self):
        """cmd_set_exposure обновляет регистр exposure_time."""
        plugin, _ = _make_plugin_configured()
        # Мокаем _apply_parameters_from_register чтобы не ходить в SDK
        plugin._apply_parameters_from_register = MagicMock()

        result = plugin.cmd_set_exposure({"exposure_time": 50_000.0})

        assert result == {"status": "ok", "exposure_time": 50_000.0}
        assert plugin._reg.exposure_time == 50_000.0
        plugin._apply_parameters_from_register.assert_called_once()

    def test_cmd_set_exposure_missing_value(self):
        """cmd_set_exposure без параметра → error."""
        plugin, _ = _make_plugin_configured()
        result = plugin.cmd_set_exposure({})
        assert result["status"] == "error"

    # --- cmd_set_gain ---

    def test_cmd_set_gain(self):
        """cmd_set_gain обновляет регистр gain."""
        plugin, _ = _make_plugin_configured()
        plugin._apply_parameters_from_register = MagicMock()

        result = plugin.cmd_set_gain({"gain": 10.0})

        assert result == {"status": "ok", "gain": 10.0}
        assert plugin._reg.gain == 10.0

    def test_cmd_set_gain_missing_value(self):
        """cmd_set_gain без параметра → error."""
        plugin, _ = _make_plugin_configured()
        result = plugin.cmd_set_gain({})
        assert result["status"] == "error"

    # --- cmd_set_frame_rate ---

    def test_cmd_set_frame_rate(self):
        """cmd_set_frame_rate обновляет _fps и регистр frame_rate."""
        plugin, _ = _make_plugin_configured()
        plugin._apply_parameters_from_register = MagicMock()

        result = plugin.cmd_set_frame_rate({"frame_rate": 60})

        assert result == {"status": "ok", "frame_rate": 60}
        assert plugin._fps == 60
        assert plugin._reg.frame_rate == 60.0

    def test_cmd_set_frame_rate_clamp(self):
        """cmd_set_frame_rate зажимает значение в диапазон [1, 120]."""
        plugin, _ = _make_plugin_configured()
        plugin._apply_parameters_from_register = MagicMock()

        # Слишком большое значение
        plugin.cmd_set_frame_rate({"frame_rate": 999})
        assert plugin._fps == 120

        # Слишком маленькое значение
        plugin.cmd_set_frame_rate({"frame_rate": 0})
        assert plugin._fps == 1

    def test_cmd_set_frame_rate_fps_alias(self):
        """cmd_set_frame_rate принимает 'fps' как альтернативный ключ."""
        plugin, _ = _make_plugin_configured()
        plugin._apply_parameters_from_register = MagicMock()

        result = plugin.cmd_set_frame_rate({"fps": 15})

        assert result["frame_rate"] == 15
        assert plugin._fps == 15

    def test_cmd_set_frame_rate_missing_value(self):
        """cmd_set_frame_rate без параметра → error."""
        plugin, _ = _make_plugin_configured()
        result = plugin.cmd_set_frame_rate({})
        assert result["status"] == "error"

    # --- cmd_open / cmd_close ---

    def test_cmd_open(self):
        """cmd_open открывает камеру по индексу из payload."""
        plugin, mock_cam = _make_plugin_configured()
        mock_cam.open.return_value = True

        result = plugin.cmd_open({"camera_index": 1})

        mock_cam.open.assert_called_once_with(1)
        assert result["status"] == "ok"

    def test_cmd_close(self):
        """cmd_close закрывает камеру и сбрасывает _is_capturing."""
        plugin, mock_cam = _make_plugin_configured()
        plugin._is_capturing = True

        result = plugin.cmd_close({})

        mock_cam.close.assert_called_once()
        assert plugin._is_capturing is False
        assert result["status"] == "ok"

    # --- register_class ---

    def test_register_class_is_hikvision_registers(self):
        """register_class указывает на HikvisionCameraRegisters."""
        from hikvision_camera_module_2.plugin.plugin import HikvisionCameraPlugin
        from hikvision_camera_module_2.plugin.registers import HikvisionCameraRegisters

        assert HikvisionCameraPlugin.register_class is HikvisionCameraRegisters

    def test_configure_sets_reg(self):
        """configure() инициализирует self._reg как HikvisionCameraRegisters."""
        from hikvision_camera_module_2.plugin.registers import HikvisionCameraRegisters

        plugin, _ = _make_plugin_configured()
        assert isinstance(plugin._reg, HikvisionCameraRegisters)
