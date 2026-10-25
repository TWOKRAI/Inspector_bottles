"""Hazard-тесты автора: корень PM (lifecycle-owner-scope, Task 1.2a, ADR-PMM-036).

Порядок (монитор раньше сигнала детям, watcher'ы и SSM раньше конца детей и сводки),
сводка с выжившими, код выхода 76 у монитора, бюджеты корня. Числа — литералы.
Вызовы, которые могут зависнуть, идут в daemon-потоке с дедлайном join.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from ...app_module.orchestrator import GenericProcessManagerApp
from ...process_module.core.process_module import ProcessModule
from ..core.process_registry import _ChildrenGroupStop
from ..core.restart_policy import RestartPolicy
from ..core.stop_budget import stop_budget
from ..monitor.process_monitor import ProcessMonitor
from ..process.process_manager_process import ProcessManagerProcess, _ChildrenStop
from ..runner.process_runner import _resolve_stop_budget


def _call_bounded(fn, timeout_s: float = 15.0):
    """``fn`` в daemon-потоке с дедлайном join: (завершился, результат, ошибка)."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — тест разбирает ошибку сам
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="pm_hazard_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error")


class _Group:
    def __init__(self, journal: list[str], result: dict[str, bool]) -> None:
        self._journal = journal
        self._result = result

    def request_stop(self) -> None:
        self._journal.append("stop_event.set")

    def join_until(self, deadline: float) -> bool:
        self._journal.append("children.join_until")
        return True

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def result(self) -> dict[str, bool]:
        return dict(self._result)


class _Registry:
    def __init__(self, journal: list[str], result: dict[str, bool], report: dict) -> None:
        self._journal = journal
        self._result = result
        self._report = report

    def children_stop(self, *, mark_reader_gone: bool) -> _Group:
        return _Group(self._journal, self._result)

    def exit_report(self, name: str) -> dict:
        return dict(self._report)


class _Monitor:
    def __init__(self, journal: list[str]) -> None:
        self._journal = journal
        self.timeouts: list[float] = []

    def stop(self, wait: bool = True, timeout: float = 10.0) -> None:
        self._journal.append("monitor.stop")
        self.timeouts.append(timeout)


# --------------------------------------------------------------------------- #
# Бюджет: читатель раннера и пины
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [None, 0])
def test_resolve_stop_budget_none_and_zero_give_default(value) -> None:
    """``shutdown_timeout`` ``None``/``0`` → умолчание g = 5,0 (прежнее ``or 5.0``)."""
    log = MagicMock()
    budget = _resolve_stop_budget({"shutdown_timeout": value}, log)
    assert budget == {"work_s": 3.0, "infra_s": 1.0, "pm_graceful_s": 5.0, "pm_total_s": 7.0, "outer_s": 8.5}


def test_resolve_stop_budget_takes_valid_dict_and_warns_on_bad_one() -> None:
    log = MagicMock()
    given = {"work_s": 0.6, "infra_s": 0.2, "pm_graceful_s": 1.0, "pm_total_s": 3.0, "outer_s": 4.5}
    assert _resolve_stop_budget({"stop_budget": given, "shutdown_timeout": 5.0}, log) == given
    log.warning.assert_not_called()

    bad = _resolve_stop_budget({"stop_budget": {"work_s": True}, "shutdown_timeout": 1.0}, log)
    assert bad == pytest.approx(given)  # выведен из shutdown_timeout 1.0 (0.8 × 0.75 = 0.6 в плавающей точке)
    assert log.warning.call_count == 1


def test_default_stop_budget_pins() -> None:
    assert ProcessModule.DEFAULT_STOP_BUDGET == {"work_s": 3.0, "infra_s": 1.0}
    assert ProcessManagerProcess.DEFAULT_STOP_BUDGET == {
        "work_s": 3.0,
        "infra_s": 1.0,
        "pm_graceful_s": 5.0,
        "pm_total_s": 7.0,
        "outer_s": 8.5,
    }


def test_pm_root_budget_is_pm_total_plus_infra() -> None:
    """Корень PM при g = 1,0: ``pm_total_s`` 3,0 + ``infra_s`` 0,2 = 3,2; ``children`` — 1,0."""
    pm = ProcessManagerProcess(config={"shutdown_timeout": 5.0})
    pm.attach_stop_budget(stop_budget(1.0))
    assert pm.initialize() is True
    try:
        assert pm._root.budget_s == pytest.approx(3.2)
        assert pm.lifetime_segments["work"].budget_s == pytest.approx(3.0)
        assert pm.lifetime_segments["work"]._names["children"].res.budget_s == 1.0
    finally:
        _call_bounded(pm.shutdown)


# --------------------------------------------------------------------------- #
# Порядок: монитор раньше stop_event
# --------------------------------------------------------------------------- #


def test_monitor_paused_before_first_stop_event_with_infra_deadline() -> None:
    journal: list[str] = []
    pm = MagicMock()
    pm._budget.return_value = stop_budget(1.0)
    pm._process_monitor = _Monitor(journal)
    pm._process_registry = _Registry(journal, {}, {})
    stop = _ChildrenStop(pm)

    stop.request_stop()
    stop.request_stop()  # повтор — no-op

    assert journal == ["monitor.stop", "stop_event.set"]
    # D4 (Task 1.9b): монитору — остаток общего срока исполнителя и паузы, поэтому с допуском.
    assert pm._process_monitor.timeouts == [pytest.approx(0.2, abs=1e-3)]


def test_registry_is_read_at_request_stop_not_at_construction() -> None:
    journal: list[str] = []
    pm = MagicMock()
    pm._budget.return_value = stop_budget(1.0)
    pm._process_monitor = _Monitor(journal)
    pm._process_registry = None
    stop = _ChildrenStop(pm)
    pm._process_registry = _Registry(journal, {"cam": True}, {})

    stop.request_stop()
    assert stop.result() == {"cam": True}


# --------------------------------------------------------------------------- #
# Сводка: выживший ребёнок
# --------------------------------------------------------------------------- #


def test_survivor_child_gives_warning_summary_and_survivor_line() -> None:
    journal: list[str] = []
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    pm.attach_stop_budget(stop_budget(1.0))
    assert pm.initialize() is True
    warnings: list[str] = []
    errors: list[str] = []
    real_warning, real_error = pm._log_warning, pm._log_error
    pm._log_warning = lambda msg, *a, **k: (warnings.append(str(msg)), real_warning(msg, *a, **k))
    pm._log_error = lambda msg, *a, **k: (errors.append(str(msg)), real_error(msg, *a, **k))
    pm._process_registry = _Registry(journal, {"cam": False}, {"released": 0, "buffered_dropped": 0, "reported": False})
    try:
        done, result, error = _call_bounded(pm.shutdown)
        assert done and error is None, error
        assert result is True
    finally:
        _call_bounded(pm.shutdown)
    assert any("ВЫЖИЛИ" in line and "cam" in line for line in errors), errors
    assert any("stop summary" in line and "not reported/lost: ['cam']" in line for line in warnings), warnings


class _RaisingRegistry:
    """Реестр, у которого ``children_stop`` падает (сбой в ``request_stop`` области детей)."""

    def __init__(self) -> None:
        self.calls = 0

    def children_stop(self, *, mark_reader_gone: bool):
        self.calls += 1
        raise RuntimeError("boom-registry")

    def exit_report(self, name: str) -> dict:
        return {"released": 0, "buffered_dropped": 0, "reported": False}


def test_registry_failure_in_request_stop_is_survivor_not_crash() -> None:
    """Реестр упал в ``request_stop``: ``shutdown()`` возвращается, ``children`` — выживший/ошибка.

    Одна попытка (``children_stop`` вызван 1 раз, не 3: request_stop, join_until, фаза 3), одна
    строка в логе, исключение наружу не уходит.
    """
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    pm.attach_stop_budget(stop_budget(1.0))
    assert pm.initialize() is True
    errors: list[str] = []
    real_error = pm._log_error
    pm._log_error = lambda msg, *a, **k: (errors.append(str(msg)), real_error(msg, *a, **k))
    registry = _RaisingRegistry()
    pm._process_registry = registry
    try:
        done, result, error = _call_bounded(pm.shutdown)
        assert done, "shutdown() завис"
        assert error is None, repr(error)
        assert result is False
        report = pm.close_root()
    finally:
        _call_bounded(pm.shutdown)
    assert registry.calls == 1
    assert report.errors, report
    assert any("children" in p for p in report.survivors), report
    assert sum("не удалось начать остановку детей" in line for line in errors) == 1, errors


# --------------------------------------------------------------------------- #
# Монитор: код 76
# --------------------------------------------------------------------------- #


def _monitor_with_store():
    from ...state_store_module import StateStoreManager

    ssm = StateStoreManager(initial_state={}, logger=None)
    mock_pm = MagicMock()
    mock_pm.name = "ProcessManager"
    mock_pm._get_protected_names.return_value = set()
    mock_pm.communication.send_message.return_value = True
    mock_pm._state_store_manager = ssm
    return ssm, ProcessMonitor(mock_pm, restart_policy=RestartPolicy(enabled=True, backoff_sec=0.0))


@pytest.mark.parametrize(
    ("exitcode", "status", "event", "restarts"), [(76, "stopped", "survivors", 0), (1, "crashed", None, 1)]
)
def test_exit_76_is_stopped_with_survivors_event_and_no_restart(exitcode, status, event, restarts) -> None:
    """76 → ``stopped`` + событие ``survivors``, рестарта нет; пара — 1 → ``crashed`` и рестарт."""
    ssm, monitor = _monitor_with_store()
    restart_calls: list[str] = []
    monitor._try_auto_restart = lambda name, reason: restart_calls.append(reason)
    proc = MagicMock()
    proc.name = "cam"
    proc.is_alive.return_value = False
    proc.pid = 123
    proc.exitcode = exitcode
    monitor.previous_states["cam"] = {"status": "running"}

    monitor._handle_dead_process(proc)

    assert monitor.previous_states["cam"]["status"] == status
    assert len(restart_calls) == restarts
    value = ssm.handle_state_get({"data": {"path": "processes.cam.supervisor.event"}}).get("value")
    if event is not None:
        assert value == event
    else:
        assert value == "crashed"


# --------------------------------------------------------------------------- #
# Ревью кода р.1 (1.2a): сбой сборки группы, гонка stop/shutdown, ошибка фазы 1, 76 после stopped
# --------------------------------------------------------------------------- #


class _GroupRegistry:
    """Реестр с настоящей ``_ChildrenGroupStop``; ``_build_child_stop`` — подмена теста."""

    os_processes = [type("P", (), {"name": "child"})()]

    def __init__(self, build, journal: list[str]) -> None:
        self._build = build
        self._journal = journal

    def _build_child_stop(self, names, mark_reader_gone):
        return self._build()

    def children_stop(self, *, mark_reader_gone: bool):
        return _ChildrenGroupStop(self, mark_reader_gone)

    def exit_report(self, name: str) -> dict:
        return {"released": 0, "buffered_dropped": 0, "reported": False}


class _OkChildGroup:
    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    def request_stop(self) -> None:
        self._journal.append("group.request_stop")

    def join_until(self, deadline: float) -> bool:
        self._journal.append("group.join_until")
        return True

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def survivors(self) -> list[str]:
        return []


def _real_pm_with(registry):
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    pm.attach_stop_budget(stop_budget(1.0))
    assert pm.initialize() is True
    pm._process_registry = registry
    return pm


def test_group_build_failure_on_runner_path_is_survivor_and_warning_summary() -> None:
    """Сбой сборки группы на пути раннера (``stop()`` + ``close_root()``): ``children`` — выживший, сводка WARNING."""

    def boom():
        raise RuntimeError("boom in _build_child_stop")

    journal: list[str] = []
    pm = _real_pm_with(_GroupRegistry(boom, journal))
    warnings: list[str] = []
    real_warning = pm._log_warning
    pm._log_warning = lambda msg, *a, **k: (warnings.append(str(msg)), real_warning(msg, *a, **k))
    try:
        done, _, error = _call_bounded(pm.stop)
        assert done and error is None, repr(error)
        done, report, error = _call_bounded(pm.close_root)
        assert done and error is None, repr(error)
    finally:
        _call_bounded(pm.shutdown)
    assert any(path.endswith("/children/processes") for path in report.survivors), report
    assert any("stop summary" in line and "not reported/lost: ['child']" in line for line in warnings), warnings


def test_join_during_foreign_build_waits_and_summary_follows_group_request_stop() -> None:
    """``stop()`` строит группу 1 с; ``shutdown()`` из второго потока ждёт сборку: сигнал детям раньше сводки."""
    journal: list[str] = []

    def slow_build():
        journal.append("build.start")
        time.sleep(1.0)
        journal.append("build.end")
        return {}, _OkChildGroup(journal)

    pm = _real_pm_with(_GroupRegistry(slow_build, journal))
    real_publish = pm._publish_stop_summary
    pm._publish_stop_summary = lambda result: (journal.append("summary"), real_publish(result))
    thread_a = threading.Thread(target=pm.stop, daemon=True, name="hz_stop")
    thread_a.start()
    time.sleep(0.15)
    done, result, error = _call_bounded(pm.shutdown)
    thread_a.join(10.0)
    assert done and error is None, repr(error)
    assert journal.index("group.request_stop") < journal.index("summary"), journal
    assert journal.count("build.start") == 1, journal


class _ObservingGroup:
    """Группа-выживший: ``join_until`` блокирует 0.3 с и возвращает ``False``; ``result()`` — то, что он увидел."""

    def __init__(self, journal: list[str]) -> None:
        self._journal = journal
        self._stopped = True  # снимок до join_until наивно говорит «остановлен»

    def request_stop(self) -> None:
        self._journal.append("group.request_stop")

    def join_until(self, deadline: float) -> bool:
        self._journal.append("group.join_until.start")
        time.sleep(0.3)
        self._stopped = False
        self._journal.append("group.join_until.end")
        return False

    def kill(self) -> None:
        pass

    def close(self) -> None:
        pass

    def result(self) -> dict[str, bool]:
        # Выживший: join_until вернул False, область close() не зовёт — карту нельзя брать из close().
        return {"cam": self._stopped}


class _ObservingRegistry:
    def __init__(self, journal: list[str]) -> None:
        self._group = _ObservingGroup(journal)

    def children_stop(self, *, mark_reader_gone: bool) -> _ObservingGroup:
        return self._group

    def exit_report(self, name: str) -> dict:
        return {"released": 0, "buffered_dropped": 0, "reported": False}


def test_summary_is_written_after_children_join_and_map_is_post_death() -> None:
    """Сводка пишется ПОСЛЕ ожидания детей, а карта — итог после ``join_until`` (выживший), не снимок до него."""
    journal: list[str] = []
    pm = _real_pm_with(_ObservingRegistry(journal))
    warnings: list[str] = []
    summary_maps: list[dict] = []
    real_warning, real_publish = pm._log_warning, pm._publish_stop_summary
    pm._log_warning = lambda msg, *a, **k: (warnings.append(str(msg)), real_warning(msg, *a, **k))
    pm._publish_stop_summary = lambda result: (
        journal.append("summary"),
        summary_maps.append(dict(result)),
        real_publish(result),
    )
    try:
        done, _, error = _call_bounded(pm.shutdown)
        assert done and error is None, repr(error)
    finally:
        _call_bounded(pm.shutdown)
    assert journal.index("group.join_until.end") < journal.index("summary"), journal
    assert summary_maps == [{"cam": False}], summary_maps
    assert any("stop summary" in line and "not reported/lost: ['cam']" in line for line in warnings), warnings


def test_phase1_error_reaches_report_errors_on_runner_path() -> None:
    """Исключение ``children_stop()`` в фазе 1 при ``stop()`` + ``close_root()`` попадает в ``errors`` отчёта корня."""
    pm = _real_pm_with(_RaisingRegistry())
    try:
        done, _, error = _call_bounded(pm.stop)
        assert done and error is None, repr(error)
        done, report, error = _call_bounded(pm.close_root)
        assert done and error is None, repr(error)
    finally:
        _call_bounded(pm.shutdown)
    assert any(path.endswith("/children/processes") for path, _ in report.errors), report


def test_exit_76_after_stopped_state_still_emits_survivors_once() -> None:
    """Ребёнок записал ``STOPPED`` до смерти (гонка опроса): 76 всё равно даёт ``survivors``, и один раз."""
    _, monitor = _monitor_with_store()
    events: list[str] = []
    monitor._emit_supervisor_event = lambda name, event, **kw: events.append(f"{name}:{event}")
    proc = MagicMock()
    proc.name = "cam"
    proc.pid = 123
    proc.exitcode = 76
    monitor.previous_states["cam"] = {"status": "stopped"}

    monitor._handle_dead_process(proc)
    monitor._handle_dead_process(proc)

    assert events == ["cam:survivors"], events


@pytest.mark.parametrize(
    ("config", "must_say"),
    [
        ({"stop_budget": [1, 2]}, "не словарь"),
        ({"stop_budget": {"work_s": 0.6}}, "нет ключа infra_s"),
        (
            {
                "stop_budget": {
                    "work_s": 0.6,
                    "infra_s": float("nan"),
                    "pm_graceful_s": 1.0,
                    "pm_total_s": 3.0,
                    "outer_s": 4.5,
                }
            },
            "не конечное число",
        ),
    ],
)
def test_resolve_stop_budget_warning_names_defect_not_value(config, must_say) -> None:
    log = MagicMock()
    _resolve_stop_budget(config, log)
    assert log.warning.call_count == 1
    text = log.warning.call_args.args[0]
    assert must_say in text, text
    assert "[1, 2]" not in text and "nan" not in text.lower() and "0.6" not in text, text


# --------------------------------------------------------------------------- #
# Порядок GenericProcessManagerApp
# --------------------------------------------------------------------------- #


def test_app_watchers_and_state_store_close_before_children_end_and_summary() -> None:
    journal: list[str] = []
    app = GenericProcessManagerApp(config={"shutdown_timeout": 1.0, "initial_state": {"system": {"x": 1}}})
    app.attach_stop_budget(stop_budget(1.0))
    assert app.initialize() is True
    store = app._state_store_manager
    real_store_shutdown = store.shutdown

    def store_shutdown() -> None:
        journal.append("state_store")
        real_store_shutdown()

    store.shutdown = store_shutdown
    app._observability_recipe_watcher = MagicMock(stop=lambda: journal.append("recipe_watcher"))
    app._observability_watcher = MagicMock(stop=lambda: journal.append("observability_watcher"))
    real_publish = app._publish_stop_summary
    app._publish_stop_summary = lambda result: (journal.append("summary"), real_publish(result))
    app._process_registry = _Registry(journal, {"cam": True}, {"released": 0, "buffered_dropped": 0, "reported": True})
    try:
        done, result, error = _call_bounded(app.shutdown)
        assert done and error is None, error
        assert result is True
    finally:
        _call_bounded(app.shutdown)
    assert journal == [
        "stop_event.set",
        "observability_watcher",
        "recipe_watcher",
        "state_store",
        "children.join_until",
        "summary",
    ], journal
