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


# ===========================================================================
# Тесты watch-from-revision + resync (Ф4.9b, ADR-SS-014/015)
# ===========================================================================


def _make_state_changed_msg_rev(deltas: list[Delta], revision: int) -> dict:
    """Как _make_state_changed_msg, но с data.revision (Ф4.9a envelope)."""
    return {
        "command": "state.changed",
        "data": {
            "deltas": [d.to_dict() for d in deltas],
            "revision": revision,
        },
    }


class TestStateProxyRevisionGapDetection:
    """_check_and_handle_revision_gap — детект разрыва без реального router."""

    def test_fail_open_when_revision_absent(self):
        """Пакет без data.revision (старый отправитель) — gap-проверка пропущена."""
        proxy = StateProxy("cam", router=None)
        delta = _make_delta(new=30)
        proxy.on_state_changed(_make_state_changed_msg([delta]))  # без revision
        assert proxy._last_revision is None
        assert proxy.get("cameras.0.config.fps") == 30  # обычная обработка прошла

    def test_first_message_sets_baseline_without_gap(self):
        """Первый пакет с revision — база отсчёта, не считается разрывом."""
        proxy = StateProxy("cam", router=None)
        delta = _make_delta(new=30)
        proxy.on_state_changed(_make_state_changed_msg_rev([delta], revision=5))
        assert proxy._last_revision == 5
        assert proxy.get("cameras.0.config.fps") == 30

    def test_sequential_revisions_no_gap(self):
        """revision N, затем N+1 — нормальная последовательность, без resync."""
        router = MockRouter()
        proxy = StateProxy("cam", router=router)
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=20)], revision=2))
        assert proxy._last_revision == 2
        assert proxy.get("cameras.0.config.fps") == 20
        # Разрыва не было → resync (state.get_subtree с 'paths') не вызывался.
        assert router.last_sent("state.get_subtree") is None

    def test_gap_triggers_resync_no_router_is_safe(self):
        """Разрыв без router — _resync() no-op, не бросает исключение.

        Изменено ревью Ф4.9 (MED-4, 2026-07-11): раньше _last_revision
        обновлялась ТОЛЬКО при УСПЕШНОМ resync — при router=None (resync
        физически невозможен) revision навсегда замирала на 1, и КАЖДЫЙ
        следующий пакет считался бы новым разрывом (перманентная блокировка
        детекции). Теперь _last_revision продвигается по факту доставленного
        пакета НЕЗАВИСИМО от исхода resync (пакет уже применён — инвариант
        (б)); resync — best-effort подстраховка, а не условие прогресса.
        """
        proxy = StateProxy("cam", router=None)
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        # Прыжок с 1 на 5 — разрыв. Без router просто нет ресинка, но пакет применён.
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=50)], revision=5))
        assert proxy.get("cameras.0.config.fps") == 50  # пакет применён несмотря на разрыв
        assert proxy._last_revision == 5  # продвинулась — нет перманентной блокировки


class TestStateProxyResync:
    """_resync() — конвергенция кэша через существующий канал state.get_subtree."""

    def test_gap_triggers_resync_via_get_subtree_paths(self):
        """Разрыв revision → StateProxy шлёт state.get_subtree с data.paths=подписки."""
        router = MockRouter()
        router.set_sync_response(
            "state.get_subtree",
            {"status": "ok", "value": {"cameras": {"0": {"config": {"fps": 99}}}}, "revision": 5},
        )
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda _d: None, exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        # Разрыв: пришла revision=5 при ожидаемой revision=2.
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=99)], revision=5))

        resync_req = router.last_sent("state.get_subtree")
        assert resync_req is not None
        assert resync_req["data"]["paths"] == ["cameras.0.**"]

    def test_gap_resync_converges_cache_to_server_value(self):
        """После resync кэш содержит значение ИЗ СНАПШОТА сервера (не из пропущенного пакета)."""
        router = MockRouter()
        router.set_sync_response(
            "state.get_subtree",
            {"status": "ok", "value": {"cameras": {"0": {"config": {"fps": 77}}}}, "revision": 9},
        )
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda _d: None, exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=999)], revision=9))

        # Кэш взял значение из resync-снапшота (77), а не из "разорванного" пакета (999).
        assert proxy.get("cameras.0.config.fps") == 77
        assert proxy._last_revision == 9

    def test_gap_resync_removes_stale_deleted_path(self):
        """Resync убирает из кэша путь, отсутствующий в свежем снапшоте (был удалён на сервере)."""
        router = MockRouter()
        router.set_sync_response(
            "state.get_subtree",
            {"status": "ok", "value": {"cameras": {"0": {}}}, "revision": 4},
        )
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda _d: None, exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        assert proxy.get("cameras.0.config.fps") == 10

        # Разрыв → resync; в свежем снапшоте fps уже нет (удалён на сервере).
        other_delta = _make_delta(path="cameras.0.state.status", new="idle")
        proxy.on_state_changed(_make_state_changed_msg_rev([other_delta], revision=4))

        # Путь удалён именно из КЭША (а не просто недоступен из-за IPC fallback).
        assert "cameras.0.config.fps" not in proxy.cache

    def test_resync_failure_still_advances_revision_no_permanent_lockout(self):
        """MED-4 (ревью 2026-07-11, было признано багом): неудачный resync
        БОЛЬШЕ НЕ замораживает _last_revision навсегда.

        Раньше (test_resync_failure_leaves_last_revision_unchanged) —
        _last_revision оставалась на 1 при неудаче resync, из-за чего
        КАЖДЫЙ следующий пакет снова считался разрывом и порождал ещё один
        (тоже неудачный) resync — перманентная блокировка progress'а. Теперь:
        пакет применяется к кэшу и доставляется в callback НЕЗАВИСИМО от
        исхода resync (fail-open, инвариант (б)), _last_revision продвигается
        до revision пришедшего пакета — блокировки нет, а следующий пакет с
        нормальным продолжением revision не считается новым разрывом.
        """
        router = MockRouter()
        router.set_sync_response("state.get_subtree", {"status": "error", "error": "boom"})
        received: list[list[Delta]] = []
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda deltas: received.append(deltas), exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=999)], revision=9))

        assert proxy._last_revision == 9  # продвинулась несмотря на неудачный resync
        assert proxy.get("cameras.0.config.fps") == 999  # пакет применён (fail-open)
        assert received and received[-1][0].new_value == 999  # callback вызван, не проглочен

        # Следующий пакет — нормальное продолжение (revision=10 после 9) — НЕ разрыв,
        # доказывает отсутствие перманентной блокировки detection'а.
        received.clear()
        sent_before = len(router.sent)
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=1000)], revision=10))
        assert proxy._last_revision == 10
        assert received and received[-1][0].new_value == 1000
        assert len(router.sent) == sent_before  # никакого нового resync

    def test_resync_no_op_without_patterns(self):
        """_resync([]) — нет активных подписок, нечего ресинкать, no-op."""
        router = MockRouter()
        proxy = StateProxy("cam", router=router)
        proxy._resync([])
        assert router.last_sent("state.get_subtree") is None
        assert proxy._pattern_refcount == {}


# ===========================================================================
# Ревью Ф4.9 2026-07-11: HIGH-1 (multi-leaf merge ложный разрыв), HIGH-2 +
# инвариант (б) (дельты доставленного пакета никогда не проглатываются из-за
# resync), MED-3 (устаревший в-полёте пакет). Модель диапазона
# [first_revision, revision] — см. _advance_revision_and_maybe_resync.
# ===========================================================================


class TestStateProxyMultiLeafMergeContinuity:
    """HIGH-1: envelope с first_revision, стыкующимся с last+1, — НЕ разрыв,
    даже если max(revision) пакета > last+1 (merge на 2+ листа)."""

    def test_multi_leaf_merge_envelope_not_treated_as_gap(self):
        router = MockRouter()
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda _d: None, exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=1)], revision=4))

        # Эмулируем пакет из merge() на 2 листа: first_revision=5, revision=6.
        merge_deltas = [
            Delta(
                path="cameras.0.config.fps",
                old_value=MISSING,
                new_value=5,
                source="camera_0",
                revision=5,
            ),
            Delta(
                path="cameras.0.config.type",
                old_value=MISSING,
                new_value="usb",
                source="camera_0",
                revision=6,
            ),
        ]
        msg = {
            "command": "state.changed",
            "data": {
                "deltas": [d.to_dict() for d in merge_deltas],
                "revision": 6,
                "first_revision": 5,
            },
        }
        proxy.on_state_changed(msg)

        assert router.last_sent("state.get_subtree") is None  # НЕ было resync
        assert proxy._last_revision == 6
        assert proxy.get("cameras.0.config.fps") == 5
        assert proxy.get("cameras.0.config.type") == "usb"

    def test_multi_leaf_merge_missing_first_revision_falls_back_to_old_behavior(self):
        """Обратная совместимость: пакет без first_revision (старый отправитель) —
        деградирует к сравнению только по envelope revision (как до фикса)."""
        router = MockRouter()
        router.set_sync_response("state.get_subtree", {"status": "ok", "value": {}, "revision": 6})
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda _d: None, exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=1)], revision=4))
        # Без first_revision в конверте — used envelope_revision как fallback.
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=6)], revision=6))

        # first_revision по умолчанию == envelope_revision(6) > expected(5) → разрыв.
        assert router.last_sent("state.get_subtree") is not None


class TestStateProxyInvariantBDeltasAlwaysDelivered:
    """Инвариант (б), ревью 2026-07-11: дельты ДОСТАВЛЕННОГО пакета ВСЕГДА
    доходят до callbacks/delta_sink — resync ДОПОЛНЯЕТ, а не ЗАМЕНЯЕТ доставку."""

    def test_gap_packet_deltas_still_delivered_to_callbacks(self):
        router = MockRouter()
        router.set_sync_response(
            "state.get_subtree",
            {"status": "ok", "value": {"cameras": {"0": {"config": {"fps": 77}}}}, "revision": 9},
        )
        received: list[list[Delta]] = []
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda deltas: received.append(deltas), exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        received.clear()

        # Разрыв: revision=9 при ожидаемой 2 — старое поведение проглотило бы
        # эту дельту целиком (return до _invoke_callbacks). Теперь — доставлена.
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=999)], revision=9))

        assert len(received) == 1
        assert received[0][0].new_value == 999

    # HIGH-2 сквозной сценарий (мутация вне паттерна подписчика + реальный
    # StateStoreManager/DeltaDispatcher) — см.
    # test_watch_from_revision.py::test_unrelated_mutation_outside_pattern_does_not_swallow_relevant_delivery
    # (нужен router, реально РЕЛЕЙЯЩИЙ state.changed между mgr и proxy — этот
    # файл использует упрощённый MockRouter без такого релея).


class TestStateProxyStaleEnvelope:
    """MED-3: пакет "в полёте" во время предыдущего resync (revision <= last) —
    игнорируется целиком, без resync-шторма и без регрессии кэша."""

    def test_stale_packet_after_resync_is_ignored_without_resync_storm(self):
        router = MockRouter()
        router.set_sync_response(
            "state.get_subtree",
            {"status": "ok", "value": {"cameras": {"0": {"config": {"fps": 77}}}}, "revision": 9},
        )
        received: list[list[Delta]] = []
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda deltas: received.append(deltas), exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=1))
        # Разрыв → resync → last_revision=9, кэш=77 (см. TestStateProxyResync).
        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=999)], revision=9))
        assert proxy._last_revision == 9
        assert proxy.get("cameras.0.config.fps") == 77

        sent_before = len(router.sent)
        received.clear()

        # Пакет "в полёте", отправленный сервером ДО resync'а (revision=6 <= last=9).
        stale_delta = _make_delta(new=6666)
        proxy.on_state_changed(_make_state_changed_msg_rev([stale_delta], revision=6))

        assert proxy.get("cameras.0.config.fps") == 77  # кэш НЕ регрессировал
        assert proxy._last_revision == 9  # last_revision не откатилась назад
        assert received == []  # устаревший пакет не доставлен в callback
        assert len(router.sent) == sent_before  # НЕ вызвал новый resync (без шторма)

    def test_exact_duplicate_envelope_is_stale(self):
        """envelope_revision == last_revision (точный дубликат) — тоже устарел."""
        router = MockRouter()
        received: list[list[Delta]] = []
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda deltas: received.append(deltas), exclude_self=False)

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=10)], revision=5))
        received.clear()

        proxy.on_state_changed(_make_state_changed_msg_rev([_make_delta(new=999)], revision=5))

        assert proxy.get("cameras.0.config.fps") == 10  # дубликат не применился
        assert received == []


# ===========================================================================
# ADR-SS-016 (PLAUSIBLE-6, ревью 2026-07-11): _send_sync должен звать
# router.request(), а не router.send(), когда router умеет request/response.
#
# У реального RouterManager send() — fire-and-forget поверх канала (кладёт
# в очередь и возвращает статус ДОСТАВКИ, например {"status":"success",
# "channel": "ctrl"}), НЕ ответ обработчика на другом конце. Настоящий
# синхронный request/response — router.request() (correlation_id + blocking
# wait). Все тестовые дублёры в этом файле (MockRouter/InMemoryRouter)
# реализуют send() КАК request-reply напрямую — маскируя баг в тестах.
# Ниже — дублёр, мимикрирующий РЕАЛЬНОЕ разделение send()/request().
# ===========================================================================


class _RealisticRouter:
    """Дублёр, воспроизводящий реальное разделение RouterManager.send()/request().

    send()    — чистый transport-ack (как QueueChannel.send()), НЕ ответ handler'а.
    request() — блокирующий request/response, возвращает конверт
                {"success": bool, "result": <ответ handler'а>} (как
                RouterManager.request()/reply_to_request()).
    """

    def __init__(self, request_result: dict | None = None, request_success: bool = True) -> None:
        self.send_calls: list[dict] = []
        self.request_calls: list[tuple[dict, float]] = []
        self._request_result = request_result if request_result is not None else {"status": "ok"}
        self._request_success = request_success

    def register_message_handler(self, key, handler, **kwargs) -> None:
        pass

    def send_async(self, msg, priority: str = "normal") -> None:
        pass

    def send(self, msg) -> dict:
        # РЕАЛЬНЫЙ router: чистый ack доставки в очередь, НЕ ответ обработчика.
        self.send_calls.append(msg)
        return {"status": "success", "channel": "ctrl"}

    def request(self, msg, timeout: float = 5.0) -> dict:
        self.request_calls.append((msg, timeout))
        if not self._request_success:
            return {"success": False, "error": "timeout", "correlation_id": "cid"}
        result = dict(self._request_result)
        request_id = msg.get("data", {}).get("request_id")
        if request_id is not None:
            result.setdefault("request_id", request_id)
        return {"success": True, "result": result, "correlation_id": "cid"}


class TestSendSyncPrefersRequestOverSend:
    """_send_sync должен использовать router.request(), когда он доступен."""

    def test_get_uses_request_and_unwraps_handler_result(self):
        """proxy.get() через реалистичный router читает ЗНАЧЕНИЕ ИЗ result, а не ack."""
        router = _RealisticRouter(request_result={"status": "ok", "value": 42})
        proxy = StateProxy("cam", router=router)

        value = proxy.get("some.path")

        assert value == 42
        assert len(router.request_calls) == 1
        assert router.send_calls == []  # send() не используется для получения ответа

    def test_get_subtree_uses_request(self):
        """proxy.get_subtree() тоже обязан идти через request(), не send()."""
        router = _RealisticRouter(request_result={"status": "ok", "value": {"fps": 30}})
        proxy = StateProxy("cam", router=router)

        assert proxy.get_subtree("cameras.0") == {"fps": 30}
        assert len(router.request_calls) == 1

    def test_request_timeout_is_fail_open(self):
        """Таймаут/неуспех request() — fail-open (default), не исключение."""
        router = _RealisticRouter(request_success=False)
        proxy = StateProxy("cam", router=router)

        assert proxy.get("some.path", default="fallback") == "fallback"

    def test_resync_uses_request_and_converges_cache(self):
        """_resync() (ядро watch-from-revision) обязан работать по РЕАЛЬНОМУ
        каналу — через request(), а не send(), иначе в проде получал бы
        transport-ack вместо снапшота и никогда не сходился с сервером."""
        router = _RealisticRouter(
            request_result={
                "status": "ok",
                "value": {"cameras": {"0": {"config": {"fps": 55}}}},
                "revision": 3,
            }
        )
        proxy = StateProxy("cam", router=router)
        proxy.subscribe("cameras.0.**", lambda _d: None, exclude_self=False)

        proxy._resync(["cameras.0.**"])

        assert proxy.get("cameras.0.config.fps") == 55
        assert proxy._last_revision == 3
        assert len(router.request_calls) >= 1

    def test_falls_back_to_send_when_router_has_no_request(self):
        """Обратная совместимость: тестовые роутеры без request() (InMemoryRouter,
        MockRouter, _RelayRouter) продолжают работать через send() как раньше."""
        router = MockRouter()
        router.set_sync_response("state.get", {"status": "ok", "value": 7, "request_id": "x"})
        proxy = StateProxy("cam", router=router)

        assert proxy.get("some.path") == 7
