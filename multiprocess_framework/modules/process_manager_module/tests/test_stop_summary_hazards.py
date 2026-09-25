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
from unittest.mock import MagicMock, patch

from ...process_module.core.process_module import ProcessModule
from ..core.process_registry import ProcessRegistry
from ..process.process_manager_process import ProcessManagerProcess
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


class _FakeRegistryForStopOnce:
    """Фейк ``ProcessRegistry`` только для теста (e) — считает вызовы на границе
    stop_all/exit_report, не подглядывает в имя вспомогательного метода PM."""

    def __init__(self) -> None:
        self.stop_all_calls = 0
        self.exit_report_calls: list[str] = []

    def stop_all(self, timeout: float = 5.0) -> dict[str, bool]:
        self.stop_all_calls += 1
        return {"child": True}

    def exit_report(self, name: str) -> dict:
        self.exit_report_calls.append(name)
        return {"released": 0, "buffered_dropped": 0, "reported": True}


def _make_minimal_pm() -> ProcessManagerProcess:
    """Минимальный PM-стенд: реальные bound-методы ``ProcessManagerProcess``
    (``_before_observability_teardown``/``_stop_children_once``/``shutdown``),
    коллабораторы — фейки на границе, которую и проверяет тест."""
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm._children_stopped = False
    pm._process_monitor = MagicMock()
    pm._process_registry = _FakeRegistryForStopOnce()
    pm._console_manager = None
    pm._log_info = MagicMock()
    pm._log_warning = MagicMock()
    pm._log_error = MagicMock()
    pm.get_config = lambda key, default=None: {"shutdown_timeout": 1.0}.get(key, default)
    return pm


def test_hook_then_second_shutdown_stops_children_exactly_once() -> None:
    """(e) Хук ``ProcessModule.stop()`` + повторный ``shutdown()`` (раннер) -> ``stop_all``
    и публикация сводки происходят РОВНО один раз за жизнь PM.

    Воспроизводит TRAP брифа: PM стартует через тот же раннер, что и дети, поэтому
    ``shutdown()`` зовётся дважды — из ``ProcessModule.stop()`` (через хук) и повторно из
    ``finally`` ``run_process_function``. Без флага ``_children_stopped`` второй вызов
    гонял бы ``stop_all`` по уже мёртвым детям и удвоил бы запись сводки в сторе.
    ``ProcessModule.shutdown`` заглушен — граница этого теста PM-собственный код
    (``_stop_children_once``/``_publish_stop_summary``), не полный teardown ProcessModule
    (вне FILES/OUT OF SCOPE задачи).
    """
    pm = _make_minimal_pm()
    with patch.object(ProcessModule, "shutdown", return_value=True):
        pm._before_observability_teardown()  # то, что ProcessModule.stop() зовёт до _flush_observability
        pm.shutdown()  # повторный вызов из runner'овского finally (тот же PM, тот же процесс)

    assert pm._process_registry.stop_all_calls == 1, "stop_all обязан выполниться РОВНО один раз за жизнь PM"
    summary_log_calls = pm._log_warning.call_count + pm._log_info.call_count
    assert summary_log_calls == 1, "сводка стопа обязана уйти РОВНО одним логом, не дважды"
    assert pm._log_error.call_count == 0, "выживших детей нет -> дежурный лог о выживших не зовётся"


class _ObservabilityOrderProbe:
    """(f) Минимальный объект с РЕАЛЬНЫМИ bound-методами ``ProcessModule.stop``/``_flush_observability``
    (взяты с класса напрямую, без наследования) — доказывает порядок внутри самого ``stop()``:
    хук ``_before_observability_teardown`` обязан отработать, пока ``_observability_store`` ещё не
    снят ``_flush_observability()``. Наблюдатели/коллабораторы дренажа — None/пустые: сам дренаж не
    под проверкой (process_module — не FILES этой задачи дальше хука), важен только ПОРЯДОК вызовов.
    """

    def __init__(self) -> None:
        self.name = "ProcessManagerOrderProbe"
        self.worker_manager = None
        self._stop_requested = False
        self._observability_hub = None
        self._observability_drain = None
        self._observability_store = MagicMock(name="store_tap_sentinel")
        self._observability_forwarders = {}
        self._observability_store_taps = []
        self._observability_tail_intents = {}
        self.stats_manager = None
        self.observed_store_before_teardown: bool | str = "hook-not-called"
        self.shutdown_called = False

    def update_process_state(self, **_kwargs) -> None:
        pass

    def _log_info(self, *_a, **_kw) -> None:
        pass

    def _before_observability_teardown(self) -> None:
        # PM переопределяет этим же хуком (Task 1.6) — здесь мы ловим, ЧТО он видит.
        self.observed_store_before_teardown = self._observability_store is not None

    def shutdown(self) -> None:
        self.shutdown_called = True

    # Реальные, не переопределённые методы ProcessModule под проверкой.
    _flush_observability = ProcessModule._flush_observability
    stop = ProcessModule.stop


def test_stop_calls_hook_before_store_teardown() -> None:
    """(f) Внутри ``ProcessModule.stop()`` хук видит живой ``_observability_store`` —
    это свойство, от которого зависят 3 живых REDS-теста (Task 1.6): не докажи его юнит-тестом,
    и регрессия порядка (хук после ``_flush_observability()``) снова уронит сводку в никуда."""
    probe = _ObservabilityOrderProbe()

    probe.stop()

    assert probe.observed_store_before_teardown is True, (
        "хук _before_observability_teardown обязан видеть _observability_store ещё живым"
    )
    assert probe._observability_store is None, "после stop() _flush_observability обязан снять стор"
    assert probe.shutdown_called is True, "stop() всё ещё обязан дойти до shutdown() в конце"
