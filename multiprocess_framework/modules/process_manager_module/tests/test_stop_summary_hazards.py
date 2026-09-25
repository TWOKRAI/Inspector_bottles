# -*- coding: utf-8 -*-
"""Task 1.6 (ADR-PMM-033) — hazard-тесты слота отчёта выхода, автор.

Юнит-уровень, без живого стенда. Каждый тест бьёт по РЕАЛЬНОМУ
``ProcessRegistry``/``run_process_function`` (не по мокам их самих) — только
``multiprocessing.Process(...)`` не стартуется (``create_and_register`` его и не
запускает: конструктор ``Process`` не порождает OS-процесс сам по себе), и
``QueueRegistry.release_queues_at_exit`` в тесте (b) подменён точечно, чтобы
воспроизвести конкретный сбой. Ничего здесь не может зависнуть (нет реальных
процессов/потоков ожидания), поэтому дедлайн join не нужен — но следующий тест,
если добавит живой процесс, обязан завести daemon-поток + join(timeout) per
project-rules.
"""

from __future__ import annotations

from multiprocessing import Event, RawArray
from unittest.mock import patch

from ..core.process_registry import ProcessRegistry
from ..runner.process_runner import run_process_function


def test_reported_written_after_numbers_gates_reading() -> None:
    """(a) Слот с числами, но ``reported=0`` — читается как «не знаем» с нулями.

    Порядок записи в runner (``released``/``buffered_dropped`` — затем
    ``reported`` последним) существует ровно для того, чтобы ребёнок, убитый
    ПОСЕРЕДИНЕ записи (между строками), читался PM как «неизвестно», а не как
    ложные частичные числа. Тест пинит эту гарантию на СТОРОНЕ ЧТЕНИЯ:
    ``exit_report`` обязан игнорировать released/buffered_dropped, пока
    reported не выставлен.
    """
    registry = ProcessRegistry()
    slot = RawArray("q", 3)
    slot[1] = 7
    slot[2] = 3
    # slot[0] (reported) НЕ выставлен — имитация "убит между строками записи".
    registry._exit_reports["victim"] = slot

    assert registry.exit_report("victim") == {"released": 0, "buffered_dropped": 0, "reported": False}

    slot[0] = 1
    assert registry.exit_report("victim") == {"released": 7, "buffered_dropped": 3, "reported": True}


def test_release_raising_leaves_slot_unreported() -> None:
    """(b) ``release_queues_at_exit`` бросает -> слот НЕ тронут, ``reported`` остаётся 0.

    Runner пишет в слот ТОЛЬКО после успешного ``release_queues_at_exit`` (см.
    ``process_runner.py`` finally-блок) — если тот бросает, до записи слота
    вообще не доходит, и PM обязан читать это как «не знаю», не как «отпустил 0».
    """
    stop_event = Event()
    stop_event.set()  # лайфцикл выходит немедленно — process_instance.run()/should_stop()

    slot = RawArray("q", 3)
    bundle = {"queues": {}, "config": {}, "custom": {}}

    class _NoopProcess:
        def initialize(self) -> bool:
            return True

        def run(self) -> None:
            pass

        def should_stop(self) -> bool:
            return True

        def shutdown(self) -> None:
            pass

    with (
        patch(
            "multiprocess_framework.modules.process_manager_module.runner.process_runner._load_process_class"
        ) as mock_load,
        patch(
            "multiprocess_framework.modules.shared_resources_module.queues.core.manager.QueueRegistry"
            ".release_queues_at_exit",
            side_effect=RuntimeError("boom: release упал (инъекция теста)"),
        ),
    ):
        mock_load.return_value = lambda **kwargs: _NoopProcess()
        run_process_function("fake.module.FakeClass", "victim", stop_event, bundle, exit_report=slot)

    assert list(slot) == [0, 0, 0], "release бросил -> слот должен остаться нетронутым (reported=0)"


def test_recreated_process_gets_fresh_slot_no_leak() -> None:
    """(c) Пересозданный процесс получает СВЕЖИЙ слот — старый отчёт не течёт в новое имя.

    ``create_and_register`` НЕ стартует процесс (``Process(...)`` — только
    конструктор, OS-процесс не порождается), поэтому вызывать его дважды на
    одном ``ProcessRegistry()`` с ``None``-зависимостями безопасно и не требует
    моков реестра очередей/shared_resources — код уже обрабатывает их отсутствие.
    """
    registry = ProcessRegistry()

    registry.create_and_register("victim", "fake.module.FakeClass")
    old_slot = registry._exit_reports["victim"]
    old_slot[1] = 5
    old_slot[2] = 2
    old_slot[0] = 1
    assert registry.exit_report("victim") == {"released": 5, "buffered_dropped": 2, "reported": True}

    # Тем же путём, что и restart: снять старое воплощение перед пересозданием
    # (ADR-PMM-030/032 — свежий ready_event/stop_event на каждый спавн; слот — той же дисциплиной).
    registry.remove_process("victim")
    registry.create_and_register("victim", "fake.module.FakeClass")

    new_slot = registry._exit_reports["victim"]
    assert new_slot is not old_slot, "новое воплощение обязано получить НОВЫЙ объект слота"
    assert registry.exit_report("victim") == {"released": 0, "buffered_dropped": 0, "reported": False}, (
        "отчёт старого воплощения не имеет права течь в отчёт нового имени"
    )


def test_exit_report_unknown_name_never_raises() -> None:
    """(d) Имя без слота (никогда не создавалось через ``_create_process``) -> «не знаю», без исключения.

    ``exit_report`` зовётся из ``PM.shutdown()``, где отказ недопустим — тест
    пинит контракт «никогда не бросает» на пустом реестре и на реестре с
    ДРУГИМИ именами (чтобы не спрятать баг индексации по ключу).
    """
    registry = ProcessRegistry()
    assert registry.exit_report("ghost") == {"released": 0, "buffered_dropped": 0, "reported": False}

    registry.create_and_register("real_child", "fake.module.FakeClass")
    assert registry.exit_report("ghost") == {"released": 0, "buffered_dropped": 0, "reported": False}
