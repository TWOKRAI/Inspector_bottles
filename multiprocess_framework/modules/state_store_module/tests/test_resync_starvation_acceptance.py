"""test_resync_starvation_acceptance.py — приёмочные тесты (независимый tester, ДО починки).

Критерии приёмки (постановка задачи "resync-tester", ветка observation-port):

  С1. Обработка дельты, вызывающей ресинхронизацию, НЕ блокирует приёмный поток
      на время таймаута (якорь: < 1.0 с при внутреннем таймауте резинка ~5 с).
  С2. Пока идёт ресинхронизация, приёмный поток продолжает разбирать ДРУГИЕ
      входящие сообщения (якорь: сообщение после дельты-триггера обработано
      в пределах того же литерального окна < 1.0 с).
  С3. Блокирующий запрос-ожидание, сделанный ИЗ приёмного потока, обязан
      отказать ГРОМКО (исключение или явный отказ с причиной), а не молча
      стоять до таймаута.
  С4. Оформление подписки на дерево из старта плагина (когда приёмный поток
      процесса ещё не создан) не стоит полного таймаута (якорь: < 2.0 с).
  С5. Пара-контроль (обязательный): блокирующий запрос-ожидание, сделанный из
      ОБЫЧНОГО потока (не приёмного), продолжает работать как раньше.

Файл написан ДО починки, строго по критериям приёмки, без чтения реализации
фикса (её ещё нет на этом коммите — detached HEAD 1bf00c4c). С1/С2/С3/С4
ОБЯЗАНЫ быть красными здесь — это ТЗ для реализатора. С5 — пара-контроль,
ожидаемо зелёный уже сегодня (иначе С3 доказывал бы только «сломали запросы
вообще», а не именно реентрантный случай).

Механизм воспроизводится НАСТОЯЩИМ RouterManager (реальные очереди
QueueChannel, реальный блокирующий request()) + настоящим StateProxy — ровно
так, как их использует ProcessModule/SystemThreads._message_processing_loop:
единственный приёмный поток крутит
router.receive(channel_types=["system","state","observability"]) в цикле;
state.changed диспетчеризуется СИНХРОННО внутри этого же вызова receive()
(event_dispatcher.dispatch зовёт handler напрямую, без пула потоков —
см. dispatch_module/core/dispatcher.py и base_dispatcher.py).

Единственное, что подменяется — исходящий queue_registry (targets-доставка
вовне): тот же приём, что и в router_module/tests/test_router_manager.py
(_FakeQueueRegistry) — фиксирует ticket'ы, ничего не резолвит взаправду,
никакого мока внутренней логики StateProxy/RouterManager.

Всё блокирующее — с явным дедлайном (join(timeout)/Event.wait(timeout)):
сам механизм под тестом — источник зависаний, тест не имеет права повиснуть
вместо падения (правило проекта).

Литералы (1.0 с / 2.0 с / 3.0 с) — вписаны руками, НЕ выведены из кода под
тестом (StateProxy._SYNC_REQUEST_TIMEOUT/RouterManager.request(timeout=...)
нигде не импортируются и не читаются).
"""

from __future__ import annotations

import threading
import time
from queue import Queue
from types import SimpleNamespace

from multiprocess_framework.modules.router_module import QueueChannel, RouterManager
from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

# ============================================================================
# Стенд: настоящий RouterManager с каналами {proc}_system/{proc}_state — как
# их заводит ProcessCommunication.register_router_channels() у настоящего
# процесса (см. router_module/tests/test_router_manager.py::TestChannelTypesFilter
# для того же приёма именования).
# ============================================================================


class _FakeQueueRegistry:
    """Фиксирует исходящие ticket'ы, ничего не резолвит взаправду.

    Тот же дубль, что router_module/tests/test_router_manager.py::_FakeQueueRegistry
    (используется там для проверки targets-fallback в _deliver_by_targets) — не
    мок внутренней логики StateProxy/RouterManager, а единственная точка вовне
    (адресная книга оркестратора), которую честно некому предоставить в тесте.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send_to_queue(self, target: str, qtype: str, msg: dict) -> bool:
        self.sent.append((target, qtype, msg))
        return True


def _make_process_router(proc_name: str) -> tuple[RouterManager, _FakeQueueRegistry, Queue, Queue]:
    """Собрать RouterManager с system/state каналами — как у настоящего процесса.

    Возвращает (router, queue_registry, q_system, q_state). q_system/q_state —
    голые queue.Queue под каналами: тест кладёт туда входящие конверты напрямую
    (симулируя IPC от другого процесса/StateStoreManager), router.receive(...)
    их вычерпывает — тем же самым путём, что и
    SystemThreads._message_processing_loop (channel_types=["system","state",
    "observability"]).
    """
    qr = _FakeQueueRegistry()
    proc = SimpleNamespace(name=proc_name)
    router = RouterManager(manager_name=proc_name, process=proc, queue_registry=qr)
    q_system: Queue = Queue()
    q_state: Queue = Queue()
    router.register_channel(QueueChannel(f"{proc_name}_system", q_system))
    router.register_channel(QueueChannel(f"{proc_name}_state", q_state))
    router.initialize()
    return router, qr, q_system, q_state


def _start_receive_loop(router: RouterManager, stop_event: threading.Event) -> threading.Thread:
    """Настоящий приёмный цикл — буквальная копия SystemThreads._message_processing_loop.

    Упрощение против оригинала: не логирует через process._log_error (в стенде
    process — голый SimpleNamespace, метода нет), просто глотает исключение и
    продолжает цикл — сам RouterManager.receive() уже логирует свои ошибки
    через собственный _log_error, эта обвязка процессу не нужна для того,
    что здесь проверяется (сама доставка/блокировка).
    """

    def _loop() -> None:
        while not stop_event.is_set():
            try:
                router.receive(timeout=0.0, channel_types=["system", "state", "observability"])
            except Exception:  # noqa: BLE001 — как и в оригинале, приёмный цикл не должен падать
                pass
            time.sleep(0.01)

    t = threading.Thread(target=_loop, name="test-message-processor", daemon=True)
    t.start()
    return t


def _state_changed_envelope(deltas: list[Delta], first_revision: int, revision: int, target: str) -> dict:
    """Конверт state.changed — тот же контракт, что StateStoreManager кладёт на провод
    (см. StateProxy.on_state_changed: msg["data"]["deltas"/"revision"/"first_revision"])."""
    return {
        "type": "event",
        "command": "state.changed",
        "sender": "ProcessManager",
        "targets": [target],
        "queue_type": "state",
        "data": {
            "deltas": [d.to_dict() for d in deltas],
            "revision": revision,
            "first_revision": first_revision,
        },
    }


def _wait_until(predicate, deadline_sec: float, interval: float = 0.01) -> bool:
    """Опрос с явным дедлайном — НИКОГДА не ждёт бесконечно (правило проекта:
    ничто не смеет виснуть вместо падения)."""
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ============================================================================
# С1 — обработка дельты-триггера не блокирует приёмный поток на таймаут
# ============================================================================


def test_c1_resync_processing_does_not_block_the_receive_thread_for_the_timeout():
    """С1: разрыв revision → resync → приёмный поток НЕ обязан ждать таймаут.

    Однопоточный, детерминированный замер: один вызов router.receive() поднимает
    пакет с разрывом revision → StateProxy.on_state_changed() → _resync() →
    блокирующий request() ИЗ ЭТОГО ЖЕ вызова receive() (event_dispatcher.dispatch
    зовёт handler синхронно, в той же кадре стека). Меряем длительность самого
    вызова receive() — это и есть время, на которое занят приёмный поток.
    """
    proc_name = "proc_c1"
    router, qr, _q_system, q_state = _make_process_router(proc_name)
    try:
        proxy = StateProxy(proc_name, router=router, server_target="ProcessManager")
        router.register_message_handler("state.changed", proxy.on_state_changed)
        # Подписка нужна, чтобы было ЧТО ресинкать — _resync() no-op на пустом
        # списке паттернов (см. _advance_revision_and_maybe_resync: patterns
        # берутся из _sub_patterns.values()). sync=False — не блокирует сама.
        proxy.subscribe("foo.**", lambda _deltas: None, sync=False)

        # Пакет №1 — база отсчёта revision (без разрыва: _last_revision был None).
        d1 = Delta(path="foo.bar", old_value=MISSING, new_value=1, source="ProcessManager", revision=1)
        q_state.put(_state_changed_envelope([d1], first_revision=1, revision=1, target=proc_name))
        first_batch = router.receive(timeout=0.0, channel_types=["state"])
        assert len(first_batch) == 1, "базовый пакет не дошёл до receive() — стенд неисправен"
        assert proxy.cache.get("foo.bar") == 1, "базовая дельта не применена к кэшу — стенд неисправен"

        # Пакет №2 — разрыв: proxy ждал first_revision<=2, получает 5.
        d2 = Delta(path="foo.bar", old_value=1, new_value=2, source="ProcessManager", revision=5)
        q_state.put(_state_changed_envelope([d2], first_revision=5, revision=5, target=proc_name))

        t0 = time.monotonic()
        router.receive(timeout=0.0, channel_types=["state"])
        elapsed = time.monotonic() - t0
    finally:
        router.shutdown()

    # Якорь существования (правило 2): "не заблокировалось" ничего не значит,
    # если resync вообще не запускался.
    resync_requests = [m for (_t, _q, m) in qr.sent if m.get("command") == "state.get_subtree"]
    assert resync_requests, (
        "ресинк не был запущен (нет исходящего state.get_subtree) — разрыв revision "
        "не спровоцировал ресинхронизацию, замер длительности ничего не доказывает"
    )

    assert elapsed < 1.0, (
        f"обработка дельты с разрывом revision заняла {elapsed:.3f} с — приёмный поток "
        "блокировался внутри request() на таймаут ресинхронизации вместо того, чтобы "
        "вернуть управление быстро"
    )


# ============================================================================
# С2 — приёмный поток продолжает разбирать другие сообщения во время resync
# ============================================================================


def test_c2_receive_thread_keeps_draining_other_messages_during_resync():
    """С2: пока идёт ресинк, приёмный поток продолжает разбирать ДРУГИЕ сообщения.

    Настоящий фоновый поток крутит receive() в цикле (как SystemThreads). Кладём
    маркерную команду в q_system только ПОСЛЕ того, как убедились, что резинк
    реально запущен (и, следовательно, приёмный поток сейчас внутри блокирующего
    request()) — иначе порядок обработки двух независимых put() не гарантирован.
    """
    proc_name = "proc_c2"
    router, qr, q_system, q_state = _make_process_router(proc_name)
    stop_event = threading.Event()
    loop_thread = _start_receive_loop(router, stop_event)
    marker_seen_at: dict[str, float] = {}
    marker_event = threading.Event()
    t_inject = None
    got = False
    try:
        proxy = StateProxy(proc_name, router=router, server_target="ProcessManager")
        router.register_message_handler("state.changed", proxy.on_state_changed)
        proxy.subscribe("foo.**", lambda _deltas: None, sync=False)

        def _on_marker(_msg: dict) -> None:
            marker_seen_at["t"] = time.monotonic()
            marker_event.set()

        router.register_message_handler("test.marker", _on_marker)

        # Пакет №1 — база отсчёта.
        d1 = Delta(path="foo.bar", old_value=MISSING, new_value=1, source="ProcessManager", revision=1)
        q_state.put(_state_changed_envelope([d1], first_revision=1, revision=1, target=proc_name))
        assert _wait_until(lambda: proxy.cache.get("foo.bar") == 1, deadline_sec=2.0), (
            "базовая дельта не применилась за 2с фоновым потоком — стенд неисправен"
        )

        # Пакет №2 — триггер разрыва (приёмный поток должен уйти в _resync()).
        d2 = Delta(path="foo.bar", old_value=1, new_value=2, source="ProcessManager", revision=5)
        q_state.put(_state_changed_envelope([d2], first_revision=5, revision=5, target=proc_name))

        # Якорь существования: ждём подтверждения, что resync реально запущен
        # (исходящий state.get_subtree уже виден) — ЭТО и значит, что приёмный
        # поток сейчас внутри pending.event.wait(...), самое подходящее время
        # класть маркер.
        assert _wait_until(
            lambda: any(m.get("command") == "state.get_subtree" for (_t, _q, m) in qr.sent),
            deadline_sec=2.0,
        ), "ресинк не был запущен — разрыв revision не спровоцировал ресинхронизацию"

        t_inject = time.monotonic()
        q_system.put({"type": "command", "command": "test.marker", "sender": "test"})

        got = marker_event.wait(timeout=3.0)
    finally:
        stop_event.set()
        loop_thread.join(timeout=6.0)
        router.shutdown()

    assert not loop_thread.is_alive(), (
        "приёмный поток не завершился за отведённое время — тест сам завис бы без дедлайна"
    )
    assert got, (
        "маркер, положенный СРАЗУ после дельты-триггера (когда resync уже точно запущен), "
        "не обработан за 3с — приёмный поток занят ресинхронизацией"
    )
    elapsed = marker_seen_at["t"] - t_inject
    assert elapsed < 1.0, (
        f"маркер обработан через {elapsed:.3f} с после постановки в очередь — приёмный поток "
        "был занят resync'ом вместо разбора остальной очереди"
    )


# ============================================================================
# С3 — реентрантный блокирующий request() из приёмного потока обязан отказать громко
# ============================================================================


def test_c3_reentrant_blocking_request_from_receive_thread_fails_loud_not_silently():
    """С3: request(), сделанный ИЗ приёмного потока, обязан отказать ГРОМКО.

    Реентрантность: command-хендлер, вызванный СИНХРОННО внутри receive() (тем
    же кадром стека, тем же потоком), сам зовёт router.request(...) — отвечать
    на него некому (единственный приёмный поток занят им самим). Контракт
    (docstring RouterManager.request(), ADR-SS-016) требует: либо (а) исключение,
    либо (б) быстрый явный отказ с отличимой от обычного таймаута причиной.
    Молчаливое ожидание timeout=2.0 (переданного явно, НЕ прочитанного из кода)
    — нарушение.
    """
    proc_name = "proc_c3"
    router, _qr, q_system, _q_state = _make_process_router(proc_name)
    outcome: dict = {}

    def _reentrant_handler(_msg: dict) -> None:
        t0 = time.monotonic()
        try:
            result = router.request(
                {
                    "type": "command",
                    "command": "some.other.command",
                    "targets": ["ProcessManager"],
                    "sender": proc_name,
                },
                timeout=2.0,
            )
            outcome["result"] = result
        except Exception as exc:  # noqa: BLE001 — именно это и есть путь (а) критерия С3
            outcome["exception"] = exc
        outcome["elapsed"] = time.monotonic() - t0

    router.register_message_handler("trigger.reentrant", _reentrant_handler)
    try:
        q_system.put({"type": "command", "command": "trigger.reentrant", "sender": "test"})
        # Вызываем receive() из ЭТОГО (тестового) потока — он и есть "приёмный
        # поток" в момент вызова: реентрантный request() случится ВНУТРИ этого
        # же кадра стека, синхронно.
        router.receive(timeout=0.0, channel_types=["system"])
    finally:
        router.shutdown()

    assert "elapsed" in outcome, "реентрантный хендлер не был вызван — сценарий не воспроизведён"

    assert outcome["elapsed"] < 1.0, (
        f"повторный request() из приёмного потока занял {outcome['elapsed']:.3f} с "
        "(передан timeout=2.0 явным параметром вызова) — значит он молча ждал, "
        "а не отказал громко"
    )
    if "exception" not in outcome:
        error_reason = outcome["result"].get("error") if isinstance(outcome["result"], dict) else None
        assert error_reason != "timeout", (
            f"request() вернул обычный error='timeout' — неотличимо от честного отказа связи; "
            "контракт требует ГРОМКОГО отказа с причиной именно про повторный вход с приёмного "
            f"потока, а не тихого дожидания таймаута (result={outcome['result']!r})"
        )


# ============================================================================
# С4 — синхронная подписка из старта плагина не стоит таймаута
# ============================================================================


def test_c4_plugin_subscribe_before_receive_thread_exists_does_not_pay_the_full_timeout():
    """С4: state.subscribe(sync=True), сделанный ДО того, как создан приёмный
    поток процесса (как из start() плагина — см. ProcessModule.initialize():
    _init_custom_managers()/_init_application_threads() (плагины, шаг 6) идут
    ДО _init_system_threads() (message_processor, шаг 7)), не должен стоить
    полного таймаута.

    Стенд: каналы зарегистрированы, router.initialize() вызван (AsyncSender
    поднят — своя внутренняя механика RouterManager), но НИКТО ни разу не
    вызывает router.receive() — ровно ситуация "приёмный поток ещё не создан".
    Ответ на синхронную подписку в принципе некому разобрать.
    """
    proc_name = "proc_c4"
    router, qr, _q_system, _q_state = _make_process_router(proc_name)
    try:
        proxy = StateProxy(proc_name, router=router, server_target="ProcessManager")

        t0 = time.monotonic()
        sub_id = proxy.subscribe("plugin.tree.**", lambda _deltas: None, sync=True)
        elapsed = time.monotonic() - t0
    finally:
        router.shutdown()

    # Якорь существования: подписка реально ушла синхронным раундтрипом.
    subscribe_requests = [m for (_t, _q, m) in qr.sent if m.get("command") == "state.subscribe"]
    assert subscribe_requests, (
        "state.subscribe не был отправлен вовсе — сценарий не воспроизведён, замер длительности ничего не доказывает"
    )
    assert sub_id, "subscribe() обязан вернуть локальный sub_id даже при неотвеченной подписке"

    assert elapsed < 2.0, (
        f"оформление подписки заняло {elapsed:.3f} с — приёмный поток процесса ещё не "
        "существует (никто не вызывал receive()), отвечать некому, подписка "
        "заблокировалась на таймаут"
    )


# ============================================================================
# С5 — пара-контроль: обычный (не приёмный) поток продолжает работать как раньше
# ============================================================================


def test_c5_control_blocking_request_from_a_normal_thread_still_resolves():
    """С5 (пара-контроль, ОБЯЗАТЕЛЬНЫЙ): request() из ОБЫЧНОГО потока (не
    приёмного) продолжает работать — ответ приходит, значение возвращается.

    Без этого контроля С3 доказывал бы только "сломали запросы вообще", а не
    именно реентрантный случай. Ожидается ЗЕЛЁНЫЙ уже сегодня: это штатный,
    существующий механизм (см. router_module/tests/test_router_manager.py::
    TestRequestResponse::test_request_resolves_when_response_received) — здесь
    тот же сценарий собран на стенде с {proc}_system/{proc}_state каналами,
    как у настоящего процесса, плюс постоянный фоновый приёмный поток.
    """
    proc_name = "proc_c5"
    router, qr, q_system, _q_state = _make_process_router(proc_name)
    stop_event = threading.Event()
    loop_thread = _start_receive_loop(router, stop_event)
    holder: dict = {}
    req_thread = None
    elapsed = None
    try:

        def _do_request() -> None:
            holder["result"] = router.request(
                {
                    "type": "command",
                    "command": "control.probe",
                    "targets": ["ProcessManager"],
                    "sender": proc_name,
                },
                timeout=3.0,
            )

        t_start = time.monotonic()
        req_thread = threading.Thread(target=_do_request, name="test-normal-thread", daemon=True)
        req_thread.start()

        found = _wait_until(
            lambda: any(m.get("command") == "control.probe" for (_t, _q, m) in qr.sent),
            deadline_sec=2.0,
        )
        assert found, "запрос не был отправлен — сценарий не воспроизведён"
        cid = None
        for _t, _q, m in qr.sent:
            if m.get("command") == "control.probe":
                cid = m.get("request_id")
                break
        assert cid, "у отправленного запроса нет request_id — сценарий не воспроизведён"

        # Отвечаем на запрос — как это сделал бы настоящий StateStoreManager
        # на другом конце. Ответ приходит control-plane системной очередью.
        q_system.put(
            {
                "type": "response",
                "command": "command.response",
                "request_id": cid,
                "success": True,
                "result": {"value": 42},
            }
        )

        req_thread.join(timeout=3.0)
        elapsed = time.monotonic() - t_start
    finally:
        stop_event.set()
        loop_thread.join(timeout=6.0)
        router.shutdown()

    assert not req_thread.is_alive(), "поток-инициатор не завершился за отведённое время — request() завис"
    result = holder.get("result")
    assert result is not None, "request() не вернул результат"
    assert result.get("success") is True, f"ожидался успешный ответ, получено: {result!r}"
    assert result.get("result") == {"value": 42}
    assert elapsed is not None and elapsed < 2.0, (
        f"обычный (не приёмный) поток ждал ответ {elapsed} с — контроль тоже сломан, "
        "и тогда С3 ничего не доказывал бы про именно РЕЕНТРАНТНЫЙ случай"
    )
