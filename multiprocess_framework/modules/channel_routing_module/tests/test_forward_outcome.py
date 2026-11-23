# -*- coding: utf-8 -*-
"""Task 0.5a: раздача tap'ам судит ВОЗВРАТ ``write()``, а не только исключение.

До 0.5a ``ChannelRoutingManager._emit_to_taps`` считал принявшим любой tap,
чей ``write()`` не бросил. Ответ ``{"status": "error"}`` (так ``RecordForwardChannel``
отвечает на мёртвый роутер) и ``{"status": "dropped"}`` без исключения проходили
как доставка: число принявших росло, счётчики потерь молчали.

После 0.5a: ``accepted`` — принят; ``refused`` — ``tap_refused_records``;
``failed`` и исключение приёмника — ``tap_write_errors``. Читается
``get_stats()``, а не ``lm.stats``: ключ обязан быть виден наружу.

Каждый сценарий — свой ``LoggerManager`` (``shutdown()`` в ``finally``),
``log_directory`` = ``tmp_path``, в daemon-потоке с ``join(5)``.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel, outcome_of
from multiprocess_framework.modules.channel_routing_module.observability import RecordForwardChannel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager

_JOIN_DEADLINE_S = 5.0


def _record() -> Dict[str, Any]:
    return {"timestamp": 1.0, "level": "ERROR", "message": "e", "module": "probe", "extra": {}}


class _DeadRouter:
    """Роутер, который бросает на любую отправку.

    Несёт и ``send_async``, и ``send``: после 0.5c форвардер зовёт ``send``, и без
    него тест краснел бы по неверной причине (``AttributeError``), а не по дефекту.
    """

    def __init__(self) -> None:
        self.calls = 0

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        self.calls += 1
        raise ConnectionError("router dead")

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        raise ConnectionError("router dead")


class _ReplyTap(IChannel):
    """Tap-заглушка: ``write()`` не бросает и отвечает заданным словарём."""

    def __init__(self, name: str, reply: Any) -> None:
        self._name = name
        self._reply = reply
        self.received: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: Dict[str, Any]) -> Any:
        self.received.append(data)
        return self._reply


class _CountingLock:
    """Обёртка лока: считает захваты (инвариант a3 — здоровый путь лок не берёт)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquired = 0

    def __enter__(self):
        self._lock.acquire()
        self.acquired += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        self._lock.release()

    def acquire(self, *args: Any, **kwargs: Any) -> bool:
        got = self._lock.acquire(*args, **kwargs)
        if got:
            self.acquired += 1
        return got

    def release(self) -> None:
        self._lock.release()


def _run_bounded(fn) -> Any:
    """Вызов в daemon-потоке с дедлайном; исключение потока пробрасывается."""
    box: Dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробросить в поток теста
            box["error"] = exc

    thread = threading.Thread(target=target, name="tap-probe", daemon=True)
    thread.start()
    thread.join(_JOIN_DEADLINE_S)
    assert not thread.is_alive(), f"сценарий завис дольше {_JOIN_DEADLINE_S} с"
    if "error" in box:
        raise box["error"]
    return box["result"]


def _emit_once(tmp_path, taps: List[Any]) -> Dict[str, Any]:
    """Один ``_emit_to_taps`` на свежем ``LoggerManager``: принявшие и приросты счётчиков."""
    lm = LoggerManager(config={"log_directory": str(tmp_path)})
    tap_names: List[str] = []
    try:
        for tap in taps:
            tap_names.append(lm.add_tap(tap, min_level="DEBUG"))
        before = lm.get_stats()
        n = lm._emit_to_taps(_record(), "ERROR")
        after = lm.get_stats()
        return {"n": n, "before": before, "after": after}
    finally:
        # Tap'ы снимаются ДО shutdown: shutdown сам эмитит запись (сводка
        # непринявших приёмников), и она легла бы в те же заглушки.
        for tap_name in tap_names:
            lm.remove_tap(tap_name)
        lm.shutdown()


def _delta(result: Dict[str, Any], key: str) -> int:
    """Прирост счётчика ``get_stats()``; ключа нет в снимке — ``KeyError`` (ключ обязан быть виден)."""
    return result["after"][key] - result["before"][key]


def test_dead_router_tap_not_accepted(tmp_path) -> None:
    """Настоящий ``RecordForwardChannel`` на мёртвом роутере: не принят, ``tap_write_errors`` +1."""
    router = _DeadRouter()
    forward = RecordForwardChannel(router=router, subscriber="gui", sender="p")

    result = _run_bounded(lambda: _emit_once(tmp_path, [forward]))

    assert router.calls == 1
    assert result["n"] == 0
    assert _delta(result, "tap_write_errors") == 1
    assert _delta(result, "tap_refused_records") == 0


def test_router_dropped_counts_refused(tmp_path) -> None:
    """Ответ tap'а ``dropped`` без исключения: не принят, ``tap_refused_records`` +1."""
    tap = _ReplyTap("dropping_tap", {"status": "dropped", "reason": "queue full"})

    result = _run_bounded(lambda: _emit_once(tmp_path, [tap]))

    assert len(tap.received) == 1
    # Ключ — первым: его отсутствие в get_stats() и есть дефект «заведён и невидим» (a4).
    assert _delta(result, "tap_refused_records") == 1
    assert result["n"] == 0
    assert _delta(result, "tap_write_errors") == 0


def test_error_reply_counts_write_error(tmp_path) -> None:
    """Ответ tap'а ``error`` без исключения — та же болезнь, что исключение: ``tap_write_errors``."""
    tap = _ReplyTap("error_tap", {"status": "error", "reason": "store closed"})

    result = _run_bounded(lambda: _emit_once(tmp_path, [tap]))

    assert result["n"] == 0
    assert _delta(result, "tap_write_errors") == 1
    assert _delta(result, "tap_refused_records") == 0


def test_refusing_tap_does_not_drop_its_neighbour(tmp_path) -> None:
    """Отказ одного tap'а не мешает соседу: принят ровно здоровый, отказ посчитан."""
    refusing = _ReplyTap("refusing_tap", {"status": "dropped"})
    healthy = _ReplyTap("healthy_tap", {"status": "success"})

    result = _run_bounded(lambda: _emit_once(tmp_path, [refusing, healthy]))

    assert len(healthy.received) == 1
    assert result["n"] == 1
    assert _delta(result, "tap_refused_records") == 1
    assert _delta(result, "tap_write_errors") == 0


def test_healthy_replies_accepted_without_loss(tmp_path) -> None:
    """``success``, ``None`` и словарь без ``status`` — приняты, потерь нет."""
    taps = [
        _ReplyTap("success_tap", {"status": "success"}),
        _ReplyTap("none_tap", None),
        _ReplyTap("plain_tap", {"channel": "x"}),
    ]

    result = _run_bounded(lambda: _emit_once(tmp_path, taps))

    assert result["n"] == 3
    assert _delta(result, "tap_write_errors") == 0
    assert _delta(result, "tap_refused_records") == 0


def test_none_reply_means_accepted() -> None:
    """Fast path ``_emit_to_taps`` (ответ ``None`` -> принят без вызова) и ``outcome_of`` — один смысл."""
    assert outcome_of(None) == "accepted"


def test_healthy_tap_does_not_take_miss_lock(tmp_path) -> None:
    """Инвариант a3: здоровая доставка в tap лок потерь не берёт; отказ — берёт."""

    def scenario() -> Dict[str, int]:
        lm = LoggerManager(config={"log_directory": str(tmp_path)})
        try:
            healthy = _ReplyTap("healthy_tap", {"status": "success"})
            lm.add_tap(healthy, min_level="DEBUG")
            spy = _CountingLock()
            lm._miss_lock = spy
            n_healthy = lm._emit_to_taps(_record(), "ERROR")
            healthy_locks = spy.acquired
            lm.remove_tap("healthy_tap")
            lm.add_tap(_ReplyTap("refusing_tap", {"status": "dropped"}), min_level="DEBUG")
            locks_before_refused = spy.acquired
            n_refused = lm._emit_to_taps(_record(), "ERROR")
            refused_locks = spy.acquired - locks_before_refused
            lm.remove_tap("refusing_tap")
            return {
                "n_healthy": n_healthy,
                "healthy_locks": healthy_locks,
                "n_refused": n_refused,
                "refused_locks": refused_locks,
            }
        finally:
            lm.shutdown()

    result = _run_bounded(scenario)

    assert result["n_healthy"] == 1
    assert result["healthy_locks"] == 0
    assert result["n_refused"] == 0
    assert result["refused_locks"] == 1


# ---------------------------------------------------------------------------
# Task 0.5c: синхронный ``router.send`` и счётчики форвардера
# ---------------------------------------------------------------------------


class _ReplyRouter:
    """Роутер-заглушка: ``send`` отвечает заданным словарём.

    ``send_async`` пишет в тот же журнал и ничего не отвечает: до 0.5c форвардер
    звал его, и красный тогда — «роутерный ответ не дошёл», а не ``AttributeError``.
    """

    def __init__(self, reply: Dict[str, Any]) -> None:
        self._reply = reply
        self.sent: List[Dict[str, Any]] = []

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        self.sent.append(message)

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self.sent.append(message)
        return self._reply


def _display(i: int) -> Dict[str, Any]:
    return {"kind": "log", "module": "probe", "ts": 1.0, "severity": "info", "message": f"m{i}"}


def test_forwarder_counters_healthy() -> None:
    """Живой роутер: одна запись — ``sent`` 1, один пуш."""
    router = _ReplyRouter({"status": "success"})
    forward = RecordForwardChannel(router=router, subscriber="gui", sender="p")

    forward.write(_record())

    assert len(router.sent) == 1
    assert forward.counters_snapshot() == {"sent": 1, "messages": 1, "dropped": 0, "send_failed": 0}


def test_forwarder_counters_dropped() -> None:
    """Роутер ответил ``dropped``: запись в ``dropped``, не в ``sent``."""
    router = _ReplyRouter({"status": "dropped", "reason": "queue full"})
    forward = RecordForwardChannel(router=router, subscriber="gui", sender="p")

    forward.write(_record())

    assert forward.counters_snapshot() == {"sent": 0, "messages": 1, "dropped": 1, "send_failed": 0}


@pytest.mark.parametrize(
    ("make_router", "expected"),
    [
        (lambda: _ReplyRouter({"status": "success"}), {"sent": 3, "messages": 1, "dropped": 0, "send_failed": 0}),
        (
            lambda: _ReplyRouter({"status": "dropped", "reason": "queue full"}),
            {"sent": 0, "messages": 1, "dropped": 3, "send_failed": 0},
        ),
        (
            lambda: _ReplyRouter({"status": "error", "reason": "no channel resolved"}),
            {"sent": 0, "messages": 1, "dropped": 0, "send_failed": 3},
        ),
        (lambda: _DeadRouter(), {"sent": 0, "messages": 1, "dropped": 0, "send_failed": 3}),
        (lambda: None, {"sent": 0, "messages": 0, "dropped": 0, "send_failed": 3}),
    ],
    ids=["success", "dropped", "error", "raises", "no_router"],
)
def test_forwarder_counters_count_records(make_router, expected: Dict[str, int]) -> None:
    """Единица счёта — записи: пачка из 3 даёт +3; ``messages`` — пуши, до роутера."""
    forward = RecordForwardChannel(router=make_router(), subscriber="gui", sender="p")

    forward.push_batch([_display(0), _display(1), _display(2)])

    snapshot = forward.counters_snapshot()
    assert snapshot == expected
    assert snapshot["sent"] + snapshot["dropped"] + snapshot["send_failed"] == 3


def test_forwarder_counters_threaded() -> None:
    """Hazard c8: 8 потоков × 250 записей — ни одной потерянной в счёте."""
    router = _ReplyRouter({"status": "success"})
    forward = RecordForwardChannel(router=router, subscriber="gui", sender="p")
    start = threading.Barrier(8)

    def emitter() -> None:
        start.wait(_JOIN_DEADLINE_S)
        for _ in range(250):
            forward.write(_record())

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # чаще переключать потоки: гонка счёта видна легче
    try:
        threads = [threading.Thread(target=emitter, name=f"fwd-emitter-{i}", daemon=True) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(_JOIN_DEADLINE_S)
    finally:
        sys.setswitchinterval(old_interval)

    assert not any(thread.is_alive() for thread in threads), f"эмиттеры зависли дольше {_JOIN_DEADLINE_S} с"
    assert forward.counters_snapshot() == {"sent": 2000, "messages": 2000, "dropped": 0, "send_failed": 0}


def test_dropped_router_reaches_tap_refused_counter(tmp_path) -> None:
    """Сквозной: роутерный ``dropped`` -> ответ форвардера -> суд tap'а -> ``tap_refused_records``."""
    router = _ReplyRouter({"status": "dropped", "reason": "queue full"})
    forward = RecordForwardChannel(router=router, subscriber="gui", sender="p")

    result = _run_bounded(lambda: _emit_once(tmp_path, [forward]))

    assert len(router.sent) == 1
    assert _delta(result, "tap_refused_records") == 1
    assert result["n"] == 0
    assert _delta(result, "tap_write_errors") == 0


class _DeadConnection:
    """Клиентское соединение сокет-канала: пир пропал, ``sendall`` бросает ``OSError``."""

    def __init__(self) -> None:
        self.sendall_calls = 0

    def fileno(self) -> int:
        return 7

    def sendall(self, data: bytes) -> None:
        self.sendall_calls += 1
        raise BrokenPipeError(32, "Broken pipe")

    def shutdown(self, how: int) -> None:
        pass

    def close(self) -> None:
        pass


class _NoQueues:
    """``queue_registry`` без очередей: адресат-канал едет мостом push->канал (Ф1.1b)."""

    def get_queue(self, process: str, qtype: str) -> None:
        return None

    def send_to_queue(self, process: str, qtype: str, message: Dict[str, Any]) -> bool:
        return False


@pytest.mark.parametrize("mode", ["broadcast", "session"])
def test_dead_client_warning_does_not_self_deadlock(tmp_path, mode: str) -> None:
    """Hazard c2: WARNING сокет-канала о мёртвом клиенте не замыкается на его же лок.

    Цепочка: ``router.send`` -> ``SocketChannel.send`` (``_write_lock``) -> сбой
    ``sendall`` -> WARNING -> ``LoggerManager`` -> tap ``RecordForwardChannel`` ->
    синхронный ``router.send`` -> тот же канал -> тот же ``_write_lock``. Поток
    сценария не внутри раздачи tap'ов, поэтому ``_tap_depth`` не спасает.
    Красный только в состоянии «синхронный ``send`` без выноса лога из-под лока».

    ``session`` (ревью этапа 5, замечание 1): пинг адресован сессии и идёт через
    ``_send_to_session``; мёртвый сокет и в ``_sessions``, и в ``_clients``, как у
    настоящего соединения, поэтому пуш форвардера (без ``session``) уходит
    broadcast'ом в тот же ``_write_lock``.
    """
    lm = LoggerManager(config={"log_directory": str(tmp_path)})
    router = RouterManager(manager_name="deadlock_probe", logger=lm, queue_registry=_NoQueues(), relay_hub=None)
    channel = SocketChannel(name="ctl_probe", port=0, session_isolation=(mode == "session"))
    dead = _DeadConnection()
    channel._clients.append(dead)
    if mode == "session":
        channel._sessions["sid-dead"] = dead
    assert router.register_channel(channel)
    forward = RecordForwardChannel(
        router=router,
        subscriber="ctl_probe",
        sender="probe",
        name="observability_forward::ctl_probe::logger_error",
    )
    witness = _ReplyTap("witness_tap", None)
    tap_names = [lm.add_tap(forward, min_level="WARNING"), lm.add_tap(witness, min_level="WARNING")]
    ping = {"type": "event", "sender": "probe", "targets": ["ctl_probe"], "command": "probe.ping", "data": {}}
    if mode == "session":
        ping["session"] = "sid-dead"
    box: Dict[str, Any] = {}

    def scenario() -> None:
        box["reply"] = router.send(ping)

    thread = threading.Thread(target=scenario, name="dead-client-probe", daemon=True)
    thread.start()
    thread.join(_JOIN_DEADLINE_S)
    hung = thread.is_alive()
    if not hung:
        # Зависший поток держит лок канала и, возможно, локи логгера: уборка
        # тогда сама повисла бы. Daemon-поток умрёт с процессом.
        for tap_name in tap_names:
            lm.remove_tap(tap_name)
        channel.close()
        lm.shutdown()

    assert not hung, f"самоблокировка: поток висит дольше {_JOIN_DEADLINE_S} с"
    assert box["reply"]["status"] == "error"
    assert dead.sendall_calls == 1
    assert any("[SocketChannel:ctl_probe]" in str(r.get("message", "")) for r in witness.received)


class _SpyLock:
    """Нереентерабельный лок с флагом ``held``: повторный вход — ``assert``, а не взаимоблокировка."""

    created: List["_SpyLock"] = []

    def __init__(self) -> None:
        self.held = False
        self.entries = 0
        _SpyLock.created.append(self)

    def __enter__(self) -> "_SpyLock":
        assert not self.held, "повторный вход в нереентерабельный лок"
        self.held = True
        self.entries += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        self.held = False


class _HeldProbeRouter:
    """Роутер-заглушка: в ``send`` записывает, держит ли форвардер лок счётчиков."""

    def __init__(self) -> None:
        self.held_during_send: List[bool] = []
        self.lock: _SpyLock | None = None

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        assert self.lock is not None
        self.held_during_send.append(self.lock.held)
        return {"status": "success"}


def test_counters_lock_is_used_and_taken_after_send(monkeypatch) -> None:
    """Ревью этапа 5, замечание 2: счёт идёт под локом, и лок НЕ держится вокруг ``send``.

    Подмена ``threading.Lock`` — только на время конструктора: подмена после
    конструктора не увидела бы ``nullcontext`` вместо лока в ``__init__``.
    """
    _SpyLock.created.clear()
    router = _HeldProbeRouter()
    with monkeypatch.context() as ctx:
        ctx.setattr(threading, "Lock", _SpyLock)
        forward = RecordForwardChannel(router=router, subscriber="gui", sender="p")
    assert len(_SpyLock.created) == 1
    lock = _SpyLock.created[0]
    router.lock = lock

    forward.push_batch([_display(0), _display(1), _display(2)])

    assert router.held_during_send == [False]
    assert lock.entries == 1
    forward.counters_snapshot()
    assert lock.entries == 2


class _RaisingRouter:
    """Роутер, чьё исключение несёт входное значение в тексте."""

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("payload secret-payload")


def test_exception_reason_is_class_name_only() -> None:
    """Ревью этапа 5, замечание 3: ``reason`` исключения — имя класса, без текста."""
    forward = RecordForwardChannel(router=_RaisingRouter(), subscriber="gui", sender="p")

    reply = forward.write(_record())

    assert reply == {"status": "error", "channel": "observability_forward", "reason": "RuntimeError"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("error", {"status": "error", "channel": "observability_forward", "reason": "router failed"}),
        ("dropped", {"status": "dropped", "channel": "observability_forward", "reason": "router refused"}),
    ],
)
def test_router_reason_is_not_copied(status: str, expected: Dict[str, str]) -> None:
    """Ревью этапа 5, замечание 4 (решение лида): текст роутера не доверенный и не копируется."""
    router = _ReplyRouter({"status": status, "reason": "bad field {'password': 'hunter2'}"})
    forward = RecordForwardChannel(router=router, subscriber="gui", sender="p")

    reply = forward.write(_record())

    assert reply == expected
