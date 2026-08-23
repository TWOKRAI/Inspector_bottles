"""test_request_contract_guard.py — hazard-тесты исполняемого контракта request().

Автор реализации (не независимый tester): проверяются ОПАСНЫЕ МЕСТА САМОГО
МЕХАНИЗМА, которые не видны из критериев приёмки, — восстановление счётчика
глубины, ложное срабатывание под нагрузкой, «ровно один раз» у колбэка
асинхронного запроса и подметание просроченных слотов.

Контракт (ADR-RTR-011, 2026-08-23):
  - ``request()`` с приёмного потока → RouterReentrantRequestError (громко),
    сообщение при этом НЕ отправляется;
  - ``request()`` при полном отсутствии приёмного цикла → быстрый отказ
    ``{"error": "timeout", "reason": "no_receive_pump"}``, сообщение УХОДИТ;
  - ``request_async()`` не блокирует и зовёт колбэк РОВНО ОДИН РАЗ.

Всё блокирующее — с явным дедлайном (join(timeout)/wait(timeout)): механизм
под тестом сам является источником зависаний, тест не имеет права повиснуть
вместо падения (правило проекта).
"""

from __future__ import annotations

import threading
import time
from queue import Queue

import pytest

from ..channels.queue_channel import QueueChannel
from ..core.router_manager import RouterManager, RouterReentrantRequestError


class _FakeQueueRegistry:
    """Фиксирует исходящие билеты (адресная книга оркестратора в тесте)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []
        self._lock = threading.Lock()

    def send_to_queue(self, target: str, qtype: str, msg: dict) -> bool:
        with self._lock:
            self.sent.append((target, qtype, msg))
        return True

    def commands(self) -> list[str]:
        with self._lock:
            return [m.get("command") for (_t, _q, m) in self.sent]

    def tickets(self, command: str) -> list[dict]:
        with self._lock:
            return [m for (_t, _q, m) in self.sent if m.get("command") == command]


def _make_router(name: str) -> tuple[RouterManager, _FakeQueueRegistry, Queue]:
    """RouterManager с одним system-каналом — как control-plane настоящего процесса."""
    qr = _FakeQueueRegistry()
    router = RouterManager(manager_name=name, queue_registry=qr)
    q_system: Queue = Queue()
    router.register_channel(QueueChannel(f"{name}_system", q_system))
    router.initialize()
    return router, qr, q_system


def _pump(router: RouterManager, stop: threading.Event) -> threading.Thread:
    """Фоновый приёмный цикл — как SystemThreads._message_processing_loop."""

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
# Восстановление глубины: отметка «я приёмный поток» не должна протекать
# ===========================================================================


def test_receive_depth_is_restored_so_the_same_thread_may_request_afterwards():
    """Отметка приёмного потока снимается по ВЫХОДЕ из receive(), а не остаётся навсегда.

    Опасность механизма: счётчик глубины ставится на входе в receive(). Если бы
    он не снимался, поток, ОДНАЖДЫ вызвавший receive() (а это любой тест, любой
    driver, любой worker), навсегда потерял бы право на request() — отказ по
    контракту начал бы срабатывать там, где нарушения нет.
    """
    router, qr, q_system = _make_router("depth_restore")
    stop = threading.Event()
    pump = _pump(router, stop)
    try:
        # Тот же поток сначала сам крутит receive()...
        router.receive(timeout=0.0, channel_types=["system"])

        holder: dict = {}

        def _answerer() -> None:
            # Отвечаем на запрос, как это сделал бы адресат.
            if _wait_until(lambda: qr.tickets("probe.after.receive"), deadline_sec=2.0):
                cid = qr.tickets("probe.after.receive")[0]["request_id"]
                q_system.put(
                    {
                        "type": "response",
                        "command": "command.response",
                        "request_id": cid,
                        "success": True,
                        "result": {"value": 7},
                    }
                )

        answerer = threading.Thread(target=_answerer, name="answerer", daemon=True)
        answerer.start()

        # ...а потом, УЖЕ ВЫЙДЯ из receive(), делает обычный запрос.
        holder["r"] = router.request(
            {"type": "command", "command": "probe.after.receive", "targets": ["B"], "sender": "A"},
            timeout=3.0,
        )
        answerer.join(timeout=3.0)
    finally:
        stop.set()
        pump.join(timeout=5.0)
        router.shutdown()

    assert not pump.is_alive(), "приёмный поток не завершился — тест завис бы без дедлайна"
    assert holder["r"].get("success") is True, (
        f"поток, ранее вызывавший receive(), получил отказ на обычном запросе: {holder['r']!r} — "
        "отметка приёмного потока протекла за пределы вызова receive()"
    )
    assert holder["r"].get("result") == {"value": 7}


def test_receive_depth_is_restored_even_when_receive_raises(monkeypatch):
    """Исключение ИЗ receive() тоже обязано снимать отметку приёмного потока.

    Опасность механизма: снятие стоит в finally. Тест ломает receive() изнутри
    (опрос каналов бросает) и проверяет, что после этого тот же поток не считается
    приёмным. Без finally поток был бы «отравлен» навсегда первым же сбоем опроса.
    """
    router, qr, _q = _make_router("depth_restore_raise")
    try:

        def _boom(*_args, **_kwargs):
            raise RuntimeError("poll сломан")

        monkeypatch.setattr(router, "_poll_all_channels", _boom)
        with pytest.raises(RuntimeError, match="poll сломан"):
            router.receive(timeout=0.0, channel_types=["system"])
        monkeypatch.undo()

        # Тот же поток теперь делает запрос. Ответа не будет (приёмника нет),
        # но отказ обязан быть НЕ реентрантным, а обычным быстрым таймаутом.
        result = router.request(
            {"type": "command", "command": "probe.after.raise", "targets": ["B"], "sender": "A"},
            timeout=0.2,
        )
    finally:
        router.shutdown()

    assert result.get("error") == "timeout", f"ожидался обычный таймаут, получено {result!r}"
    # Якорь существования: сообщение реально ушло — значит путь дошёл до отправки,
    # а не был отбит контрактной проверкой.
    assert qr.tickets("probe.after.raise"), "сообщение не отправлено — сработал ложный отказ по контракту"


# ===========================================================================
# Ложное срабатывание под нагрузкой: обычные потоки не должны получать отказ
# ===========================================================================


def test_contract_refusal_does_not_fire_on_normal_threads_under_load():
    """8 обычных потоков × 5 запросов при работающем приёмном цикле — ни одного отказа.

    Опасность механизма: отметка «я приёмный поток» живёт в thread-local. Ошибка
    в её области видимости (например, общий флаг на роутер вместо потоковой
    отметки) проявилась бы именно так — как отказ обычному потоку, когда приёмный
    цикл в этот момент занят разбором почты.
    """
    router, qr, q_system = _make_router("no_false_refusal")
    stop = threading.Event()
    pump = _pump(router, stop)
    refusals: list[BaseException] = []
    results: list[dict] = []
    results_lock = threading.Lock()

    # Автоответчик: превращает каждый запрос в ответ (роль адресата).
    def _answer_loop() -> None:
        answered: set[str] = set()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not stop.is_set():
            for ticket in qr.tickets("load.probe"):
                cid = ticket.get("request_id")
                if cid and cid not in answered:
                    answered.add(cid)
                    q_system.put(
                        {
                            "type": "response",
                            "command": "command.response",
                            "request_id": cid,
                            "success": True,
                            "result": {"cid": cid},
                        }
                    )
            time.sleep(0.002)

    answerer = threading.Thread(target=_answer_loop, name="answerer", daemon=True)
    answerer.start()

    def _worker() -> None:
        for _ in range(5):
            try:
                res = router.request(
                    {"type": "command", "command": "load.probe", "targets": ["B"], "sender": "A"},
                    timeout=5.0,
                )
                with results_lock:
                    results.append(res)
            except BaseException as exc:  # noqa: BLE001 — ловим ЛЮБОЙ отказ, включая контрактный
                with results_lock:
                    refusals.append(exc)
                return

    threads = [threading.Thread(target=_worker, name=f"req-{i}", daemon=True) for i in range(8)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)
        alive = [t.name for t in threads if t.is_alive()]
    finally:
        stop.set()
        answerer.join(timeout=3.0)
        pump.join(timeout=5.0)
        router.shutdown()

    assert not alive, f"потоки-инициаторы не завершились: {alive} — request() завис"
    assert not refusals, f"обычные потоки получили отказ по контракту: {refusals!r}"
    assert len(results) == 40, f"ожидалось 40 ответов (8 потоков × 5), получено {len(results)}"
    failed = [r for r in results if r.get("success") is not True]
    assert not failed, f"часть запросов из обычных потоков не отработала: {failed[:3]!r}"


# ===========================================================================
# request_async: не блокирует, зовёт колбэк ровно один раз
# ===========================================================================


def test_request_async_does_not_block_the_caller_and_delivers_on_the_receive_thread():
    """Асинхронный запрос возвращает управление сразу, ответ приходит колбэком.

    Заодно фиксируется, ГДЕ исполняется колбэк: на приёмном потоке (внутри
    receive()). Это часть контракта — от неё зависит, что StateProxy может
    менять кэш без локов.
    """
    router, qr, q_system = _make_router("async_basic")
    seen: list[dict] = []
    seen_thread: list[str] = []
    done = threading.Event()

    def _on_response(envelope: dict) -> None:
        seen.append(envelope)
        seen_thread.append(threading.current_thread().name)
        done.set()

    stop = threading.Event()
    pump = _pump(router, stop)
    try:
        t0 = time.monotonic()
        cid = router.request_async(
            {"type": "command", "command": "async.probe", "targets": ["B"], "sender": "A"},
            on_response=_on_response,
            timeout=5.0,
        )
        elapsed = time.monotonic() - t0
        assert elapsed < 0.5, f"request_async заблокировал вызывающего на {elapsed:.3f} с"
        assert cid, "request_async не вернул correlation_id"

        q_system.put(
            {
                "type": "response",
                "command": "command.response",
                "request_id": cid,
                "success": True,
                "result": {"value": 1},
            }
        )
        got = done.wait(timeout=3.0)
    finally:
        stop.set()
        pump.join(timeout=5.0)
        router.shutdown()

    # Якорь существования: запрос реально ушёл.
    assert qr.tickets("async.probe"), "async-запрос не отправлен — сценарий не воспроизведён"
    assert got, "колбэк не вызван за 3 с"
    assert len(seen) == 1, f"колбэк вызван {len(seen)} раз(а), ожидался ровно 1"
    assert seen[0].get("result") == {"value": 1}
    assert seen_thread == ["pump"], f"колбэк исполнен не на приёмном потоке, а на {seen_thread!r}"


def test_request_async_callback_is_not_called_twice_when_sweep_runs_after_the_answer():
    """Ответ пришёл — последующее подметание таймаутов НЕ зовёт колбэк повторно.

    Опасность механизма: две дороги к одному слоту (ответ и подметание по
    дедлайну). Если бы каждая звала колбэк сама, StateProxy получил бы и снимок,
    и «таймаут» — то есть снял бы отметку «ресинк идёт» дважды и мог бы
    применить снимок к чужому окну.
    """
    router, _qr, q_system = _make_router("async_once")
    calls: list[dict] = []
    done = threading.Event()

    def _on_response(envelope: dict) -> None:
        calls.append(envelope)
        done.set()

    try:
        cid = router.request_async(
            {"type": "command", "command": "once.probe", "targets": ["B"], "sender": "A"},
            on_response=_on_response,
            timeout=0.05,  # дедлайн ЯВНО короткий: к моменту подметания он истечёт
        )
        q_system.put(
            {
                "type": "response",
                "command": "command.response",
                "request_id": cid,
                "success": True,
                "result": {"value": 2},
            }
        )
        router.receive(timeout=0.0, channel_types=["system"])  # резолвит ответ
        assert done.wait(timeout=2.0), "колбэк не вызван на ответе"

        # Дедлайн заведомо истёк — крутим приёмные такты, на которых работает
        # подметание просроченных слотов.
        time.sleep(0.1)
        for _ in range(5):
            router.receive(timeout=0.0, channel_types=["system"])
    finally:
        router.shutdown()

    assert len(calls) == 1, f"колбэк вызван {len(calls)} раз(а): {calls!r} — «ровно один раз» нарушено"
    assert calls[0].get("success") is True


def test_request_async_reports_timeout_when_the_answer_never_comes():
    """Ответ, который не придёт НИКОГДА: колбэк получает таймаут, слот освобождается.

    Названо тестом (а не рассуждением), что происходит: колбэк вызывается ровно
    один раз с ``{"success": False, "error": "timeout"}``, реестр pending пуст —
    иначе слот копился бы вечно, а вызывающий навсегда остался бы в состоянии
    «запрос ещё идёт».
    """
    router, qr, _q = _make_router("async_timeout")
    calls: list[dict] = []
    done = threading.Event()

    def _on_response(envelope: dict) -> None:
        calls.append(envelope)
        done.set()

    try:
        router.request_async(
            {"type": "command", "command": "lost.probe", "targets": ["B"], "sender": "A"},
            on_response=_on_response,
            timeout=0.1,
        )
        assert qr.tickets("lost.probe"), "запрос не отправлен — сценарий не воспроизведён"
        assert calls == [], "колбэк вызван ДО дедлайна — таймаут сработал раньше времени"

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not done.is_set():
            router.receive(timeout=0.0, channel_types=["system"])
            time.sleep(0.01)
        fired = done.is_set()
        pending_left = len(router._pending_requests)
        async_left = router._async_pending_count
    finally:
        router.shutdown()

    assert fired, "колбэк не вызван по таймауту за 3 с — слот остался бы в реестре навсегда"
    assert len(calls) == 1, f"колбэк вызван {len(calls)} раз(а), ожидался ровно 1"
    assert calls[0].get("error") == "timeout", f"ожидался конверт таймаута, получено {calls[0]!r}"
    assert pending_left == 0, f"pending-слот не снят: осталось {pending_left}"
    assert async_left == 0, f"счётчик асинхронных слотов не обнулён: {async_left}"


def test_request_async_calls_back_synchronously_when_send_fails():
    """Провал отправки — колбэк ровно один раз, СИНХРОННО, с причиной не «timeout».

    Иначе вызывающий (StateProxy) остался бы с отметкой «ресинк идёт» до конца
    жизни процесса: подметать нечего — слот снят, ответа не будет.
    """
    # Без queue_registry и без канала под targets отправка не состоится.
    router = RouterManager(manager_name="async_send_fail")
    calls: list[dict] = []

    def _on_response(envelope: dict) -> None:
        calls.append(envelope)

    try:
        router.request_async(
            {"type": "command", "command": "nowhere.probe", "targets": ["B"], "sender": "A"},
            on_response=_on_response,
            timeout=5.0,
        )
        # Синхронность: колбэк уже вызван, ждать ничего не нужно.
        immediate = list(calls)
        pending_left = len(router._pending_requests)
    finally:
        router.shutdown()

    assert len(immediate) == 1, f"колбэк не вызван синхронно при провале отправки: {immediate!r}"
    assert immediate[0].get("success") is False
    assert immediate[0].get("error") != "timeout", (
        f"провал отправки неотличим от таймаута: {immediate[0]!r} — вызывающий не поймёт, ждать ему или нет"
    )
    assert pending_left == 0, f"слот не снят при провале отправки: осталось {pending_left}"


# ===========================================================================
# Реентрантный отказ: сообщение НЕ отправляется
# ===========================================================================


def test_reentrant_request_does_not_send_the_message_at_all():
    """Отказ по контракту случается ДО отправки — «опоздавшей почты» не появится.

    Живой симптом, ради которого это важно: ответы на запросы, чей pending-слот
    уже истёк, приезжали в системную очередь раз в ~5 с и разбирались как чужая
    почта. Если бы реентрантный вызов всё-таки отправлял сообщение, отказ убрал
    бы простой, но оставил бы поток мусорных ответов.
    """
    router, qr, q_system = _make_router("reentrant_no_send")
    outcome: dict = {}
    sent_from_handler: list[str] = []

    def _handler(_msg: dict) -> None:
        try:
            router.request(
                {"type": "command", "command": "reentrant.probe", "targets": ["B"], "sender": "A"},
                timeout=2.0,
            )
        except RouterReentrantRequestError as exc:
            outcome["exc"] = exc
        # Контроль: обычная (неблокирующая) отправка с того же приёмного потока
        # обязана пройти — отказ адресован ожиданию ответа, а не отправке.
        # Именно send(), не send_async(): билет обязан лечь в реестр СИНХРОННО,
        # иначе тест сверял бы расторопность фонового отправителя.
        router.send({"type": "command", "command": "control.after.refusal", "targets": ["B"], "sender": "A"})
        sent_from_handler.append("control.after.refusal")

    router.register_message_handler("trigger.reentrant", _handler)
    try:
        q_system.put({"type": "command", "command": "trigger.reentrant", "sender": "test"})
        t0 = time.monotonic()
        router.receive(timeout=0.0, channel_types=["system"])
        elapsed = time.monotonic() - t0
    finally:
        router.shutdown()

    assert "exc" in outcome, "реентрантный вызов не отказал исключением — сценарий не воспроизведён"
    assert elapsed < 1.0, f"реентрантный вызов занял {elapsed:.3f} с (передан timeout=2.0) — отказ не быстрый"
    assert qr.tickets("reentrant.probe") == [], (
        "реентрантный request() всё-таки отправил сообщение — ответ на него приедет "
        "в пустой pending-слот и ляжет «опоздавшей почтой»"
    )
    # Якорь существования: пустой список билетов выше значит «отказали именно
    # этому вызову», а не «этот роутер вообще ничего не отправляет».
    assert sent_from_handler, "хендлер не отправил контрольное сообщение — стенд неисправен"
    assert qr.tickets("control.after.refusal"), (
        "роутер не отправил контрольное сообщение с того же приёмного потока — "
        "отсутствие билета реентрантного запроса ничего не доказывало бы"
    )


def test_request_async_is_allowed_from_the_receive_thread():
    """Асинхронный запрос с приёмного потока — ЗАКОННЫЙ путь, он не отказывает.

    Пара-контроль к отказу выше: если бы проверка контракта стояла в общем месте
    для обоих методов, единственная замена блокирующему запросу тоже перестала бы
    работать — и чинить дефект было бы нечем.
    """
    router, qr, q_system = _make_router("async_from_pump")
    outcome: dict = {}

    def _handler(_msg: dict) -> None:
        try:
            outcome["cid"] = router.request_async(
                {"type": "command", "command": "async.from.pump", "targets": ["B"], "sender": "A"},
                on_response=lambda env: outcome.setdefault("env", env),
                timeout=5.0,
            )
        except BaseException as exc:  # noqa: BLE001
            outcome["exc"] = exc

    router.register_message_handler("trigger.async", _handler)
    try:
        q_system.put({"type": "command", "command": "trigger.async", "sender": "test"})
        router.receive(timeout=0.0, channel_types=["system"])
    finally:
        router.shutdown()

    assert "exc" not in outcome, f"асинхронный запрос с приёмного потока отказал: {outcome['exc']!r}"
    assert outcome.get("cid"), "асинхронный запрос не был отправлен с приёмного потока"
    assert qr.tickets("async.from.pump"), "билет асинхронного запроса не ушёл"


def test_no_pump_refusal_is_named_and_fast_but_still_sends():
    """Отсутствие приёмного цикла: быстрый отказ с названной причиной, сообщение ушло.

    Литералы 0.2/2.0 вписаны руками. 2.0 — потолок ожидания (внутреннее окно
    ожидания приёмника заведомо меньше), 0.2 — нижняя граница: отказ обязан быть
    именно быстрым, а не мгновенным по случайной причине вроде провала отправки.
    """
    router, qr, _q = _make_router("no_pump")
    try:
        t0 = time.monotonic()
        result = router.request(
            {"type": "command", "command": "nopump.probe", "targets": ["B"], "sender": "A"},
            timeout=30.0,  # заведомо больше окна ожидания приёмника
        )
        elapsed = time.monotonic() - t0
    finally:
        router.shutdown()

    assert qr.tickets("nopump.probe"), (
        "сообщение не отправлено — деградация обязана быть fire-and-forget: команда доезжает, мы лишь не ждём ответа"
    )
    assert elapsed < 2.0, f"отказ занял {elapsed:.3f} с при timeout=30.0 — ожидание не прервано"
    assert result.get("success") is False
    assert result.get("reason") == "no_receive_pump", (
        f"причина отказа не названа: {result!r} — вызывающий не отличит её от обычного таймаута связи"
    )
