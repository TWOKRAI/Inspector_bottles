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
    # По умолчанию общий system_stop_event не проброшен (None) → fallback на IPC
    sr.get_system_stop_event.return_value = None
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
        """data_type='frame_ready' -> сообщение в frame_mailbox (ключ "" без sender), без события Qt."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.frame_received.connect(received.append)

        msg = {"data_type": "frame_ready", "payload": "test"}
        bridge.dispatch(msg)

        taken = bridge.frame_mailbox.take("")
        assert taken is not None
        assert taken[0] == msg
        assert received == []  # frame_received больше не эмитится из dispatch

    def test_dispatch_frame(self, qtbot):
        """data_type='frame' -> сообщение в frame_mailbox (ключ "" без sender)."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.frame_received.connect(received.append)

        msg = {"data_type": "frame"}
        bridge.dispatch(msg)

        taken = bridge.frame_mailbox.take("")
        assert taken is not None
        assert taken[0] == msg
        assert received == []  # frame_received больше не эмитится из dispatch

    def test_dispatch_frame_counts_nbytes(self, qtbot):
        """Кадр 10x10x3 uint8 учтён в ящике как 300 байт (nbytes берётся из frame.nbytes)."""
        import numpy as np

        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()

        bridge.dispatch({"data_type": "frame", "sender": "cam0", "frame": np.zeros((10, 10, 3), dtype=np.uint8)})

        assert bridge.frame_mailbox.stats()["bytes_held"] == 300

    def test_dispatch_frame_rejected_when_mailbox_full(self, qtbot):
        """65-й sender при max_keys=64: dispatch не бросает, отказ считается в stats()['rejected']."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        for i in range(64):
            bridge.dispatch({"data_type": "frame", "sender": f"cam{i}"})
        assert bridge.frame_mailbox.stats()["rejected"] == 0

        bridge.dispatch({"data_type": "frame", "sender": "cam64"})  # не должен бросить

        stats = bridge.frame_mailbox.stats()
        assert stats["rejected"] == 1
        assert stats["put"] == 64
        assert bridge.frame_mailbox.take("cam64") is None

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

    def test_dispatch_state_delta_goes_to_state_updated(self, qtbot):
        """data_type='state_delta' → signal state_updated (Фаза 1.3)."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received = []
        bridge.state_updated.connect(received.append)

        msg = {
            "data_type": "state_delta",
            "path": "processes.cam.workers.w1.status",
            "value": "running",
        }
        bridge.dispatch(msg)

        assert len(received) == 1
        assert received[0] == msg

    def test_dispatch_gui_local_metric_goes_to_state(self, qtbot):
        """Ф5.19: data_type='gui_local_metric' → state_updated (замена fake state_delta), НЕ observability."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        state, obs = [], []
        bridge.state_updated.connect(state.append)
        bridge.observability_received.connect(obs.append)

        msg = {"data_type": "gui_local_metric", "path": "system.chain_fps", "value": 30.0}
        bridge.dispatch(msg)

        assert len(state) == 1
        assert state[0] == msg
        assert obs == []

    def test_dispatch_observability_record_goes_to_observability_signal(self, qtbot):
        """Ф5.20b: data_type='observability_record' → observability_received, НЕ state."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        obs, state = [], []
        bridge.observability_received.connect(obs.append)
        bridge.state_updated.connect(state.append)

        msg = {
            "data_type": "observability_record",
            "process": "cam",
            "records": [{"kind": "log", "module": "cam", "ts": 1.0, "severity": "info", "message": "hi"}],
        }
        bridge.dispatch(msg)

        assert len(obs) == 1
        assert obs[0] == msg
        assert state == []  # НЕ путается со state-плоскостью

    def test_observability_callback_invoked(self, qtbot):
        """set_observability_callback вызывается перед сигналом."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        seen = []
        bridge.set_observability_callback(seen.append)
        bridge.dispatch({"data_type": "observability_record", "records": []})
        assert len(seen) == 1

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


class TestObservabilityRecordHandler:
    """Ф5.20b: GuiProcess._on_observability_record нормализует push → bridge.dispatch."""

    @pytest.fixture(autouse=True)
    def _setup_qapp(self, qapp):
        pass

    def _handler(self):
        """Вызвать handler на fake-self с реальным bridge (метод трогает только _bridge)."""
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.process import GuiProcess

        bridge = DataReceiverBridge()
        got = []
        bridge.observability_received.connect(got.append)
        fake_self = MagicMock()
        fake_self._bridge = bridge
        return GuiProcess._on_observability_record, fake_self, got

    def test_batch_records_forwarded(self, qtbot):
        handler, fake_self, got = self._handler()
        msg = {
            "command": "observability.record",
            "sender": "cam",
            "data": {"process": "cam", "records": [{"m": 1}, {"m": 2}]},
        }
        handler(fake_self, msg)
        assert len(got) == 1
        assert got[0]["data_type"] == "observability_record"
        assert got[0]["process"] == "cam"
        # Ф3.4: обработчик — первая точка, где запись увидел ЧУЖОЙ процесс,
        # поэтому он же ставит отметку приёма. Сверяем содержимое без неё, а
        # саму отметку — отдельным тестом ниже.
        assert [{k: v for k, v in r.items() if k != "observed_ts"} for r in got[0]["records"]] == [
            {"m": 1},
            {"m": 2},
        ]

    def test_single_record_wrapped_in_list(self, qtbot):
        handler, fake_self, got = self._handler()
        msg = {"data": {"process": "cam", "record": {"m": 9}}}
        handler(fake_self, msg)
        assert [{k: v for k, v in r.items() if k != "observed_ts"} for r in got[0]["records"]] == [{"m": 9}]

    def test_empty_no_dispatch(self, qtbot):
        handler, fake_self, got = self._handler()
        handler(fake_self, {"data": {"process": "cam"}})
        assert got == []

    def test_handler_stamps_the_moment_of_receipt(self, qtbot):
        """Ф3.4: ПРОВОДКА, а не помощник.

        Тесты самого ``stamp_observed`` живут в framework и доказывают функцию.
        Здесь проверяется, что её ВЫЗВАЛИ — и вызвали в правильной точке: на
        приёме, где запись впервые увидел чужой процесс. Без этого теста
        корректная функция могла бы просто нигде не звучать.
        """
        import time

        handler, fake_self, got = self._handler()
        before = time.time()
        handler(fake_self, {"data": {"process": "cam", "records": [{"ts": 1.0}]}})
        after = time.time()

        stamped = got[0]["records"][0]
        assert "observed_ts" in stamped, "обработчик не поставил отметку приёма"
        assert before <= stamped["observed_ts"] <= after, "отметка не из часов приёмника"
        assert stamped["observed_ts"] - stamped["ts"] > 0, "задержка доставки не считается"

    def test_handler_keeps_a_stamp_made_upstream(self, qtbot):
        """Пересылка через вторые руки не обнуляет задержку первого приёмника."""
        handler, fake_self, got = self._handler()
        handler(fake_self, {"data": {"process": "cam", "records": [{"ts": 1.0, "observed_ts": 5.0}]}})
        assert got[0]["records"][0]["observed_ts"] == 5.0


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

    def test_bridge_created_in_init_application_threads(self, qtbot):
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

        # create_worker вызван с "data_receiver" ровно один раз. Считаем по имени: база
        # создаёт и свои воркеры (readiness_snapshot, _init_run_state_workers) — это намеренно.
        receiver_calls = [c for c in mock_wm.create_worker.call_args_list if c[0][0] == "data_receiver"]
        assert len(receiver_calls) == 1

        # воркер data_receiver стоит на bound-методе run_loop именно FrameIntake: иначе
        # WorkerManager.get_worker_status не подмешает get_cycle_metrics в статус воркера
        target = receiver_calls[0][0][1]
        assert target.__self__ is process._frame_intake
        assert target.__func__.__name__ == "run_loop"

        # метрики ящика и очереди Qt привязаны к живым объектам процесса, не к нулям по умолчанию
        import threading

        from PySide6.QtCore import QCoreApplication

        process._bridge.frame_mailbox.put("cam", {"frame": 1}, 10)
        process._bridge.frame_mailbox.put("cam", {"frame": 2}, 10)  # вытеснил первый
        sender = threading.Thread(
            target=lambda: process._bridge.dispatch({"data_type": "state_delta", "path": "a.b", "value": 1}),
            daemon=True,
        )
        sender.start()
        sender.join(5.0)
        metrics = process._frame_intake.get_cycle_metrics()
        assert metrics["superseded"] == 1
        assert metrics["pending"] == 1
        assert metrics["bytes_held"] == 10
        assert metrics["qt_pending"] == 1  # сообщение передано в Qt из чужого потока и не обработано
        QCoreApplication.processEvents()
        assert process._frame_intake.get_cycle_metrics()["qt_pending"] == 0

    def test_data_receiver_loop_delegates_to_frame_intake(self):
        """GuiProcess._data_receiver_loop (FREEZE) делегирует FrameIntake.run_loop с теми же событиями."""
        import threading

        from multiprocess_prototype.frontend.process import GuiProcess

        process = GuiProcess(name="gui", shared_resources=_make_mock_shared_resources())
        process._frame_intake = MagicMock()
        stop_event, pause_event = threading.Event(), threading.Event()

        process._data_receiver_loop(stop_event, pause_event)

        process._frame_intake.run_loop.assert_called_once_with(stop_event, pause_event)


# ============================================================================
# test_topology_parses
# ============================================================================


class TestTopologyParses:
    """Проверяем валидность hello_world.yaml."""

    def test_topology_parses(self):
        """Загрузить hello_world.yaml и проверить SystemBlueprint.model_validate()."""
        import yaml
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            SystemBlueprint,
        )

        from multiprocess_prototype.backend.launch import merge_topologies

        topo_dir = Path(__file__).parent.parent.parent / "backend" / "topology"
        pipeline_path = topo_dir / "hello_world.yaml"
        base_path = topo_dir / "base.yaml"
        presentation_path = Path(__file__).parent.parent / "presentation.yaml"
        assert pipeline_path.exists(), f"Файл не найден: {pipeline_path}"

        with pipeline_path.open(encoding="utf-8") as f:
            pipeline = yaml.safe_load(f)
        with base_path.open(encoding="utf-8") as f:
            base = yaml.safe_load(f)
        with presentation_path.open(encoding="utf-8") as f:
            presentation = yaml.safe_load(f)

        # Ф2 frontend-constructor (d6faaa80): gui уехал из base.yaml в
        # презентационный overlay presentation.yaml, фундамент стал headless-only.
        # Тест валидирует сборку SystemBuilder.from_manifest: base ⊕ presentation
        # ⊕ pipeline — иначе gui отсутствует и chain_targets:[gui] не резолвится.
        data = merge_topologies(merge_topologies(base, presentation), pipeline)
        blueprint = SystemBlueprint.model_validate(data)

        assert blueprint.name == "hello_world"
        # base.yaml: gui + devices (always-on); pipeline: camera_0
        assert len(blueprint.processes) == 3

        proc_names = {p.process_name for p in blueprint.processes}
        assert "camera_0" in proc_names
        assert "gui" in proc_names
        assert "devices" in proc_names

    def test_topology_check_returns_no_errors(self):
        """blueprint.check() не возвращает ошибок для hello_world."""
        import yaml
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            SystemBlueprint,
        )

        topology_path = Path(__file__).parent.parent.parent / "backend" / "topology" / "hello_world.yaml"
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
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )

        cfg = ProcessConfig(process_name="test")
        assert hasattr(cfg, "process_class")
        assert cfg.process_class == ""

    def test_process_class_stored(self):
        """ProcessConfig сохраняет переданный process_class."""
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )

        cfg = ProcessConfig(
            process_name="gui",
            process_class="multiprocess_prototype.frontend.process.GuiProcess",
        )
        assert cfg.process_class == "multiprocess_prototype.frontend.process.GuiProcess"

    def test_as_generic_config_passes_process_class(self):
        """as_generic_config() передаёт process_class в GenericProcessConfig."""
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )

        cfg = ProcessConfig(
            process_name="gui",
            process_class="multiprocess_prototype.frontend.process.GuiProcess",
            plugins=[],
        )
        generic = cfg.as_generic_config()

        assert generic.process_class == "multiprocess_prototype.frontend.process.GuiProcess"

    def test_as_generic_config_default_class_when_empty(self):
        """as_generic_config() с пустым process_class сохраняет дефолтный GenericProcess путь."""
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            ProcessConfig,
        )

        cfg = ProcessConfig(process_name="default_proc", plugins=[])
        generic = cfg.as_generic_config()

        # Дефолт из GenericProcessConfig
        assert "GenericProcess" in generic.process_class


# ============================================================================
# TestDataReceiverErrorRecovery
# ============================================================================


class TestDataReceiverErrorRecovery:
    """Тесты exponential backoff и error recovery в цикле приёма (настоящий ``FrameIntake``)."""

    def _make_intake(self, receive):
        """Настоящий FrameIntake с фейковыми колбэками; sleep не передан -> time.sleep модуля frame_intake."""
        from multiprocess_prototype.frontend.frame_intake import FrameIntake

        callbacks = {
            "put": MagicMock(name="put"),
            "log_info": MagicMock(name="log_info"),
            "log_critical": MagicMock(name="log_critical"),
            "track_error": MagicMock(name="track_error"),
            "record_metric": MagicMock(name="record_metric"),
        }
        intake = FrameIntake(
            receive,
            callbacks["put"],
            callbacks["log_info"],
            callbacks["log_critical"],
            callbacks["track_error"],
            callbacks["record_metric"],
        )
        return intake, callbacks

    def _run_loop(self, intake, stop_event, pause_event) -> None:
        """Прогнать run_loop в daemon-потоке с join-дедлайном (цикл, что может зависнуть, тест не вешает)."""
        import threading

        thread = threading.Thread(target=intake.run_loop, args=(stop_event, pause_event), daemon=True)
        thread.start()
        thread.join(5.0)
        stop_event.set()
        assert not thread.is_alive(), "run_loop не вышел за 5 с"

    def test_backoff_increases_on_errors(self):
        """Backoff растёт при последовательных ошибках."""
        import threading

        stop_event = threading.Event()
        pause_event = threading.Event()
        sleep_calls = []

        # Router всегда бросает исключение
        receive = MagicMock(side_effect=RuntimeError("сетевая ошибка"))
        intake, _ = self._make_intake(receive)

        def fake_sleep(seconds):
            sleep_calls.append(seconds)
            # После 3-й ошибки останавливаем цикл
            if len(sleep_calls) >= 3:
                stop_event.set()

        with patch("multiprocess_prototype.frontend.frame_intake.time") as mock_time:
            mock_time.sleep.side_effect = fake_sleep
            self._run_loop(intake, stop_event, pause_event)

        # Проверяем что backoff растёт: 0.1 → 0.2 → 0.4
        assert len(sleep_calls) >= 2
        assert sleep_calls[0] < sleep_calls[1], "Backoff должен расти"

    def test_counter_resets_on_success(self):
        """Counter сбрасывается после успешного получения сообщений."""
        import threading

        stop_event = threading.Event()
        pause_event = threading.Event()

        # Сценарий: ошибка → успех → стоп
        step = [0]

        def side_effect(**kwargs):
            step[0] += 1
            if step[0] == 1:
                raise RuntimeError("ошибка")
            # шаг 2: успешный receive → после этого ставим stop
            stop_event.set()
            return [{"data_type": "frame"}]

        intake, callbacks = self._make_intake(MagicMock(side_effect=side_effect))

        with patch("multiprocess_prototype.frontend.frame_intake.time") as mock_time:
            mock_time.sleep.return_value = None  # sleep ничего не делает
            self._run_loop(intake, stop_event, pause_event)

        # log_info должен быть вызван с сообщением о восстановлении
        recovery_calls = [call for call in callbacks["log_info"].call_args_list if "восстановление" in str(call)]
        assert len(recovery_calls) == 1

    def test_critical_after_threshold(self):
        """log_critical вызывается ровно при достижении порога 5 ошибок подряд."""
        import threading

        stop_event = threading.Event()
        pause_event = threading.Event()
        error_count = [0]

        intake, callbacks = self._make_intake(MagicMock(side_effect=RuntimeError("постоянная ошибка")))

        with patch("multiprocess_prototype.frontend.frame_intake.time") as mock_time:

            def fake_sleep(seconds):
                error_count[0] += 1
                if error_count[0] >= 6:
                    stop_event.set()

            mock_time.sleep.side_effect = fake_sleep
            self._run_loop(intake, stop_event, pause_event)

        # log_critical должен быть вызван ровно 1 раз (при consecutive == 5)
        assert callbacks["log_critical"].call_count == 1
        call_args = callbacks["log_critical"].call_args
        assert "5" in str(call_args)

    def test_track_error_called(self):
        """track_error вызывается при каждой ошибке с правильным контекстом."""
        import threading

        stop_event = threading.Event()
        pause_event = threading.Event()

        intake, callbacks = self._make_intake(MagicMock(side_effect=ValueError("тест")))

        with patch("multiprocess_prototype.frontend.frame_intake.time") as mock_time:
            call_cnt = [0]

            def fake_sleep(seconds):
                call_cnt[0] += 1
                if call_cnt[0] >= 2:
                    stop_event.set()

            mock_time.sleep.side_effect = fake_sleep
            self._run_loop(intake, stop_event, pause_event)

        # track_error вызван для каждой ошибки
        assert callbacks["track_error"].call_count >= 2

        # Проверяем контекст первого вызова
        first_call = callbacks["track_error"].call_args_list[0]
        exc_arg = first_call[0][0]
        ctx_arg = first_call[1].get("context") or first_call[0][1]
        assert isinstance(exc_arg, ValueError)
        assert ctx_arg["loop"] == "data_receiver"
        assert "consecutive" in ctx_arg

    def test_record_metric_on_error_and_success(self):
        """record_metric вызывается при ошибках ('data_receiver.errors') и успехе ('data_receiver.success')."""
        import threading

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

        intake, callbacks = self._make_intake(MagicMock(side_effect=side_effect))

        with patch("multiprocess_prototype.frontend.frame_intake.time") as mock_time:
            mock_time.sleep.return_value = None  # sleep мгновенный
            self._run_loop(intake, stop_event, pause_event)

        metric_names = [call[0][0] for call in callbacks["record_metric"].call_args_list]
        assert "data_receiver.errors" in metric_names
        assert "data_receiver.success" in metric_names


class TestRequestSystemShutdown:
    """GuiProcess._request_system_shutdown — закрытие GUI гасит всю систему.

    Task 1.1: первые три теста — путь БЕЗ координатора (``shutdown_sent`` по умолчанию
    False: сбой отправки, backend_gone, старый запуск). Когда CloseCoordinator уже отправил
    system.shutdown, путь другой — ``test_no_event_when_coordinator_sent_shutdown``.
    """

    def test_sets_system_stop_event_when_available(self):
        """Основной путь: взводит ОБЩИЙ system_stop_event, IPC НЕ шлёт."""
        import threading

        from multiprocess_prototype.frontend.process import GuiProcess

        ev = threading.Event()
        sr = _make_mock_shared_resources()
        sr.get_system_stop_event.return_value = ev
        process = GuiProcess(name="gui", shared_resources=sr)
        process.send_message = MagicMock()
        process._log_info = MagicMock()
        assert process.shutdown_sent is False  # путь без координатора

        process._request_system_shutdown()

        assert ev.is_set(), "общий system_stop_event должен быть взведён"
        process.send_message.assert_not_called()  # IPC не нужен — event основной путь

    def test_fallback_ipc_when_no_event(self):
        """Fallback: общий event не проброшен → IPC command='process.command' с system.shutdown."""
        from multiprocess_prototype.frontend.process import GuiProcess

        sr = _make_mock_shared_resources()  # get_process_data → None → нет event
        process = GuiProcess(name="gui", shared_resources=sr)
        process.send_message = MagicMock()
        process._log_info = MagicMock()
        process._log_warning = MagicMock()
        assert process.shutdown_sent is False  # путь без координатора

        process._request_system_shutdown()

        process.send_message.assert_called_once()
        target, msg = process.send_message.call_args[0]
        assert target == "ProcessManager"
        assert msg["command"] == "process.command"
        assert msg["targets"] == ["ProcessManager"]
        assert msg["data"] == {"cmd": "system.shutdown"}
        assert msg["sender"] == "gui"

    def test_best_effort_swallows_send_error(self):
        """Ошибка send_message на выходе не пробрасывается (best-effort), логируется warning."""
        from multiprocess_prototype.frontend.process import GuiProcess

        sr = _make_mock_shared_resources()
        process = GuiProcess(name="gui", shared_resources=sr)
        process.send_message = MagicMock(side_effect=RuntimeError("router closed"))
        process._log_info = MagicMock()
        process._log_warning = MagicMock()
        assert process.shutdown_sent is False  # путь без координатора

        process._request_system_shutdown()  # не должно бросить

        process._log_warning.assert_called_once()

    def test_no_event_when_coordinator_sent_shutdown(self):
        """Координатор закрытия уже отправил system.shutdown (shutdown_sent) → общий event НЕ взводится."""
        import threading

        from multiprocess_prototype.frontend.process import GuiProcess

        ev = threading.Event()
        sr = _make_mock_shared_resources()
        sr.get_system_stop_event.return_value = ev
        process = GuiProcess(name="gui", shared_resources=sr)
        process.send_message = MagicMock()
        process._log_info = MagicMock()
        process._log_warning = MagicMock()
        process.shutdown_sent = True

        process._request_system_shutdown()

        assert not ev.is_set(), "после отправки shutdown координатором общий system_stop_event взводить нельзя"

    def test_no_ipc_fallback_when_coordinator_sent_shutdown(self):
        """shutdown_sent и общего event нет (старый launch): IPC-команда system.shutdown НЕ шлётся."""
        from multiprocess_prototype.frontend.process import GuiProcess

        sr = _make_mock_shared_resources()  # get_system_stop_event → None: event недоступен
        process = GuiProcess(name="gui", shared_resources=sr)
        process.send_message = MagicMock()
        process._log_info = MagicMock()
        process._log_warning = MagicMock()
        process.shutdown_sent = True

        process._request_system_shutdown()

        process.send_message.assert_not_called()


class TestGuiProcessSubscriptions:
    """GuiProcess подписывается на нужные пути StateStore.

    Баг #1: отсутствие подписки devices.** блокировало push-дельты реестра
    устройств → комбо DeviceComboController оставалось пустым.
    """

    def _run_init_threads_with_mock_proxy(self, process):
        """Запустить _init_application_threads и вернуть список подписанных путей.

        GuiStateProxy импортируется внутри функции (локальный import), поэтому
        патчим по полному пути модуля, а не по имени в process-модуле.
        """
        subscribed_paths: list[str] = []
        mock_proxy = MagicMock()
        mock_proxy.subscribe.side_effect = lambda path, *a, **kw: subscribed_paths.append(path)

        with (
            patch(
                "multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy.GuiStateProxy.__init__",
                return_value=None,
            ),
            patch(
                "multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy.GuiStateProxy.initialize",
            ),
            patch(
                "multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy.GuiStateProxy.subscribe",
                side_effect=lambda path, *a, **kw: subscribed_paths.append(path),
            ),
        ):
            process._init_application_threads()

        return subscribed_paths

    def test_subscriptions_include_devices(self):
        """_init_application_threads подписывается на devices.**."""
        from multiprocess_prototype.frontend.process import GuiProcess

        sr = _make_mock_shared_resources()
        process = GuiProcess(name="gui", shared_resources=sr)

        process._init_configuration = MagicMock()
        process._init_queues = MagicMock()
        process._init_managers = MagicMock()
        process._init_communication = MagicMock()
        process._register_process_state = MagicMock()
        process._init_system_threads = MagicMock()
        process._init_custom_managers = MagicMock()
        process.update_process_state = MagicMock()
        process.worker_manager = MagicMock()
        # router_manager нужен для register_message_handler
        process.router_manager = MagicMock()

        subscribed_paths = self._run_init_threads_with_mock_proxy(process)

        # Обязательные подписки
        assert "processes.**" in subscribed_paths, "подписка processes.** отсутствует"
        assert "system.**" in subscribed_paths, "подписка system.** отсутствует"
        assert "devices.**" in subscribed_paths, (
            "подписка devices.** отсутствует — push-дельты реестра устройств не дойдут до GUI"
        )
        assert "calibration.**" in subscribed_paths, (
            "подписка calibration.** отсутствует — прогресс визарда калибровки не дойдёт до GUI"
        )

    def test_subscriptions_all_four_present(self):
        """Подписок ровно четыре: processes/system/devices/calibration."""
        from multiprocess_prototype.frontend.process import GuiProcess

        sr = _make_mock_shared_resources()
        process = GuiProcess(name="gui", shared_resources=sr)

        process._init_configuration = MagicMock()
        process._init_queues = MagicMock()
        process._init_managers = MagicMock()
        process._init_communication = MagicMock()
        process._register_process_state = MagicMock()
        process._init_system_threads = MagicMock()
        process._init_custom_managers = MagicMock()
        process.update_process_state = MagicMock()
        process.worker_manager = MagicMock()
        process.router_manager = MagicMock()

        subscribed_paths = self._run_init_threads_with_mock_proxy(process)

        assert set(subscribed_paths) >= {"processes.**", "system.**", "devices.**", "calibration.**"}


class TestStateDeltasToBridge:
    """GuiProcess._on_state_deltas_to_bridge: дельты StateStore → bridge.dispatch(state_delta).

    Task 1.1 (telemetry-A): _StateDeltaEmitter + invokeMethod удалены; дельты гонятся
    через тот же DataReceiverBridge, что и кадры (delta_sink из GuiStateProxy).
    """

    @pytest.fixture(autouse=True)
    def _setup_qapp(self, qapp):
        pass

    def test_sink_converts_deltas_to_state_delta(self, qtbot):
        from types import SimpleNamespace

        from multiprocess_framework.modules.state_store_module.core.delta import Delta
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.process import GuiProcess

        bridge = DataReceiverBridge()
        states = []
        bridge.state_updated.connect(states.append)

        # _on_state_deltas_to_bridge нужен только self._bridge — лёгкий stand-in
        fake = SimpleNamespace(_bridge=bridge)
        deltas = [
            Delta(
                path="processes.cam.workers.w1.status",
                old_value="init",
                new_value="running",
                source="camera_0",
                transaction_id="tx-1",
            ),
            Delta(
                path="processes.cam.workers.w1.effective_hz",
                old_value=10.0,
                new_value=12.5,
                source="camera_0",
                transaction_id="tx-1",
            ),
        ]
        GuiProcess._on_state_deltas_to_bridge(fake, deltas)

        assert len(states) == 2
        assert states[0]["data_type"] == "state_delta"
        assert states[0]["path"] == "processes.cam.workers.w1.status"
        assert states[0]["value"] == "running"
        assert states[0]["deleted"] is False
        assert states[0]["old_value"] == "init"
        # transaction_id больше не теряется (акцептанс 5.9)
        assert states[0]["transaction_id"] == "tx-1"
        assert states[0]["source"] == "camera_0"
        assert states[1]["path"] == "processes.cam.workers.w1.effective_hz"
        assert states[1]["value"] == 12.5

    def test_sink_delete_delta_marked_deleted(self, qtbot):
        """Удаление узла (new_value=MISSING) → deleted=True, value=None (не sentinel)."""
        from types import SimpleNamespace

        from multiprocess_framework.modules.state_store_module.core.delta import (
            MISSING,
            Delta,
        )
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.process import GuiProcess

        bridge = DataReceiverBridge()
        states = []
        bridge.state_updated.connect(states.append)

        delta = Delta(
            path="processes.cam.workers.w1.status",
            old_value="running",
            new_value=MISSING,
            source="camera_0",
            transaction_id="tx-del",
        )
        GuiProcess._on_state_deltas_to_bridge(SimpleNamespace(_bridge=bridge), [delta])

        assert len(states) == 1
        assert states[0]["deleted"] is True
        assert states[0]["value"] is None  # sentinel MISSING не протекает в GUI
        assert states[0]["old_value"] == "running"
        assert states[0]["transaction_id"] == "tx-del"

    def test_sink_empty_deltas_noop(self, qtbot):
        from types import SimpleNamespace

        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.process import GuiProcess

        bridge = DataReceiverBridge()
        states = []
        bridge.state_updated.connect(states.append)

        GuiProcess._on_state_deltas_to_bridge(SimpleNamespace(_bridge=bridge), [])
        assert states == []

    def test_delta_delivery_crosses_io_to_qt_thread(self, qtbot):
        """Регрессия Task 1.1: state.changed из НЕ-main потока доставляется в Qt main thread.

        Воспроизводит точную поломку, которую чинит фикс: раньше переход IO→Qt шёл
        через QMetaObject.invokeMethod(_StateDeltaEmitter) и МОЛЧА терялся в PySide6 6.10.
        Теперь GuiStateProxy.on_state_changed (вызванный из отдельного Python-потока,
        как message_processor) → delta_sink → bridge.dispatch → _deliver.emit
        (QueuedConnection) надёжно пересекает поток, как у кадров.
        """
        import threading

        from multiprocess_framework.modules.state_store_module.core.delta import Delta
        from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import (
            GuiStateProxy,
        )
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge

        bridge = DataReceiverBridge()
        received: list = []
        bridge.state_updated.connect(received.append)

        # delta_sink идентичен GuiProcess._on_state_deltas_to_bridge
        def sink(deltas: list) -> None:
            for d in deltas:
                bridge.dispatch({"data_type": "state_delta", "path": d.path, "value": d.new_value})

        proxy = GuiStateProxy("gui", router=None, delta_sink=sink)
        msg = {
            "command": "state.changed",
            "data": {
                "deltas": [
                    Delta(
                        path="processes.cam.state.status",
                        old_value="initializing",
                        new_value="running",
                        source="ProcessManager",
                    ).to_dict()
                ]
            },
        }

        # Вызов из ОТДЕЛЬНОГО потока (не main, не QThread) — как message_processor в IO.
        t = threading.Thread(target=proxy.on_state_changed, args=(msg,))
        t.start()
        t.join()

        # Доставка поставлена в очередь Qt main thread — прокачиваем event loop.
        qtbot.waitUntil(lambda: len(received) == 1, timeout=2000)
        assert received[0]["data_type"] == "state_delta"
        assert received[0]["path"] == "processes.cam.state.status"
        assert received[0]["value"] == "running"
        # кэш обновлён в потоке-источнике (до пересечения границы)
        assert proxy.cache["processes.cam.state.status"] == "running"


# ============================================================================
# test_on_command_response — сток отказов ProcessManager (GATE G4)
# ============================================================================


class TestOnCommandResponse:
    """GuiProcess._on_command_response: отказ PM не должен пропадать бесследно.

    Мотивация теста — дефект, найденный ревью: handler читал причину из
    ``message["data"]["result"]``, а ``reply_to_request`` кладёт ``result`` на
    ВЕРХНИЙ уровень ответа. Тестов не было, поэтому ошибку не поймали: WARNING
    писался всегда с «причина не указана». Здесь фиксируем реальную форму.
    """

    @staticmethod
    def _make_process() -> "object":
        """GuiProcess без запуска: интересует только метод-handler."""
        from multiprocess_prototype.frontend.process import GuiProcess

        proc = GuiProcess.__new__(GuiProcess)
        proc._log_warning = MagicMock()  # type: ignore[attr-defined]
        return proc

    def test_failure_logs_reason_from_top_level_result(self) -> None:
        """success=False + result.reason на верхнем уровне → WARNING с причиной."""
        proc = self._make_process()
        proc._on_command_response(  # type: ignore[attr-defined]
            {
                "type": "response",
                "command": "process.command.response",
                "request_id": "abc-123",
                "success": False,
                "result": {"status": "error", "reason": "No handler for key 'process.hot_add'"},
            }
        )
        proc._log_warning.assert_called_once()  # type: ignore[attr-defined]
        text = proc._log_warning.call_args[0][0]  # type: ignore[attr-defined]
        assert "No handler for key 'process.hot_add'" in text
        assert "abc-123" in text

    def test_success_is_silent(self) -> None:
        """Успешный ответ не логируется — иначе шум на каждую команду."""
        proc = self._make_process()
        proc._on_command_response({"success": True, "result": {"ok": 1}})  # type: ignore[attr-defined]
        proc._log_warning.assert_not_called()  # type: ignore[attr-defined]

    def test_missing_success_key_is_treated_as_success(self) -> None:
        """Ответ без ключа success считаем успехом — не шумим на чужих формах."""
        proc = self._make_process()
        proc._on_command_response({"result": {"ok": 1}})  # type: ignore[attr-defined]
        proc._log_warning.assert_not_called()  # type: ignore[attr-defined]

    def test_non_dict_message_is_noop(self) -> None:
        """Не-dict не роняет приёмный поток."""
        proc = self._make_process()
        proc._on_command_response("мусор")  # type: ignore[attr-defined]
        proc._on_command_response(None)  # type: ignore[attr-defined]
        proc._log_warning.assert_not_called()  # type: ignore[attr-defined]

    def test_failure_without_reason_still_logs(self) -> None:
        """Отказ без причины всё равно виден — молчать про неуспех нельзя."""
        proc = self._make_process()
        proc._on_command_response({"success": False, "result": None})  # type: ignore[attr-defined]
        proc._log_warning.assert_called_once()  # type: ignore[attr-defined]
        assert "причина не указана" in proc._log_warning.call_args[0][0]  # type: ignore[attr-defined]

    def test_legacy_nested_result_still_read(self) -> None:
        """Fallback на data.result — совместимость с legacy-обёрткой."""
        proc = self._make_process()
        proc._on_command_response(  # type: ignore[attr-defined]
            {"success": False, "data": {"result": {"reason": "legacy-форма"}}}
        )
        assert "legacy-форма" in proc._log_warning.call_args[0][0]  # type: ignore[attr-defined]
