# -*- coding: utf-8 -*-
"""Task 1.2c (system-run-state) — hazard-тесты автора: внеочередной heartbeat при смене ``paused``.

Не слепой набор (``test_heartbeat_paused_push.py``) — свойства, которые автор гарантирует: смена сравнивается с
последним УШЕДШИМ в PM значением (любым путём); нет смены — нет сообщения; первый снимок сменой не считается;
антидребезг <= 2 в секунду, подавленная смена не теряется; сбой отправки не бросает и логируется раз на серию;
регулярный и внеочередной пути делят ОДИН замок отправки; выключенный heartbeat не пушит; остановка процесса во
время push не виснет.

Стенд — настоящий ``ProcessHeartbeat`` с минимальным носителем (быстро и детерминированно), плюс настоящий процесс
под ``run_process_function`` для остановки во время push. Блокирующие вызовы — daemon-потоки с join-дедлайном.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin

_THIS = "multiprocess_framework.modules.process_module.tests.test_heartbeat_paused_push_hazards"
_JOIN_S = 30.0
#: Окно антидребезга heartbeat — 0,5 с; сон чуть больше выводит из него.
_GAP_S = 0.55


def _snap(paused: bool) -> dict:
    return {"ready": True, "reasons": [], "paused": paused, "at": 1.0}


class _Svc:
    """Минимальный носитель ``ProcessHeartbeat``: снимок, запись отправок, сбой/задержка отправки по флагам."""

    def __init__(self, paused: bool | None = None) -> None:
        self.name = "hbp_proc"
        self.worker_manager = None
        self._readiness_snapshot = None if paused is None else _snap(paused)
        self.sent: list[dict] = []
        self.errors: list[str] = []
        self.fail: Exception | None = None
        self.delay = 0.0
        self.max_inflight = 0
        self._inflight = 0
        self._lock = threading.Lock()
        self._config: dict[str, Any] = {"heartbeat_interval": 30.0}

    def set_paused(self, paused: bool) -> None:
        self._readiness_snapshot = _snap(paused)

    def send_message(self, target: str, message: dict) -> bool:
        with self._lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.fail is not None:
                raise self.fail
            self.sent.append(message)
        finally:
            with self._lock:
                self._inflight -= 1
        return True

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def log_info(self, msg: str, **kw) -> None: ...

    def log_debug(self, msg: str, **kw) -> None: ...

    def log_error(self, msg: str, **kw) -> None:
        self.errors.append(msg)


def _started_heartbeat(svc: _Svc) -> ProcessHeartbeat:
    hb = ProcessHeartbeat(svc)  # type: ignore[arg-type]
    hb._started = True  # воркер такта не нужен: регулярный путь зовём руками
    return hb


def _paused_sent(svc: _Svc) -> list[Any]:
    return [m["readiness"]["paused"] for m in svc.sent if "readiness" in m]


def test_no_push_without_change() -> None:
    """Последний ушедший ``paused`` = текущий -> внеочередных сообщений нет, сколько ни зови."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})  # регулярный: paused False ушёл

    assert [hb.push_if_paused_changed() for _ in range(5)] == [False] * 5

    assert _paused_sent(svc) == [False]


def test_first_snapshot_is_not_a_change() -> None:
    """В PM готовность ещё не уходила (регулярного heartbeat не было) -> снимок сменой не считается."""
    svc = _Svc(paused=True)
    hb = _started_heartbeat(svc)

    assert hb.push_if_paused_changed() is False
    assert svc.sent == []


def test_change_pushes_once_in_regular_format() -> None:
    """Смена ``paused`` относительно ушедшего -> одно внеочередное сообщение того же формата, что регулярное."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})
    svc.set_paused(True)

    assert hb.push_if_paused_changed() is True
    assert hb.push_if_paused_changed() is False  # уже ушло

    regular, pushed = svc.sent
    assert set(pushed) == set(regular), (sorted(pushed), sorted(regular))
    assert pushed["readiness"] == _snap(True) and pushed["command"] == "heartbeat"
    pushed["readiness"]["reasons"].append({"x": 1})
    assert svc._readiness_snapshot == _snap(True), "внеочередное сообщение несёт не копию снимка"


def test_regular_heartbeat_carrying_new_paused_suppresses_push() -> None:
    """Смену унёс регулярный heartbeat -> внеочередной не нужен (сравнение с ушедшим любым путём)."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})
    svc.set_paused(True)
    hb._send_heartbeat({})  # регулярный несёт paused True

    assert hb.push_if_paused_changed() is False
    assert _paused_sent(svc) == [False, True]


def test_debounce_suppressed_change_is_not_lost() -> None:
    """Смена внутри окна антидребезга подавлена, но после затишья итог уходит (не теряется)."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})
    svc.set_paused(True)
    assert hb.push_if_paused_changed() is True  # t0
    svc.set_paused(False)

    assert hb.push_if_paused_changed() is False  # внутри окна: подавлено
    time.sleep(_GAP_S)
    assert hb.push_if_paused_changed() is True  # затишье: итог доставлен

    assert _paused_sent(svc) == [False, True, False]


def test_flapping_snapshot_is_debounced_and_final_state_delivered() -> None:
    """40 смен ``paused`` за 1 с: не больше 3 внеочередных (окно 0,5 с), итог после затишья доставлен."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})
    started = time.monotonic()
    pushes = 0
    for i in range(40):
        svc.set_paused(i % 2 == 0)  # последнее значение i=39 -> False; пик серии True
        pushes += hb.push_if_paused_changed()
        time.sleep(0.025)
    window = time.monotonic() - started
    svc.set_paused(True)  # итог серии отличается от последнего ушедшего (False или True по фазе) — сделаем явный
    time.sleep(_GAP_S)
    hb.push_if_paused_changed()

    assert 1 <= pushes <= 3, f"{pushes} внеочередных за {window:.2f} с"
    assert _paused_sent(svc)[-1] is True, _paused_sent(svc)


def test_push_send_failure_does_not_raise_and_logs_once_per_exception_type() -> None:
    """Сбой отправки не бросает наружу; лог один раз на серию (ключ — тип); после успеха серия закрыта."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})
    svc.set_paused(True)
    svc.fail = RuntimeError("сбой 1")

    assert hb.push_if_paused_changed() is False
    time.sleep(_GAP_S)
    svc.fail = RuntimeError("другой текст, тот же тип")
    assert hb.push_if_paused_changed() is False
    assert len(svc.errors) == 1, svc.errors  # тот же тип — одна серия

    time.sleep(_GAP_S)
    svc.fail = None
    assert hb.push_if_paused_changed() is True  # повтор прошёл: сбой не потерял смену
    assert _paused_sent(svc) == [False, True]

    svc.set_paused(False)
    time.sleep(_GAP_S)
    svc.fail = ValueError("новая серия")
    assert hb.push_if_paused_changed() is False
    assert len(svc.errors) == 2, svc.errors


def test_regular_heartbeat_unaffected_by_failed_push() -> None:
    """После сбоя внеочередной отправки регулярный heartbeat идёт как прежде."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})
    svc.set_paused(True)
    svc.fail = RuntimeError("сбой")
    assert hb.push_if_paused_changed() is False
    svc.fail = None

    hb._send_heartbeat({})

    assert _paused_sent(svc) == [False, True]


def test_disabled_heartbeat_does_not_push() -> None:
    """``heartbeat_interval <= 0``: heartbeat выключен (``start()`` ничего не заводит) — push не уходит и не падает."""
    svc = _Svc(paused=False)
    svc._config["heartbeat_interval"] = 0
    hb = ProcessHeartbeat(svc)  # type: ignore[arg-type]
    hb.start()
    hb._last_sent_paused = False  # как если бы регулярный уже уходил
    svc.set_paused(True)

    assert hb.push_if_paused_changed() is False
    assert svc.sent == []


def test_regular_and_push_share_one_send_lock() -> None:
    """Регулярный heartbeat держит отправку, внеочередной ждёт: одновременно не больше одной отправки, дубля нет."""
    svc = _Svc(paused=False)
    hb = _started_heartbeat(svc)
    hb._send_heartbeat({})
    svc.set_paused(True)  # регулярный ниже понесёт paused True; push по тому же значению стал бы дублем
    svc.delay = 0.4
    regular = threading.Thread(target=lambda: hb._send_heartbeat({}), daemon=True, name="hbp-regular")
    pusher = threading.Thread(target=hb.push_if_paused_changed, daemon=True, name="hbp-push")
    regular.start()
    time.sleep(0.1)  # регулярный внутри send_message (держит замок)
    pusher.start()
    regular.join(_JOIN_S)
    pusher.join(_JOIN_S)

    assert not regular.is_alive() and not pusher.is_alive(), "отправки зависли"
    assert svc.max_inflight == 1, f"одновременных отправок: {svc.max_inflight}"
    assert _paused_sent(svc) == [False, True], "внеочередной продублировал уже ушедшее значение"


# --------------------------------------------------------------------------- #
# Настоящий процесс: остановка во время внеочередной отправки
# --------------------------------------------------------------------------- #

SHARED: dict[str, Any] = {}


class HbpPlugin(ProcessModulePlugin):
    name = "hbp_plugin"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class HbpSlowSendProcess(GenericProcess):
    """Настоящий процесс; heartbeat-отправка медленная (``SHARED["delay"]``), сообщения — в очередь теста."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self

    def send_message(self, target: str, message: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(message, dict) and message.get("command") == "heartbeat":
            SHARED["entered"].set()
            time.sleep(SHARED["delay"])
            SHARED["queue"].put(message)
            return True
        return super().send_message(target, message, *args, **kwargs)


@contextlib.contextmanager
def _real_process(delay: float):
    """Настоящий процесс с плагином, интервал heartbeat 30 с; готов, снимок есть, стартовый heartbeat осел."""
    event = multiprocessing.Event()
    event.set()
    out = multiprocessing.get_context("spawn").Queue()
    SHARED.clear()
    SHARED.update({"event": event, "proc": None, "queue": out, "entered": threading.Event(), "delay": delay})
    cfg: dict[str, Any] = {
        "config": {"plugins": [{"plugin_class": f"{_THIS}.HbpPlugin", "plugin_name": "hbp_plugin"}]},
        "heartbeat_interval": 30.0,
    }
    own_ready = multiprocessing.Event()
    bundle = {
        "queues": {"data": multiprocessing.Queue()},
        "config": cfg,
        "custom": {"process_config": cfg, "ready_event": own_ready},
    }
    stop = threading.Event()
    thread = threading.Thread(
        target=run_process_function,
        args=(f"{_THIS}.HbpSlowSendProcess", "hbp_real", stop, bundle, None),
        daemon=True,
        name="hbp-real-process",
    )
    thread.start()
    try:
        assert own_ready.wait(_JOIN_S)
        end = time.monotonic() + 5.0
        while time.monotonic() < end and not (SHARED["proc"]._readiness_snapshot or {}).get("ready"):
            time.sleep(0.02)
        time.sleep(1.0 + delay)  # стартовый heartbeat ушёл: ``_last_sent_paused`` известен
        yield event, out, stop, thread
    finally:
        SHARED["delay"] = 0.0
        stop.set()
        thread.join(_JOIN_S)
        out.close()
        out.cancel_join_thread()
        SHARED.clear()


def _drain(out: Any) -> list[dict]:
    got: list[dict] = []
    while True:
        try:
            got.append(out.get(timeout=0.2))
        except Exception:  # noqa: BLE001 — очередь пуста
            return got


@pytest.mark.timeout(120)
def test_stop_during_slow_push_does_not_hang_the_process() -> None:
    """Процесс останавливают, пока воркер снимка внутри медленной внеочередной отправки: выход в срок, без зависания."""
    with _real_process(0.0) as (event, out, stop, thread):
        SHARED["entered"].clear()
        SHARED["delay"] = 1.5
        event.clear()
        assert SHARED["entered"].wait(5.0), "внеочередная отправка не началась"

        stop.set()  # воркер снимка сейчас внутри send_message
        thread.join(_JOIN_S)
        assert not thread.is_alive(), "процесс завис при остановке во время внеочередной отправки"


@pytest.mark.timeout(120)
def test_real_process_flapping_odd_series_is_debounced_and_final_state_delivered() -> None:
    """21 переключение за ~1 с (кончается ``clear()``): <= 3 внеочередных за серию, итог ``paused == True`` доставлен.

    Нечётная серия: итог отличается от ушедшего значения (``False``), поэтому доставка итога не выполняется сама собой
    (у чётной серии, возвращающей значение, снимок может не увидеть пик и сообщений не будет совсем — это не дефект).
    """
    with _real_process(0.0) as (event, out, stop, thread):
        _drain(out)
        started = time.time()
        for i in range(21):
            (event.clear if i % 2 == 0 else event.set)()
            time.sleep(0.05)
        ended = time.time()
        time.sleep(2.5)  # затишье
        got = _drain(out)

        in_window = [m for m in got if started <= m["timestamp"] <= ended + 0.2]
        assert len(in_window) <= 3, f"дребезг не подавлен: {len(in_window)} heartbeat за серию"
        assert got and got[-1]["readiness"]["paused"] is True, [m["readiness"]["paused"] for m in got]
