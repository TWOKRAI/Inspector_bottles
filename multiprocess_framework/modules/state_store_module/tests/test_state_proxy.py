"""Тесты для StateProxy и GuiStateProxy.

Все тесты работают без реального RouterManager — используется MockRouter.
Интеграционные тесты используют StateStoreManager напрямую.
GuiStateProxy тестируется без Qt через fallback-режим (delta_sink=None).
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import GuiStateProxy


# ---------------------------------------------------------------------------
# MockRouter — мок RouterManager для тестов
# ---------------------------------------------------------------------------


class MockRouter:
    """Мок RouterManager для тестов StateProxy."""

    def __init__(self):
        self.sent: list[dict] = []
        self.handlers: dict[str, object] = {}
        # Для синхронных ответов: command → ответный dict
        self._sync_responses: dict[str, dict] = {}

    def send_async(self, msg, priority="normal"):
        """Сохраняет сообщение в списке sent."""
        self.sent.append(msg if isinstance(msg, dict) else msg)

    def send(self, msg) -> dict:
        """Синхронная отправка. Возвращает настроенный ответ или success."""
        self.sent.append(msg if isinstance(msg, dict) else msg)
        command = msg.get("command", "")
        if command in self._sync_responses:
            return self._sync_responses[command]
        return {"status": "success"}

    def register_message_handler(self, key, handler, **kwargs):
        """Регистрирует обработчик."""
        self.handlers[key] = handler

    def set_sync_response(self, command: str, response: dict) -> None:
        """Настроить синхронный ответ для команды (для тестов)."""
        self._sync_responses[command] = response

    def last_sent(self, command: str | None = None) -> dict | None:
        """Вернуть последнее отправленное сообщение (фильтр по command)."""
        if command is None:
            return self.sent[-1] if self.sent else None
        for msg in reversed(self.sent):
            if isinstance(msg, dict) and msg.get("command") == command:
                return msg
        return None


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_state_changed_msg(deltas: list[Delta]) -> dict:
    """Создать IPC-сообщение state.changed из списка дельт."""
    return {
        "command": "state.changed",
        "data": {
            "deltas": [d.to_dict() for d in deltas],
        },
    }


def _make_delta(path="cameras.0.config.fps", old=MISSING, new=30, source="gui") -> Delta:
    """Создать тестовую Delta."""
    return Delta(path=path, old_value=old, new_value=new, source=source)


def _make_mock_logger(warnings_sink: list[str]):
    """Mock-logger, складывающий warning-сообщения в указанный список.

    StateProxy использует ObservableMixin, который вызывает
    `manager.warning(...)` или `manager.log_warning(...)` на переданном logger.
    Достаточно реализовать оба интерфейса.
    """

    class _Logger:
        def warning(self, msg, *args, **kwargs):
            warnings_sink.append(msg if not args else msg % args)

        def log_warning(self, msg, *args, **kwargs):
            self.warning(msg, *args, **kwargs)

        # Остальные уровни — no-op
        def info(self, *a, **kw):
            pass

        def debug(self, *a, **kw):
            pass

        def error(self, *a, **kw):
            pass

        def log_info(self, *a, **kw):
            pass

        def log_debug(self, *a, **kw):
            pass

        def log_error(self, *a, **kw):
            pass

    return _Logger()


# ===========================================================================
# Тесты StateProxy — инициализация
# ===========================================================================


class TestStateProxyInit:
    """Инициализация и базовые свойства StateProxy."""

    def test_init_default(self):
        """Создание с настройками по умолчанию."""
        proxy = StateProxy("camera_0")
        assert proxy.process_name == "camera_0"
        assert proxy.cache == {}

    def test_init_with_router(self):
        """Создание с router."""
        router = MockRouter()
        proxy = StateProxy("gui", router=router)
        assert proxy.process_name == "gui"

    def test_cache_empty_on_init(self):
        """Кэш пуст после создания."""
        proxy = StateProxy("test_process")
        assert len(proxy.cache) == 0


# ===========================================================================
# Тесты StateProxy — запись (set, merge)
# ===========================================================================


class TestStateProxyWrite:
    """Тесты методов set и merge."""

    def test_set_sends_ipc_message(self):
        """set() отправляет IPC-сообщение state.set через router."""
        router = MockRouter()
        proxy = StateProxy("camera_0", router=router)

        proxy.set("cameras.0.state.fps", 28.5)

        assert len(router.sent) == 1
        msg = router.sent[0]
        assert msg["command"] == "state.set"
        assert msg["data"]["path"] == "cameras.0.state.fps"
        assert msg["data"]["value"] == 28.5
        assert msg["data"]["source"] == "camera_0"

    def test_set_message_format(self):
        """set() формирует корректный IPC-формат сообщения."""
        router = MockRouter()
        proxy = StateProxy("camera_0", router=router)

        proxy.set("cameras.0.config.fps", 30)

        msg = router.sent[0]
        assert msg["type"] == "command"
        assert msg["sender"] == "camera_0"
        assert msg["targets"] == ["ProcessManager"]

    def test_set_no_router_no_error(self):
        """set() без router не бросает исключений."""
        proxy = StateProxy("camera_0", router=None)
        proxy.set("cameras.0.config.fps", 30)  # должно молча игнорироваться

    def test_merge_sends_ipc_message(self):
        """merge() отправляет IPC-сообщение state.merge через router."""
        router = MockRouter()
        proxy = StateProxy("recipe_engine", router=router)

        proxy.merge("cameras.0.config", {"fps": 30, "type": "usb"})

        assert len(router.sent) == 1
        msg = router.sent[0]
        assert msg["command"] == "state.merge"
        assert msg["data"]["path"] == "cameras.0.config"
        assert msg["data"]["data"] == {"fps": 30, "type": "usb"}
        assert msg["data"]["source"] == "recipe_engine"

    def test_merge_message_format(self):
        """merge() формирует корректный IPC-формат."""
        router = MockRouter()
        proxy = StateProxy("gui", router=router)

        proxy.merge("system", {"status": "ok"})

        msg = router.sent[0]
        assert msg["type"] == "command"
        assert msg["targets"] == ["ProcessManager"]


# ===========================================================================
# Тесты StateProxy — чтение (get, get_subtree)
# ===========================================================================


class TestStateProxyRead:
    """Тесты методов get и get_subtree."""

    def test_get_from_cache(self):
        """get() возвращает значение из кэша."""
        proxy = StateProxy("camera_0")
        # Наполняем кэш через on_state_changed
        delta = _make_delta(path="cameras.0.config.fps", new=30)
        proxy.on_state_changed(_make_state_changed_msg([delta]))

        result = proxy.get("cameras.0.config.fps")
        assert result == 30

    def test_get_default_when_not_in_cache_no_router(self):
        """get() с default возвращает default если нет в кэше и router=None."""
        proxy = StateProxy("camera_0", router=None)
        result = proxy.get("cameras.0.config.fps", default=25)
        assert result == 25

    def test_get_raises_keyerror_no_cache_no_router(self):
        """get() без default и без router бросает KeyError."""
        proxy = StateProxy("camera_0", router=None)
        try:
            proxy.get("cameras.0.config.fps")
            assert False, "Должна быть KeyError"
        except KeyError:
            pass

    def test_get_ipc_fallback(self):
        """get() при промахе кэша делает IPC-запрос state.get."""
        router = MockRouter()
        router.set_sync_response("state.get", {"status": "ok", "value": 42})
        proxy = StateProxy("camera_0", router=router)

        result = proxy.get("cameras.0.config.fps", default=0)

        assert result == 42
        # Проверяем что был отправлен запрос
        msg = router.last_sent("state.get")
        assert msg is not None
        assert msg["data"]["path"] == "cameras.0.config.fps"

    def test_get_ipc_fallback_uses_default_on_error(self):
        """get() использует default при ошибочном IPC-ответе."""
        router = MockRouter()
        router.set_sync_response("state.get", {"status": "error", "error": "not found"})
        proxy = StateProxy("camera_0", router=router)

        result = proxy.get("cameras.0.config.fps", default=99)
        assert result == 99

    def test_get_subtree_ipc_call(self):
        """get_subtree() отправляет IPC-запрос state.get_subtree."""
        router = MockRouter()
        router.set_sync_response(
            "state.get_subtree",
            {"status": "ok", "value": {"fps": 30, "type": "webcam"}},
        )
        proxy = StateProxy("gui", router=router)

        result = proxy.get_subtree("cameras.0.config")

        assert result == {"fps": 30, "type": "webcam"}
        msg = router.last_sent("state.get_subtree")
        assert msg is not None
        assert msg["data"]["path"] == "cameras.0.config"

    def test_get_subtree_no_router_returns_empty(self):
        """get_subtree() без router возвращает пустой dict."""
        proxy = StateProxy("camera_0", router=None)
        result = proxy.get_subtree("cameras.0")
        assert result == {}


# ===========================================================================
# Тесты StateProxy — подписки
# ===========================================================================


class TestStateProxySubscribe:
    """Тесты методов subscribe и unsubscribe."""

    def test_subscribe_sends_ipc(self):
        """subscribe() отправляет state.subscribe в IPC."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "test-sub-1"})
        proxy = StateProxy("camera_0", router=router)

        def callback(deltas):
            pass

        sub_id = proxy.subscribe("cameras.0.config.*", callback)

        assert sub_id == "test-sub-1"
        msg = router.last_sent("state.subscribe")
        assert msg is not None
        assert msg["data"]["pattern"] == "cameras.0.config.*"
        assert msg["data"]["subscriber"] == "camera_0"

    def test_subscribe_exclude_self_true(self):
        """subscribe(exclude_self=True) → exclude_sources содержит имя процесса."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        proxy.subscribe("cameras.**", lambda d: None, exclude_self=True)

        msg = router.last_sent("state.subscribe")
        assert "camera_0" in msg["data"]["exclude_sources"]

    def test_subscribe_exclude_self_false(self):
        """subscribe(exclude_self=False) → exclude_sources пуст."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        proxy.subscribe("cameras.**", lambda d: None, exclude_self=False)

        msg = router.last_sent("state.subscribe")
        assert msg["data"]["exclude_sources"] == []

    def test_subscribe_returns_sub_id(self):
        """subscribe() возвращает sub_id."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "my-sub-id"})
        proxy = StateProxy("gui", router=router)

        sub_id = proxy.subscribe("cameras.*", lambda d: None)
        assert sub_id == "my-sub-id"

    def test_subscribe_no_router_returns_local_id(self):
        """subscribe() без router возвращает локально сгенерированный sub_id."""
        proxy = StateProxy("camera_0", router=None)
        sub_id = proxy.subscribe("cameras.*", lambda d: None)
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    def test_subscribe_warns_on_server_error(self):
        """Если сервер вернул error — выдаём warning, sub_id всё равно создаётся локально."""
        warnings: list[str] = []
        logger = _make_mock_logger(warnings)
        router = MockRouter()
        router.set_sync_response(
            "state.subscribe",
            {"status": "error", "error": "broken"},
        )
        proxy = StateProxy("camera_0", router=router, logger=logger)
        sub_id = proxy.subscribe("cameras.*", lambda d: None)
        assert isinstance(sub_id, str) and len(sub_id) > 0
        assert any("cameras.*" in w for w in warnings), warnings

    def test_subscribe_warns_on_missing_sub_id(self):
        """Сервер ответил ok, но без sub_id — тоже warning (контракт нарушен)."""
        warnings: list[str] = []
        logger = _make_mock_logger(warnings)
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok"})  # без sub_id
        proxy = StateProxy("camera_0", router=router, logger=logger)
        proxy.subscribe("cameras.*", lambda d: None)
        assert any("sub_id" in w for w in warnings), warnings

    def test_subscribe_warns_on_none_response(self):
        """router.send вернул None — warning «не подтверждена сервером»."""
        warnings: list[str] = []
        logger = _make_mock_logger(warnings)
        router = MockRouter()

        # Отвечаем явно None для state.subscribe
        def _send_returning_none(msg):
            router.sent.append(msg)
            return None

        router.send = _send_returning_none  # type: ignore[method-assign]
        proxy = StateProxy("camera_0", router=router, logger=logger)
        proxy.subscribe("cameras.*", lambda d: None)
        assert any("response=None" in w or "не подтверждена" in w for w in warnings), warnings

    def test_unsubscribe_sends_ipc(self):
        """unsubscribe() отправляет state.unsubscribe в IPC."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        proxy.subscribe("cameras.*", lambda d: None)
        router.sent.clear()

        proxy.unsubscribe("sub-1")

        msg = router.last_sent("state.unsubscribe")
        assert msg is not None
        assert msg["data"]["sub_id"] == "sub-1"

    def test_unsubscribe_removes_local_callback(self):
        """unsubscribe() удаляет локальный callback."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        called = []
        proxy.subscribe("cameras.*", lambda d: called.append(d))

        # Отписываемся
        proxy.unsubscribe("sub-1")

        # Имитируем state.changed — callback не должен вызваться
        delta = _make_delta()
        proxy.on_state_changed(_make_state_changed_msg([delta]))
        assert called == []


# ===========================================================================
# Тесты StateProxy — обработка входящих
# ===========================================================================


class TestStateProxyOnStateChanged:
    """Тесты on_state_changed: кэш + callbacks."""

    def test_on_state_changed_updates_cache(self):
        """on_state_changed() обновляет кэш из дельт."""
        proxy = StateProxy("camera_0")
        delta = _make_delta(path="cameras.0.config.fps", new=30)
        proxy.on_state_changed(_make_state_changed_msg([delta]))

        assert proxy.cache["cameras.0.config.fps"] == 30

    def test_on_state_changed_multiple_deltas(self):
        """on_state_changed() обрабатывает несколько дельт."""
        proxy = StateProxy("camera_0")
        deltas = [
            _make_delta(path="cameras.0.config.fps", new=30),
            _make_delta(path="cameras.0.config.type", new="webcam"),
        ]
        proxy.on_state_changed(_make_state_changed_msg(deltas))

        assert proxy.cache["cameras.0.config.fps"] == 30
        assert proxy.cache["cameras.0.config.type"] == "webcam"

    def test_on_state_changed_delete_removes_from_cache(self):
        """on_state_changed() с MISSING new_value удаляет из кэша."""
        proxy = StateProxy("camera_0")

        # Сначала добавляем в кэш
        create_delta = _make_delta(path="cameras.0.config.fps", new=30)
        proxy.on_state_changed(_make_state_changed_msg([create_delta]))
        assert "cameras.0.config.fps" in proxy.cache

        # Теперь удаляем
        delete_delta = Delta(
            path="cameras.0.config.fps",
            old_value=30,
            new_value=MISSING,
            source="gui",
        )
        proxy.on_state_changed(_make_state_changed_msg([delete_delta]))
        assert "cameras.0.config.fps" not in proxy.cache

    def test_on_state_changed_invokes_callback(self):
        """on_state_changed() вызывает зарегистрированные callbacks."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        received: list[list[Delta]] = []
        proxy.subscribe("cameras.**", lambda deltas: received.append(deltas))

        delta = _make_delta()
        proxy.on_state_changed(_make_state_changed_msg([delta]))

        assert len(received) == 1
        assert received[0][0].path == "cameras.0.config.fps"

    def test_on_state_changed_empty_msg_no_error(self):
        """on_state_changed() с пустым/невалидным msg не бросает исключений."""
        proxy = StateProxy("camera_0")
        proxy.on_state_changed({})  # без data — молча игнорируется
        proxy.on_state_changed({"data": {}})  # без deltas — молча игнорируется
        proxy.on_state_changed({"data": {"deltas": []}})  # пустые deltas

    def test_on_state_changed_callback_exception_no_crash(self):
        """Исключение в callback не ломает обработку остальных."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        called_after = []

        def bad_callback(deltas):
            raise RuntimeError("плохой callback")

        def good_callback(deltas):
            called_after.append(deltas)

        # Добавляем два callback
        proxy._callbacks["sub-1"] = [bad_callback, good_callback]
        proxy._sub_ids.append("sub-1")

        delta = _make_delta()
        # Не должно бросить исключение
        proxy.on_state_changed(_make_state_changed_msg([delta]))

        # good_callback всё равно был вызван
        assert len(called_after) == 1


# ===========================================================================
# Тесты StateProxy — фильтрация callbacks по pattern подписки
# ===========================================================================


class TestStateProxyCallbackFiltering:
    """Каждый callback получает ТОЛЬКО дельты, чьи path матчат его pattern."""

    @staticmethod
    def _make_proxy_with_subs(*patterns: str) -> tuple[StateProxy, MockRouter, dict]:
        """Создать StateProxy с подписками на указанные patterns.

        Возвращает (proxy, router, received) — received: pattern -> list[list[Delta]].
        """
        router = MockRouter()
        proxy = StateProxy("camera_0", router=router)
        received: dict[str, list[list[Delta]]] = {p: [] for p in patterns}

        for i, pattern in enumerate(patterns):
            sub_id = f"sub-{i}"
            router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": sub_id})
            proxy.subscribe(pattern, lambda d, p=pattern: received[p].append(d))

        return proxy, router, received

    def test_callback_receives_only_matching_deltas(self):
        """Callback с pattern 'cameras.0.*' не должен получать дельты renderer.*"""
        proxy, _router, received = self._make_proxy_with_subs("cameras.0.*", "renderer.*")

        deltas = [
            _make_delta(path="cameras.0.fps", new=30),
            _make_delta(path="renderer.alpha", new=0.5),
        ]
        proxy.on_state_changed(_make_state_changed_msg(deltas))

        # cameras.0.* видит только cameras.0.fps
        assert len(received["cameras.0.*"]) == 1
        assert [d.path for d in received["cameras.0.*"][0]] == ["cameras.0.fps"]

        # renderer.* видит только renderer.alpha
        assert len(received["renderer.*"]) == 1
        assert [d.path for d in received["renderer.*"][0]] == ["renderer.alpha"]

    def test_callback_not_called_when_no_match(self):
        """Callback не вызывается, если в пакете нет дельт под его pattern."""
        proxy, _router, received = self._make_proxy_with_subs("renderer.*")

        # Только cameras.* — для renderer.* совпадений нет
        proxy.on_state_changed(_make_state_changed_msg([_make_delta(path="cameras.0.fps", new=30)]))

        assert received["renderer.*"] == []

    def test_double_star_pattern_matches_all(self):
        """Pattern '**' (или 'cameras.**') совпадает со всеми вложенными путями."""
        proxy, _router, received = self._make_proxy_with_subs("cameras.**")

        deltas = [
            _make_delta(path="cameras.0.config.fps", new=30),
            _make_delta(path="cameras.1.state.actual_fps", new=29.7),
            _make_delta(path="renderer.alpha", new=0.5),
        ]
        proxy.on_state_changed(_make_state_changed_msg(deltas))

        # cameras.** ловит обе cameras-дельты, не ловит renderer
        assert len(received["cameras.**"]) == 1
        paths = [d.path for d in received["cameras.**"][0]]
        assert paths == ["cameras.0.config.fps", "cameras.1.state.actual_fps"]

    def test_legacy_callback_without_pattern_receives_all(self):
        """Если pattern для sub_id не сохранён (ручная регистрация) — без фильтрации.

        Это сохраняет совместимость с тестами и сценариями, где callbacks
        добавляются напрямую в _callbacks (см. test_on_state_changed_callback_exception).
        """
        proxy = StateProxy("camera_0")
        received: list[list[Delta]] = []
        proxy._callbacks["manual-sub"] = [lambda d: received.append(d)]
        # Намеренно НЕ заполняем _sub_patterns

        deltas = [
            _make_delta(path="cameras.0.fps", new=30),
            _make_delta(path="renderer.alpha", new=0.5),
        ]
        proxy.on_state_changed(_make_state_changed_msg(deltas))

        # Без pattern — callback получил все дельты (legacy-режим)
        assert len(received) == 1
        assert len(received[0]) == 2


# ===========================================================================
# Тесты StateProxy — lifecycle
# ===========================================================================


class TestStateProxyLifecycle:
    """Тесты shutdown."""

    def test_shutdown_sends_unsubscribe_all(self):
        """shutdown() отправляет state.unsubscribe_all в IPC."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        proxy.subscribe("cameras.*", lambda d: None)
        router.sent.clear()

        proxy.shutdown()

        msg = router.last_sent("state.unsubscribe_all")
        assert msg is not None
        assert msg["data"]["subscriber"] == "camera_0"

    def test_shutdown_clears_callbacks(self):
        """shutdown() очищает локальный реестр callbacks."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "sub-1"})
        proxy = StateProxy("camera_0", router=router)

        proxy.subscribe("cameras.*", lambda d: None)
        assert len(proxy._callbacks) == 1

        proxy.shutdown()
        assert len(proxy._callbacks) == 0
        assert len(proxy._sub_ids) == 0

    def test_shutdown_no_router_no_error(self):
        """shutdown() без router не бросает исключений."""
        proxy = StateProxy("camera_0", router=None)
        proxy.shutdown()  # должно молча работать


# ===========================================================================
# Тесты GuiStateProxy
# ===========================================================================


class TestGuiStateProxy:
    """Тесты GuiStateProxy в fallback-режиме (без Qt)."""

    def test_gui_proxy_init(self):
        """GuiStateProxy создаётся без ошибок."""
        proxy = GuiStateProxy("gui", router=None, delta_sink=None)
        assert proxy.process_name == "gui"

    def test_gui_proxy_inherits_state_proxy(self):
        """GuiStateProxy является подклассом StateProxy."""
        proxy = GuiStateProxy("gui")
        assert isinstance(proxy, StateProxy)

    def test_gui_proxy_fallback_calls_callback(self):
        """GuiStateProxy без delta_sink вызывает локальные callbacks напрямую (fallback)."""
        proxy = GuiStateProxy("gui", router=None, delta_sink=None)

        received: list[list[Delta]] = []
        # Добавляем callback вручную (без IPC subscribe)
        proxy._callbacks["test-sub"] = [lambda d: received.append(d)]

        delta = _make_delta()
        proxy.on_state_changed(_make_state_changed_msg([delta]))

        assert len(received) == 1
        assert received[0][0].path == "cameras.0.config.fps"

    def test_gui_proxy_delta_sink_receives_deltas(self):
        """GuiStateProxy с delta_sink передаёт дельты в sink (не в локальные callbacks)."""
        sink_deltas: list[list[Delta]] = []
        local_called: list = []
        proxy = GuiStateProxy("gui", router=None, delta_sink=lambda d: sink_deltas.append(d))
        # Локальный callback не должен вызываться, когда задан delta_sink
        proxy._callbacks["test-sub"] = [lambda d: local_called.append(d)]

        delta = _make_delta(path="system.status", new="running")
        proxy.on_state_changed(_make_state_changed_msg([delta]))

        assert len(sink_deltas) == 1
        assert sink_deltas[0][0].path == "system.status"
        assert local_called == []
        # кэш обновлён независимо от пути доставки
        assert proxy.cache["system.status"] == "running"

    def test_gui_proxy_updates_cache(self):
        """GuiStateProxy обновляет кэш в on_state_changed."""
        proxy = GuiStateProxy("gui", router=None)

        delta = _make_delta(path="system.status", new="running")
        proxy.on_state_changed(_make_state_changed_msg([delta]))

        assert proxy.cache["system.status"] == "running"

    def test_gui_proxy_set_inherited(self):
        """GuiStateProxy наследует set() от StateProxy."""
        router = MockRouter()
        proxy = GuiStateProxy("gui", router=router)

        proxy.set("cameras.0.config.fps", 30)

        msg = router.last_sent("state.set")
        assert msg is not None
        assert msg["data"]["value"] == 30

    def test_gui_proxy_subscribe_inherited(self):
        """GuiStateProxy наследует subscribe() от StateProxy."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "gui-sub-1"})
        proxy = GuiStateProxy("gui", router=router)

        sub_id = proxy.subscribe("cameras.**", lambda d: None)
        assert sub_id == "gui-sub-1"

    def test_gui_proxy_shutdown_inherited(self):
        """GuiStateProxy наследует shutdown() от StateProxy."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "gui-sub-1"})
        proxy = GuiStateProxy("gui", router=router)

        proxy.subscribe("cameras.*", lambda d: None)
        router.sent.clear()

        proxy.shutdown()

        msg = router.last_sent("state.unsubscribe_all")
        assert msg is not None


# ===========================================================================
# Интеграционные тесты: StateProxy + StateStoreManager
# ===========================================================================


class TestStateProxyIntegration:
    """Интеграционные тесты: proxy <-> manager в одном процессе."""

    def _build_pair(self):
        """Создать связку proxy + manager с общим MockRouter."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.initialize()
        proxy = StateProxy("camera_0", router=router)
        return proxy, mgr, router

    def test_proxy_set_reaches_manager(self):
        """proxy.set() → manager.handle_state_set() → значение в TreeStore."""
        proxy, mgr, router = self._build_pair()

        proxy.set("cameras.0.config.fps", 30)

        # Получаем сообщение и скармливаем менеджеру
        msg = router.last_sent("state.set")
        assert msg is not None
        result = mgr.handle_state_set(msg)
        assert result["status"] == "ok"
        assert mgr.store.get("cameras.0.config.fps") == 30

    def test_proxy_subscribe_and_receive_change(self):
        """Полный цикл: subscribe → set → state.changed → on_state_changed."""
        proxy, mgr, router = self._build_pair()

        received: list[list[Delta]] = []

        # Подписываемся через менеджер напрямую (симулируем IPC)
        sub_result = mgr.handle_state_subscribe(
            {
                "data": {
                    "pattern": "cameras.**",
                    "subscriber": "camera_0",
                    "exclude_sources": [],
                },
            }
        )
        assert sub_result["status"] == "ok"
        sub_id = sub_result["sub_id"]

        # Регистрируем callback локально
        proxy._callbacks[sub_id] = [lambda d: received.append(d)]
        proxy._sub_ids.append(sub_id)

        # Кто-то устанавливает значение
        mgr.handle_state_set(
            {
                "data": {"path": "cameras.0.config.fps", "value": 28, "source": "gui"},
            }
        )

        # Manager отправил state.changed — находим его и передаём proxy
        state_changed_msg = router.last_sent("state.changed")
        assert state_changed_msg is not None
        assert state_changed_msg["targets"] == ["camera_0"]

        proxy.on_state_changed(state_changed_msg)

        # Проверяем что callback вызван и кэш обновлён
        assert len(received) == 1
        assert received[0][0].path == "cameras.0.config.fps"
        assert proxy.cache["cameras.0.config.fps"] == 28

    def test_proxy_cache_updated_on_state_changed(self):
        """proxy.on_state_changed() обновляет кэш корректно."""
        proxy, mgr, router = self._build_pair()

        # Подписываем camera_0 через менеджер
        mgr.handle_state_subscribe(
            {
                "data": {
                    "pattern": "system.**",
                    "subscriber": "camera_0",
                    "exclude_sources": [],
                },
            }
        )

        # Изменение состояния
        mgr.handle_state_set(
            {
                "data": {"path": "system.status", "value": "running", "source": "manager"},
            }
        )

        # Находим state.changed и передаём proxy
        msg = router.last_sent("state.changed")
        proxy.on_state_changed(msg)

        assert proxy.cache["system.status"] == "running"


# ---------------------------------------------------------------------------
# ensure_subscription / release_subscription (refcount, 5.9)
# ---------------------------------------------------------------------------


def _count_sent(router: "MockRouter", command: str) -> int:
    return sum(1 for m in router.sent if isinstance(m, dict) and m.get("command") == command)


class TestEnsureSubscription:
    """Идемпотентная подписка с refcount — дедуп по паттерну."""

    def test_ensure_creates_one_server_subscription(self):
        """Два ensure на один pattern → ровно один state.subscribe."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "srv-1"})
        proxy = StateProxy("cam", router=router)

        s1 = proxy.ensure_subscription("processes.**")
        s2 = proxy.ensure_subscription("processes.**")

        assert s1 == s2 == "srv-1"
        assert _count_sent(router, "state.subscribe") == 1
        assert proxy._pattern_refcount["processes.**"] == 2

    def test_ensure_dedup_returns_same_sub_id_no_router(self):
        """router=None: повторный ensure возвращает тот же локальный sub_id."""
        proxy = StateProxy("cam", router=None)
        s1 = proxy.ensure_subscription("a.b.*")
        s2 = proxy.ensure_subscription("a.b.*")
        assert s1 == s2
        assert proxy._pattern_refcount["a.b.*"] == 2

    def test_release_decrements_then_unsubscribes(self):
        """release снимает серверную подписку только при обнулении refcount."""
        router = MockRouter()
        router.set_sync_response("state.subscribe", {"status": "ok", "sub_id": "srv-1"})
        proxy = StateProxy("cam", router=router)

        proxy.ensure_subscription("processes.**")
        proxy.ensure_subscription("processes.**")

        assert proxy.release_subscription("processes.**") is False  # 2 → 1
        assert _count_sent(router, "state.unsubscribe") == 0

        assert proxy.release_subscription("processes.**") is True  # 1 → 0
        assert _count_sent(router, "state.unsubscribe") == 1
        assert "processes.**" not in proxy._pattern_sub_id
        assert "processes.**" not in proxy._pattern_refcount

    def test_release_unknown_pattern_is_noop(self):
        router = MockRouter()
        proxy = StateProxy("cam", router=router)
        assert proxy.release_subscription("never.subscribed") is False
        assert _count_sent(router, "state.unsubscribe") == 0

    def test_ensure_multiple_callbacks_all_invoked_once(self):
        """Оба callback'а одной ensure-подписки вызываются, дельта доставлена один раз."""
        proxy = StateProxy("cam", router=None)
        seen1: list = []
        seen2: list = []
        proxy.ensure_subscription("processes.*.state.fps", seen1.append)
        proxy.ensure_subscription("processes.*.state.fps", seen2.append)

        delta = Delta(
            path="processes.cam.state.fps",
            old_value=10,
            new_value=30,
            source="other",
        )
        proxy.on_state_changed({"data": {"deltas": [delta.to_dict()]}})

        assert len(seen1) == 1
        assert len(seen2) == 1
        assert seen1[0][0].new_value == 30

    def test_ensure_without_callback_subscribes_safely(self):
        """ensure без callback — серверная подписка есть, доставка не падает."""
        proxy = StateProxy("cam", router=None)
        sub_id = proxy.ensure_subscription("processes.**")
        assert sub_id in proxy._sub_ids
        delta = Delta(path="processes.cam.state.fps", old_value=1, new_value=2, source="x")
        proxy.on_state_changed({"data": {"deltas": [delta.to_dict()]}})  # не бросает

    def test_direct_unsubscribe_clears_refcount_registry(self):
        """Прямой unsubscribe ensure-подписки чистит pattern-реестр (нет висяка)."""
        proxy = StateProxy("cam", router=None)
        sub_id = proxy.ensure_subscription("a.**")
        proxy.unsubscribe(sub_id)
        assert "a.**" not in proxy._pattern_sub_id
        assert "a.**" not in proxy._pattern_refcount

    def test_shutdown_clears_refcount_registry(self):
        proxy = StateProxy("cam", router=None)
        proxy.ensure_subscription("a.**")
        proxy.shutdown()
        assert proxy._pattern_sub_id == {}
        assert proxy._pattern_refcount == {}
