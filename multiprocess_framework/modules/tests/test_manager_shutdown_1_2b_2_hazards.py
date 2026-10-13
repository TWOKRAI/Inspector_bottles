"""Авторские hazard-тесты Task 1.2b-2 (lifecycle-owner-scope): кодмод ``shutdown`` -> ``_on_shutdown``.

Что здесь, чего нет у слепого тестера:

- принятое изменение поведения (ревью р.1 п.6): исключение тела ``StateProxy`` ->
  ``False`` + одна строка шаблона; запись корня ``state_proxy`` больше не даёт ошибку
  в ``CloseReport.errors`` (до 1.2b-2 — одна ошибка);
- гонка ``shutdown()`` и ``shutdown_nowait()`` у ``WorkerPoolExecutor``;
- значение ``_ON_SHUTDOWN_WAIT_S`` экземпляра ``ProcessModule`` не течёт в класс и
  в соседний экземпляр;
- переопределение ``_ON_SHUTDOWN_WAIT_S`` на экземпляре входит в формулу срока.

Ожидаемые значения — литералы; всё, что может зависнуть, идёт в daemon-потоке со
сроком; корни ``t02…`` закрываются.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.base_manager.core.base_manager import BaseManager
from multiprocess_framework.modules.chain_module import WorkerPoolExecutor
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

DEADLINE_S = 15.0
LOGGER_NAME = "multiprocess_framework.modules.base_manager.core.base_manager"


def call_bounded(fn, timeout_s: float):
    """Вызвать ``fn`` в daemon-потоке; вернуть (завершился, результат, ошибка, длительность)."""
    box: dict = {}

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=run, daemon=True, name="call_bounded_1_2b_2")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error"), box.get("elapsed")


def _template_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]


# ---------------------------------------------------------------------------
# StateProxy: исключение тела -> False + строка шаблона, вне CloseReport.errors
# ---------------------------------------------------------------------------


def _proxy_with_failing_send(process_name: str) -> StateProxy:
    """``StateProxy`` с живой подпиской, у которого ``_send`` бросает."""
    proxy = StateProxy(process_name, router=object())
    proxy._sub_ids.append("t02-sub-1")

    def failing_send(msg: dict) -> None:
        raise RuntimeError("router lost")

    proxy._send = failing_send  # type: ignore[method-assign]
    return proxy


def test_state_proxy_body_exception_returns_false_with_one_template_line(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    proxy = _proxy_with_failing_send("t02hz_sp")
    assert isinstance(proxy._sub_ids, list)

    done, result, error, _ = call_bounded(proxy.shutdown, DEADLINE_S)
    assert done, "shutdown() завис"
    assert error is None, f"исключение тела ушло наружу: {error!r}"
    assert result is False

    expected = "shutdown StateProxy:t02hz_sp: _on_shutdown упал: RuntimeError: router lost"
    assert _template_lines(caplog).count(expected) == 1, _template_lines(caplog)

    # Повтор — кэш шаблона: то же False, тело второй раз не идёт, строки не прибавилось.
    assert proxy.shutdown() is False
    assert _template_lines(caplog).count(expected) == 1


def test_state_proxy_in_root_is_not_a_root_error() -> None:
    proxy = _proxy_with_failing_send("t02hz_sp_root")
    root = open_scope(f"t02hz-root-{uuid.uuid4().hex[:8]}", budget_s=2.0)
    root.own(proxy.shutdown, name="state_proxy", kind="callable")

    done, report, error, _ = call_bounded(root.close, DEADLINE_S)
    assert done, "close корня завис"
    assert error is None, repr(error)
    # До 1.2b-2 своё shutdown() бросало наружу -> одна ошибка в отчёте корня.
    assert report.errors == ()


# ---------------------------------------------------------------------------
# WorkerPoolExecutor: гонка shutdown() и shutdown_nowait()
# ---------------------------------------------------------------------------


class _Sleep:
    def __init__(self, sink: list, i: int) -> None:
        self._sink = sink
        self._i = i

    def process(self, frame):
        time.sleep(0.01)
        self._sink.append(self._i)
        return self._i

    def configure(self, p):
        pass


@pytest.mark.parametrize("round_no", range(5))
def test_worker_pool_shutdown_races_shutdown_nowait(round_no: int) -> None:
    sink: list = []
    ex = WorkerPoolExecutor(max_workers=2, step_timeout=5.0)
    for i in range(10):
        ex.submit(_Sleep(sink, i), None, None)

    start = threading.Barrier(2)
    results: dict = {}

    def call(name: str, fn) -> None:
        start.wait(DEADLINE_S)
        try:
            ret = fn()
            # Снимок В МОМЕНТ возврата: «True» обязан значить «воркеры уже вышли».
            alive = [t.name for t in threading.enumerate() if ex._name_prefix in t.name and t.is_alive()]
            results[name] = (ret, len(sink), alive)
        except BaseException as exc:  # noqa: BLE001
            results[name] = exc

    a = threading.Thread(target=call, args=("shutdown", ex.shutdown), daemon=True)
    b = threading.Thread(target=call, args=("nowait", ex.shutdown_nowait), daemon=True)
    a.start()
    b.start()
    a.join(DEADLINE_S)
    b.join(DEADLINE_S)
    assert not a.is_alive() and not b.is_alive(), "останов пула завис"
    assert set(results) == {"shutdown", "nowait"}, results
    final = len(sink)
    for name, value in results.items():
        assert isinstance(value, tuple), f"{name}: {value!r}"
        ret, n_at_return, alive_at_return = value
        assert ret is True, f"{name}: {value!r}"
        assert alive_at_return == [], f"{name} вернул True при живых воркерах: {value!r}"
        assert n_at_return == final, f"{name}: хвост дописывался после возврата: {value!r}, итог {final}"
    # Взятые задачи доисполнены, невзятые отменены: исполнен префикс очереди без дыр.
    assert sorted(sink) == list(range(final)), sink
    assert ex.shutdown() is True
    assert ex.shutdown_nowait() is True


# ---------------------------------------------------------------------------
# ProcessModule: значение экземпляра не течёт в класс и соседа
# ---------------------------------------------------------------------------


def test_process_module_instance_wait_is_per_instance() -> None:
    a = ProcessModule("t02hz_pa", config={})
    b = ProcessModule("t02hz_pb", config={})
    try:
        a.attach_stop_budget({"work_s": 0.3, "infra_s": 0.2})
        b.attach_stop_budget({"work_s": 1.0, "infra_s": 0.5})
        assert a.initialize() is True
        assert b.initialize() is True
        assert a._ON_SHUTDOWN_WAIT_S == pytest.approx(0.5)
        assert b._ON_SHUTDOWN_WAIT_S == pytest.approx(1.5)
        assert ProcessModule._ON_SHUTDOWN_WAIT_S == 5.0
        assert BaseManager._ON_SHUTDOWN_WAIT_S == 5.0
    finally:
        for proc in (a, b):
            call_bounded(proc.shutdown, 30.0)
            proc.close_root()
    assert a.close_root() is not None
    assert b.close_root() is not None


# ---------------------------------------------------------------------------
# Формула: переопределение на экземпляре
# ---------------------------------------------------------------------------


class _GateManager(BaseManager):
    def __init__(self, name: str, entered: threading.Event, gate: threading.Event) -> None:
        super().__init__(name)
        self._entered = entered
        self._gate = gate

    def initialize(self) -> bool:
        return True

    def _on_shutdown(self) -> bool:
        self._entered.set()
        self._gate.wait(DEADLINE_S)
        return True


def test_instance_override_enters_second_call_wait(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    entered, gate = threading.Event(), threading.Event()
    mgr = _GateManager("t02hz_inst", entered, gate)
    mgr._ON_SHUTDOWN_WAIT_S = 0.2
    root = open_scope(f"t02hz-inst-{uuid.uuid4().hex[:8]}", budget_s=0.3, kill_reserve_s=0.0)
    mgr.attach_scope(root)

    first: dict = {}
    th = threading.Thread(target=lambda: first.setdefault("r", mgr.shutdown()), daemon=True)
    th.start()
    try:
        assert entered.wait(DEADLINE_S), "первый вызов не дошёл до _on_shutdown"
        done, result, error, elapsed = call_bounded(mgr.shutdown, DEADLINE_S)
        assert done and error is None, repr(error)
        assert result is False
        # 0.3 (область) + 0.2 (экземпляр); без экземпляра было бы 5.3.
        assert 0.45 <= elapsed < 1.5, f"второй вызов ждал {elapsed:.3f} с, ожидалось 0,5 с"
    finally:
        gate.set()
    th.join(DEADLINE_S)
    assert first["r"] is True
    expected = "shutdown t02hz_inst: первый вызов не завершился за 0.5 с — второй вызов вернул False"
    assert _template_lines(caplog).count(expected) == 1, _template_lines(caplog)
    assert _GateManager._ON_SHUTDOWN_WAIT_S == 5.0
