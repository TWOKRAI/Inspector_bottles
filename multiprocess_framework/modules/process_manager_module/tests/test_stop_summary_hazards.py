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

import threading
from multiprocessing import Event, RawArray
from unittest.mock import patch

from ..core.process_registry import ProcessRegistry
from ..core.stop_budget import stop_budget
from ..process.process_manager_process import ProcessManagerProcess
from ..runner.process_runner import run_process_function


def test_unreported_slot_reads_as_unknown() -> None:
    """(a) Слот с числами, но ``reported=0`` — читается как «не знаем» с нулями.

    ВАЖНО (ревью Task 1.6, it.1): этот тест проверяет ТОЛЬКО ЧТЕНИЕ —
    ``exit_report`` обязан игнорировать released/buffered_dropped, пока
    reported не выставлен. Порядок ЗАПИСИ в runner (released/buffered_dropped
    — затем reported последним, «чтобы ребёнок, убитый ПОСЕРЕДИНЕ записи между
    строками читался как неизвестно») этим тестом НЕ закреплён — слот здесь
    собирается вручную, раннер не зовётся. Видимо такой порядок только при
    kill РОВНО между тремя `int`-присваиваниями в runner'е (`process_runner.py`
    finally) — сценарий не воспроизведён ни одним тестом в этом файле.
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


def _call_bounded(fn, timeout_s: float = 15.0):
    """``fn`` в daemon-потоке с дедлайном join: (завершился, результат, ошибка)."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — тест разбирает ошибку сам
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="stop_summary_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error")


class _Group:
    """Группа детей на границе ``ProcessRegistry.children_stop`` — журнал вызовов."""

    def __init__(self, journal: list[str], fail_request: bool) -> None:
        self._journal = journal
        self._fail_request = fail_request

    def request_stop(self) -> None:
        self._journal.append("request_stop")
        if self._fail_request:
            raise RuntimeError("boom: request_stop детей упал (инъекция теста)")

    def join_until(self, deadline: float) -> bool:
        return True

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def result(self) -> dict[str, bool]:
        return {"child": True}


class _Registry:
    def __init__(self, journal: list[str], *, fail_request: bool = False) -> None:
        self._journal = journal
        self._fail_request = fail_request

    def children_stop(self, *, mark_reader_gone: bool) -> _Group:
        self._journal.append("children_stop")
        return _Group(self._journal, self._fail_request)

    def exit_report(self, name: str) -> dict:
        return {"released": 0, "buffered_dropped": 0, "reported": True}


def _real_pm(journal: list[str], *, fail_request: bool = False) -> ProcessManagerProcess:
    """Настоящий PM с корнем (``initialize()``); реестр и слив подменены ПОСЛЕ подъёма —
    корень читает их поздно (Task 1.2a)."""
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    pm.attach_stop_budget(stop_budget(1.0))
    assert pm.initialize() is True
    real_publish = pm._publish_stop_summary

    def publish(result: dict[str, bool]) -> None:
        journal.append("summary")
        real_publish(result)

    pm._publish_stop_summary = publish
    pm._flush_observability = lambda: journal.append("flush")
    pm._process_registry = _Registry(journal, fail_request=fail_request)
    return pm


def test_stop_then_two_shutdowns_stop_children_exactly_once() -> None:
    """(e) Путь раннера: ``stop()`` (= ``cancel()`` корня), затем ``shutdown()`` дважды
    (``close_root`` раннера + повтор) → дети и сводка РОВНО один раз за жизнь PM.

    Task 1.2a: флаг ``_children_stopped`` удалён — единственность даёт корень
    (повторный ``close()`` возвращает тот же отчёт и ничего не гасит)."""
    journal: list[str] = []
    pm = _real_pm(journal)
    try:
        done, _, error = _call_bounded(pm.stop)
        assert done and error is None, error
        first = _call_bounded(pm.shutdown)
        second = _call_bounded(pm.shutdown)
        assert first[0] and second[0], "shutdown() завис"
        assert first[1] is True and second[1] is True, (first, second)
    finally:
        _call_bounded(pm.shutdown)
    assert journal.count("children_stop") == 1, journal
    assert journal.count("request_stop") == 1, journal
    assert journal.count("summary") == 1, journal
    assert journal.count("flush") == 1, journal


def test_stop_alone_does_not_publish_summary_close_does_before_flush() -> None:
    """(f) ``stop()`` только сигналит: детей гасит фаза 1 (``request_stop``), но сводки и
    слива ещё нет — их пишет закрытие корня, сводка раньше слива (store-tap жив)."""
    journal: list[str] = []
    pm = _real_pm(journal)
    try:
        done, _, error = _call_bounded(pm.stop)
        assert done and error is None, error
        assert "summary" not in journal and "flush" not in journal, journal
        done, _, error = _call_bounded(pm.shutdown)
        assert done and error is None, error
    finally:
        _call_bounded(pm.shutdown)
    assert journal.index("request_stop") < journal.index("summary") < journal.index("flush"), journal


def test_raising_children_stop_still_flushes_and_publishes_once() -> None:
    """(g) ``request_stop`` группы детей бросает → закрытие корня не срывается: сводка уходит
    один раз, слив стора происходит, ``shutdown()`` возвращает ``False`` (ошибка в отчёте),
    повтор — no-op (Task 1.2a: ретрая нет, единственность — у корня)."""
    journal: list[str] = []
    pm = _real_pm(journal, fail_request=True)
    try:
        done, first, error = _call_bounded(pm.shutdown)
        assert done and error is None, error
        assert first is False, "ошибка фазы 1 детей обязана попасть в отчёт корня"
        done, second, error = _call_bounded(pm.shutdown)
        assert done and error is None, error
        assert second is False, "повтор возвращает итог первого закрытия"
    finally:
        _call_bounded(pm.shutdown)
    assert journal.count("children_stop") == 1, journal
    assert journal.count("summary") == 1, journal
    assert journal.count("flush") == 1, journal
