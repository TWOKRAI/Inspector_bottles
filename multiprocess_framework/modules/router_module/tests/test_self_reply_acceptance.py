# -*- coding: utf-8 -*-
"""test_self_reply_acceptance.py — приёмочные тесты Task 1.3b (RED, независимый tester).

Контракт (спецификация 00743214, план gui-service Task 1.3b): запрос
``request()``/``request_async()`` к САМОМУ СЕБЕ (``targets=[<своё имя>]``)
обязан разрешиться в ходе ОДНОГО вызова :meth:`RouterManager.receive` —
хендлер, ответивший через :meth:`RouterManager.reply_to_request`, отдаёт
ответ напрямую (``_resolve_pending``), а не кладёт его обратно в очередь
(``send()``), откуда его разберёт только СЛЕДУЮЩИЙ приёмный такт.

Сегодня (до фикса) ``reply_to_request`` всегда шлёт через ``send()`` —
самоответ уходит в собственную очередь и ждёт второго ``receive()``.
Гварды (чужой адресат / поздний ответ без pending) обязаны остаться на
прежнем пути и не сломаться.

Независимый tester: пишет ТОЛЬКО из DESIGN/ACCEPTANCE спецификации выше,
implementation-файлы роутера не читались как источник поведения (только
существующая сигнатура ``reply_to_request``/``request``/``request_async`` и
существующие тесты-образцы того же модуля — для стенда, не для контракта).
"""

from __future__ import annotations

import threading
import time
from queue import Queue
from typing import Any, Dict, List, Tuple


from ..channels.queue_channel import QueueChannel
from ..core.router_manager import RouterManager


class _LoopbackQueueRegistry:
    """queue_registry-двойник: самоадресованные (``target == own_name``)
    system-тикеты реально попадают в СОБСТВЕННУЮ ``q_system`` роутера — как
    происходит у реального оркестратора при ``sender == target``. Прочие
    адресаты копятся в отдельных ``Queue`` по имени — наблюдаемый эффект
    транспортной границы (та же роль, что у ``queue_registry.send_to_queue``
    в проде), а не подсмотр имени внутреннего метода.

    Без ``get_queue`` — как и у ``_FakeQueueRegistry`` в
    ``test_request_contract_guard.py`` — это намеренно: без него
    ``_queue_absent`` всегда возвращает True и путь моста push→канал (Ф1.1b)
    / relay-хаба (Ф1.7) не перехватывает обычную адресную доставку.
    """

    def __init__(self, own_name: str, own_system_queue: Queue) -> None:
        self._own_name = own_name
        self._own_q = own_system_queue
        self._other_queues: Dict[str, Queue] = {}
        self.sent: List[Tuple[str, str, dict]] = []
        self._lock = threading.Lock()

    def send_to_queue(
        self,
        target: str,
        qtype: str,
        msg: dict,
        timeout: float = 0.0,
        on_evict=None,
    ) -> bool:
        with self._lock:
            self.sent.append((target, qtype, dict(msg)))
        if target == self._own_name and qtype == "system":
            self._own_q.put(msg)
        else:
            self._other_queues.setdefault(target, Queue()).put(msg)
        return True

    def tickets(self, command: str) -> List[dict]:
        with self._lock:
            return [m for (_t, _q, m) in self.sent if m.get("command") == command]

    def queue_for(self, target: str) -> Queue:
        return self._other_queues.setdefault(target, Queue())


def _make_self_router(name: str) -> Tuple[RouterManager, _LoopbackQueueRegistry, Queue]:
    """RouterManager с одним system-каналом, чей queue_registry заворачивает
    самоадресованные тикеты обратно в его же ``q_system`` — стенд для
    сценария «процесс шлёт запрос самому себе» (driver/CommandManager внутри
    одного процесса)."""
    q_system: Queue = Queue()
    qr = _LoopbackQueueRegistry(name, q_system)
    router = RouterManager(manager_name=name, queue_registry=qr)
    router.register_channel(QueueChannel(f"{name}_system", q_system))
    router.initialize()
    return router, qr, q_system


def _pump(router: RouterManager, stop: threading.Event) -> threading.Thread:
    """Фоновый приёмный цикл — как SystemThreads._message_processing_loop
    (используется ТОЛЬКО там, где тест намеренно терпим к нескольким
    приёмным тактам, не к контракту «ровно один»)."""

    def _loop() -> None:
        while not stop.is_set():
            try:
                router.receive(timeout=0.0, channel_types=["system"])
            except Exception:  # noqa: BLE001 — приёмный цикл не падает
                pass
            time.sleep(0.005)

    t = threading.Thread(target=_loop, name="pump", daemon=True)
    t.start()
    return t


def _wait_until(predicate, deadline_sec: float, interval: float = 0.005) -> bool:
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ===========================================================================
# 1. Самозапрос разрешается ОДНИМ receive() (RED сегодня)
# ===========================================================================


def test_self_request_resolves_within_single_receive():
    """``request()`` к самому себе обязан завершиться после ОДНОГО ``receive()``.

    Сегодня хендлер отвечает через ``reply_to_request`` → тот шлёт ``send()``
    → ответ ложится в ту же ``q_system``, но её уже опросили В ЭТОМ ЖЕ
    вызове (``_poll_all_channels`` снимает снимок ДО диспетчеризации) —
    разобрать его сможет только следующий ``receive()``. Ждущий поток не
    имеет права зависнуть: дедлайн — ``join(timeout=...)``, не бесконечное
    ожидание.
    """
    router, qr, q_system = _make_self_router("self_sync")
    result_holder: Dict[str, Any] = {}

    def _handler(msg: dict) -> None:
        router.reply_to_request(msg, {"value": 42})

    router.register_message_handler("self.echo", _handler)

    def _requester() -> None:
        result_holder["r"] = router.request(
            {"type": "command", "command": "self.echo", "targets": ["self_sync"], "sender": "self_sync"},
            timeout=3.0,
        )

    t = threading.Thread(target=_requester, name="requester", daemon=True)
    receive_elapsed = None
    try:
        t.start()
        assert _wait_until(lambda: qr.tickets("self.echo"), deadline_sec=2.0), (
            "запрос не дошёл до собственной очереди за 2 с — стенд неисправен, сценарий не воспроизведён"
        )

        t0 = time.monotonic()
        router.receive(timeout=0.0, channel_types=["system"])
        receive_elapsed = time.monotonic() - t0

        t.join(timeout=1.0)
        resolved_after_one_receive = not t.is_alive()
    finally:
        # Дедлайн на случай RED: если контракт не выполнен, поток всё ещё
        # ждёт свой pending.event до собственного timeout=3.0 у request().
        t.join(timeout=3.0)
        router.shutdown()

    assert resolved_after_one_receive, (
        f"request() к себе НЕ завершился после одного receive() (сам receive занял "
        f"{receive_elapsed:.3f} с) — самоответ ушёл обычным send() и ждёт второго "
        "приёмного такта, которого в этом тесте не было"
    )
    assert result_holder.get("r", {}).get("success") is True, f"неожиданный конверт: {result_holder.get('r')!r}"
    assert result_holder["r"].get("result") == {"value": 42}
    # Вторичный якорь мехнизма (не спой на имени метода, а эффект на границе
    # транспорта): принятый самоответ не обязан проходить через обычный
    # send()/queue_registry вовсе — иначе он ничем не отличался бы от гвардов
    # ниже, для которых транспортный тикет ЕСТЬ.
    assert qr.tickets("command.response") == [], (
        f"принятый самоответ прошёл через обычный transport-путь "
        f"(queue_registry.send_to_queue записал {qr.tickets('command.response')!r}) — "
        "ожидался прямой резолв БЕЗ постановки в очередь"
    )


# ===========================================================================
# 2. Конверт самоответа несёт success/result (может быть green уже сегодня)
# ===========================================================================


def test_self_request_response_carries_success_and_result():
    """Полезная нагрузка самоответа корректна — НЕЗАВИСИМО от того, за сколько
    приёмных тактов она доехала (терпим к нескольким receive() — фоновый
    насос). Пара к тесту выше: тот пинит ТАЙМИНГ (один такт), этот —
    ПРАВИЛЬНОСТЬ payload. Предсказание: может быть green уже сегодня, если
    насос успевает докрутить второй такт за отведённый join — фиксируем факт
    в отчёте, а не полагаемся на него как на доказательство фикса.
    """
    router, qr, q_system = _make_self_router("self_payload")
    result_holder: Dict[str, Any] = {}

    def _handler(msg: dict) -> None:
        # Берём конкретное поле, а не весь msg["data"]: request() зеркалит
        # свой correlation_id внутрь data (setdefault) — сравнивать пришлось
        # бы с недетерминированным uuid, что и обнаружилось первым прогоном.
        payload_n = (msg.get("data") or {}).get("n")
        router.reply_to_request(msg, {"echo": {"n": payload_n}}, success=True)

    router.register_message_handler("self.payload", _handler)

    def _requester() -> None:
        result_holder["r"] = router.request(
            {
                "type": "command",
                "command": "self.payload",
                "targets": ["self_payload"],
                "sender": "self_payload",
                "data": {"n": 5},
            },
            timeout=3.0,
        )

    t = threading.Thread(target=_requester, name="requester", daemon=True)
    stop = threading.Event()
    pump = _pump(router, stop)
    try:
        t.start()
        t.join(timeout=3.0)
    finally:
        stop.set()
        pump.join(timeout=3.0)
        t.join(timeout=1.0)
        router.shutdown()

    assert not t.is_alive(), "request() к себе завис даже под фоновым насосом приёма"
    r = result_holder.get("r", {})
    assert r.get("success") is True, f"неожиданный конверт: {r!r}"
    assert r.get("result") == {"echo": {"n": 5}}


# ===========================================================================
# 3. Гвард: чужой адресат — обычный send() (green сегодня и после фикса)
# ===========================================================================


def test_foreign_target_reply_uses_send():
    """Ответ НЕ себе обязан уйти обычным транспортом (``send()`` →
    ``queue_registry.send_to_queue``) — это НЕ должно измениться фиксом:
    самоответ — узкий частный случай, чужой адресат идёт прежним путём.

    Наблюдаемый эффект — реальная доставка в очередь чужого адресата (не
    спой на имени ``send``/``_resolve_pending``): без этого ответ мог бы
    молча потеряться, а тест этого бы не заметил.
    """
    router, qr, q_system = _make_self_router("self_guard_foreign")

    def _handler(msg: dict) -> None:
        router.reply_to_request(msg, {"ok": True})

    router.register_message_handler("foreign.probe", _handler)
    try:
        q_system.put(
            {
                "type": "command",
                "command": "foreign.probe",
                "sender": "other_process",
                "reply_to": "other_process",
                "request_id": "cid-foreign-1",
            }
        )
        router.receive(timeout=0.0, channel_types=["system"])
    finally:
        router.shutdown()

    foreign_q = qr.queue_for("other_process")
    assert not foreign_q.empty(), (
        "ответ чужому адресату не доехал до его очереди — обычный send()-путь "
        "не сработал (или был ошибочно подменён прямым резолвом)"
    )
    envelope = foreign_q.get_nowait()
    assert envelope.get("request_id") == "cid-foreign-1"
    assert envelope.get("result") == {"ok": True}
    replies = qr.tickets("command.response")
    assert replies and replies[-1]["targets"] == ["other_process"], (
        f"транспортный тикет ответа не записан для чужого адресата: {replies!r}"
    )


# ===========================================================================
# 4. Гвард: поздний ответ без pending — обычный send() (green сегодня и после)
# ===========================================================================


def test_late_reply_after_pending_gone_uses_send():
    """Самоадресованный ответ БЕЗ зарегистрированного pending-слота (запрос
    никто не делал через ``request()`` — модель «опоздавшего» ответа, слот
    которого уже снят по таймауту) обязан УЙТИ обычным send(), а не молча
    потеряться в попытке прямого резолва несуществующего pending.

    Наблюдаемый эффект — транспортный тикет реально записан в
    queue_registry (тот же якорь, что у соседнего гварда test_reentrant_*
    в test_request_contract_guard.py), а не спой на имени метода.
    """
    router, qr, q_system = _make_self_router("self_guard_late")

    def _handler(msg: dict) -> None:
        router.reply_to_request(msg, {"late": True})

    router.register_message_handler("self.late", _handler)
    try:
        q_system.put(
            {
                "type": "command",
                "command": "self.late",
                "sender": "self_guard_late",
                "reply_to": "self_guard_late",
                "request_id": "cid-late-no-pending",
            }
        )
        # ВАЖНО: pending для этого cid никогда не регистрировался — request()
        # не вызывался. Модель совпадает со случаем «pending уже снят
        # (например, по таймауту) к моменту прихода ответа»: обработчик
        # reply_to_request в обоих случаях не находит pending под этим cid.
        router.receive(timeout=0.0, channel_types=["system"])
    finally:
        router.shutdown()

    replies = qr.tickets("command.response")
    assert replies, "поздний самоответ (без pending) не отправлен вовсе — обязан уйти обычным send(), как и раньше"
    assert replies[-1]["targets"] == ["self_guard_late"]
    assert replies[-1]["request_id"] == "cid-late-no-pending"


# ===========================================================================
# 5. request_async к себе — колбэк ровно один раз (RED или green — см. отчёт)
# ===========================================================================


def test_request_async_to_self_callback_exactly_once():
    """``request_async()`` к самому себе: колбэк вызывается РОВНО ОДИН раз, и
    (пункт контракта Task 1.3b) успевает сработать за ОДИН ``receive()`` —
    так же, как синхронный ``request()`` в тесте 1. Второй сегмент теста
    добирает ещё немного тактов С ДЕДЛАЙНОМ — не чтобы «починить» проверку,
    а чтобы отличить «навсегда завис» от «нужно больше одного такта», и не
    оставить непогашенный фоновый эффект (колбэк, который всё-таки прилетит
    позже и удивит соседний тест).
    """
    router, qr, q_system = _make_self_router("self_async")
    calls: List[dict] = []
    done = threading.Event()

    def _on_response(envelope: dict) -> None:
        calls.append(envelope)
        done.set()

    def _handler(msg: dict) -> None:
        router.reply_to_request(msg, {"async": True})

    router.register_message_handler("self.async.echo", _handler)

    fired_after_one_receive = False
    try:
        cid = router.request_async(
            {
                "type": "command",
                "command": "self.async.echo",
                "targets": ["self_async"],
                "sender": "self_async",
            },
            on_response=_on_response,
            timeout=3.0,
        )
        assert cid, "request_async не вернул correlation_id"
        assert _wait_until(lambda: qr.tickets("self.async.echo"), deadline_sec=2.0), (
            "асинхронный самозапрос не дошёл до собственной очереди — стенд неисправен"
        )

        router.receive(timeout=0.0, channel_types=["system"])
        fired_after_one_receive = done.is_set()

        # Добор тактов с явным дедлайном — только чтобы не оставить билет
        # неразобранным и не спутать RED («нужен второй такт») с зависанием.
        deadline = time.monotonic() + 2.0
        while not done.is_set() and time.monotonic() < deadline:
            router.receive(timeout=0.0, channel_types=["system"])
            time.sleep(0.01)
    finally:
        router.shutdown()

    assert done.is_set(), "колбэк request_async на самоответ не вызван даже за несколько приёмных тактов"
    assert len(calls) == 1, f"колбэк вызван {len(calls)} раз(а), ожидался ровно 1"
    assert calls[0].get("result") == {"async": True}
    assert fired_after_one_receive, (
        "колбэк request_async на самоответ не сработал после ОДНОГО receive() — "
        "самоответ ушёл обычным send() и ждал второго приёмного такта"
    )
