"""Т.3 (plans/observation-port/plan.md) — acceptance-тесты НЕЗАВИСИМОГО тестера.

Написаны ДО реализации, работой из акцептанс-критериев (см. ТЗ Т.3), без чтения
кода реализации задачи — только уже существующий контракт ``StateProxy``,
изученный как контекст механизма. Ожидаемо КРАСНЫЕ там, где отмечено явно;
там, где существующий механизм (async-подписка ``sync=False``) уже даёт нужное
свойство — отмечено как «ЗЕЛЁНЫЙ ДО РЕАЛИЗАЦИИ» с объяснением, что именно ещё
не сделано.

Механизм (см. ``proxy/state_proxy.py``):
  - ``subscribe(pattern, cb, sync=True)`` — блокирующий request/response до
    ``sub_id`` сервера; таймаут запроса — ``StateProxy._SYNC_REQUEST_TIMEOUT``
    (5.0 с на момент написания, пин'уется литералом ниже — НЕ читается из
    атрибута класса, чтобы тест доказывал контракт, а не подстраивался под код).
  - ``subscribe(..., sync=False)`` — fire-and-forget, не блокирует поток.
  - ``_confirmed_patterns`` заполняется ТОЛЬКО подтверждённым sync-путём;
    ``_find_covering_pattern`` считает покрывающими только эти паттерны.

Критерий 3 требует ПУБЛИЧНО читаемое число подтверждённых паттернов — такого
свойства в коде нет (только приватное ``_confirmed_patterns``). Тестер выбирает
имя контракта ``StateProxy.confirmed_pattern_count`` (по аналогии с
существующими публичными ``@property`` — ``process_name``, ``cache``) — это
дизайн-решение тестера, а не факт из кода.

Правка (реализация Task Т.3, решение 3 постановки): исходный
``test_evidence_based_confirmation_variant_pattern_becomes_covering_after_delta``
был условным — «зелёный, ЕСЛИ реализация выберет evidence-based
подтверждение». Реализация закрыла развилку в пользу строго server-ack-only
(единственного пути, где подтверждение не зависит от того, что конверт
``state.changed`` не несёт ``sub_id`` — см. решение 3 в ТЗ). Тест переписан
(единственное разрешённое исключение из «остальные тесты — byte-identical») в
``test_delta_evidence_does_not_confirm_a_pattern_for_coverage`` — строго
СИЛЬНЕЕ исходного, а не слабее: конструирует ИМЕННО опасность из решения 3
(подтверждённая узкая + неподтверждённая широкая подписки совпадают по дельте)
и доказывает, что широкая подписка не становится покрывающей.
"""

from __future__ import annotations

import threading
import time

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

# Таймаут синхронного request() — см. StateProxy._SYNC_REQUEST_TIMEOUT в
# proxy/state_proxy.py (прочитан как контекст механизма, ПИНУЕТСЯ литералом).
SYNC_REQUEST_TIMEOUT_LITERAL = 5.0
#: Грейс RouterManager._NO_PUMP_GRACE_SEC — столько (а НЕ полный таймаут)
#: стоит sync-запрос, когда приёмного цикла на роутере ещё не было.
NO_PUMP_GRACE_LITERAL = 0.5


# ---------------------------------------------------------------------------
# Двойники роутера
# ---------------------------------------------------------------------------


class _NeverRepliesRouter:
    """Роутер с живым транспортом, но БЕЗ приёмного потока на другом конце.

    Воспроизводит реальный контракт ``RouterManager``:
      - ``send_async`` — честный fire-and-forget, сообщение "в очереди" СРАЗУ;
      - ``request(msg, timeout=...)`` — блокирует ВЕСЬ переданный timeout
        (реальный round-trip, на который никогда не придёт ответ, потому что
        приёмный поток процесса ещё не создан), затем возвращает fail-open.

    ``subscribe_messages`` собирает команды ``state.subscribe`` независимо от
    того, каким методом их отправил proxy (``request`` или ``send_async``) —
    тест не навязывает реализации выбор sync/async, только наблюдаемый эффект.
    """

    def __init__(self) -> None:
        self.subscribe_messages: list[dict] = []
        self.request_calls: list[tuple[dict, float]] = []
        self.send_async_calls: list[dict] = []

    def send_async(self, msg: dict, priority: str = "normal") -> dict:
        self.send_async_calls.append(msg)
        if msg.get("command") == "state.subscribe":
            self.subscribe_messages.append(msg)
        return {"status": "success", "channel": "ctrl"}

    def request(self, msg: dict, timeout: float = 5.0, correlation_id: str | None = None) -> dict:
        self.request_calls.append((msg, timeout))
        if msg.get("command") == "state.subscribe":
            self.subscribe_messages.append(msg)
        # Н2 (ревью Ф1+Ф2): грейс, а НЕ полный таймаут — так ведёт себя
        # настоящий RouterManager.request без приёмного цикла
        # (router_manager.py:1062, _NO_PUMP_GRACE_SEC=0.5; константа была уже
        # на базе 44cb7065 — сверено git show). Прежний sleep(timeout) делал
        # фейк расходящимся с продом, и контрольный тест пинал свойство,
        # которого у прода нет: набор доказывал сам себя.
        time.sleep(min(timeout, NO_PUMP_GRACE_LITERAL))
        return {"success": False, "error": "timeout", "reason": "no_receive_pump"}


class _EchoRouter:
    """Роутер, честно и НЕМЕДЛЕННО подтверждающий любую sync-подписку.

    Контраст для _NeverRepliesRouter: сервер жив, приёмный поток есть.
    """

    def request(self, msg: dict, timeout: float = 5.0, correlation_id: str | None = None) -> dict:
        if msg.get("command") == "state.subscribe":
            return {"success": True, "result": {"status": "ok", "sub_id": f"srv-{msg['data']['pattern']}"}}
        return {"success": True, "result": {"status": "ok"}}

    def send_async(self, msg: dict, priority: str = "normal") -> dict:
        return {"status": "success"}


def _run_with_deadline(fn, deadline: float):
    """Выполнить fn() в daemon-потоке с join(deadline).

    Возвращает (finished, elapsed) — при регрессии (fn зависает) тест обязан
    УПАСТЬ по истечении deadline, а не повиснуть вместе с fn().
    """
    holder: dict = {}

    def _target():
        holder["result"] = fn()

    t = threading.Thread(target=_target, daemon=True)
    start = time.perf_counter()
    t.start()
    t.join(deadline)
    elapsed = time.perf_counter() - start
    return (not t.is_alive()), elapsed


# ---------------------------------------------------------------------------
# Twin control (обязателен по ТЗ Т.3): доказываем, что таймаут ДЕЙСТВИТЕЛЬНО
# списывается на легитимном (ждущем) пути — иначе быстрый async-тест ничего
# не доказывает (мог бы пройти по любой причине, включая сломанный роутер).
# ---------------------------------------------------------------------------


class TestSyncSubscribeChargesTimeoutControl:
    def test_sync_subscribe_blocks_for_the_full_request_timeout(self):
        router = _NeverRepliesRouter()
        proxy = StateProxy("gui", router=router, server_target="ProcessManager")
        proxy.initialize()

        finished, elapsed = _run_with_deadline(
            lambda: proxy.subscribe("processes.**", lambda _d: None, exclude_self=True, sync=True),
            deadline=SYNC_REQUEST_TIMEOUT_LITERAL + 3.0,
        )

        assert finished, (
            f"sync-подписка не завершилась даже за {SYNC_REQUEST_TIMEOUT_LITERAL + 3.0:.1f} с — "
            "контрольный (эталонный) путь сам сломан, сравнение с async-путём недостоверно"
        )
        # Н2: сравниваем с ГРЕЙСОМ, а не с полным таймаутом. Контроль не ослаб —
        # async-путь ниже укладывается в тысячные доли секунды, разрыв остаётся
        # трёхпорядковым; зато перестал пиниться несуществующий контракт.
        assert elapsed >= NO_PUMP_GRACE_LITERAL * 0.8, (
            f"sync-подписка к серверу без приёмного цикла обязана списать грейс "
            f"({NO_PUMP_GRACE_LITERAL} с), а заняла {elapsed:.2f} с — контрольный путь сам сломан"
        )
        assert elapsed < SYNC_REQUEST_TIMEOUT_LITERAL, (
            f"заняла {elapsed:.2f} с — это ПОЛНЫЙ таймаут: фейк-роутер разошёлся с контрактом "
            f"RouterManager (грейс {NO_PUMP_GRACE_LITERAL} с), и набор доказывает сам себя"
        )
        assert "processes.**" not in proxy._confirmed_patterns, (
            "сервер не подтвердил подписку (ответа не было) — паттерн не имеет права попасть в подтверждённые"
        )


# ---------------------------------------------------------------------------
# Критерий 1 — основное свойство: подписка из контекста, где ответ прийти не
# может, не должна стоить таймаут. ЗЕЛЁНЫЙ ДО РЕАЛИЗАЦИИ на уровне ПРИМИТИВА
# StateProxy.subscribe(sync=False) — этот примитив уже существует
# (Ф-GUI-read-model 0.2). Красный вариант этого же свойства — на уровне
# GuiProcess, см. multiprocess_prototype/frontend/tests/
# test_t3_gui_boot_subscribe_nonblocking.py (там GUI ещё зовёт sync=True).
# ---------------------------------------------------------------------------


class TestFourSubscriptionsDoNotBlockAtBoot:
    PATTERNS = ("processes.**", "system.**", "devices.**", "calibration.**")

    def test_four_boot_subscriptions_complete_far_below_sync_timeout(self):
        router = _NeverRepliesRouter()
        proxy = StateProxy("gui", router=router, server_target="ProcessManager")
        proxy.initialize()

        def _subscribe_all():
            for pattern in self.PATTERNS:
                proxy.subscribe(pattern, lambda _d: None, exclude_self=True, sync=False)

        finished, elapsed = _run_with_deadline(_subscribe_all, deadline=3.0)

        assert finished, (
            "четыре подписки не завершились даже за 3.0 с (эталонный больной путь стоил бы "
            f"~{4 * SYNC_REQUEST_TIMEOUT_LITERAL:.0f} с)"
        )
        assert elapsed < 1.0, (
            f"четыре подписки заняли {elapsed:.3f} с — ожидалось много меньше "
            f"{SYNC_REQUEST_TIMEOUT_LITERAL} с (таймаут ОДНОГО синхронного запроса)"
        )


# ---------------------------------------------------------------------------
# Критерий 2 — не блокировать не значит не подписаться.
# ЗЕЛЁНЫЙ ДО РЕАЛИЗАЦИИ (уже существующее свойство async-подписки).
# ---------------------------------------------------------------------------


class TestSubscriptionStillReachesServerAndCallbackFires:
    def test_async_subscribe_sends_correct_message_and_fires_callback(self):
        router = _NeverRepliesRouter()
        proxy = StateProxy("cam0", router=router, server_target="ProcessManager")
        proxy.initialize()

        received: list[Delta] = []
        proxy.subscribe(
            "cameras.0.**",
            lambda deltas: received.extend(deltas),
            exclude_self=True,
            sync=False,
        )

        assert len(router.subscribe_messages) == 1, router.subscribe_messages
        msg = router.subscribe_messages[0]
        assert msg["command"] == "state.subscribe"
        assert msg["data"]["pattern"] == "cameras.0.**"
        assert msg["data"]["subscriber"] == "cam0"
        assert msg["data"]["exclude_sources"] == ["cam0"]

        delta = Delta(path="cameras.0.config.fps", old_value=25, new_value=30, source="ProcessManager")
        proxy.on_state_changed({"command": "state.changed", "data": {"deltas": [delta.to_dict()]}})

        assert len(received) == 1, "callback подписки не сработал на матчащую дельту"
        assert received[0].path == "cameras.0.config.fps"
        assert received[0].new_value == 30


# ---------------------------------------------------------------------------
# Критерий 3 — честная бухгалтерия подтверждений.
# ---------------------------------------------------------------------------


class TestCoverageHonesty:
    def test_async_pattern_does_not_cover_narrower_pattern(self):
        """ЗЕЛЁНЫЙ ДО РЕАЛИЗАЦИИ: неподтверждённый (async) паттерн уже сегодня
        не считается покрывающим — регрессия здесь была бы РЕГРЕССОМ, не новой фичей.
        """
        router = _NeverRepliesRouter()
        proxy = StateProxy("gui", router=router, server_target="ProcessManager")
        proxy.initialize()

        proxy.subscribe("processes.**", lambda _d: None, exclude_self=True, sync=False)
        before = len(router.subscribe_messages)

        proxy.ensure_subscription("processes.cam0.**", lambda _d: None, exclude_self=True)
        after = len(router.subscribe_messages)

        assert after == before + 1, (
            "неподтверждённый широкий паттерн 'processes.**' не должен был 'усыновить' "
            f"'processes.cam0.**' без собственного state.subscribe (before={before}, after={after})"
        )

    def test_confirmed_pattern_count_is_readable_from_outside(self):
        """КРАСНЫЙ: публичного счётчика подтверждённых паттернов сегодня нет.

        Ожидаемая ошибка — AttributeError на 'confirmed_pattern_count' (символ
        отсутствует в реализации). Имя — дизайн-решение тестера (см. докстринг
        модуля), не факт из кода.
        """
        proxy = StateProxy("gui", router=_EchoRouter(), server_target="ProcessManager")
        proxy.initialize()

        assert proxy.confirmed_pattern_count == 0, "до первой подтверждённой подписки счётчик обязан быть 0"

        proxy.subscribe("processes.**", lambda _d: None, exclude_self=True, sync=True)

        assert proxy.confirmed_pattern_count == 1, (
            "после успешного sync-subscribe с ack от сервера подтверждённых паттернов должно "
            "стать 1 — оператор обязан видеть это БЕЗ обращения к приватным полям"
        )

    def test_delta_evidence_does_not_confirm_a_pattern_for_coverage(self):
        """Реализация ЗАКРЫЛА условный вариант критерия 3 (см. Task Т.3, решение 3
        в постановке — plans/observation-port/plan.md): подтверждение паттерна для
        coverage-check остаётся СТРОГО server-ack-only, приход дельты НЕ
        подтверждает паттерн. Это усиление исходного (условного) теста, а не
        ослабление: было «зелёный ЕСЛИ реализация выберет evidence-based» — стало
        «зелёный, потому что evidence-based here считается дефектом, и тест это
        доказывает инъекцией конкретного механизма».

        Причина запрета названа явно в ТЗ и воспроизводится здесь: конверт
        ``state.changed`` не несёт ``sub_id`` (см. ``StateProxy.on_state_changed``,
        ``_deserialize_deltas`` — дельта знает path/old/new/source, но НЕ то, какая
        подписка её вызвала). Дельта, попавшая под широкий async-паттерн, могла в
        реальности быть порождена СОВСЕМ ДРУГОЙ, более узкой подпиской — сервер
        рассылает дельты по адресату (``targets``), а не по подписке-источнику.
        Если бы приход такой дельты подтверждал широкий паттерн как покрывающий,
        `_find_covering_pattern` начал бы считать его источником потока для всех
        более узких паттернов — включая те, на которые сервер в реальности НИКОГДА
        не создавал подписку для этого широкого паттерна, — и последующий
        `ensure_subscription` на них тихо пропустил бы РЕАЛЬНО нужный
        `state.subscribe`. Ровно этот сценарий и воспроизводит тест ниже: узкая
        `processes.cam0.state.status` подтверждена СВОЕЙ отдельной sync-подпиской
        (легитимный источник дельты), широкая `processes.**` остаётся
        неподтверждённой async-подпиской; после того как та же дельта прогоняется
        через `on_state_changed` (что при evidence-based подтверждении «доказало»
        бы широкий паттерн), повторный `ensure_subscription` на ДРУГОЙ узкий
        паттерн (`processes.cam1.**`, для которого своей подписки ещё нет) обязан
        уйти на сервер — если бы широкий паттерн тихо стал покрывающим, эта
        строка нашла бы мнимое покрытие и не отправила бы нужный state.subscribe.
        """
        router = _NeverRepliesRouter()
        proxy = StateProxy("gui", router=router, server_target="ProcessManager")
        proxy.initialize()

        # Легитимный источник дельты: узкая подписка ДЕЙСТВИТЕЛЬНО подтверждена
        # сервером (echo-роутер вернул бы sub_id; здесь важно, что confirmed).
        echo_proxy_confirms = StateProxy("gui-confirm-helper", router=_EchoRouter(), server_target="ProcessManager")
        echo_proxy_confirms.initialize()
        echo_proxy_confirms.subscribe("processes.cam0.state.status", lambda _d: None, exclude_self=True, sync=True)
        assert "processes.cam0.state.status" in echo_proxy_confirms._confirmed_patterns

        # Широкий паттерн — async, сервер НЕ подтвердил (as в проде GUI, Task Т.3).
        proxy.subscribe("processes.**", lambda _d: None, exclude_self=True, sync=False)
        assert "processes.**" not in proxy._confirmed_patterns

        # Дельта, которая матчит и узкий (реальный источник), и широкий паттерн —
        # неотличимая по конверту от «пришла благодаря широкому».
        delta = Delta(path="processes.cam0.state.status", old_value=None, new_value="running", source="cam0")
        proxy.on_state_changed({"command": "state.changed", "data": {"deltas": [delta.to_dict()]}})

        # Широкий паттерн ОБЯЗАН остаться неподтверждённым — дельта не сервер-ack.
        assert "processes.**" not in proxy._confirmed_patterns, (
            "приход дельты не должен добавлять паттерн в _confirmed_patterns — "
            "конверт state.changed не несёт sub_id, дельта могла прийти от чужой подписки"
        )

        before = len(router.subscribe_messages)
        proxy.ensure_subscription("processes.cam1.**", lambda _d: None, exclude_self=True)
        after = len(router.subscribe_messages)

        assert after == before + 1, (
            "processes.cam1.** не имеет собственной подписки и не покрыт НИЧЕМ "
            "подтверждённым — 'processes.**' не имеет права выступить покрывающим "
            f"на основании дельты-свидетельства (before={before}, after={after})"
        )
