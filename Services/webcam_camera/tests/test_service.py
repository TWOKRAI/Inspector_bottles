"""Smoke-тесты для WebcamCameraService.

Проверяют базовый контракт shell-класса: start / stop / get_status.
Реальная камера не нужна — тесты работают без оборудования.
"""

from __future__ import annotations


from Services.webcam_camera.service import WebcamCameraService


class TestWebcamCameraServiceInit:
    """Тесты инициализации."""

    def test_initial_status_is_stopped(self):
        """После создания сервис находится в состоянии stopped."""
        svc = WebcamCameraService()
        assert svc.status == "stopped"

    def test_initial_config_is_empty(self):
        """После создания конфиг пустой."""
        svc = WebcamCameraService()
        assert svc.config == {}

    def test_name_constant(self):
        """Имя сервиса совпадает с ожидаемым идентификатором."""
        svc = WebcamCameraService()
        assert svc.name == "webcam_camera"

    def test_logger_defaults_to_none(self):
        """При создании без аргументов logger не установлен."""
        svc = WebcamCameraService()
        assert svc._logger is None


class TestWebcamCameraServiceStart:
    """Тесты метода start()."""

    def test_start_sets_status_running(self):
        """start() переводит статус в running."""
        svc = WebcamCameraService()
        svc.start({})
        assert svc.status == "running"

    def test_start_returns_true(self):
        """start() возвращает True."""
        svc = WebcamCameraService()
        result = svc.start({"device_id": 0})
        assert result is True

    def test_start_saves_config(self):
        """start() сохраняет переданный конфиг."""
        svc = WebcamCameraService()
        cfg = {"device_id": 1, "width": 1920, "height": 1080}
        svc.start(cfg)
        assert svc.config == cfg

    def test_start_with_empty_config(self):
        """start() принимает пустой конфиг без ошибок."""
        svc = WebcamCameraService()
        result = svc.start({})
        assert result is True
        assert svc.status == "running"


class TestWebcamCameraServiceStop:
    """Тесты метода stop()."""

    def test_stop_sets_status_stopped(self):
        """stop() переводит статус обратно в stopped."""
        svc = WebcamCameraService()
        svc.start({})
        svc.stop()
        assert svc.status == "stopped"

    def test_stop_returns_true(self):
        """stop() возвращает True."""
        svc = WebcamCameraService()
        result = svc.stop()
        assert result is True

    def test_stop_idempotent(self):
        """Повторный stop() не вызывает ошибок, статус остаётся stopped."""
        svc = WebcamCameraService()
        svc.stop()
        svc.stop()
        assert svc.status == "stopped"


class TestWebcamCameraServiceGetStatus:
    """Тесты метода get_status()."""

    def test_get_status_returns_dict(self):
        """get_status() возвращает словарь."""
        svc = WebcamCameraService()
        result = svc.get_status()
        assert isinstance(result, dict)

    def test_get_status_has_required_keys(self):
        """get_status() содержит ключи name, status, config."""
        svc = WebcamCameraService()
        result = svc.get_status()
        assert "name" in result
        assert "status" in result
        assert "config" in result

    def test_get_status_reflects_current_state(self):
        """get_status() отражает актуальное состояние после start/stop."""
        svc = WebcamCameraService()
        cfg = {"device_id": 0}

        svc.start(cfg)
        status_running = svc.get_status()
        assert status_running["status"] == "running"
        assert status_running["config"] == cfg
        assert status_running["name"] == "webcam_camera"

        svc.stop()
        status_stopped = svc.get_status()
        assert status_stopped["status"] == "stopped"


class TestWebcamCameraServiceLogger:
    """Тесты инъекции logger."""

    def test_logger_info_called_on_start(self):
        """start() вызывает logger.info при наличии логгера."""

        class _FakeLogger:
            def __init__(self):
                self.calls: list[str] = []

            def info(self, msg: str) -> None:
                self.calls.append(msg)

        logger = _FakeLogger()
        svc = WebcamCameraService(logger=logger)
        svc.start({"device_id": 0})
        assert len(logger.calls) == 1
        assert "start()" in logger.calls[0]

    def test_logger_info_called_on_stop(self):
        """stop() вызывает logger.info при наличии логгера."""

        class _FakeLogger:
            def __init__(self):
                self.calls: list[str] = []

            def info(self, msg: str) -> None:
                self.calls.append(msg)

        logger = _FakeLogger()
        svc = WebcamCameraService(logger=logger)
        svc.start({})
        svc.stop()
        assert len(logger.calls) == 2  # start + stop

    def test_no_logger_no_error(self):
        """Без логгера start/stop работают без ошибок."""
        svc = WebcamCameraService()  # logger=None
        svc.start({"device_id": 0})
        svc.stop()
        assert svc.status == "stopped"
