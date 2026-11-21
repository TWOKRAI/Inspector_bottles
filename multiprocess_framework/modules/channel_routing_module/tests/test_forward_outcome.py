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

import threading
from typing import Any, Dict, List

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel, outcome_of
from multiprocess_framework.modules.channel_routing_module.observability import RecordForwardChannel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

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
