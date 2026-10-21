# -*- coding: utf-8 -*-
"""Hazard- и контрактные тесты автора Task 1.9a: развилка ``CommandManager`` и роутер (H3, H4, H6 + контракт D3/D4).

Правила стенда: ждущие вызовы — в daemon-потоке с дедлайном join; ожидания — литералы; часы —
``time.perf_counter()``; исполнитель — настоящий ``KeyedExecutor`` с настоящим ``WorkerManager``;
H4/H6 и контракт роутера — через настоящие ``RouterManager`` + ``CommandManager``.
"""

from __future__ import annotations

import copy
import inspect
import threading
import time
from queue import Queue
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.command_module import DEFERRED, ICommandManager
from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.keyed_executor import KeyedExecutor


def run_bounded(fn: Callable[[], Any], timeout: float = 5.0) -> tuple[Any, int]:
    box: dict[str, Any] = {}

    def target() -> None:
        box["ident"] = threading.get_ident()
        try:
            box["ret"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    t = threading.Thread(target=target, name="cm-hazard-probe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pytest.fail(f"вызов не вернулся за {timeout} с (зависание)")
    if "exc" in box:
        raise box["exc"]
    return box.get("ret"), box["ident"]


class LogRec:
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

    def warnings(self) -> list[str]:
        with self._lock:
            return [m for lvl, m in self.records if lvl == "warning"]


class StatsRec:
    """Слот ``stats``: запоминает ``record_timing``; прочие вызовы — no-op."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.timings: list[tuple[str, float, dict]] = []
        self.metrics: list[tuple[str, dict]] = []

    def record_metric(self, name: str, value: Any = 1, tags: dict | None = None, **kw: Any) -> None:
        with self._lock:
            self.metrics.append((name, dict(tags or {})))

    def record_timing(self, name: str, duration: float, tags: dict | None = None, **kw: Any) -> None:
        with self._lock:
            self.timings.append((name, duration, dict(tags or {})))

    def __getattr__(self, item: str) -> Callable[..., None]:
        return lambda *a, **k: None

    def durations(self, command: str) -> list[float]:
        with self._lock:
            return [
                d
                for (n, d, t) in self.timings
                if n == "command_manager.command.execution.duration" and t.get("command") == command
            ]


def make_cm(name: str = "seg", stats: StatsRec | None = None) -> tuple[CommandManager, LogRec]:
    log = LogRec()
    managers: dict[str, Any] = {"logger": log}
    if stats is not None:
        managers["stats"] = stats
    cm = CommandManager(manager_name=name, managers=managers)
    cm.initialize()
    return cm, log


@pytest.fixture
def make_executor():
    created: list[tuple[KeyedExecutor, WorkerManager]] = []

    def factory(name: str = "t", **kwargs: Any) -> KeyedExecutor:
        wm = WorkerManager(f"wmc-{name}-{len(created)}")
        wm.initialize()
        ex = KeyedExecutor(name, worker_manager=wm, **kwargs)
        created.append((ex, wm))
        return ex

    yield factory
    for ex, wm in created:
        try:
            ex.request_stop()
            ex.join_until(time.monotonic() + 2.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            wm.shutdown()
        except Exception:  # noqa: BLE001
            pass


class SendRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sent: list[dict] = []

    def send_to_queue(self, target, qtype, msg, timeout: float = 0.0, on_evict=None) -> bool:
        with self._lock:
            self.sent.append(dict(msg))
        return True

    def get_queue(self, process, qtype):
        return None

    def by_request(self, request_id: str) -> list[dict]:
        with self._lock:
            return [m for m in self.sent if m.get("request_id") == request_id]


class _Proc:
    def __init__(self, name: str, cm: Any) -> None:
        self.name = name
        self.command_manager = cm


class Wired:
    def __init__(self, cm: Any) -> None:
        self.q: Queue = Queue()
        self.reg = SendRegistry()
        self.router = RouterManager(manager_name="seg", process=_Proc("seg", cm), queue_registry=self.reg)
        self.router.register_channel(QueueChannel("seg_system", self.q))
        self.router.initialize()

    def put(self, command: str, request_id: str, data: dict) -> None:
        self.q.put({"type": "command", "command": command, "sender": "gui", "request_id": request_id, "data": data})

    def receive_once(self) -> None:
        run_bounded(lambda: self.router.receive(timeout=0.0, channel_types=["system"]), timeout=5.0)

    def wait_replies(self, request_id: str, timeout: float = 3.0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.reg.by_request(request_id)
            if got:
                return got
            time.sleep(0.01)
        return self.reg.by_request(request_id)

    def close(self) -> None:
        threading.Thread(target=self._safe_shutdown, daemon=True).start()

    def _safe_shutdown(self) -> None:
        try:
            self.router.shutdown()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def wired():
    made: list[Wired] = []

    def factory(cm: Any) -> Wired:
        w = Wired(cm)
        made.append(w)
        return w

    yield factory
    for w in made:
        w.close()


# ---------------------------------------------------------------------------
# H3: метрика длительности меряет исполнение, а не подачу
# ---------------------------------------------------------------------------


def test_h3_duration_metric_measures_execution_not_submit(make_executor):
    """H3: операция 0,3 с через исполнитель — метрика длительности ≥ 0,3 с (а не ~0 подачи)."""
    stats = StatsRec()
    cm, _log = make_cm("h3", stats=stats)
    ex = make_executor("h3")

    def slow(data: dict) -> dict:
        threading.Event().wait(0.3)
        return {"success": True}

    assert cm.register_command("slow.cmd", slow, executor=ex, key_from="process_name") is True
    got: list[Any] = []
    done = threading.Event()
    ret, _ = run_bounded(
        lambda: cm.handle_command(
            {"command": "slow.cmd", "data": {"process_name": "p1"}},
            reply=lambda r: (got.append(r), done.set()),
        )
    )
    assert ret is DEFERRED
    assert done.wait(3.0), "reply не пришёл за 3 с"
    durations = stats.durations("slow.cmd")
    assert len(durations) == 1, f"ожидали одну запись длительности, получили {durations!r}"
    assert durations[0] >= 0.3, f"длительность {durations[0]:.3f} с < 0.3 — меряется подача, не исполнение"


# ---------------------------------------------------------------------------
# H4: исключение в обработчике отложенной команды — тот же конверт, что у синхронной
# ---------------------------------------------------------------------------


def test_h4_handler_exception_in_deferred_command_gives_same_envelope(make_executor, wired):
    ex = make_executor("h4")
    cm, _log = make_cm("seg")

    def boom(data: dict) -> dict:
        raise ValueError("h4-boom")

    assert cm.register_command("boom.plain", boom) is True
    assert cm.register_command("boom.exec", boom, executor=ex, key_from="process_name") is True
    w = wired(cm)
    w.put("boom.plain", "h4-plain", {"process_name": "p1"})
    w.receive_once()
    w.put("boom.exec", "h4-exec", {"process_name": "p1"})
    w.receive_once()
    plain = w.wait_replies("h4-plain")
    got = w.wait_replies("h4-exec")
    time.sleep(0.2)
    plain, got = w.reg.by_request("h4-plain"), w.reg.by_request("h4-exec")
    assert len(plain) == 1 and len(got) == 1, f"ответов: без исполнителя {len(plain)}, с исполнителем {len(got)}"
    assert got[0]["success"] is False
    assert got[0]["result"].get("status") == "error", f"конверт отложенной: {got[0]['result']!r}"
    assert "h4-boom" in str(got[0]["result"].get("reason") or got[0]["result"].get("error"))
    strip = lambda env: {k: v for k, v in env.items() if k != "request_id"}  # noqa: E731
    assert strip(got[0]) == strip(plain[0])


# ---------------------------------------------------------------------------
# H6: снятие трубки не ждёт исполнителя
# ---------------------------------------------------------------------------


def _p99(samples: list[float]) -> float:
    s = sorted(samples)
    return s[min(len(s) - 1, int(round(0.99 * (len(s) - 1))))]


def test_h6_receive_latency_unaffected_while_executor_busy(make_executor, wired):
    """H6: p99 от put до входа в обработчик команды без исполнителя ≤ 20 мс или ≤ p99 без нагрузки + 10 мс."""
    ex = make_executor("h6", max_workers=2)
    cm, _log = make_cm("seg")
    entered: list[float] = []

    def plain(data: dict) -> dict:
        entered.append(time.perf_counter())
        return {"success": True}

    def heavy(data: dict) -> dict:
        threading.Event().wait(1.0)
        return {"success": True}

    assert cm.register_command("plain.cmd", plain) is True
    assert cm.register_command("heavy.cmd", heavy, executor=ex, key_from="process_name") is True
    w = wired(cm)

    def measure(n: int, prefix: str, heavy_every: int = 0) -> list[float]:
        lat: list[float] = []

        def loop() -> None:
            for i in range(n):
                entered.clear()
                t_put = time.perf_counter()
                if heavy_every and i % heavy_every == 0:
                    # Тяжёлая команда с исполнителем — в той же очереди ПЕРЕД простой:
                    # приёмный поток снимает её трубку первой и не должен её ждать.
                    w.put("heavy.cmd", f"{prefix}-heavy-{i}", {"process_name": f"p{i % 2 + 1}"})
                w.put("plain.cmd", f"{prefix}-{i}", {})
                deadline = time.monotonic() + 3.0
                while not entered and time.monotonic() < deadline:
                    w.router.receive(timeout=0.0, channel_types=["system"])
                lat.append(entered[0] - t_put if entered else float("inf"))

        run_bounded(loop, timeout=30.0)
        return lat

    baseline = _p99(measure(200, "base"))
    # Нагрузка: два ключа заняты по 1 с, ещё по одной ждёт за каждым.
    for i, pn in enumerate(("p1", "p2", "p1", "p2")):
        w.put("heavy.cmd", f"heavy-{i}", {"process_name": pn})
        w.receive_once()
    loaded = _p99(measure(200, "load", heavy_every=25))
    assert loaded <= 0.020 or loaded <= baseline + 0.010, (
        f"p99 снятия трубки под нагрузкой {loaded * 1000:.1f} мс (без нагрузки {baseline * 1000:.1f} мс)"
    )


# ---------------------------------------------------------------------------
# Контракт D3/D4
# ---------------------------------------------------------------------------


def test_contract_metadata_holds_only_strings_and_caller_dict_is_not_mutated(make_executor):
    ex = make_executor("meta")
    cm, _log = make_cm("seg")
    caller_meta = {"description": "d"}
    assert cm.register_command("m.key", lambda d: {}, metadata=caller_meta, executor=ex, key_from="process_name")
    assert cm.register_command("m.all", lambda d: {}, executor=ex, targets="all")
    assert caller_meta == {"description": "d"}, "metadata вызывающего мутирована"
    assert cm.get_command_info("m.key")["metadata"] == {
        "description": "d",
        "executor": "meta",
        "key_from": "process_name",
    }
    assert cm.get_command_info("m.all")["metadata"] == {"executor": "meta", "targets": "all"}


def test_contract_key_from_or_targets_without_executor_is_refused():
    cm, log = make_cm("seg")
    assert cm.register_command("x.1", lambda d: {}, key_from="process_name") is False
    assert cm.register_command("x.2", lambda d: {}, targets="all") is False
    assert cm.get_command_info("x.1") is None and cm.get_command_info("x.2") is None
    assert len(log.warnings()) == 2


def test_contract_deferred_with_reply_delivers_once_and_never_returns_deferred_without_reply(make_executor):
    ex = make_executor("once")
    cm, _log = make_cm("seg")
    assert cm.register_command("c.once", lambda d: {"success": True, "v": 3}, executor=ex, key_from="process_name")
    got: list[Any] = []
    ret, _ = run_bounded(
        lambda: cm.handle_command({"command": "c.once", "data": {"process_name": "p"}}, reply=got.append)
    )
    assert ret is DEFERRED
    deadline = time.monotonic() + 3.0
    while not got and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.2)
    assert got == [{"success": True, "v": 3}]
    # Без reply — результат обработчика, не DEFERRED (ревью р.1 п.6).
    ret2, _ = run_bounded(lambda: cm.handle_command({"command": "c.once", "data": {"process_name": "p"}}))
    assert ret2 is not DEFERRED
    assert ret2 == {"success": True, "v": 3}


def test_contract_executor_refusal_counts_as_command_error(make_executor):
    """Отказ исполнителя — ошибка команды: WARNING и метрика errors, длительности нет (ревью р.1 п.3)."""
    stats = StatsRec()
    cm, log = make_cm("seg", stats=stats)
    ex = make_executor("refm")
    ex.request_stop()
    assert cm.register_command("c.ref", lambda d: {"success": True}, executor=ex, key_from="process_name")
    got: list[Any] = []
    ret, _ = run_bounded(
        lambda: cm.handle_command({"command": "c.ref", "data": {"process_name": "p"}}, reply=got.append)
    )
    assert ret is DEFERRED
    assert got == [{"success": False, "error": "system_stopping"}]
    assert ("command_manager.command.execution.errors", {"command": "c.ref"}) in stats.metrics
    assert ("command_manager.command.execution.success", {"command": "c.ref"}) not in stats.metrics
    assert stats.durations("c.ref") == []
    assert [w for w in log.warnings() if "c.ref" in w and "system_stopping" in w]


def test_contract_targets_all_orders_after_earlier_keyed_command(make_executor):
    ex = make_executor("all", max_workers=4)
    cm, _log = make_cm("seg")
    marks: dict[str, float] = {}

    def keyed(data: dict) -> dict:
        threading.Event().wait(0.2)
        marks["keyed_end"] = time.perf_counter()
        return {"success": True}

    def everyone(data: dict) -> dict:
        marks["all_start"] = time.perf_counter()
        return {"success": True}

    assert cm.register_command("c.keyed", keyed, executor=ex, key_from="process_name")
    assert cm.register_command("c.all", everyone, executor=ex, targets="all")
    got: list[Any] = []
    run_bounded(lambda: cm.handle_command({"command": "c.keyed", "data": {"process_name": "p"}}, reply=got.append))
    run_bounded(lambda: cm.handle_command({"command": "c.all", "data": {}}, reply=got.append))
    deadline = time.monotonic() + 3.0
    while len(got) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(got) == 2
    assert marks["all_start"] >= marks["keyed_end"], "targets='all' обогнала ранее поданную команду с ключом"


def test_contract_overwrite_command_makes_command_synchronous_again(make_executor):
    ex = make_executor("ow")
    cm, _log = make_cm("seg")
    assert cm.register_command("c.ow", lambda d: {"v": 1}, executor=ex, key_from="process_name")
    assert cm.overwrite_command("c.ow", lambda d: {"v": 2}) is True
    got: list[Any] = []
    ret, _ = run_bounded(lambda: cm.handle_command({"command": "c.ow", "data": {}}, reply=got.append))
    assert ret == {"v": 2}
    assert got == []


def test_contract_erased_executor_metadata_runs_inline_through_router(make_executor, wired):
    """update_command_metadata стёр строку executor → роутер не передаёт reply → на месте + WARNING, один ответ."""
    ex = make_executor("erase")
    cm, log = make_cm("seg")
    threads: list[int] = []

    def handler(data: dict) -> dict:
        threads.append(threading.get_ident())
        return {"success": True}

    assert cm.register_command("c.erase", handler, executor=ex, key_from="process_name")
    assert cm.update_command_metadata("c.erase", {"description": "без executor"}) is True
    assert "executor" not in cm.get_command_info("c.erase")["metadata"]
    w = wired(cm)
    w.put("c.erase", "erase-1", {"process_name": "p"})
    run_bounded(lambda: (w.router.receive(timeout=0.0, channel_types=["system"]), threads))
    got = w.wait_replies("erase-1")
    time.sleep(0.2)
    assert len(w.reg.by_request("erase-1")) == 1 and got[0]["success"] is True
    assert [m for m in log.warnings() if "исполнено вне очереди ключа" in m and "c.erase" in m]


def test_contract_key_missing_through_router_gets_one_auto_reply(make_executor, wired):
    ex = make_executor("km")
    cm, _log = make_cm("seg")
    called: list[Any] = []
    assert cm.register_command("c.km", lambda d: called.append(d) or {}, executor=ex, key_from="process_name")
    w = wired(cm)
    w.put("c.km", "km-1", {})
    w.receive_once()
    got = w.wait_replies("km-1")
    time.sleep(0.2)
    got = w.reg.by_request("km-1")
    assert len(got) == 1
    assert got[0]["success"] is False
    assert got[0]["result"] == {"success": False, "error": "key_missing", "command": "c.km"}
    assert called == []


def test_contract_executor_refusal_reaches_initiator_as_one_reply(make_executor, wired):
    """Отказ исполнителя (закрыт) — ровно один ответ инициатору, success=False, error=system_stopping."""
    ex = make_executor("stopped")
    ex.request_stop()
    cm, _log = make_cm("seg")
    assert cm.register_command("c.stop", lambda d: {"success": True}, executor=ex, key_from="process_name")
    w = wired(cm)
    w.put("c.stop", "stop-1", {"process_name": "p"})
    w.receive_once()
    w.wait_replies("stop-1")
    time.sleep(0.2)
    got = w.reg.by_request("stop-1")
    assert len(got) == 1
    assert got[0]["success"] is False
    assert got[0]["result"] == {"success": False, "error": "system_stopping"}


def test_contract_deferred_sentinel_identity_survives_copy():
    assert repr(DEFERRED) == "DEFERRED"
    assert copy.copy(DEFERRED) is DEFERRED
    assert copy.deepcopy(DEFERRED) is DEFERRED


def test_contract_interface_handle_command_accepts_keyword_only_reply():
    params = inspect.signature(ICommandManager.handle_command).parameters
    assert params["reply"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["reply"].default is None
    params_cm = inspect.signature(CommandManager.handle_command).parameters
    assert params_cm["reply"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params_cm["reply"].default is None


def test_h11_refusal_reaches_initiator_even_if_outcome_accounting_fails(make_executor):
    """H11: исполнитель закрыт, учёт исхода бросает → reply ровно один раз, system_stopping.

    Слоты stats/logger сбои глотают сами (``_call_manager``), поэтому сбой учёта моделируется
    подменой ``_finish_command`` на экземпляре — дефект в самом учёте (как в черновике ревьюера)."""
    cm, _log = make_cm("seg")

    def broken_accounting(*a: Any, **k: Any) -> None:
        raise RuntimeError("accounting failed")

    cm._finish_command = broken_accounting  # type: ignore[method-assign]
    ex = make_executor("h11")
    assert cm.register_command("c.h11", lambda d: {"success": True}, executor=ex, key_from="process_name")
    ex.request_stop()
    got: list[Any] = []
    ret, _ = run_bounded(
        lambda: cm.handle_command({"command": "c.h11", "data": {"process_name": "p"}}, reply=got.append)
    )
    time.sleep(0.1)
    assert ret is DEFERRED
    assert got == [{"success": False, "error": "system_stopping"}], f"ответы инициатору: {got!r}"
