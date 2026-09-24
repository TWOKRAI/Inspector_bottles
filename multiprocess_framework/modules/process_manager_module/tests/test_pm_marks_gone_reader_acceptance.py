# -*- coding: utf-8 -*-
"""Task 1.2 (`plans/lifecycle-stop-ownership.md`) — независимый акцептанс, ДО реализации.

PM должен взводить метку «читатель ушёл навсегда» (``ReaderGoneQueue``) на очередях
ребёнка, которого он сам остановил/убил НАВСЕГДА (``ProcessRegistry.stop_one``/
``stop_many``), а не только сам ребёнок на системном стопе (это уже покрыто
``test_writer_outlives_reader_acceptance.py`` — сюда не дублируется). При рестарте
метку взводить НЕЛЬЗЯ (очереди переиспользуются), а новая инкарнация обязана
получить метку СНЯТОЙ ДО спавна. PM обязан отказывать в спавне после системного
стопа.

Тесты пишутся вслепую по брифу (design), без чтения реализации — источник
поведения на этом дереве ДО фикса:
  * ``ProcessRegistry.stop_one``/``stop_many`` НЕ принимают ``mark_reader_gone`` и
    НЕ трогают очереди вообще.
  * ``ProcessRegistry.create_and_register`` НЕ снимает метку.
  * ``ProcessManagerProcess.stop_process``/``restart_process``/``start_process``/
    ``create_process`` НЕ знают о системном стопе и НЕ принимают
    ``mark_reader_gone``.
  * ``reader_gone.set_reader_gone`` не существует.
"""

from __future__ import annotations

import multiprocessing
import time
from typing import Any
from unittest.mock import MagicMock, patch

from multiprocess_framework.modules.process_manager_module.runner.process_runner import (
    run_process_function,
)
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ..core.process_registry import ProcessRegistry
from ..process.process_manager_process import ProcessManagerProcess

# ---------------------------------------------------------------------------
# Top-level классы дочерних процессов (spawn пиклит цель по dotted-пути).
# ---------------------------------------------------------------------------


class _ReaderIgnoresEverything:
    """Читатель владеет очередью 'data', но НИКОГДА не доходит до наблюдения за
    stop_event — ``run()`` блокируется навсегда. Регистр обязан эскалировать до
    terminate/kill, чтобы его остановить (никакого штатного выхода, значит
    собственный exit-hook читателя никогда не отработает — метку обязан взвести
    ИМЕННО регистр, со своей стороны)."""

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        time.sleep(120)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _ReaderHonorsStop:
    """Читатель владеет очередью 'data', ``run()`` возвращается сразу, штатно
    ждёт СВОЙ ``stop_event`` (framework lifecycle) — graceful-остановка."""

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        pass

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _ReaderExitsImmediately:
    """Читатель выходит САМ, ещё до того, как кто-либо позвал ``stop_one``/
    ``stop_many`` — сценарий «ребёнок уже мёртв на момент опроса»."""

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        pass

    def should_stop(self) -> bool:
        return True

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _SendBigFrameThenWaitForStop:
    """Писатель: кладёт ОДНО сообщение 1 MiB продовым путём
    (``queue_registry.send_to_queue``) соседу 'Reader' через ``routing_map``,
    затем штатно ждёт СВОЙ ``stop_event`` — framework-путь выхода."""

    TARGET_PROCESS = "Reader"
    QUEUE_TYPE = "data"
    PAYLOAD = b"x" * (1024 * 1024)  # 1 MiB — заведомо больше OS pipe buffer

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name
        self.shared_resources = shared_resources

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        self.shared_resources.queue_registry.send_to_queue(self.TARGET_PROCESS, self.QUEUE_TYPE, self.PAYLOAD)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _class_path(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _cleanup(*procs) -> None:
    for proc in procs:
        if proc is None:
            continue
        try:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=3.0)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=3.0)
        except Exception:
            pass


def _close_queue(q) -> None:
    try:
        q.close()
        q.cancel_join_thread()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# (1) Ребёнок, убитый регистром (terminate/kill) — писатель обязан выйти быстро.
# ---------------------------------------------------------------------------


class TestKilledReaderWriterExitsUnder2s:
    def test_killed_reader_writer_exits_under_2s(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        srm = SharedResourcesManager()
        assert srm.initialize()
        assert srm.register_process("Reader", {"queues": {"data": {}}})
        q = srm.queue_registry.get_process_queues("Reader")["data"]

        registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)

        reader_stop = ctx.Event()
        writer_stop = ctx.Event()

        reader_bundle = {"queues": {"data": q}, "config": {}, "custom": {}}
        writer_bundle = {
            "queues": {},
            "config": {},
            "custom": {},
            "routing_map": {"Reader": {"data": q}},
        }

        reader = ctx.Process(
            target=run_process_function,
            args=(_class_path(_ReaderIgnoresEverything), "Reader", reader_stop, reader_bundle, None),
            name="Reader",
        )
        writer = ctx.Process(
            target=run_process_function,
            args=(_class_path(_SendBigFrameThenWaitForStop), "Writer", writer_stop, writer_bundle, None),
            name="Writer",
        )
        registry.add_process(reader)
        registry._stop_events["Reader"] = reader_stop

        try:
            reader.start()
            writer.start()
            time.sleep(0.3)  # writer.run() успевает отправить 1 MiB, reader никогда не читает

            stopped = registry.stop_one("Reader", timeout=0.5)
            assert stopped is True, "reader должен быть подтверждён мёртвым (terminate/kill)"
            assert not reader.is_alive()

            assert q.is_reader_gone() is True, (
                "stop_one должен взвести метку «читатель ушёл навсегда» на очередях "
                "убитого им ребёнка — иначе писатель зависнет в exit-hook"
            )

            start = time.monotonic()
            writer_stop.set()
            writer.join(timeout=2.0)
            elapsed = time.monotonic() - start
            alive = writer.is_alive()

            assert not alive, f"writer не вышел за 2.0s после убийства reader'а регистром; elapsed={elapsed:.3f}s"
            assert elapsed < 2.0, f"writer вышел за {elapsed:.3f}s (>= 2.0s)"
        finally:
            _cleanup(reader, writer)
            _close_queue(q)


# ---------------------------------------------------------------------------
# (2) Graceful индивидуальный стоп через регистр — тоже помечает.
# ---------------------------------------------------------------------------


class TestStopMarksConfirmedDeadReaderQueue:
    def test_stop_marks_confirmed_dead_reader_queue(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        srm = SharedResourcesManager()
        assert srm.initialize()
        assert srm.register_process("Reader", {"queues": {"data": {}}})
        q = srm.queue_registry.get_process_queues("Reader")["data"]

        registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)

        reader_stop = ctx.Event()
        reader_bundle = {"queues": {"data": q}, "config": {}, "custom": {}}
        reader = ctx.Process(
            target=run_process_function,
            args=(_class_path(_ReaderHonorsStop), "Reader", reader_stop, reader_bundle, None),
            name="Reader",
        )
        registry.add_process(reader)
        registry._stop_events["Reader"] = reader_stop

        try:
            reader.start()
            time.sleep(0.2)

            stopped = registry.stop_one("Reader", timeout=2.0)
            assert stopped is True
            assert not reader.is_alive()

            assert q.is_reader_gone() is True, (
                "graceful индивидуальный стоп через регистр — тоже подтверждённая смерть, метка обязана взводиться"
            )
        finally:
            _cleanup(reader)
            _close_queue(q)


# ---------------------------------------------------------------------------
# (3) Флаг mark_reader_gone=False — метку НЕ трогает.
# ---------------------------------------------------------------------------


class TestStopWithFlagFalseDoesNotMark:
    def test_stop_with_flag_false_does_not_mark(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        srm = SharedResourcesManager()
        assert srm.initialize()
        assert srm.register_process("Reader", {"queues": {"data": {}}})
        q = srm.queue_registry.get_process_queues("Reader")["data"]

        registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)

        reader_stop = ctx.Event()
        reader_bundle = {"queues": {"data": q}, "config": {}, "custom": {}}
        reader = ctx.Process(
            target=run_process_function,
            args=(_class_path(_ReaderHonorsStop), "Reader", reader_stop, reader_bundle, None),
            name="Reader",
        )
        registry.add_process(reader)
        registry._stop_events["Reader"] = reader_stop

        try:
            reader.start()
            time.sleep(0.2)

            stopped = registry.stop_one("Reader", timeout=2.0, mark_reader_gone=False)
            assert stopped is True
            assert not reader.is_alive()
            assert q.is_reader_gone() is False, "mark_reader_gone=False обязан оставить метку нетронутой"
        finally:
            _cleanup(reader)
            _close_queue(q)


# ---------------------------------------------------------------------------
# (4) stop_many помечает и того, кто уже умер сам к моменту опроса.
# ---------------------------------------------------------------------------


class TestStopManyMarksAlreadyDeadChild:
    def test_stop_many_marks_already_dead_child(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        srm = SharedResourcesManager()
        assert srm.initialize()
        assert srm.register_process("Reader", {"queues": {"data": {}}})
        q = srm.queue_registry.get_process_queues("Reader")["data"]

        registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)

        reader_bundle = {"queues": {"data": q}, "config": {}, "custom": {}}
        reader = ctx.Process(
            target=run_process_function,
            args=(_class_path(_ReaderExitsImmediately), "Reader", None, reader_bundle, None),
            name="Reader",
        )
        registry.add_process(reader)

        try:
            reader.start()
            reader.join(timeout=5.0)
            assert not reader.is_alive(), "reader не вышел сам за 5.0s — тест не смог подготовить сценарий"

            result = registry.stop_many(["Reader"])
            assert result == {"Reader": True}
            assert q.is_reader_gone() is True, (
                "уже мёртвый к моменту опроса ребёнок — тоже «confirmed dead», метка обязана взводиться"
            )
        finally:
            _cleanup(reader)
            _close_queue(q)


# ---------------------------------------------------------------------------
# (5) create_and_register снимает метку ДО спавна новой инкарнации.
# ---------------------------------------------------------------------------


class TestCreateAndRegisterClearsMark:
    def test_create_and_register_clears_mark(self) -> None:
        srm = SharedResourcesManager()
        assert srm.initialize()
        assert srm.register_process("Reader", {"queues": {"data": {}}})
        q = srm.queue_registry.get_process_queues("Reader")["data"]

        registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)

        try:
            q.mark_reader_gone()
            assert q.is_reader_gone() is True

            # class_path заведомо не спавнится в этом тесте (process.start() не зовётся) —
            # валидность dotted-пути проверяется только внутри run_process_function.
            process = registry.create_and_register("Reader", "os.getpid", {"queues": {"data": {}}}, "normal")
            assert process is not None

            assert q.is_reader_gone() is False, (
                "create_and_register обязан снять метку ДО спавна — новая инкарнация "
                "на переиспользованной очереди это живой читатель"
            )
        finally:
            _close_queue(q)


# ---------------------------------------------------------------------------
# (6) PM.restart_process — снимает флаг marking при остановке старой инкарнации.
# ---------------------------------------------------------------------------


class TestRestartProcessDoesNotMark:
    def test_restart_process_does_not_mark_and_new_incarnation_reads_intact(self) -> None:
        """Полный реальный restart_process тянет за собой ~10 несвязанных внутренностей
        PM (wire reissue, routing epoch, telemetry replay) — построение их всех не
        относится к контракту Task 1.2. Пин — на КОНТРАКТ вызова: ``restart_process``
        обязан звать ``stop_process(name, mark_reader_gone=False)`` (иначе отпущенный
        посреди записи кадр испортил бы поток новой инкарнации). Последний резерв
        по брифу — заявлено явно."""
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp._process_configs = {"Reader": {"class": "os.getpid", "priority": "normal"}}
            pmp._process_registry = MagicMock()
            pmp._process_registry.create_and_register.return_value = MagicMock()
            pmp._process_registry.remove_process = MagicMock()
            pmp._wire_reissue_enabled = lambda: False
            pmp._process_queue_ids = lambda name: {}
            pmp._bump_incarnation = MagicMock()
            pmp._priority = MagicMock()
            pmp.get_config = lambda k: None
            pmp._mark_instance_started = MagicMock()
            pmp._wait_processes_ready = MagicMock()
            pmp._bump_routing_epoch = MagicMock()
            pmp._broadcast_routing_refresh = MagicMock()
            pmp._publish_process_identity = MagicMock()
            pmp._replay_telemetry_runtime_delta = MagicMock()
            pmp._instance_restarts = {}
            pmp._log_info = lambda *a, **k: True
            pmp._log_error = lambda *a, **k: True
            pmp._log_warning = lambda *a, **k: True
            pmp.stop_process = MagicMock(return_value=True)

            result = pmp.restart_process("Reader")

            assert result is True
            pmp.stop_process.assert_called_once_with("Reader", mark_reader_gone=False)


# ---------------------------------------------------------------------------
# (7) PM отказывает в спавне после системного стопа.
# ---------------------------------------------------------------------------


class TestSpawnRefusedAfterSystemStop:
    def test_spawn_refused_after_system_stop(self) -> None:
        stop_evt = multiprocessing.Event()
        stop_evt.set()

        # (a) create_process
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp._process_configs = {}
            pmp._process_registry = MagicMock()
            pmp._priority = MagicMock()
            pmp._system_stop_event = stop_evt
            pmp._log_info = lambda *a, **k: True
            pmp._log_error = lambda *a, **k: True
            pmp._log_warning = lambda *a, **k: True

            result_create = pmp.create_process("X", "os.getpid", {}, "normal")
            assert not result_create, "create_process обязан отказать после системного стопа"
            pmp._process_registry.create_and_register.assert_not_called()

        # (b) start_process (без имени — «стартовать всех»)
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp2 = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp2.name = "ProcessManager"
            pmp2.shared_resources = None
            pmp2.config = {}
            pmp2._process_registry = MagicMock()
            pmp2._process_registry.os_processes = []
            pmp2._priority = MagicMock()
            pmp2._system_stop_event = stop_evt
            pmp2._log_info = lambda *a, **k: True
            pmp2._log_error = lambda *a, **k: True
            pmp2._log_warning = lambda *a, **k: True

            result_start = pmp2.start_process()
            assert not result_start, "start_process обязан отказать после системного стопа"
            pmp2._process_registry.start_all.assert_not_called()

        # (c) restart_process — те же заглушки, что в тесте 6 (без них restart_process
        # падает на несвязанных внутренностях PM ДО того, как дойдёт до проверяемого
        # места: _wire_reissue_enabled/get_config лезут в несуществующий
        # config_handler, если restart_process не отказал сразу).
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp3 = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp3.name = "ProcessManager"
            pmp3.shared_resources = None
            pmp3.config = {}
            pmp3._process_configs = {"Reader": {"class": "os.getpid", "priority": "normal"}}
            pmp3._process_registry = MagicMock()
            pmp3._process_registry.create_and_register.return_value = MagicMock()
            pmp3._process_registry.remove_process = MagicMock()
            pmp3._wire_reissue_enabled = lambda: False
            pmp3._process_queue_ids = lambda name: {}
            pmp3._bump_incarnation = MagicMock()
            pmp3._priority = MagicMock()
            pmp3.get_config = lambda k: None
            pmp3._mark_instance_started = MagicMock()
            pmp3._wait_processes_ready = MagicMock()
            pmp3._bump_routing_epoch = MagicMock()
            pmp3._broadcast_routing_refresh = MagicMock()
            pmp3._publish_process_identity = MagicMock()
            pmp3._replay_telemetry_runtime_delta = MagicMock()
            pmp3._instance_restarts = {}
            pmp3._log_info = lambda *a, **k: True
            pmp3._log_error = lambda *a, **k: True
            pmp3._log_warning = lambda *a, **k: True
            pmp3.stop_process = MagicMock(return_value=True)
            pmp3._system_stop_event = stop_evt

            result_restart = pmp3.restart_process("Reader")
            assert not result_restart, "restart_process обязан отказать после системного стопа"
            pmp3._process_registry.create_and_register.assert_not_called()


# ---------------------------------------------------------------------------
# (8) Хелпер set_reader_gone — считает и игнорирует не-ReaderGoneQueue.
# ---------------------------------------------------------------------------


class TestSetReaderGoneHelper:
    def test_set_reader_gone_helper_counts_and_ignores_plain_queue(self) -> None:
        from multiprocessing import Queue as PlainQueue

        from multiprocess_framework.modules.shared_resources_module.queues.core.reader_gone import (
            ReaderGoneQueue,
            set_reader_gone,
        )

        q1 = ReaderGoneQueue()
        q2 = ReaderGoneQueue()
        plain = PlainQueue()
        try:
            count = set_reader_gone([q1, q2, plain, "not-a-queue"], True)
            assert count == 2, "set_reader_gone обязан считать только ReaderGoneQueue"
            assert q1.is_reader_gone() is True
            assert q2.is_reader_gone() is True

            count2 = set_reader_gone([q1], False)
            assert count2 == 1
            assert q1.is_reader_gone() is False
        finally:
            _close_queue(q1)
            _close_queue(q2)
            _close_queue(plain)
