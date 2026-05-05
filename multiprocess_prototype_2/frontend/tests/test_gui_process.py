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
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.frame_received.connect(received.append)

        msg = {"data_type": "frame_ready", "payload": "test"}
        bridge.dispatch(msg)

        assert len(received) == 1
        assert received[0] == msg

    def test_dispatch_frame(self, qtbot):
        """data_type='frame' → signal frame_received."""
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.frame_received.connect(received.append)

        msg = {"data_type": "frame"}
        bridge.dispatch(msg)

        assert len(received) == 1

    def test_dispatch_state_changed(self, qtbot):
        """data_type='state_changed' → signal state_updated."""
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.state_updated.connect(received.append)

        msg = {"data_type": "state_changed", "state": "running"}
        bridge.dispatch(msg)

        assert len(received) == 1
        assert received[0] == msg

    def test_dispatch_status(self, qtbot):
        """data_type='status' → signal state_updated."""
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.state_updated.connect(received.append)

        bridge.dispatch({"data_type": "status"})
        assert len(received) == 1

    def test_dispatch_fps_update(self, qtbot):
        """data_type='fps_update' → signal state_updated."""
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.state_updated.connect(received.append)

        bridge.dispatch({"data_type": "fps_update", "fps": 30})
        assert len(received) == 1

    def test_dispatch_unknown_goes_to_command_response(self, qtbot):
        """Неизвестный data_type → signal command_response."""
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.command_response.connect(received.append)

        bridge.dispatch({"data_type": "some_command", "cmd": "do_something"})
        assert len(received) == 1

    def test_dispatch_empty_data_type(self, qtbot):
        """Пустой data_type → command_response (fallback)."""
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

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
        from multiprocess_prototype_2.frontend.process import GuiProcess

        sr = _make_mock_shared_resources()
        process = GuiProcess(name="gui", shared_resources=sr)

        assert process.name == "gui"
        assert process.is_initialized is False

    def test_bridge_created_in_init_application_threads(self):
        """_init_application_threads() создаёт DataReceiverBridge."""
        from multiprocess_prototype_2.frontend.process import GuiProcess
        from multiprocess_prototype_2.frontend.bridge import DataReceiverBridge

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
    """Проверяем валидность phase4_gui.yaml."""

    def test_topology_parses(self):
        """Загрузить phase4_gui.yaml и проверить SystemBlueprint.model_validate()."""
        import yaml
        from multiprocess_framework.modules.process_module.generic.blueprint import SystemBlueprint

        topology_path = (
            Path(__file__).parent.parent.parent / "topology" / "phase4_gui.yaml"
        )
        assert topology_path.exists(), f"Файл не найден: {topology_path}"

        with topology_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        blueprint = SystemBlueprint.model_validate(data)

        assert blueprint.name == "phase4_gui"
        assert len(blueprint.processes) == 1

        proc = blueprint.processes[0]
        assert proc.process_name == "gui"
        assert proc.process_class == "multiprocess_prototype_2.frontend.process.GuiProcess"
        assert proc.plugins == []

    def test_topology_check_returns_no_errors(self):
        """blueprint.check() не возвращает ошибок для phase4_gui."""
        import yaml
        from multiprocess_framework.modules.process_module.generic.blueprint import SystemBlueprint

        topology_path = (
            Path(__file__).parent.parent.parent / "topology" / "phase4_gui.yaml"
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
            process_class="multiprocess_prototype_2.frontend.process.GuiProcess",
        )
        assert cfg.process_class == "multiprocess_prototype_2.frontend.process.GuiProcess"

    def test_as_generic_config_passes_process_class(self):
        """as_generic_config() передаёт process_class в GenericProcessConfig."""
        from multiprocess_framework.modules.process_module.generic.blueprint import ProcessConfig

        cfg = ProcessConfig(
            process_name="gui",
            process_class="multiprocess_prototype_2.frontend.process.GuiProcess",
            plugins=[],
        )
        generic = cfg.as_generic_config()

        assert generic.process_class == "multiprocess_prototype_2.frontend.process.GuiProcess"

    def test_as_generic_config_default_class_when_empty(self):
        """as_generic_config() с пустым process_class сохраняет дефолтный GenericProcess путь."""
        from multiprocess_framework.modules.process_module.generic.blueprint import ProcessConfig

        cfg = ProcessConfig(process_name="default_proc", plugins=[])
        generic = cfg.as_generic_config()

        # Дефолт из GenericProcessConfig
        assert "GenericProcess" in generic.process_class
