"""Тесты для GuiProcess, DataReceiverBridge и topology phase4_gui."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Вспомогательная функция — минимальный mock shared_resources
# ============================================================================

def _make_mock_shared_resources() -> MagicMock:
    """Создать минимальный mock shared_resources для тестов ProcessModule."""
    sr = MagicMock()
    # process_data = None → ProcessLifecycle продолжит без лишних действий
    sr.get_process_data.return_value = None
    sr.update_process_state.return_value = None
    # process_state_registry — нужен ProcessState
    sr.process_state_registry = MagicMock()
    sr.process_state_registry.register.return_value = None
    sr.process_state_registry.update.return_value = None
    return sr


# ============================================================================
# test_data_receiver_bridge_dispatch
# ============================================================================

class TestDataReceiverBridgeDispatch:
    """Проверяем что DataReceiverBridge emit'ит правильные signals по data_type."""

    @pytest.fixture(autouse=True)
    def _setup_qapp(self, qapp):
        """qapp из pytest-qt гарантирует существование QApplication."""
        pass

    def test_dispatch_frame_ready(self, qtbot):
        """data_type='frame_ready' → signal frame_received."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.frame_received.connect(received.append)

        msg = {"data_type": "frame_ready", "payload": "test"}
        bridge.dispatch(msg)

        assert len(received) == 1
        assert received[0] == msg

    def test_dispatch_frame(self, qtbot):
        """data_type='frame' → signal frame_received."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.frame_received.connect(received.append)

        msg = {"data_type": "frame"}
        bridge.dispatch(msg)

        assert len(received) == 1

    def test_dispatch_state_changed(self, qtbot):
        """data_type='state_changed' → signal state_updated."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.state_updated.connect(received.append)

        msg = {"data_type": "state_changed", "state": "running"}
        bridge.dispatch(msg)

        assert len(received) == 1
        assert received[0] == msg

    def test_dispatch_status(self, qtbot):
        """data_type='status' → signal state_updated."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.state_updated.connect(received.append)

        bridge.dispatch({"data_type": "status"})
        assert len(received) == 1

    def test_dispatch_fps_update(self, qtbot):
        """data_type='fps_update' → signal state_updated."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.state_updated.connect(received.append)

        bridge.dispatch({"data_type": "fps_update", "fps": 30})
        assert len(received) == 1

    def test_dispatch_unknown_goes_to_command_response(self, qtbot):
        """Неизвестный data_type → signal command_response."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.command_response.connect(received.append)

        bridge.dispatch({"data_type": "some_command", "cmd": "do_something"})
        assert len(received) == 1

    def test_dispatch_empty_data_type(self, qtbot):
        """Пустой data_type → command_response (fallback)."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.command_response.connect(received.append)

        bridge.dispatch({})
        assert len(received) == 1


# ============================================================================
# test_gui_process_instantiation
# ============================================================================

class TestGuiProcessInstantiation:
    """Проверяем создание GuiProcess и инициализацию bridge."""

    def test_gui_process_instantiation(self):
        """GuiProcess создаётся без ошибок."""
        from multiprocess_prototype.frontend.process import GuiProcess

        sr = _make_mock_shared_resources()
        process = GuiProcess(name="gui", shared_resources=sr)

        assert process.name == "gui"
        assert process.is_initialized is False

    def test_bridge_created_in_init_application_threads(self):
        """_init_application_threads() создаёт DataReceiverBridge."""
        from multiprocess_prototype.frontend.process import GuiProcess
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        sr = _make_mock_shared_resources()
        process = GuiProcess(name="gui", shared_resources=sr)

        # Мокируем всё, что нужно ProcessModule.initialize()
        process._init_configuration = MagicMock()
        process._init_queues = MagicMock()
        process._init_managers = MagicMock()
        process._init_communication = MagicMock()
        process._register_process_state = MagicMock()
        process._init_system_threads = MagicMock()
        process._init_custom_managers = MagicMock()
        process.update_process_state = MagicMock()

        # worker_manager нужен для create_worker
        mock_wm = MagicMock()
        process.worker_manager = mock_wm

        # Вызываем _init_application_threads напрямую
        process._init_application_threads()

        # Bridge должен быть создан
        assert hasattr(process, "_bridge")
        assert isinstance(process._bridge, DataReceiverBridge)

        # create_worker вызван с "data_receiver"
        mock_wm.create_worker.assert_called_once()
        call_args = mock_wm.create_worker.call_args
        assert call_args[0][0] == "data_receiver"


# ============================================================================
# test_topology_parses
# ============================================================================

class TestTopologyParses:
    """Проверяем валидность hello_world.yaml."""

    def test_topology_parses(self):
        """Загрузить hello_world.yaml и проверить SystemBlueprint.model_validate()."""
        import yaml
        from multiprocess_framework.modules.process_module.generic.blueprint import SystemBlueprint

        topology_path = (
            Path(__file__).parent.parent.parent / "topology" / "hello_world.yaml"
        )
        assert topology_path.exists(), f"Файл не найден: {topology_path}"

        with topology_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        blueprint = SystemBlueprint.model_validate(data)

        assert blueprint.name == "hello_world"
        assert len(blueprint.processes) == 2

        proc_names = {p.process_name for p in blueprint.processes}
        assert "camera_0" in proc_names
        assert "gui" in proc_names

    def test_topology_check_returns_no_errors(self):
        """blueprint.check() не возвращает ошибок для hello_world."""
        import yaml
        from multiprocess_framework.modules.process_module.generic.blueprint import SystemBlueprint

        topology_path = (
            Path(__file__).parent.parent.parent / "topology" / "hello_world.yaml"
        )
        with topology_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        blueprint = SystemBlueprint.model_validate(data)
        errors = blueprint.check()

        assert errors == []


# ============================================================================
# test_process_class_field
# ============================================================================

class TestProcessClassField:
    """Проверяем поле process_class в ProcessConfig и as_generic_config()."""

    def test_process_class_field_exists(self):
        """ProcessConfig имеет поле process_class с дефолтом ''."""
        from multiprocess_framework.modules.process_module.generic.blueprint import ProcessConfig

        cfg = ProcessConfig(process_name="test")
        assert hasattr(cfg, "process_class")
        assert cfg.process_class == ""

    def test_process_class_stored(self):
        """ProcessConfig сохраняет переданный process_class."""
        from multiprocess_framework.modules.process_module.generic.blueprint import ProcessConfig

        cfg = ProcessConfig(
            process_name="gui",
            process_class="multiprocess_prototype.frontend.process.GuiProcess",
        )
        assert cfg.process_class == "multiprocess_prototype.frontend.process.GuiProcess"

    def test_as_generic_config_passes_process_class(self):
        """as_generic_config() передаёт process_class в GenericProcessConfig."""
        from multiprocess_framework.modules.process_module.generic.blueprint import ProcessConfig

        cfg = ProcessConfig(
            process_name="gui",
            process_class="multiprocess_prototype.frontend.process.GuiProcess",
            plugins=[],
        )
        generic = cfg.as_generic_config()

        assert generic.process_class == "multiprocess_prototype.frontend.process.GuiProcess"

    def test_as_generic_config_default_class_when_empty(self):
        """as_generic_config() с пустым process_class сохраняет дефолтный GenericProcess путь."""
        from multiprocess_framework.modules.process_module.generic.blueprint import ProcessConfig

        cfg = ProcessConfig(process_name="default_proc", plugins=[])
        generic = cfg.as_generic_config()

        # Дефолт из GenericProcessConfig
        assert "GenericProcess" in generic.process_class


# ============================================================================
# TestDataReceiverErrorRecovery
# ============================================================================

class TestDataReceiverErrorRecovery:
    """Тесты exponential backoff и error recovery в data_receiver_loop."""

    def _make_process(self):
        """Создать mock GuiProcess с нужными атрибутами."""
        from multiprocess_prototype.frontend.process import GuiProcess

        process = MagicMock()
        process.name = "gui_test"
        process._bridge = MagicMock()
        process._log_error = MagicMock()
        process._log_info = MagicMock()
        process._log_critical = MagicMock()
        process._track_error = MagicMock()
        process._record_metric = MagicMock()
        # Привязываем реальный метод
        process._data_receiver_loop = GuiProcess._data_receiver_loop.__get__(process)
        return process

    def _make_stop_event(self, delay: float = 0.0):
        """Создать stop_event, который сработает через delay секунд."""
        import threading
        stop_event = threading.Event()
        if delay > 0:
            threading.Timer(delay, stop_event.set).start()
        return stop_event

    def test_backoff_increases_on_errors(self):
        """Backoff растёт при последовательных ошибках."""
        import threading
        import time as time_module

        process = self._make_process()
        stop_event = threading.Event()
        pause_event = threading.Event()

        call_count = [0]
        sleep_calls = []

        # Router всегда бросает исключение
        process.router_manager.receive.side_effect = RuntimeError("сетевая ошибка")

        original_sleep = time_module.sleep

        def fake_sleep(seconds):
            sleep_calls.append(seconds)
            # После 3-й ошибки останавливаем цикл
            if len(sleep_calls) >= 3:
                stop_event.set()

        with patch("multiprocess_prototype.frontend.process.time") as mock_time:
            mock_time.sleep.side_effect = fake_sleep
            process._data_receiver_loop(stop_event, pause_event)

        # Проверяем что backoff растёт: 0.1 → 0.2 → 0.4
        assert len(sleep_calls) >= 2
        assert sleep_calls[0] < sleep_calls[1], "Backoff должен расти"

    def test_counter_resets_on_success(self):
        """Counter сбрасывается после успешного получения сообщений."""
        import threading

        process = self._make_process()
        stop_event = threading.Event()
        pause_event = threading.Event()

        # Сценарий: ошибка → успех → стоп
        # После sleep (ошибка) — не останавливаем; останавливаем только после успеха
        step = [0]

        def side_effect(**kwargs):
            step[0] += 1
            if step[0] == 1:
                raise RuntimeError("ошибка")
            # шаг 2: успешный receive → после этого ставим stop
            stop_event.set()
            return [{"data_type": "frame"}]

        process.router_manager.receive.side_effect = side_effect

        with patch("multiprocess_prototype.frontend.process.time") as mock_time:
            mock_time.sleep.return_value = None  # sleep ничего не делает
            process._data_receiver_loop(stop_event, pause_event)

        # _log_info должен быть вызван с сообщением о восстановлении
        recovery_calls = [
            call for call in process._log_info.call_args_list
            if "восстановление" in str(call)
        ]
        assert len(recovery_calls) == 1

    def test_critical_after_threshold(self):
        """_log_critical вызывается ровно при достижении порога 5 ошибок подряд."""
        import threading

        process = self._make_process()
        stop_event = threading.Event()
        pause_event = threading.Event()

        error_count = [0]

        process.router_manager.receive.side_effect = RuntimeError("постоянная ошибка")

        with patch("multiprocess_prototype.frontend.process.time") as mock_time:
            def fake_sleep(seconds):
                error_count[0] += 1
                if error_count[0] >= 6:
                    stop_event.set()
            mock_time.sleep.side_effect = fake_sleep
            process._data_receiver_loop(stop_event, pause_event)

        # _log_critical должен быть вызван ровно 1 раз (при consecutive == 5)
        assert process._log_critical.call_count == 1
        call_args = process._log_critical.call_args
        assert "5" in str(call_args)

    def test_track_error_called(self):
        """_track_error вызывается при каждой ошибке с правильным контекстом."""
        import threading

        process = self._make_process()
        stop_event = threading.Event()
        pause_event = threading.Event()

        process.router_manager.receive.side_effect = ValueError("тест")

        with patch("multiprocess_prototype.frontend.process.time") as mock_time:
            call_cnt = [0]
            def fake_sleep(seconds):
                call_cnt[0] += 1
                if call_cnt[0] >= 2:
                    stop_event.set()
            mock_time.sleep.side_effect = fake_sleep
            process._data_receiver_loop(stop_event, pause_event)

        # _track_error вызван для каждой ошибки
        assert process._track_error.call_count >= 2

        # Проверяем контекст первого вызова
        first_call = process._track_error.call_args_list[0]
        exc_arg = first_call[0][0]
        ctx_arg = first_call[1].get("context") or first_call[0][1]
        assert isinstance(exc_arg, ValueError)
        assert ctx_arg["loop"] == "data_receiver"
        assert "consecutive" in ctx_arg

    def test_record_metric_on_error_and_success(self):
        """_record_metric вызывается при ошибках ('data_receiver.errors') и успехе ('data_receiver.success')."""
        import threading

        process = self._make_process()
        stop_event = threading.Event()
        pause_event = threading.Event()

        # Ошибка → потом успех → стоп
        step = [0]

        def side_effect(**kwargs):
            step[0] += 1
            if step[0] == 1:
                raise RuntimeError("ошибка")
            stop_event.set()
            return [{"data_type": "status"}]

        process.router_manager.receive.side_effect = side_effect

        with patch("multiprocess_prototype.frontend.process.time") as mock_time:
            mock_time.sleep.return_value = None  # sleep мгновенный
            process._data_receiver_loop(stop_event, pause_event)

        metric_names = [call[0][0] for call in process._record_metric.call_args_list]
        assert "data_receiver.errors" in metric_names
        assert "data_receiver.success" in metric_names
