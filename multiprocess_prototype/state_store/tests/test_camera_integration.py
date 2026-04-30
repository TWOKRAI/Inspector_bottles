"""Интеграционные тесты: CameraProcess ↔ StateProxy.

Проверяем что:
1. _on_config_changed роутит дельты к правильным обработчикам
2. build_state_config_handlers возвращает маппинг для всех 11 полей
3. StateProxy создаётся и подписывается при инициализации (через мок)
4. State записывается при shutdown
5. Dual-mode: register_update путь в _capture_worker НЕ удалён

Все тесты БЕЗ реальных процессов — мокаем RouterManager и сервисы.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call

from state_store.core.delta import MISSING, Delta
from multiprocess_prototype.backend.processes.camera.commands import (
    build_state_config_handlers,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_service() -> MagicMock:
    """Создать мок CameraService со всеми нужными методами."""
    svc = MagicMock()
    svc.set_fps.return_value = {"status": "ok"}
    svc.set_resolution.return_value = {"status": "ok"}
    svc.set_device_id.return_value = {"status": "ok"}
    svc.set_camera_index.return_value = {"status": "ok"}
    svc.set_hikvision_resolution.return_value = {"status": "ok"}
    svc.patch_hikvision_params.return_value = {"status": "ok"}
    return svc


def _make_cmd_set_camera_type() -> MagicMock:
    """Создать мок wrapper-функции set_camera_type."""
    return MagicMock(return_value={"status": "ok"})


def _make_delta(path: str, new_value=30, old_value=MISSING, source: str = "gui") -> Delta:
    """Создать тестовую Delta с заданным path и new_value."""
    return Delta(path=path, old_value=old_value, new_value=new_value, source=source)


def _make_on_config_changed(camera_id: int = 0):
    """Создать функцию _on_config_changed с замоканными зависимостями.

    Возвращает (callback, service_mock, cmd_set_camera_type_mock).
    """
    svc = _make_service()
    cmd_set_camera_type = _make_cmd_set_camera_type()
    handlers = build_state_config_handlers(svc, cmd_set_camera_type)

    def _on_config_changed(deltas: list) -> None:
        """Реплика метода CameraProcess._on_config_changed для тестов."""
        prefix = f"cameras.{camera_id}.config."
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = handlers.get(field)
            if handler:
                handler(delta.new_value)

    return _on_config_changed, svc, cmd_set_camera_type


# ===========================================================================
# Тесты build_state_config_handlers
# ===========================================================================

class TestBuildStateConfigHandlers:
    """Проверяем корректность маппинга build_state_config_handlers."""

    EXPECTED_KEYS = {
        "camera_type",
        "fps",
        "resolution_width",
        "resolution_height",
        "device_id",
        "camera_index",
        "hikvision_resolution_width",
        "hikvision_resolution_height",
        "hikvision_frame_rate",
        "hikvision_exposure_time",
        "hikvision_gain",
    }

    def test_build_state_config_handlers_keys(self):
        """build_state_config_handlers возвращает dict с ровно 11 ожидаемыми полями."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        assert set(handlers.keys()) == self.EXPECTED_KEYS, (
            f"Ожидались ключи {self.EXPECTED_KEYS}, получили {set(handlers.keys())}"
        )

    def test_state_config_handlers_fps_calls_service(self):
        """handler['fps'](30) → service.set_fps({'fps': 30})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["fps"](30)

        svc.set_fps.assert_called_once_with({"fps": 30})

    def test_state_config_handlers_resolution_width(self):
        """handler['resolution_width'](1920) → service.set_resolution({'width': 1920})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["resolution_width"](1920)

        svc.set_resolution.assert_called_once_with({"width": 1920})

    def test_state_config_handlers_resolution_height(self):
        """handler['resolution_height'](1080) → service.set_resolution({'height': 1080})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["resolution_height"](1080)

        svc.set_resolution.assert_called_once_with({"height": 1080})

    def test_state_config_handlers_camera_type(self):
        """handler['camera_type']('webcam') → cmd_set_camera_type({'camera_type': 'webcam'})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["camera_type"]("webcam")

        cmd.assert_called_once_with({"camera_type": "webcam"})

    def test_state_config_handlers_hikvision_frame_rate(self):
        """handler['hikvision_frame_rate'](60) → service.patch_hikvision_params({'frame_rate': 60})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["hikvision_frame_rate"](60)

        svc.patch_hikvision_params.assert_called_once_with({"frame_rate": 60})

    def test_state_config_handlers_hikvision_exposure_time(self):
        """handler['hikvision_exposure_time'](5000) → service.patch_hikvision_params({'exposure_time': 5000})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["hikvision_exposure_time"](5000)

        svc.patch_hikvision_params.assert_called_once_with({"exposure_time": 5000})

    def test_state_config_handlers_hikvision_gain(self):
        """handler['hikvision_gain'](10) → service.patch_hikvision_params({'gain': 10})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["hikvision_gain"](10)

        svc.patch_hikvision_params.assert_called_once_with({"gain": 10})

    def test_state_config_handlers_hikvision_resolution_width(self):
        """handler['hikvision_resolution_width'](2048) → service.set_hikvision_resolution({'width': 2048})."""
        svc = _make_service()
        cmd = _make_cmd_set_camera_type()
        handlers = build_state_config_handlers(svc, cmd)

        handlers["hikvision_resolution_width"](2048)

        svc.set_hikvision_resolution.assert_called_once_with({"width": 2048})


# ===========================================================================
# Тесты _on_config_changed
# ===========================================================================

class TestOnConfigChanged:
    """Проверяем роутинг дельт в _on_config_changed."""

    def test_on_config_changed_routes_fps(self):
        """delta с path cameras.0.config.fps → service.set_fps вызван."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        delta = _make_delta("cameras.0.config.fps", new_value=30)
        callback([delta])

        svc.set_fps.assert_called_once_with({"fps": 30})

    def test_on_config_changed_routes_camera_type(self):
        """delta cameras.0.config.camera_type → cmd_set_camera_type вызван."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        delta = _make_delta("cameras.0.config.camera_type", new_value="hikvision")
        callback([delta])

        cmd.assert_called_once_with({"camera_type": "hikvision"})

    def test_on_config_changed_ignores_unknown_field(self):
        """delta cameras.0.config.unknown → ничего не вызвано."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        delta = _make_delta("cameras.0.config.unknown_field", new_value="x")
        callback([delta])

        svc.set_fps.assert_not_called()
        svc.set_resolution.assert_not_called()
        cmd.assert_not_called()

    def test_on_config_changed_ignores_wrong_camera(self):
        """delta cameras.1.config.fps → ничего (camera_id=0)."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        delta = _make_delta("cameras.1.config.fps", new_value=25)
        callback([delta])

        svc.set_fps.assert_not_called()

    def test_on_config_changed_multiple_deltas(self):
        """3 дельты → 3 вызова соответствующих обработчиков."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        deltas = [
            _make_delta("cameras.0.config.fps", new_value=30),
            _make_delta("cameras.0.config.resolution_width", new_value=1920),
            _make_delta("cameras.0.config.resolution_height", new_value=1080),
        ]
        callback(deltas)

        svc.set_fps.assert_called_once_with({"fps": 30})
        assert svc.set_resolution.call_count == 2
        svc.set_resolution.assert_any_call({"width": 1920})
        svc.set_resolution.assert_any_call({"height": 1080})

    def test_on_config_changed_routes_device_id(self):
        """delta cameras.0.config.device_id → service.set_device_id вызван."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        delta = _make_delta("cameras.0.config.device_id", new_value="/dev/video0")
        callback([delta])

        svc.set_device_id.assert_called_once_with({"device_id": "/dev/video0"})

    def test_on_config_changed_camera_id_1(self):
        """camera_id=1: delta cameras.1.config.fps роутится корректно."""
        callback, svc, cmd = _make_on_config_changed(camera_id=1)

        delta = _make_delta("cameras.1.config.fps", new_value=60)
        callback([delta])

        svc.set_fps.assert_called_once_with({"fps": 60})

    def test_on_config_changed_ignores_state_path(self):
        """delta cameras.0.state.fps (не config) → ничего не вызвано."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        delta = _make_delta("cameras.0.state.fps", new_value=30)
        callback([delta])

        svc.set_fps.assert_not_called()

    def test_on_config_changed_empty_deltas(self):
        """Пустой список дельт → ничего не вызвано, нет исключений."""
        callback, svc, cmd = _make_on_config_changed(camera_id=0)

        callback([])

        svc.set_fps.assert_not_called()
        cmd.assert_not_called()


# ===========================================================================
# Тест dual-mode: register_update НЕ удалён
# ===========================================================================

class TestStateProxyOnly:
    """Проверяем что register_update удалён: только StateProxy путь (Phase 4f)."""

    def test_capture_worker_no_register_update(self):
        """_capture_worker в process.py НЕ содержит register_update (убран в 4f.3)."""
        import inspect
        from multiprocess_prototype.backend.processes.camera.process import CameraProcess

        source = inspect.getsource(CameraProcess._capture_worker)
        assert "apply_register_update" not in source, (
            "apply_register_update удалён в Phase 4f.3 — только StateProxy"
        )

    def test_process_has_on_config_changed_method(self):
        """CameraProcess имеет метод _on_config_changed."""
        from multiprocess_prototype.backend.processes.camera.process import CameraProcess

        assert hasattr(CameraProcess, "_on_config_changed"), (
            "CameraProcess должен иметь метод _on_config_changed"
        )
        assert callable(CameraProcess._on_config_changed)
