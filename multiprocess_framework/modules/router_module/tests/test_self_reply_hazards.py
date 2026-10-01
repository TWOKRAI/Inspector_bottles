# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.3b (ADR-RTR-013): синхронный самоответ в ``reply_to_request``.

Что может сломаться именно в этом механизме:

1. Сценарий ``system.shutdown``: обработчик сам гасит приёмный цикл сразу после ответа —
   больше ни одного ``receive()`` не будет. До фикса ответ лежал в собственной очереди и
   ждал такта, которого нет; ожидающий ``request()`` висел до таймаута.
2. Колбэк ``request_async`` к себе теперь зовётся ВНУТРИ ``reply_to_request`` на потоке
   обработчика (раньше — внутри ``receive()``). Колбэк, бросивший исключение, не имеет
   права уронить ни ``reply_to_request``, ни диспетчеризацию обработчика.

Стенд — помощники приёмочного файла тестера (петлевой queue_registry), чтобы оба набора
били в один и тот же транспорт.
"""

from __future__ import annotations

import threading
from queue import Queue
from types import SimpleNamespace
from typing import Any, Dict


from ..channels.queue_channel import QueueChannel
from ..core.router_manager import RouterManager
from .test_self_reply_acceptance import _LoopbackQueueRegistry, _make_self_router, _wait_until


def test_handler_stopping_the_loop_still_delivers_its_reply():
    """Приёмный цикл останавливается внутри обработчика — ответ всё равно доходит."""
    router, qr, _q = _make_self_router("self_stop")
    stop = threading.Event()
    result: Dict[str, Any] = {}

    def _handler(msg: dict) -> None:
        router.reply_to_request(msg, {"stopping": True})
        stop.set()  # как _cmd_system_shutdown: после ответа процесс гасит свой цикл

    router.register_message_handler("self.shutdown", _handler)

    def _loop() -> None:
        while not stop.is_set():
            router.receive(timeout=0.0, channel_types=["system"])
            stop.wait(0.005)

    def _requester() -> None:
        result["r"] = router.request(
            {"type": "command", "command": "self.shutdown", "targets": ["self_stop"], "sender": "self_stop"},
            timeout=2.0,
        )

    req = threading.Thread(target=_requester, daemon=True)
    loop = threading.Thread(target=_loop, daemon=True)
    try:
        req.start()
        assert _wait_until(lambda: qr.tickets("self.shutdown"), deadline_sec=2.0), "запрос не дошёл до очереди"
        loop.start()
        loop.join(timeout=2.0)
        assert not loop.is_alive(), "обработчик не остановил цикл — стенд не воспроизвёл сценарий"
        req.join(timeout=0.5)  # после остановки цикла receive() больше нет
        delivered = not req.is_alive()
    finally:
        stop.set()
        req.join(timeout=3.0)
        router.shutdown()

    assert delivered, "ответ не дошёл после остановки приёмного цикла — сценарий потери ответа system.shutdown"
    assert result["r"].get("success") is True
    assert result["r"].get("result") == {"stopping": True}


def test_raising_async_callback_does_not_break_the_handler():
    """Колбэк самоответа бросает — ``reply_to_request`` и остаток обработчика живы."""
    router, qr, _q = _make_self_router("self_cb")
    calls: list = []
    after_reply = threading.Event()

    def _on_response(_resp: dict) -> None:
        calls.append(1)
        raise RuntimeError("колбэк упал")

    def _handler(msg: dict) -> None:
        router.reply_to_request(msg, {"x": 1})
        after_reply.set()  # строка после ответа обязана выполниться

    router.register_message_handler("self.cb", _handler)
    try:
        cid = router.request_async(
            {"type": "command", "command": "self.cb", "targets": ["self_cb"], "sender": "self_cb"},
            on_response=_on_response,
            timeout=2.0,
        )
        assert cid
        assert _wait_until(lambda: qr.tickets("self.cb"), deadline_sec=2.0), "запрос не дошёл до очереди"
        router.receive(timeout=0.0, channel_types=["system"])
        assert after_reply.wait(1.0), "исключение колбэка прервало обработчик после reply_to_request"
        router.receive(timeout=0.0, channel_types=["system"])  # лишний такт: второго вызова быть не должно
    finally:
        router.shutdown()

    assert calls == [1], f"колбэк вызван {len(calls)} раз, ожидался ровно один"


def test_self_reply_resolves_when_router_id_differs_from_process_name():
    """Прод-форма хаба: ``router_id='router_X'``, ``process.name='X'``, дверь ставит ``reply_to='X'``.

    Найдено ревью 1.3b: стенд приёмки без процесса проверял только запасную ветку ``router_id``;
    сравнение только с ``router_id`` оставляло все тесты зелёными, а в проде возвращало потерю.
    """
    q: Queue = Queue()
    qr = _LoopbackQueueRegistry("X", q)
    router = RouterManager(manager_name="router_X", queue_registry=qr, process=SimpleNamespace(name="X"))
    router.register_channel(QueueChannel("X_system", q))
    router.initialize()
    router.register_message_handler("self.echo", lambda m: router.reply_to_request(m, {"v": 1}))
    out: Dict[str, Any] = {}

    def _requester() -> None:
        out["r"] = router.request(
            {"type": "command", "command": "self.echo", "targets": ["X"], "sender": "drv", "reply_to": "X"},
            timeout=1.0,
        )

    t = threading.Thread(target=_requester, daemon=True)
    try:
        t.start()
        assert _wait_until(lambda: qr.tickets("self.echo"), deadline_sec=2.0), "запрос не дошёл до очереди"
        router.receive(timeout=0.0, channel_types=["system"])  # ровно один такт
        t.join(timeout=0.3)
        resolved = not t.is_alive()
    finally:
        t.join(timeout=2.0)
        router.shutdown()
    assert resolved, "самоответ по ветке process.name не разрешён за один receive()"
    assert out["r"].get("result") == {"v": 1}


def test_reply_to_other_does_not_resolve_own_pending_with_same_cid():
    """Явный ``reply_to`` на другого адресата не разрешает свой pending с тем же id.

    Найдено ревью 1.3b: без условия ``reply_target == sender_name`` ответ, адресованный
    ``elsewhere``, доставался своему ожидающему, а ``elsewhere`` не получал ничего.
    """
    router, qr, _q = _make_self_router("hub")
    router.register_message_handler("self.cmd", lambda m: router.reply_to_request(m, {"for": "elsewhere"}))
    calls: list = []
    try:
        router.request_async(
            {
                "type": "command",
                "command": "self.cmd",
                "targets": ["hub"],
                "sender": "drv",
                "reply_to": "elsewhere",
                "request_id": "cid-X",
            },
            on_response=calls.append,
            timeout=5.0,
        )
        assert _wait_until(lambda: qr.tickets("self.cmd"), deadline_sec=2.0), "запрос не дошёл до очереди"
        router.receive(timeout=0.0, channel_types=["system"])
        other = qr.queue_for("elsewhere")
        assert calls == [], f"свой pending разрешён ответом для 'elsewhere': {calls!r}"
        assert other.qsize() == 1 and other.get_nowait()["request_id"] == "cid-X"
    finally:
        router.shutdown()
