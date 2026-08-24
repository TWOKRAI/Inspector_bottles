"""Т.3 (plans/observation-port/plan.md) — acceptance-тесты НЕЗАВИСИМОГО тестера
для GuiProcess._init_application_threads.

КРАСНЫЙ по конструкции: на момент написания ``GuiProcess._init_application_threads``
(``multiprocess_prototype/frontend/process.py``) зовёт
``self._gui_state_proxy.subscribe(pattern, cb, exclude_self=True)`` БЕЗ
``sync=False`` — то есть sync=True по умолчанию — а приёмный поток
(``data_receiver`` worker) создаётся ПОСЛЕ этого блока. С роутером, который
никогда не отвечает (как на реальном старте GUI, где отвечать некому), это
стоит четыре полных таймаута request() подряд — измерено на живом стенде:
20.03 с до несвязанного grace-фикса, 2.02 с после (см. контекст ТЗ Т.3);
в ОБОИХ замерах подтверждённых паттернов было 0.

Тест использует РЕАЛЬНЫЕ StateProxy/GuiStateProxy (только роутер — двойник) —
в отличие от существующего ``TestGuiProcessSubscriptions`` в
``test_gui_process.py``, который патчит ``GuiStateProxy.subscribe`` целиком и
поэтому не может увидеть ни блокировку, ни реальную форму IPC-сообщения.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

# Таймаут синхронного request() — StateProxy._SYNC_REQUEST_TIMEOUT (прочитан
# как контекст механизма, пинуется литералом, не читается из атрибута класса).
SYNC_REQUEST_TIMEOUT_LITERAL = 5.0
EXPECTED_PATTERNS = {"processes.**", "system.**", "devices.**", "calibration.**"}


class _NeverRepliesRouter:
    """Роутер с живым транспортом, но без приёмного потока на другом конце.

    Как на реальном старте GUI: send_async кладёт сообщение в очередь СРАЗУ,
    request() честно блокирует на весь timeout (ответа не будет никогда — тот
    же приёмный поток, который должен был бы его разобрать, ещё не создан).
    """

    def __init__(self) -> None:
        self.subscribe_messages: list[dict] = []

    def send_async(self, msg: dict, priority: str = "normal") -> dict:
        if msg.get("command") == "state.subscribe":
            self.subscribe_messages.append(msg)
        return {"status": "success", "channel": "ctrl"}

    def request(self, msg: dict, timeout: float = 5.0, correlation_id: str | None = None) -> dict:
        if msg.get("command") == "state.subscribe":
            self.subscribe_messages.append(msg)
        time.sleep(timeout)
        return {"success": False, "error": "timeout"}

    def register_message_handler(self, *args, **kwargs) -> None:
        pass


def _run_with_deadline(fn, deadline: float):
    """Выполнить fn() в daemon-потоке с join(deadline).

    При регрессии (fn зависает) тест ОБЯЗАН упасть по истечении deadline, а не
    повиснуть вместе с fn() — таймаут теста не маскирует таймаут кода.
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


def _make_mock_shared_resources() -> MagicMock:
    """Минимальный mock shared_resources для ProcessModule (см. test_gui_process.py)."""
    sr = MagicMock()
    sr.get_process_data.return_value = None
    sr.update_process_state.return_value = None
    sr.get_system_stop_event.return_value = None
    sr.process_state_registry = MagicMock()
    sr.process_state_registry.register.return_value = None
    sr.process_state_registry.update.return_value = None
    return sr


def _make_gui_process(router: _NeverRepliesRouter):
    from multiprocess_prototype.frontend.process import GuiProcess

    sr = _make_mock_shared_resources()
    process = GuiProcess(name="gui", shared_resources=sr)
    process.worker_manager = MagicMock()
    process.router_manager = router
    return process


# ---------------------------------------------------------------------------
# Twin control (обязателен по ТЗ Т.3, в ТОМ ЖЕ файле): подписка, форсированная
# в sync=True режиме против недостижимого сервера, ДЕЙСТВИТЕЛЬНО стоит полный
# таймаут — иначе быстрый результат основного теста ничего не доказывает.
# ---------------------------------------------------------------------------


class TestSyncPathControl:
    def test_forced_sync_subscribe_against_gui_state_proxy_blocks_full_timeout(self):
        from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import GuiStateProxy

        router = _NeverRepliesRouter()
        proxy = GuiStateProxy("gui", router=router, server_target="ProcessManager")
        proxy.initialize()

        finished, elapsed = _run_with_deadline(
            lambda: proxy.subscribe("processes.**", lambda _d: None, exclude_self=True, sync=True),
            deadline=SYNC_REQUEST_TIMEOUT_LITERAL + 3.0,
        )

        assert finished, f"контрольная sync-подписка не завершилась даже за {SYNC_REQUEST_TIMEOUT_LITERAL + 3.0:.1f} с"
        assert elapsed >= SYNC_REQUEST_TIMEOUT_LITERAL - 0.5, (
            f"sync-подписка GuiStateProxy к недостижимому серверу обязана стоить полный "
            f"таймаут ({SYNC_REQUEST_TIMEOUT_LITERAL} с), заняла {elapsed:.2f} с — "
            "контроль недостоверен"
        )


# ---------------------------------------------------------------------------
# Критерии 1 + 4 — основной красный тест.
# ---------------------------------------------------------------------------


class TestGuiBootSubscriptionsDoNotBlock:
    def test_four_boot_subscriptions_do_not_charge_a_request_timeout(self):
        router = _NeverRepliesRouter()
        process = _make_gui_process(router)

        finished, elapsed = _run_with_deadline(process._init_application_threads, deadline=3.0)

        assert finished, (
            "_init_application_threads не завершился даже за 3.0 с — при старте GUI на "
            f"недостижимом сервере эталонный больной путь стоил бы ~{4 * SYNC_REQUEST_TIMEOUT_LITERAL:.0f} с "
            "(измерено на живом стенде: 20.03 с); подписки всё ещё блокируют поток, "
            "хотя приёмный поток на этот момент ещё не создан и ответить некому"
        )
        assert elapsed < 1.0, (
            f"четыре стартовые подписки GUI заняли {elapsed:.3f} с — ожидалось значительно "
            f"меньше одного таймаута синхронного запроса ({SYNC_REQUEST_TIMEOUT_LITERAL} с)"
        )

    def test_four_boot_subscriptions_still_reach_the_router_with_right_shape(self):
        router = _NeverRepliesRouter()
        process = _make_gui_process(router)

        finished, _elapsed = _run_with_deadline(process._init_application_threads, deadline=3.0)
        assert finished, "см. test_four_boot_subscriptions_do_not_charge_a_request_timeout — метод обязан вернуться"

        subs = router.subscribe_messages
        assert len(subs) == 4, f"ожидалось ровно 4 state.subscribe, получено {len(subs)}: {subs}"

        patterns_seen = {m["data"]["pattern"] for m in subs}
        assert patterns_seen == EXPECTED_PATTERNS, f"неверный набор паттернов: {patterns_seen}"

        for m in subs:
            assert m["command"] == "state.subscribe", m
            assert m["data"]["subscriber"] == "gui", m
            assert m["data"]["exclude_sources"] == ["gui"], (
                f"exclude_sources для '{m['data']['pattern']}' должен быть ['gui'] (exclude_self=True), "
                f"получено {m['data']['exclude_sources']}"
            )
