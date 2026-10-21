# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 1.9m: ``ExecutorManager`` в процессе (REDS R8-R10).

Написаны независимым тестером ТОЛЬКО по контракту ``plans/lifecycle-stop-ownership/tasks/T1.9m.md``
(D3 ключ конфига ``executors`` / ``executor_manager`` / запись в ``work``, D6 ``introspect.executors``,
D2 ``ExecutorManager``) и разделу «REDS — слепой тестер» ``T1.9m_facts.md``; реализации нет в дереве.

Ожидание до реализации: R8-R10 красные - у ``ProcessModule`` нет ``executor_manager``, ключ
``executors`` не создаёт потоков, нет команды ``introspect.executors``, ``ProcessLaunchConfig`` не знает
поле ``executors``, нет модуля ``worker_module.executor_manager``. Новые имена импортируются ВНУТРИ
тестов: каждый тест докладывает свой красный.

Стенд - настоящий ``ProcessModule`` (обвязка ``test_process_root_acceptance.py``): ``ProcessModule(name,
config=...)`` + ``initialize()``; имя потока рабочего исполнителя - ``"<процесс>_keyed-<имя>-<i>"``.
Каждый ждущий вызов - в daemon-потоке с дедлайном ``join``; каждый процесс закрывается в ``finally``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands

# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


def call_bounded(fn: Callable[[], Any], timeout_s: float) -> tuple[bool, Any, BaseException | None, float]:
    """Вызвать ``fn`` в daemon-потоке: (завершился, результат, ошибка, длительность)."""
    box: dict[str, Any] = {}

    def run() -> None:
        t0 = time.perf_counter()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.perf_counter() - t0

    th = threading.Thread(target=run, daemon=True, name="call_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error"), box.get("elapsed", float("nan"))


def keyed_threads(prefix: str) -> list[threading.Thread]:
    """Живые потоки рабочих исполнителей процесса ``prefix`` (имя ``"<процесс>_keyed-..."``)."""
    return [t for t in threading.enumerate() if t.name.startswith(f"{prefix}_keyed-") and t.is_alive()]


def all_keyed_thread_names() -> set[str]:
    return {t.name for t in threading.enumerate() if "_keyed-" in t.name}


def wait_until(pred: Callable[[], bool], timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def make_process(name: str, config: dict | None = None, cls: type = ProcessModule) -> ProcessModule:
    proc = cls(name, config=config if config is not None else {})
    assert proc.initialize() is True
    return proc


class SlowRequestStop:
    """Запись ``work``: ``request_stop`` не блокирует мгновенно, а спит ``sleep_s`` (фаза 1 идёт по порядку)."""

    def __init__(self, sleep_s: float) -> None:
        self._sleep_s = sleep_s

    def request_stop(self) -> None:
        time.sleep(self._sleep_s)

    def join_until(self, deadline: float) -> bool:
        return True


class ProcessWithSlowEntry(ProcessModule):
    """Наследник регистрирует в ``_own_work`` запись, чей ``request_stop`` спит 0,5 с."""

    def _own_work(self, work) -> None:
        work.own(SlowRequestStop(0.5), name="slow-entry", kind="test")


# ---------------------------------------------------------------------------
# R8
# ---------------------------------------------------------------------------


def test_process_config_executors_created_and_introspected() -> None:
    """R8: исполнитель из ``config["config"]["executors"]`` создан до команд, виден в ``introspect.executors``."""
    proc = make_process("p8", {"config": {"executors": {"io": {"kind": "keyed", "max_workers": 2}}}})
    try:
        names = {t.name for t in keyed_threads("p8")}
        assert names == {"p8_keyed-io-0", "p8_keyed-io-1"}, names

        BuiltinCommands(proc).register()
        res = proc.command_manager.handle_command({"command": "introspect.executors", "data": {}})

        assert res["success"] is True, res
        expected = {
            "kind": "keyed",
            "source": "config",
            "serial": False,
            "max_workers": 2,
            "max_pending": 64,
            "owned": True,
        }
        entry = res["executors"]["io"]
        for key, value in expected.items():
            assert entry.get(key) == value, f"executors.io[{key!r}] = {entry.get(key)!r}, ожидали {value!r}"
    finally:
        done, _, error, _ = call_bounded(proc.shutdown, 20.0)
    assert done, "shutdown() завис"
    assert error is None, repr(error)
    assert wait_until(lambda: not keyed_threads("p8"), 1.0), [t.name for t in keyed_threads("p8")]


# ---------------------------------------------------------------------------
# R9
# ---------------------------------------------------------------------------


def test_process_close_refuses_queue_in_phase_one() -> None:
    """R9: приём исполнителя закрывается в фазе 1 ``work`` раньше записей наследника: очередь - ``system_stopping``."""
    proc = make_process(
        "p9",
        {"config": {"executors": {"io": {"kind": "keyed", "max_workers": 2}}}},
        cls=ProcessWithSlowEntry,
    )
    shutdown_thread: threading.Thread | None = None
    try:
        ex = proc.executor_manager.get("io")
        started = threading.Event()
        first_done = threading.Event()
        second: dict[str, Any] = {}
        second_replied = threading.Event()

        def first_op() -> dict:
            started.set()
            time.sleep(1.0)
            return {"success": True}

        def second_reply(result: Any) -> None:
            second["at"] = time.perf_counter()
            second["result"] = result
            second_replied.set()

        ex.submit(first_op, frozenset({"a"}), lambda r: first_done.set())
        assert started.wait(5.0), "первая операция не началась"
        ex.submit(lambda: {"success": True}, frozenset({"a"}), second_reply)
        assert not second_replied.is_set(), "вторая операция (ключ {a}) не вправе исполниться до конца первой"

        t_call = time.perf_counter()
        shutdown_thread = threading.Thread(target=proc.shutdown, daemon=True, name="shutdown-probe")
        shutdown_thread.start()

        assert second_replied.wait(5.0), "ждущая операция не получила ответа"
        assert second["result"] == {"success": False, "error": "system_stopping"}
        delay = second["at"] - t_call
        assert delay <= 0.2, f"отказ очереди пришёл через {delay:.3f} с после shutdown() (ждали фазу 1, <= 0.2 с)"
    finally:
        if shutdown_thread is not None:
            shutdown_thread.join(30.0)
        call_bounded(proc.shutdown, 30.0)


# ---------------------------------------------------------------------------
# R10
# ---------------------------------------------------------------------------


class FakeLogger:
    """Слот ``logger``: запоминает записи по уровням."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, message: Any) -> None:
        with self._lock:
            self.records.append((level, str(message() if callable(message) else message)))

    def debug(self, message: Any, **kw: Any) -> None:
        self._add("debug", message)

    def info(self, message: Any, **kw: Any) -> None:
        self._add("info", message)

    def warning(self, message: Any, **kw: Any) -> None:
        self._add("warning", message)

    def error(self, message: Any, **kw: Any) -> None:
        self._add("error", message)

    def critical(self, message: Any, **kw: Any) -> None:
        self._add("critical", message)

    def loud(self) -> list[tuple[str, str]]:
        with self._lock:
            return [(lvl, m) for lvl, m in self.records if lvl in ("info", "warning", "error", "critical")]


def test_zero_cost_without_executors_and_launch_config_shape() -> None:
    """R10: без ключа ``executors`` - ни потока, ни строки лога; ``build()`` не меняет форму ``proc_dict``."""
    before = all_keyed_thread_names()
    proc = make_process("p10")
    try:
        assert proc.executor_manager is not None
        assert all_keyed_thread_names() - before == set(), all_keyed_thread_names() - before
        assert proc.executor_manager.describe()["executors"] == {}
    finally:
        done, _, error, _ = call_bounded(proc.shutdown, 20.0)
    assert done, "shutdown() завис"
    assert error is None, repr(error)

    # Отдельный менеджер: конструктор + initialize + пустые секции - тишина уровня INFO и выше.
    from multiprocess_framework.modules.worker_module import WorkerManager
    from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager

    wm = WorkerManager(manager_name="t10", process=None)
    assert wm.initialize() is True
    log = FakeLogger()
    try:
        mgr = ExecutorManager("t10_executors", worker_manager=wm, managers={"logger": log})
        assert mgr.initialize() is True
        assert mgr.load_config(None) == []
        assert mgr.load_config({}) == []
        assert log.loud() == [], f"нулевая стоимость нарушена: {log.loud()!r}"
    finally:
        call_bounded(wm.shutdown, 10.0)

    from multiprocess_framework.modules.process_module.configs.process_launch_config import ProcessLaunchConfig

    plain = ProcessLaunchConfig(process_name="p").build()[1]["config"]
    assert "executors" not in plain, plain
    with_executors = ProcessLaunchConfig(process_name="p", executors={"io": {"kind": "keyed"}}).build()[1]["config"]
    assert with_executors["executors"] == {"io": {"kind": "keyed"}}
