# -*- coding: utf-8 -*-
"""Hazard-тесты автора C-60: хук плагина ``request_stop`` (H1–H7, H2b).

План: ``plans/lifecycle-stop-ownership/tasks/C-60.md`` («Hazard автора»).

Стенд — настоящие ``ProcessModule`` / ``GenericProcess``, настоящий ``PluginOrchestrator`` и настоящие
воркеры ``WorkerManager``; двойник только у транспортного стока ``GenericProcess`` (H6). Порядок —
только журналом событий (порядок вызова); моменты ``time.monotonic`` — только для задержек ≥ 0,1 с
(шаг часов Windows 15,6 мс). Каждому процессу — уникальное имя (процессы одного интерпретатора делят
слоты процессных хуков по имени). Каждый вызов, способный зависнуть, — в daemon-потоке с ``join``-дедлайном.
"""

from __future__ import annotations

import itertools
import threading
import time
import uuid
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

#: Срок сегмента ``work`` = 1,0 с (литерал брифа: ``W``).
BUDGET_W1: dict[str, float] = {"work_s": 1.0, "infra_s": 0.25}
#: Отказ исполнителя после закрытия приёма (литерал, R9 ``test_process_executors_acceptance.py``).
REFUSAL = {"success": False, "error": "system_stopping"}
OK = {"success": True}

_RUN_ID = uuid.uuid4().hex[:6]
_SEQ = itertools.count()


def _unique(prefix: str) -> str:
    """Уникальное имя процесса на каждый повтор."""
    return f"{prefix}_{_RUN_ID}_{next(_SEQ)}"


# ---------------------------------------------------------------------------
# Журнал и настройки зондов (плагины создаются оркестратором по dotted path)
# ---------------------------------------------------------------------------


class _Journal:
    """Журнал строк ``"<плагин>.<событие>"`` в порядке вызова, с моментами ``monotonic``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[tuple[str, float]] = []

    def reset(self) -> None:
        with self._lock:
            self._events = []

    def add(self, name: str) -> None:
        with self._lock:
            self._events.append((name, time.monotonic()))

    def names(self) -> list[str]:
        with self._lock:
            return [n for n, _ in self._events]

    def moment(self, name: str) -> float | None:
        with self._lock:
            for n, t in self._events:
                if n == name:
                    return t
        return None


JOURNAL = _Journal()


class _Knobs:
    """Поведение зондов на тест: сон хука, исполнитель для подачи из хука, отпуск воркеров."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.hook_sleep_s = 0.0
        self.hook_submit_to: Any = None
        self.hook_replies: list[Any] = []
        self.worker_running = threading.Event()
        #: Отпуск воркеров зонда в ``finally`` (H2b оставляет их без ``stop_event``).
        self.release_workers = threading.Event()


KNOBS = _Knobs()


def _worker_loop(label: str) -> Callable[[Any, Any], None]:
    """Цикл воркера зонда до ``stop_event`` (или отпуска теста); на выходе ``<label>.worker_exit``."""

    def loop(stop_event: Any, pause_event: Any) -> None:
        KNOBS.worker_running.set()
        try:
            while not stop_event.is_set() and not KNOBS.release_workers.is_set():
                time.sleep(0.01)
        finally:
            JOURNAL.add(f"{label}.worker_exit")

    return loop


class HookPlugin(ProcessModulePlugin):
    """Плагин без воркера: хук пишет журнал; по настройке подаёт операцию исполнителю и спит."""

    name = "hk"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("hk.request_stop")
        executor = KNOBS.hook_submit_to
        if executor is not None:
            executor.submit(lambda: OK, frozenset({"hook"}), KNOBS.hook_replies.append)
        if KNOBS.hook_sleep_s:
            time.sleep(KNOBS.hook_sleep_s)

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("hk.shutdown")


class WorkerHookPlugin(ProcessModulePlugin):
    """Плагин с воркером: хук пишет журнал и спит ``KNOBS.hook_sleep_s``."""

    name = "wk"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("wk_worker", _worker_loop("wk"), cfg, auto_start=True)

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("wk.request_stop")
        if KNOBS.hook_sleep_s:
            time.sleep(KNOBS.hook_sleep_s)

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("wk.shutdown")


class ConfigureFailsPlugin(ProcessModulePlugin):
    """``configure`` бросает — плагин остаётся IDLE (H4)."""

    name = "cf"

    def configure(self, ctx: PluginContext) -> None:
        raise RuntimeError("c60 hazard: configure fails on purpose")

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("cf.request_stop")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("cf.shutdown")


class StartFailsPlugin(ProcessModulePlugin):
    """``start`` бросает — плагин остаётся READY (H4)."""

    name = "sf"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        raise RuntimeError("c60 hazard: start fails on purpose")

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("sf.request_stop")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("sf.shutdown")


class GenericProbePlugin(ProcessModulePlugin):
    """Плагин ``GenericProcess`` (H6): воркер + подписка на дерево (чтобы ``state_proxy`` слал unsubscribe_all)."""

    name = "gp"
    category = "utility"
    inputs: list = []
    outputs: list = []

    def configure(self, ctx: PluginContext) -> None:
        if ctx.state_proxy is not None:
            ctx.state_proxy.subscribe("sim.c60.*", lambda _deltas: None, sync=False)

    def start(self, ctx: PluginContext) -> None:
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("gp_worker", _worker_loop("gp"), cfg, auto_start=True)

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("gp.request_stop")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("gp.shutdown")


# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


def _entry(plugin_name: str, cls: type) -> dict[str, str]:
    return {"plugin_name": plugin_name, "plugin_class": f"{__name__}.{cls.__name__}"}


def _make_process(name: str, plugins: list[dict[str, str]], budget: dict[str, float] | None = BUDGET_W1):
    app_cfg: dict[str, Any] = {"executors": {"io": {"serial": True}}}
    if plugins:
        app_cfg["plugins"] = plugins
    proc = ProcessModule(name, config={"config": app_cfg})
    if budget is not None:
        proc.attach_stop_budget(budget)
    assert proc.initialize() is True, f"{name}: initialize() не дошёл до конца"
    return proc


def _bounded(fn: Callable[[], Any], timeout_s: float = 30.0) -> dict[str, Any]:
    """``fn()`` в daemon-потоке с ``join``-дедлайном: t0, длительность, результат, ошибка, ``done``."""
    box: dict[str, Any] = {}

    def run() -> None:
        box["t0"] = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - box["t0"]

    th = threading.Thread(target=run, daemon=True, name="c60-hazard-call")
    th.start()
    th.join(timeout_s)
    box["done"] = not th.is_alive()
    return box


def _start_fresh() -> None:
    JOURNAL.reset()
    KNOBS.reset()


# ---------------------------------------------------------------------------
# H1 — стоп во время старта задачи
# ---------------------------------------------------------------------------


def test_h1_stop_races_task_submit_hook_once_no_silence() -> None:
    """H1: ``submit`` соседнего потока одновременно с ``shutdown()``, 50 повторов без долгой операции.

    На каждом повторе: хук ровно один раз; закрытие не зависает и возвращает ``True``; операция соседа
    получает ровно один ответ — результат или отказ ``system_stopping``, не тишину. Подача ИЗ хука получает
    отказ ``system_stopping`` синхронно: приём исполнителя закрыт фазой 1 ``work`` раньше хука (фаза 2).
    """
    failures: list[str] = []
    outcomes = {"ok": 0, "refusal": 0, "silent": 0, "other": 0}
    for i in range(50):
        _start_fresh()
        name = _unique("c60h1")
        proc = _make_process(name, [_entry("hk", HookPlugin)])
        try:
            io = proc.executor_manager.get("io")
            assert io is not None, f"{name}: исполнитель io не создан"
            KNOBS.hook_submit_to = io
            replies: list[Any] = []
            replied = threading.Event()

            def reply(result: Any, _replies: list[Any] = replies, _ev: threading.Event = replied) -> None:
                _replies.append(result)
                _ev.set()

            gate = threading.Barrier(2)

            def submitter(_io: Any = io, _gate: threading.Barrier = gate, _reply: Any = reply) -> None:
                _gate.wait(5.0)
                _io.submit(lambda: OK, frozenset({"k"}), _reply)

            sub = threading.Thread(target=submitter, daemon=True, name="c60-h1-submit")
            sub.start()

            def stop(_gate: threading.Barrier = gate, _proc: Any = proc) -> Any:
                _gate.wait(5.0)
                return _proc.shutdown()

            m = _bounded(stop, 20.0)
            sub.join(5.0)
            if not m["done"]:
                failures.append(f"{name}: shutdown() завис (join 20 с)")
                continue
            if m.get("error") is not None or m.get("result") is not True:
                failures.append(f"{name}: shutdown() -> {m.get('result')!r}, ошибка {m.get('error')!r}")
            replied.wait(5.0)
            time.sleep(0.02)  # второй (лишний) ответ, если бы он был, успевает прийти
            if replies == [OK]:
                outcomes["ok"] += 1
            elif replies == [REFUSAL]:
                outcomes["refusal"] += 1
            elif not replies:
                outcomes["silent"] += 1
            else:
                outcomes["other"] += 1
                failures.append(f"{name}: ответы операции соседа {replies!r}")
            if JOURNAL.names().count("hk.request_stop") != 1:
                failures.append(f"{name}: хук вызван {JOURNAL.names().count('hk.request_stop')} раз; {JOURNAL.names()}")
            if KNOBS.hook_replies != [REFUSAL]:
                failures.append(f"{name}: подача из хука получила {KNOBS.hook_replies!r}, ждали [{REFUSAL!r}]")
        finally:
            _bounded(proc.shutdown, 20.0)
    assert not failures, "\n".join(failures)
    # Сколько подач успели исполниться, а сколько сняты, — гонка, не утверждается; утверждается счёт:
    # каждая из 50 подач получила ровно один ответ (результат или отказ), ни одной тишины.
    assert outcomes["ok"] + outcomes["refusal"] == 50, outcomes


# ---------------------------------------------------------------------------
# H2 / H2b — блокирующий хук
# ---------------------------------------------------------------------------


def _run_blocking_hook(name: str, sleep_s: float) -> tuple[dict[str, Any], Any, list[str]]:
    _start_fresh()
    KNOBS.hook_sleep_s = sleep_s
    proc = _make_process(name, [_entry("wk", WorkerHookPlugin)])
    try:
        assert KNOBS.worker_running.wait(5.0), f"{name}: воркер зонда не стартовал"
        m = _bounded(proc.shutdown, 30.0)
        report = proc.close_root()
        names = JOURNAL.names()
        m["shutdown_at"] = JOURNAL.moment("wk.shutdown")
    finally:
        KNOBS.release_workers.set()
        _bounded(proc.shutdown, 20.0)
    return m, report, names


def test_h2_short_blocking_hook_eats_budget_without_survivors() -> None:
    """H2: хук спит 0,5 с при ``W`` = 1,0, без операции: выживших нет, ``shutdown`` плагина ≤ 1,40 с от ``t0``."""
    name = _unique("c60h2")
    m, report, names = _run_blocking_hook(name, 0.5)
    assert m["done"], f"{name}: shutdown() завис (join 30 с)"
    assert m.get("error") is None, repr(m.get("error"))
    assert m["result"] is True
    assert list(report.survivors) == []
    assert names == ["wk.request_stop", "wk.worker_exit", "wk.shutdown"]
    assert m["shutdown_at"] is not None
    delay = m["shutdown_at"] - m["t0"]
    assert delay <= 1.40, f"shutdown плагина через {delay:.3f} с после shutdown() процесса (ждали <= 1.40)"


def test_h2b_hook_longer_than_budget_leaves_workers_survivor() -> None:
    """H2b: хук спит 1,5 с (``W`` + 0,5) при ``W`` = 1,0: ``True``, выживший — ровно ``workers``, 1,45–1,80 с.

    Принятое следствие контракта «хук не ждёт»: фреймворк хук не ограничивает и не зависает.
    """
    name = _unique("c60h2b")
    m, report, names = _run_blocking_hook(name, 1.5)
    assert m["done"], f"{name}: shutdown() завис (join 30 с)"
    assert m.get("error") is None, repr(m.get("error"))
    assert m["result"] is True
    assert list(report.survivors) == [f"proc/{name}/work/workers"]
    assert 1.45 <= m["elapsed"] <= 1.80, f"shutdown() занял {m['elapsed']:.3f} с (ждали [1.45; 1.80])"
    assert names[0] == "wk.request_stop", names
    assert names.count("wk.request_stop") == 1, names
    assert "wk.shutdown" in names, names


# ---------------------------------------------------------------------------
# H3 — stop() без shutdown()
# ---------------------------------------------------------------------------


def test_h3_stop_signal_does_not_fire_hook_only_close_does() -> None:
    """H3: ``stop()`` (сигнал, ``cancel`` корня) хук не зовёт; ``shutdown()`` после него — один раз."""
    _start_fresh()
    name = _unique("c60h3")
    proc = _make_process(name, [_entry("hk", HookPlugin)])
    try:
        s = _bounded(proc.stop, 10.0)
        assert s["done"], "stop() завис"
        assert s.get("error") is None, repr(s.get("error"))
        time.sleep(0.2)
        assert JOURNAL.names() == []
        m = _bounded(proc.shutdown, 20.0)
        assert m["done"], "shutdown() завис"
        assert m.get("error") is None, repr(m.get("error"))
    finally:
        _bounded(proc.shutdown, 20.0)
    assert JOURNAL.names() == ["hk.request_stop", "hk.shutdown"]


# ---------------------------------------------------------------------------
# H4 — состояния плагина
# ---------------------------------------------------------------------------


def _close_and_journal(proc: Any) -> list[str]:
    try:
        m = _bounded(proc.shutdown, 20.0)
        assert m["done"], "shutdown() завис"
        assert m.get("error") is None, repr(m.get("error"))
    finally:
        _bounded(proc.shutdown, 20.0)
    return JOURNAL.names()


def test_h4_idle_plugin_after_failed_configure_gets_no_hook_but_shutdown() -> None:
    """H4 IDLE: ``configure`` бросил — хука нет, ``shutdown`` есть."""
    _start_fresh()
    proc = _make_process(_unique("c60h4i"), [_entry("cf", ConfigureFailsPlugin)])
    assert [p.state for p in proc._orchestrator.plugins] == [PluginState.IDLE]
    assert _close_and_journal(proc) == ["cf.shutdown"]


def test_h4_ready_plugin_after_failed_start_gets_hook() -> None:
    """H4 READY: ``start`` бросил — плагин READY, хук получает до ``shutdown``."""
    _start_fresh()
    proc = _make_process(_unique("c60h4r"), [_entry("sf", StartFailsPlugin)])
    assert [p.state for p in proc._orchestrator.plugins] == [PluginState.READY]
    assert _close_and_journal(proc) == ["sf.request_stop", "sf.shutdown"]


def test_h4_stopped_plugin_gets_no_hook() -> None:
    """H4 STOPPED: после ``orchestrator.shutdown()`` закрытие процесса хук не зовёт."""
    _start_fresh()
    proc = _make_process(_unique("c60h4s"), [_entry("hk", HookPlugin)])
    d = _bounded(proc._orchestrator.shutdown, 10.0)
    assert d["done"] and d.get("error") is None, repr(d.get("error"))
    assert [p.state for p in proc._orchestrator.plugins] == [PluginState.STOPPED]
    assert _close_and_journal(proc) == ["hk.shutdown"]


def test_h4_paused_plugin_gets_hook() -> None:
    """H4 PAUSED (ревью r1): RUNNING → ``_do_pause`` → закрытие процесса — хук получает до ``shutdown``."""
    _start_fresh()
    proc = _make_process(_unique("c60h4p"), [_entry("hk", HookPlugin)])
    orch = proc._orchestrator
    plugin, ctx = orch.plugins[0], orch._contexts[0]
    plugin._do_pause(ctx)
    assert [p.state for p in orch.plugins] == [PluginState.PAUSED]
    assert _close_and_journal(proc) == ["hk.request_stop", "hk.shutdown"]


# ---------------------------------------------------------------------------
# H5 — процесс без плагинов
# ---------------------------------------------------------------------------


def test_h5_process_without_plugins_closes_clean() -> None:
    """H5: процесс без плагинов (оркестратора нет) — закрытие ``True``, ошибок и выживших нет."""
    name = _unique("c60h5")
    proc = _make_process(name, [])
    try:
        m = _bounded(proc.shutdown, 20.0)
        report = proc.close_root()
    finally:
        _bounded(proc.shutdown, 20.0)
    assert m["done"], "shutdown() завис"
    assert m.get("error") is None, repr(m.get("error"))
    assert m["result"] is True
    assert list(report.errors) == []
    assert list(report.survivors) == []


# ---------------------------------------------------------------------------
# H6 — GenericProcess: хук раньше state_proxy и выхода воркера
# ---------------------------------------------------------------------------


class _JournalingQueueRegistry:
    """Транспортный сток ``GenericProcess``: пишет в журнал ``state.unsubscribe_all`` (роутер настоящий)."""

    def send_to_queue(self, target: str, qtype: str, msg: dict) -> bool:
        if isinstance(msg, dict) and msg.get("command") == "state.unsubscribe_all":
            JOURNAL.add("state.unsubscribe_all")
        return True

    def register_process_queues(self, *_a: object, **_kw: object) -> None:
        """No-op: реальные очереди стенду не нужны."""


def test_h6_generic_process_hook_before_state_proxy_and_worker_exit() -> None:
    """H6: ``GenericProcess`` — ``request_stop`` первым: раньше выхода воркера плагина и раньше unsubscribe_all."""
    _start_fresh()
    name = _unique("c60h6")
    proc = GenericProcess(name=name, config={"config": {"plugins": [_entry("gp", GenericProbePlugin)]}})
    sink = _JournalingQueueRegistry()

    def init_queues_stub() -> None:
        proc.queues = {}
        proc.queue_registry = sink
        proc.memory_manager = None

    proc._init_queues = init_queues_stub  # type: ignore[method-assign]
    proc.attach_stop_budget(BUDGET_W1)
    try:
        assert proc.initialize() is True, f"{name}: initialize() не дошёл до конца"
        assert KNOBS.worker_running.wait(5.0), f"{name}: воркер плагина не стартовал"
        m = _bounded(proc.shutdown, 20.0)
        assert m["done"], "shutdown() завис"
        assert m.get("error") is None, repr(m.get("error"))
        # unsubscribe_all уходит через фоновый отправитель — короткий опрос.
        deadline = time.monotonic() + 2.0
        while "state.unsubscribe_all" not in JOURNAL.names() and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        KNOBS.release_workers.set()
        _bounded(proc.shutdown, 20.0)
    names = JOURNAL.names()
    assert names[0] == "gp.request_stop", names
    assert names.count("gp.request_stop") == 1, names
    assert "gp.worker_exit" in names, names
    assert "state.unsubscribe_all" in names, names
    assert names.index("gp.worker_exit") < names.index("gp.shutdown"), names


# ---------------------------------------------------------------------------
# H7 — прямой двойной вызов оркестратора
# ---------------------------------------------------------------------------


def test_h7_direct_double_request_stop_repeats_hook_state_unchanged() -> None:
    """H7: ``_orchestrator.request_stop()`` дважды на RUNNING — хук 2 раза, без исключений, плагин RUNNING.

    Фреймворк не дедуплицирует (флага нет): идемпотентность — на плагине. Закрытие после — ещё один хук.
    """
    _start_fresh()
    proc = _make_process(_unique("c60h7"), [_entry("hk", HookPlugin)])
    try:
        first = _bounded(proc._orchestrator.request_stop, 10.0)
        second = _bounded(proc._orchestrator.request_stop, 10.0)
        assert first["done"] and second["done"], "request_stop() оркестратора завис"
        assert first.get("error") is None and second.get("error") is None, (first.get("error"), second.get("error"))
        assert JOURNAL.names() == ["hk.request_stop", "hk.request_stop"]
        assert [p.state for p in proc._orchestrator.plugins] == [PluginState.RUNNING]
    finally:
        names = _close_and_journal(proc)
    assert names == ["hk.request_stop", "hk.request_stop", "hk.request_stop", "hk.shutdown"]


# ---------------------------------------------------------------------------
# H8 — исключение хука видно в журнале ошибок процесса (ревью r1)
# ---------------------------------------------------------------------------


class RaisingHookPlugin(ProcessModulePlugin):
    """``request_stop`` бросает ``RuntimeError("boom")``."""

    name = "rb"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("rb.request_stop")
        raise RuntimeError("boom")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("rb.shutdown")


def test_h8_hook_failure_is_logged_as_error(capfd: pytest.CaptureFixture[str]) -> None:
    """H8: бросок хука — ровно одна строка ERROR с именем процесса, плагина и текстом; закрытие ``True``.

    Наблюдается настоящий сток журнала процесса (поток stderr, захват на уровне дескриптора): логгер процесса
    в корневой ``logging`` не распространяется, поэтому ``caplog`` строку не видит.
    """
    _start_fresh()
    name = _unique("c60h8")
    proc = _make_process(name, [_entry("rb", RaisingHookPlugin)])
    capfd.readouterr()  # сбросить строки сборки процесса
    try:
        m = _bounded(proc.shutdown, 20.0)
    finally:
        _bounded(proc.shutdown, 20.0)
    captured = capfd.readouterr()
    assert m["done"], "shutdown() завис"
    assert m.get("error") is None, repr(m.get("error"))
    assert m["result"] is True
    assert JOURNAL.names() == ["rb.request_stop", "rb.shutdown"]
    expected = f"PluginOrchestrator[{name}]: request_stop 'rb': boom"
    lines = (captured.err + captured.out).splitlines()
    hits = [ln for ln in lines if expected in ln]
    assert len(hits) == 1, lines
    assert "[ERROR]" in hits[0], hits[0]


# ---------------------------------------------------------------------------
# H9 — сторож умолчаний базового класса (регрессия C-60: удалённый штатный shutdown)
# ---------------------------------------------------------------------------


class BarePlugin(ProcessModulePlugin):
    """Плагин без своих ``shutdown`` и ``request_stop``: живёт на умолчаниях базового класса."""

    name = "bare"

    def configure(self, ctx: PluginContext) -> None:
        pass


def test_h9_plugin_on_base_defaults_closes_clean() -> None:
    """H9: плагин без своих ``shutdown``/``request_stop`` — закрытие ``True``, ошибок нет, плагин STOPPED."""
    name = _unique("c60h9")
    proc = _make_process(name, [_entry("bare", BarePlugin)])
    try:
        assert [p.state for p in proc._orchestrator.plugins] == [PluginState.RUNNING]
        m = _bounded(proc.shutdown, 20.0)
        report = proc.close_root()
    finally:
        _bounded(proc.shutdown, 20.0)
    assert m["done"], "shutdown() завис"
    assert m.get("error") is None, repr(m.get("error"))
    assert m["result"] is True
    assert list(report.errors) == []
    assert list(report.survivors) == []
    assert [p.state for p in proc._orchestrator.plugins] == [PluginState.STOPPED]


def test_h9_base_class_lifecycle_defaults_are_noops() -> None:
    """H9: ``ProcessModulePlugin.shutdown`` и ``.request_stop`` объявлены в базе и по умолчанию возвращают ``None``."""
    plugin = BarePlugin()
    assert "shutdown" in vars(ProcessModulePlugin)
    assert "request_stop" in vars(ProcessModulePlugin)
    assert plugin.shutdown(None) is None  # type: ignore[arg-type]
    assert plugin.request_stop(None) is None  # type: ignore[arg-type]
