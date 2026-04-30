"""Тесты для StateStoreManager и DeltaDispatcher.

Все тесты работают без реального RouterManager — используется MockRouter или None.
"""
from __future__ import annotations

from multiprocess_prototype.state_store.core.delta import MISSING, Delta
from multiprocess_prototype.state_store.core.subscription_manager import SubscriptionManager
from multiprocess_prototype.state_store.manager.delta_dispatcher import DeltaDispatcher
from multiprocess_prototype.state_store.manager.state_store_manager import StateStoreManager

# ---------------------------------------------------------------------------
# MockRouter — мок RouterManager для тестов
# ---------------------------------------------------------------------------

class MockRouter:
    """Мок RouterManager для тестов."""

    def __init__(self):
        self.sent_messages: list[dict] = []
        self.registered_handlers: dict[str, object] = {}

    def send_async(self, message, priority="normal"):
        if isinstance(message, dict):
            self.sent_messages.append(message)
        else:
            self.sent_messages.append(
                message.to_dict() if hasattr(message, "to_dict") else message
            )

    def register_message_handler(self, key, handler, expects_full_message=True):
        self.registered_handlers[key] = handler


class MockCommandManager:
    """Мок CommandManager для тестов."""

    def __init__(self):
        self.registered_commands: dict[str, object] = {}

    def register_command(self, name, handler, metadata=None, tags=None):
        self.registered_commands[name] = {
            "handler": handler,
            "metadata": metadata,
            "tags": tags,
        }


# ===========================================================================
# Тесты StateStoreManager
# ===========================================================================

class TestStateStoreManagerInit:
    """Инициализация и базовые свойства StateStoreManager."""

    def test_init_default(self):
        """Создание с настройками по умолчанию."""
        mgr = StateStoreManager()
        assert mgr.store is not None
        assert mgr.subscription_manager is not None
        assert mgr.dispatcher is not None

    def test_init_with_initial_state(self):
        """Создание с начальным состоянием."""
        mgr = StateStoreManager(initial_state={"cameras": {"0": {"fps": 30}}})
        assert mgr.store.get("cameras.0.fps") == 30

    def test_initialize_without_router(self):
        """Инициализация без router (тестовый режим)."""
        mgr = StateStoreManager()
        assert mgr.initialize() is True

    def test_initialize_with_router(self):
        """Инициализация с router — регистрирует обработчики."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.initialize()
        # Проверяем что обработчики зарегистрированы
        assert "state.set" in router.registered_handlers
        assert "state.get" in router.registered_handlers
        assert "state.subscribe" in router.registered_handlers
        assert len(router.registered_handlers) == 7

    def test_shutdown_clears_subscriptions(self):
        """shutdown() удаляет все подписки."""
        mgr = StateStoreManager()
        mgr.initialize()
        # Создаём подписки
        mgr.handle_state_subscribe({"data": {"pattern": "cameras.*", "subscriber": "gui"}})
        mgr.handle_state_subscribe({"data": {"pattern": "system.*", "subscriber": "monitor"}})
        assert mgr.subscription_manager.subscription_count == 2
        # Останавливаем
        assert mgr.shutdown() is True
        assert mgr.subscription_manager.subscription_count == 0


class TestStateStoreManagerSet:
    """Тесты handle_state_set."""

    def test_set_basic(self):
        """Базовая установка значения."""
        mgr = StateStoreManager()
        result = mgr.handle_state_set({"data": {"path": "x.y", "value": 42, "source": "gui"}})
        assert result["status"] == "ok"
        assert result["changed"] is True
        assert mgr.store.get("x.y") == 42

    def test_set_no_change(self):
        """Установка того же значения — changed=False."""
        mgr = StateStoreManager(initial_state={"x": {"y": 42}})
        result = mgr.handle_state_set({"data": {"path": "x.y", "value": 42, "source": "gui"}})
        assert result["status"] == "ok"
        assert result["changed"] is False

    def test_set_missing_path(self):
        """Отсутствие path — ошибка."""
        mgr = StateStoreManager()
        result = mgr.handle_state_set({"data": {"value": 42}})
        assert result["status"] == "error"

    def test_set_dispatches_delta(self):
        """set с подпиской — дельта рассылается подписчику."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        # Подписываем gui на x.*
        mgr.handle_state_subscribe({"data": {"pattern": "x.*", "subscriber": "gui"}})
        # Устанавливаем значение
        mgr.handle_state_set({"data": {"path": "x.y", "value": 42, "source": "system"}})
        # Проверяем что сообщение отправлено
        assert len(router.sent_messages) == 1
        msg = router.sent_messages[0]
        assert msg["command"] == "state.changed"
        assert msg["targets"] == ["gui"]
        assert len(msg["data"]["deltas"]) == 1
        assert msg["data"]["deltas"][0]["path"] == "x.y"

    def test_set_from_data_field(self):
        """Извлечение данных из msg['data'] (формат CommandManager)."""
        mgr = StateStoreManager()
        result = mgr.handle_state_set({
            "type": "command",
            "command": "state.set",
            "data": {"path": "a.b", "value": "test", "source": "gui"},
        })
        assert result["status"] == "ok"
        assert mgr.store.get("a.b") == "test"

    def test_set_from_flat_msg(self):
        """Прямой dict без data-обёртки."""
        mgr = StateStoreManager()
        result = mgr.handle_state_set({"path": "a.b", "value": "test", "source": "gui"})
        assert result["status"] == "ok"
        assert mgr.store.get("a.b") == "test"


class TestStateStoreManagerMerge:
    """Тесты handle_state_merge."""

    def test_merge_basic(self):
        """Базовый merge."""
        mgr = StateStoreManager()
        result = mgr.handle_state_merge({
            "data": {"path": "cameras.0", "data": {"fps": 30, "type": "webcam"}, "source": "gui"},
        })
        assert result["status"] == "ok"
        assert result["changes_count"] == 2
        assert mgr.store.get("cameras.0.fps") == 30
        assert mgr.store.get("cameras.0.type") == "webcam"

    def test_merge_invalid_data(self):
        """merge без data — ошибка."""
        mgr = StateStoreManager()
        result = mgr.handle_state_merge({"data": {"path": "x"}})
        assert result["status"] == "error"

    def test_merge_dispatches_deltas(self):
        """merge с подпиской — дельты рассылаются."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.handle_state_subscribe({"data": {"pattern": "cameras.**", "subscriber": "processor"}})
        mgr.handle_state_merge({
            "data": {"path": "cameras.0", "data": {"fps": 30, "type": "webcam"}, "source": "gui"},
        })
        # Одно сообщение state.changed с двумя дельтами
        assert len(router.sent_messages) == 1
        msg = router.sent_messages[0]
        assert msg["targets"] == ["processor"]
        assert len(msg["data"]["deltas"]) == 2


class TestStateStoreManagerGet:
    """Тесты handle_state_get и handle_state_get_subtree."""

    def test_get_existing(self):
        """Чтение существующего значения."""
        mgr = StateStoreManager(initial_state={"x": {"y": 42}})
        result = mgr.handle_state_get({"data": {"path": "x.y", "request_id": "req-1"}})
        assert result["status"] == "ok"
        assert result["request_id"] == "req-1"
        assert result["value"] == 42

    def test_get_missing(self):
        """Чтение несуществующего пути — ошибка."""
        mgr = StateStoreManager()
        result = mgr.handle_state_get({"data": {"path": "no.such.path", "request_id": "req-2"}})
        assert result["status"] == "error"
        assert result["request_id"] == "req-2"

    def test_get_subtree(self):
        """Чтение поддерева."""
        mgr = StateStoreManager(initial_state={"cameras": {"0": {"fps": 30, "type": "webcam"}}})
        result = mgr.handle_state_get_subtree({"data": {"path": "cameras.0", "request_id": "req-3"}})
        assert result["status"] == "ok"
        assert result["value"] == {"fps": 30, "type": "webcam"}


class TestStateStoreManagerSubscriptions:
    """Тесты handle_state_subscribe / unsubscribe / unsubscribe_all."""

    def test_subscribe(self):
        """Создание подписки."""
        mgr = StateStoreManager()
        result = mgr.handle_state_subscribe({
            "data": {"pattern": "cameras.*", "subscriber": "gui"},
        })
        assert result["status"] == "ok"
        assert "sub_id" in result
        assert mgr.subscription_manager.subscription_count == 1

    def test_subscribe_with_exclude(self):
        """Подписка с exclude_sources."""
        mgr = StateStoreManager()
        result = mgr.handle_state_subscribe({
            "data": {
                "pattern": "cameras.*",
                "subscriber": "gui",
                "exclude_sources": ["gui"],
            },
        })
        assert result["status"] == "ok"

    def test_subscribe_missing_fields(self):
        """Подписка без обязательных полей — ошибка."""
        mgr = StateStoreManager()
        result = mgr.handle_state_subscribe({"data": {"pattern": "cameras.*"}})
        assert result["status"] == "error"

    def test_unsubscribe(self):
        """Отписка по sub_id."""
        mgr = StateStoreManager()
        sub_result = mgr.handle_state_subscribe({
            "data": {"pattern": "cameras.*", "subscriber": "gui"},
        })
        sub_id = sub_result["sub_id"]
        result = mgr.handle_state_unsubscribe({"data": {"sub_id": sub_id}})
        assert result["status"] == "ok"
        assert result["success"] is True
        assert mgr.subscription_manager.subscription_count == 0

    def test_unsubscribe_all(self):
        """Отписка всех подписок процесса."""
        mgr = StateStoreManager()
        mgr.handle_state_subscribe({"data": {"pattern": "cameras.*", "subscriber": "gui"}})
        mgr.handle_state_subscribe({"data": {"pattern": "system.*", "subscriber": "gui"}})
        mgr.handle_state_subscribe({"data": {"pattern": "cameras.*", "subscriber": "monitor"}})
        assert mgr.subscription_manager.subscription_count == 3

        result = mgr.handle_state_unsubscribe_all({"data": {"subscriber": "gui"}})
        assert result["status"] == "ok"
        assert result["count"] == 2
        assert mgr.subscription_manager.subscription_count == 1


class TestStateStoreManagerRegister:
    """Тесты register_commands и register_message_handlers."""

    def test_register_commands(self):
        """Регистрация команд в CommandManager."""
        mgr = StateStoreManager()
        cmd_mgr = MockCommandManager()
        mgr.register_commands(cmd_mgr)
        expected = {
            "state.set", "state.merge", "state.get", "state.get_subtree",
            "state.subscribe", "state.unsubscribe", "state.unsubscribe_all",
        }
        assert set(cmd_mgr.registered_commands.keys()) == expected
        # Проверяем теги
        for info in cmd_mgr.registered_commands.values():
            assert "state_store" in info["tags"]

    def test_register_message_handlers(self):
        """Регистрация обработчиков в RouterManager."""
        mgr = StateStoreManager()
        router = MockRouter()
        mgr.register_message_handlers(router)
        assert len(router.registered_handlers) == 7
        assert "state.set" in router.registered_handlers


# ===========================================================================
# Тесты DeltaDispatcher
# ===========================================================================

class TestDeltaDispatcher:
    """Тесты DeltaDispatcher."""

    def _make_delta(self, path="x.y", old=MISSING, new=42, source="gui"):
        """Вспомогательный метод создания дельты."""
        return Delta(path=path, old_value=old, new_value=new, source=source)

    def test_dispatch_empty(self):
        """Пустой список дельт — ничего не отправляется."""
        subs = SubscriptionManager()
        dispatcher = DeltaDispatcher(subs)
        stats = dispatcher.dispatch([])
        assert stats == {}

    def test_dispatch_no_subscribers(self):
        """Дельта без подписчиков — ничего не отправляется."""
        subs = SubscriptionManager()
        dispatcher = DeltaDispatcher(subs)
        delta = self._make_delta()
        stats = dispatcher.dispatch([delta])
        assert stats == {}

    def test_dispatch_single_subscriber(self):
        """Одна дельта, один подписчик — одно сообщение."""
        router = MockRouter()
        subs = SubscriptionManager()
        subs.subscribe("x.*", subscriber="gui")
        dispatcher = DeltaDispatcher(subs, router=router)

        delta = self._make_delta()
        stats = dispatcher.dispatch_single(delta)

        assert stats == {"gui": 1}
        assert len(router.sent_messages) == 1
        msg = router.sent_messages[0]
        assert msg["command"] == "state.changed"
        assert msg["targets"] == ["gui"]

    def test_dispatch_multiple_subscribers(self):
        """Дельта матчит двух подписчиков — два сообщения."""
        router = MockRouter()
        subs = SubscriptionManager()
        subs.subscribe("x.*", subscriber="gui")
        subs.subscribe("x.*", subscriber="monitor")
        dispatcher = DeltaDispatcher(subs, router=router)

        delta = self._make_delta()
        stats = dispatcher.dispatch_single(delta)

        assert stats == {"gui": 1, "monitor": 1}
        assert len(router.sent_messages) == 2

    def test_dispatch_deduplication(self):
        """Дедупликация: subscriber с 2 матчащими подписками получает дельту 1 раз."""
        router = MockRouter()
        subs = SubscriptionManager()
        # gui подписан двумя паттернами, оба матчат x.y
        subs.subscribe("x.*", subscriber="gui")
        subs.subscribe("x.**", subscriber="gui")
        dispatcher = DeltaDispatcher(subs, router=router)

        delta = self._make_delta()
        stats = dispatcher.dispatch_single(delta)

        # gui получает дельту ОДИН раз, несмотря на 2 подписки
        assert stats == {"gui": 1}
        assert len(router.sent_messages) == 1
        assert len(router.sent_messages[0]["data"]["deltas"]) == 1

    def test_dispatch_batch(self):
        """Batch: несколько дельт — одно state.changed сообщение per subscriber."""
        router = MockRouter()
        subs = SubscriptionManager()
        subs.subscribe("cameras.**", subscriber="processor")
        dispatcher = DeltaDispatcher(subs, router=router)

        deltas = [
            self._make_delta(path="cameras.0.fps", new=30, source="gui"),
            self._make_delta(path="cameras.0.type", new="webcam", source="gui"),
        ]
        stats = dispatcher.dispatch(deltas)

        assert stats == {"processor": 2}
        # Одно сообщение с двумя дельтами
        assert len(router.sent_messages) == 1
        assert len(router.sent_messages[0]["data"]["deltas"]) == 2

    def test_dispatch_exclude_sources(self):
        """exclude_sources: дельта от gui не приходит подписчику с exclude gui."""
        router = MockRouter()
        subs = SubscriptionManager()
        subs.subscribe("x.*", subscriber="gui", exclude_sources=("gui",))
        dispatcher = DeltaDispatcher(subs, router=router)

        delta = self._make_delta(source="gui")
        stats = dispatcher.dispatch_single(delta)

        assert stats == {}
        assert len(router.sent_messages) == 0

    def test_dispatch_without_router(self):
        """Без router — статистика собирается, сообщения не отправляются."""
        subs = SubscriptionManager()
        subs.subscribe("x.*", subscriber="gui")
        dispatcher = DeltaDispatcher(subs, router=None)

        delta = self._make_delta()
        stats = dispatcher.dispatch_single(delta)

        # Статистика собрана
        assert stats == {"gui": 1}

    def test_dispatch_delta_serialization(self):
        """Проверяем формат сериализованных дельт в сообщении."""
        router = MockRouter()
        subs = SubscriptionManager()
        subs.subscribe("x.*", subscriber="gui")
        dispatcher = DeltaDispatcher(subs, router=router)

        delta = self._make_delta(path="x.y", old=10, new=20, source="system")
        dispatcher.dispatch_single(delta)

        msg = router.sent_messages[0]
        d = msg["data"]["deltas"][0]
        assert d["path"] == "x.y"
        assert d["old_value"] == 10
        assert d["new_value"] == 20
        assert d["source"] == "system"
        assert "timestamp" in d
        assert "transaction_id" in d


# ===========================================================================
# Интеграционные тесты — StateStoreManager + DeltaDispatcher
# ===========================================================================

class TestIntegration:
    """Сквозные тесты: IPC-сообщение -> set -> subscribe -> dispatch."""

    def test_full_flow(self):
        """Полный цикл: подписка -> set -> получение state.changed."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.initialize()

        # 1. Подписываем processor на cameras.**
        sub_result = mgr.handle_state_subscribe({
            "data": {"pattern": "cameras.**", "subscriber": "processor"},
        })
        assert sub_result["status"] == "ok"

        # 2. Устанавливаем значение
        set_result = mgr.handle_state_set({
            "data": {"path": "cameras.0.fps", "value": 30, "source": "gui"},
        })
        assert set_result["status"] == "ok"
        assert set_result["changed"] is True

        # 3. Проверяем что processor получил state.changed
        assert len(router.sent_messages) == 1
        msg = router.sent_messages[0]
        assert msg["command"] == "state.changed"
        assert msg["targets"] == ["processor"]

        # 4. Читаем обратно
        get_result = mgr.handle_state_get({
            "data": {"path": "cameras.0.fps", "request_id": "check-1"},
        })
        assert get_result["value"] == 30

    def test_merge_and_subscribe_flow(self):
        """merge + подписка: несколько дельт в одном сообщении."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.initialize()

        # Подписываем
        mgr.handle_state_subscribe({
            "data": {"pattern": "cameras.**", "subscriber": "monitor"},
        })

        # Merge нескольких полей
        mgr.handle_state_merge({
            "data": {
                "path": "cameras.0",
                "data": {"fps": 30, "type": "webcam", "enabled": True},
                "source": "recipe",
            },
        })

        # Одно сообщение с 3 дельтами
        assert len(router.sent_messages) == 1
        assert len(router.sent_messages[0]["data"]["deltas"]) == 3

    def test_unsubscribe_stops_delivery(self):
        """После отписки дельты не доставляются."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.initialize()

        # Подписываем и тут же отписываем
        sub_result = mgr.handle_state_subscribe({
            "data": {"pattern": "x.*", "subscriber": "gui"},
        })
        mgr.handle_state_unsubscribe({"data": {"sub_id": sub_result["sub_id"]}})

        # set не вызывает рассылку
        mgr.handle_state_set({"data": {"path": "x.y", "value": 42, "source": "test"}})
        assert len(router.sent_messages) == 0
