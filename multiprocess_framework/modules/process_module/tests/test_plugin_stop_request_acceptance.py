# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты C-60: хук плагина ``request_stop`` (R1, R1b, R2, R3, R4, R5).

Написаны независимым тестером ТОЛЬКО по выжимке ``C60_EXCERPT.md``; реализации хука в дереве нет.

Контракт (выжимка): плагин процесса получает весть «стоп процесса начат» (``request_stop(ctx)``) на закрытии
процесса (``proc.shutdown()``) раньше ожидания воркеров и исполнителей процесса и раньше ``shutdown`` плагина;
плагины - в порядке, обратном загрузке; один вызов на закрытие; исключение хука не мешает соседу, остановке
воркеров и ``shutdown`` плагинов; ``proc.shutdown()`` возвращает ``True``.

Ожидание до реализации: R1, R1b, R3, R4 красные (хук не зовётся / зовётся поздно), R2 и R5 зелёные.

Стенд - настоящий ``ProcessModule`` (публичное API); порядок проверяется ТОЛЬКО по журналу событий,
моменты ``monotonic`` - только для задержек не меньше 0,1 с. Каждому процессу - уникальное имя.
Каждый ждущий вызов - в daemon-потоке с дедлайном ``join(30)``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

# ---------------------------------------------------------------------------
# Общий журнал событий (список в порядке вызова, под замком)
# ---------------------------------------------------------------------------


class _Journal:
    """Журнал строк ``"<имя>.<событие>"`` с моментами ``time.monotonic()``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[tuple[str, float]] = []
        self.worker_running = threading.Event()  # воркер зонда начал цикл (не строка журнала)

    def reset(self) -> None:
        with self._lock:
            self._events = []
        self.worker_running.clear()

    def add(self, name: str) -> None:
        with self._lock:
            self._events.append((name, time.monotonic()))

    def names(self) -> list[str]:
        with self._lock:
            return [n for n, _ in self._events]

    def moment(self, name: str) -> float | None:
        """Момент первой записи ``name`` или ``None``."""
        with self._lock:
            for n, t in self._events:
                if n == name:
                    return t
        return None


JOURNAL = _Journal()


def _worker_loop(label: str):
    """Цикл воркера зонда: до ``stop_event``; на выходе пишет ``<label>.worker_exit``."""

    def loop(stop_event: Any, pause_event: Any) -> None:
        JOURNAL.worker_running.set()
        try:
            while not stop_event.is_set():
                time.sleep(0.01)
        finally:
            JOURNAL.add(f"{label}.worker_exit")

    return loop


# ---------------------------------------------------------------------------
# Плагины-зонды
# ---------------------------------------------------------------------------


class ProbePlugin(ProcessModulePlugin):
    """Зонд с воркером и хуком ``request_stop`` (R1, R1b, R2)."""

    name = "probe"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("probe_worker", _worker_loop("probe"), cfg, auto_start=True)

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("probe.request_stop")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("probe.shutdown")


class NoHookPlugin(ProcessModulePlugin):
    """Зонд с воркером БЕЗ ``request_stop`` (R5): хук берётся умолчанием базового класса."""

    name = "probe"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("probe_worker", _worker_loop("probe"), cfg, auto_start=True)

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("probe.shutdown")


class PluginA(ProcessModulePlugin):
    """Плагин A без воркера (R3, R4): обычный хук."""

    name = "A"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        pass

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("A.request_stop")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("A.shutdown")


class PluginB(ProcessModulePlugin):
    """Плагин B без воркера (R3): обычный хук."""

    name = "B"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        pass

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("B.request_stop")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("B.shutdown")


class PluginBRaises(ProcessModulePlugin):
    """Плагин B без воркера (R4): ``request_stop`` пишет в журнал и бросает ``RuntimeError``."""

    name = "B"

    def configure(self, ctx: PluginContext) -> None:
        pass

    def start(self, ctx: PluginContext) -> None:
        pass

    def request_stop(self, ctx: PluginContext) -> None:
        JOURNAL.add("B.request_stop")
        raise RuntimeError("c60 probe: request_stop of B fails on purpose")

    def shutdown(self, ctx: PluginContext) -> None:
        JOURNAL.add("B.shutdown")


# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


def _plugin_entry(plugin_name: str, cls: type) -> dict[str, str]:
    return {"plugin_name": plugin_name, "plugin_class": f"{__name__}.{cls.__name__}"}


def _make_process(name: str, plugins: list[dict[str, str]], budget: dict[str, float] | None) -> ProcessModule:
    proc = ProcessModule(
        name,
        config={"config": {"executors": {"io": {"serial": True}}, "plugins": plugins}},
    )
    if budget is not None:
        proc.attach_stop_budget(budget)
    assert proc.initialize() is True
    return proc


def _bounded_shutdown(proc: ProcessModule, timeout_s: float = 30.0) -> dict[str, Any]:
    """``proc.shutdown()`` в daemon-потоке с ``join``-дедлайном: t0, длительность, результат, ошибка."""
    box: dict[str, Any] = {}

    def run() -> None:
        box["t0"] = time.monotonic()
        try:
            box["result"] = proc.shutdown()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - box["t0"]

    th = threading.Thread(target=run, daemon=True, name="c60-shutdown-probe")
    th.start()
    th.join(timeout_s)
    box["done"] = not th.is_alive()
    return box


class _Op:
    """Долгая операция исполнителя ``io``: «начало» -> ждёт ``release`` до ``L`` секунд -> момент конца."""

    def __init__(self, length_s: float) -> None:
        self.length_s = length_s
        self.started = threading.Event()
        self.release = threading.Event()
        self.ended = threading.Event()
        self.end_at: float | None = None

    def action(self) -> dict:
        self.started.set()
        self.release.wait(self.length_s)
        self.end_at = time.monotonic()
        self.ended.set()
        return {"success": True}


def _run_scenario(name: str, plugin_cls: type, budget: dict[str, float] | None, op_len_s: float) -> dict[str, Any]:
    """Один процесс с зондом-воркером и долгой операцией ``io``: закрыть, вернуть замеры."""
    JOURNAL.reset()
    proc = _make_process(name, [_plugin_entry("probe", plugin_cls)], budget)
    op = _Op(op_len_s)
    out: dict[str, Any] = {}
    try:
        assert JOURNAL.worker_running.wait(5.0), f"{name}: воркер зонда не стартовал"
        io = proc.executor_manager.get("io")
        assert io is not None, f"{name}: исполнитель io не создан"
        io.submit(op.action, frozenset({"k"}), lambda result: None)
        assert op.started.wait(5.0), f"{name}: долгая операция не началась до закрытия"

        out = _bounded_shutdown(proc)
        out["op_ended"] = op.ended.wait(op_len_s + 5.0)
        out["op_end_at"] = op.end_at
        out["names"] = JOURNAL.names()
        out["request_stop_at"] = JOURNAL.moment("probe.request_stop")
        out["shutdown_at"] = JOURNAL.moment("probe.shutdown")
    finally:
        op.release.set()
        _bounded_shutdown(proc)
    return out


def _first_news(m: dict[str, Any]) -> float | None:
    """«Первая весть» = минимум моментов ``request_stop`` и ``shutdown`` плагина (``None`` - не было ни одного)."""
    moments = [t for t in (m["request_stop_at"], m["shutdown_at"]) if t is not None]
    return min(moments) if moments else None


# ---------------------------------------------------------------------------
# R1
# ---------------------------------------------------------------------------


def test_plugin_hears_stop_before_long_executor_op_ends() -> None:
    """R1: бюджет работ 1,0 с, операция 2,5 с начата до закрытия; весть плагину - в первые 0,25 с, до конца операции."""
    failures: list[str] = []
    for i in range(5):
        m = _run_scenario(f"c60r1_{i}", ProbePlugin, {"work_s": 1.0, "infra_s": 0.25}, 2.5)
        assert m["done"], f"c60r1_{i}: proc.shutdown() завис (join 30 с)"
        assert m["op_ended"], f"c60r1_{i}: долгая операция не закончилась"
        first = _first_news(m)
        if first is None:
            failures.append(f"c60r1_{i}: плагин не получил ни request_stop, ни shutdown; журнал {m['names']}")
            continue
        delay = first - m["t0"]
        after = m["op_end_at"] - first
        if delay > 0.25:
            failures.append(
                f"c60r1_{i}: первая весть через {delay:.3f} с после shutdown() (ждали <= 0.25); журнал {m['names']}"
            )
        if after < 1.0:
            failures.append(f"c60r1_{i}: конец операции через {after:.3f} с после первой вести (ждали >= 1.0)")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# R1b
# ---------------------------------------------------------------------------


def test_plugin_hears_stop_before_long_op_default_budget() -> None:
    """R1b: бюджет процесса по умолчанию (work_s = 3,0), операция 4,0 с; весть плагину - в первые 0,25 с."""
    m = _run_scenario("c60r1b_0", ProbePlugin, None, 4.0)
    assert m["done"], "c60r1b_0: proc.shutdown() завис (join 30 с)"
    first = _first_news(m)
    assert first is not None, f"плагин не получил ни request_stop, ни shutdown; журнал {m['names']}"
    delay = first - m["t0"]
    assert delay <= 0.25, f"первая весть через {delay:.3f} с после shutdown() (ждали <= 0.25); журнал {m['names']}"


# ---------------------------------------------------------------------------
# R2 (страж)
# ---------------------------------------------------------------------------


def test_plugin_shutdown_still_after_own_workers_stop() -> None:
    """R2: ``shutdown`` плагина по-прежнему после остановки его воркера и по-прежнему около бюджета (0,95-1,40 с)."""
    failures: list[str] = []
    for i in range(5):
        m = _run_scenario(f"c60r2_{i}", ProbePlugin, {"work_s": 1.0, "infra_s": 0.25}, 2.5)
        assert m["done"], f"c60r2_{i}: proc.shutdown() завис (join 30 с)"
        names = m["names"]
        if m["shutdown_at"] is None:
            failures.append(f"c60r2_{i}: probe.shutdown не записан; журнал {names}")
            continue
        elapsed = m["shutdown_at"] - m["t0"]
        if not 0.95 <= elapsed <= 1.40:
            failures.append(
                f"c60r2_{i}: shutdown плагина через {elapsed:.3f} с после shutdown() процесса (ждали [0.95; 1.40])"
            )
        if "probe.worker_exit" not in names or "probe.shutdown" not in names:
            failures.append(f"c60r2_{i}: в журнале нет worker_exit или shutdown: {names}")
        elif names.index("probe.worker_exit") > names.index("probe.shutdown"):
            failures.append(f"c60r2_{i}: worker_exit позже shutdown плагина: {names}")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------


def test_stop_request_reaches_running_plugins_once_in_reverse_order() -> None:
    """R3: хук - каждому работающему плагину один раз, в порядке, обратном загрузке, раньше их ``shutdown``."""
    JOURNAL.reset()
    proc = _make_process("c60r3_0", [_plugin_entry("A", PluginA), _plugin_entry("B", PluginB)], None)
    try:
        first = _bounded_shutdown(proc)
        second = _bounded_shutdown(proc)
    finally:
        _bounded_shutdown(proc)
    assert first["done"], "первый proc.shutdown() завис (join 30 с)"
    assert second["done"], "повторный proc.shutdown() завис (join 30 с)"
    assert JOURNAL.names() == ["B.request_stop", "A.request_stop", "B.shutdown", "A.shutdown"]


# ---------------------------------------------------------------------------
# R4
# ---------------------------------------------------------------------------


def test_stop_request_failure_does_not_block_neighbours() -> None:
    """R4: ``request_stop`` второго плагина бросает - хук первого, ``shutdown`` обоих и ``True`` целы."""
    JOURNAL.reset()
    proc = _make_process("c60r4_0", [_plugin_entry("A", PluginA), _plugin_entry("B", PluginBRaises)], None)
    try:
        m = _bounded_shutdown(proc)
    finally:
        _bounded_shutdown(proc)
    assert m["done"], "proc.shutdown() завис (join 30 с)"
    assert "error" not in m, f"proc.shutdown() бросил {m.get('error')!r}"
    assert JOURNAL.names() == ["B.request_stop", "A.request_stop", "B.shutdown", "A.shutdown"]
    assert m["result"] is True, f"proc.shutdown() вернул {m['result']!r}, ждали True"
    assert m["elapsed"] <= 2.0, f"proc.shutdown() занял {m['elapsed']:.3f} с (ждали <= 2.0)"


# ---------------------------------------------------------------------------
# R5 (страж)
# ---------------------------------------------------------------------------


def test_plugin_without_hook_unchanged() -> None:
    """R5: плагин без ``request_stop`` живёт как раньше: ``shutdown`` около бюджета (0,95-1,40 с), без исключений."""
    failures: list[str] = []
    for i in range(5):
        m = _run_scenario(f"c60r5_{i}", NoHookPlugin, {"work_s": 1.0, "infra_s": 0.25}, 2.5)
        assert m["done"], f"c60r5_{i}: proc.shutdown() завис (join 30 с)"
        if "error" in m:
            failures.append(f"c60r5_{i}: proc.shutdown() бросил {m['error']!r}")
            continue
        if m["shutdown_at"] is None:
            failures.append(f"c60r5_{i}: probe.shutdown не записан; журнал {m['names']}")
            continue
        elapsed = m["shutdown_at"] - m["t0"]
        if not 0.95 <= elapsed <= 1.40:
            failures.append(
                f"c60r5_{i}: shutdown плагина через {elapsed:.3f} с после shutdown() процесса (ждали [0.95; 1.40])"
            )
    assert not failures, "\n".join(failures)
