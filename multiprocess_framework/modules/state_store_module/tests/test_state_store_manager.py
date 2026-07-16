"""Тесты для StateStoreManager и DeltaDispatcher.

Все тесты работают без реального RouterManager — используется MockRouter или None.
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.core.delta import (
    MISSING,
    STATE_ENVELOPE_MARKER,
    Delta,
)
from multiprocess_framework.modules.state_store_module.core.subscription_manager import SubscriptionManager
from multiprocess_framework.modules.state_store_module.manager.delta_dispatcher import DeltaDispatcher
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager

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
            self.sent_messages.append(message.to_dict() if hasattr(message, "to_dict") else message)

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
        assert len(router.registered_handlers) == 8

    def test_initialize_auto_register_ipc_false_skips_raw(self):
        """auto_register_ipc=False: initialize() НЕ регистрирует RAW-обработчики.

        Это интерим-фикс серверного разрыва телеметрии (см.
        plans/comm-system-target-architecture.md, P0 2026-06-03): RAW-хендлеры
        не зовут reply_to_request и, побеждая по «первая регистрация» в
        dispatcher, ломали request/reply state.* (timeout). При False
        единственный владелец ключей — CommandManager + wrapped-путь.
        """
        router = MockRouter()
        mgr = StateStoreManager(router=router, auto_register_ipc=False)
        assert mgr.initialize() is True
        # RAW-регистрации НЕТ — event_dispatcher не занят сырыми хендлерами.
        assert router.registered_handlers == {}

    def test_initialize_auto_register_ipc_true_is_default(self):
        """Дефолт auto_register_ipc=True сохраняет legacy-поведение (RAW)."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)  # без явного флага
        mgr.initialize()
        assert len(router.registered_handlers) == 8

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
        result = mgr.handle_state_set(
            {
                "type": "command",
                "command": "state.set",
                "data": {"path": "a.b", "value": "test", "source": "gui"},
            }
        )
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
        result = mgr.handle_state_merge(
            {
                "data": {"path": "cameras.0", "data": {"fps": 30, "type": "webcam"}, "source": "gui"},
            }
        )
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
        mgr.handle_state_merge(
            {
                "data": {"path": "cameras.0", "data": {"fps": 30, "type": "webcam"}, "source": "gui"},
            }
        )
        # Одно сообщение state.changed с двумя дельтами
        assert len(router.sent_messages) == 1
        msg = router.sent_messages[0]
        assert msg["targets"] == ["processor"]
        assert len(msg["data"]["deltas"]) == 2

    def test_merge_commandmanager_form_payload_with_source_key(self):
        """Ж-3 (RS-2): развёрнутый конверт (expects_full_message=False) с payload,
        содержащим ключ 'source' — НЕ должен падать с «Поле 'data' обязательно».

        Регресс тихого `state.merge failed` на switch: камера публикует
        `processes.<cam>.state.cam.actual` через proxy.merge, а её actual-параметры
        содержат ключ 'source' (напр. 'camera://0'). Форма B: конверт передан
        напрямую с явным маркером (Ф7 G.2 шаг 4) — payload под 'data', маркер
        снимает неоднозначность независимо от содержимого payload.
        """
        mgr = StateStoreManager()
        payload = {"source": "camera://0", "resolution": "1080p"}
        # msg = помеченный конверт (форма B): маркер + path + data
        result = mgr.handle_state_merge(
            {
                "path": "processes.cam0.state.cam.actual",
                "data": payload,
                "source": "cam0",
                STATE_ENVELOPE_MARKER: True,
            }
        )
        assert result["status"] == "ok"
        assert result["changes_count"] == 2
        assert mgr.store.get("processes.cam0.state.cam.actual.source") == "camera://0"

    def test_merge_missing_path_is_error(self):
        """F2 (ревью G.2): маркированный конверт без path → громкая ошибка, не merge в корень."""
        mgr = StateStoreManager()
        mgr.handle_state_set({"data": {"path": "keep.me", "value": 1, "source": "s"}})
        result = mgr.handle_state_merge({"data": {"fps": 30}, "source": "s", STATE_ENVELOPE_MARKER: True})
        assert result["status"] == "error"
        assert "path" in result["error"]
        # дерево не тронуто
        assert mgr.store.get("keep.me") == 1
        assert mgr.store.get("fps", MISSING) is MISSING

    def test_merge_empty_path_is_error(self):
        """F2: path='' → ошибка (симметрично handle_state_set), корень не затёрт."""
        mgr = StateStoreManager()
        mgr.handle_state_set({"data": {"path": "keep.me", "value": 1, "source": "s"}})
        result = mgr.handle_state_merge({"path": "", "data": {"fps": 30}, "source": "s", STATE_ENVELOPE_MARKER: True})
        assert result["status"] == "error"
        assert mgr.store.get("keep.me") == 1

    def test_merge_commandmanager_form_payload_with_path_key(self):
        """Ж-3: тот же путь, но payload содержит ключ 'path' (device-config).

        Явный маркер снимает прежний shape-sniffing: top-level 'path' в самом
        конверте больше не путается с 'path' внутри payload."""
        mgr = StateStoreManager()
        payload = {"path": "/dev/video0", "fps": 30}
        result = mgr.handle_state_merge(
            {
                "path": "processes.dev.state",
                "data": payload,
                "source": "dev",
                STATE_ENVELOPE_MARKER: True,
            }
        )
        assert result["status"] == "ok"
        assert mgr.store.get("processes.dev.state.path") == "/dev/video0"
        assert mgr.store.get("processes.dev.state.fps") == 30


class TestStateStoreManagerDelete:
    """Тесты handle_state_delete (RS-2: очистка ghost-поддерева при cleanup)."""

    def test_delete_existing_subtree(self):
        """Удаление существующего поддерева процесса."""
        mgr = StateStoreManager(initial_state={"processes": {"preproc": {"state": {"status": "running"}}}})
        result = mgr.handle_state_delete({"data": {"path": "processes.preproc", "source": "PM"}})
        assert result["status"] == "ok"
        assert result["changed"] is True
        assert mgr.store.get("processes.preproc", None) is None

    def test_delete_missing_is_idempotent(self):
        """Удаление отсутствующего узла — не ошибка (changed=False)."""
        mgr = StateStoreManager()
        result = mgr.handle_state_delete({"data": {"path": "processes.ghost", "source": "PM"}})
        assert result["status"] == "ok"
        assert result["changed"] is False

    def test_delete_missing_path(self):
        """Отсутствие path — ошибка."""
        mgr = StateStoreManager()
        result = mgr.handle_state_delete({"data": {"source": "PM"}})
        assert result["status"] == "error"

    def test_delete_dispatches_delta(self):
        """delete с подпиской — дельта рассылается подписчику."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        # Значение ставим ДО подписки (set не рассылается — подписчика ещё нет).
        mgr.handle_state_set({"data": {"path": "processes.p.x", "value": 1, "source": "s"}})
        mgr.handle_state_subscribe({"data": {"pattern": "processes.**", "subscriber": "gui"}})
        router.sent_messages.clear()  # игнорируем возможный initial-snapshot подписки
        mgr.handle_state_delete({"data": {"path": "processes.p", "source": "PM"}})
        assert len(router.sent_messages) == 1
        assert router.sent_messages[0]["targets"] == ["gui"]
        deltas = router.sent_messages[0]["data"]["deltas"]
        assert any(d["path"] == "processes.p" for d in deltas)


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

    def test_get_subtree_includes_revision(self):
        """Ф4.9a: ответ несёт текущую revision дерева (аддитивное поле)."""
        mgr = StateStoreManager()
        mgr.handle_state_set({"data": {"path": "x.y", "value": 1, "source": "s"}})
        mgr.handle_state_set({"data": {"path": "x.z", "value": 2, "source": "s"}})
        result = mgr.handle_state_get_subtree({"data": {"path": "x", "request_id": "req-rev"}})
        assert result["status"] == "ok"
        assert result["revision"] == mgr.store.revision == 2

    def test_get_subtree_with_paths_uses_snapshot(self):
        """Ф4.9b, ADR-SS-015: data.paths (список glob-паттернов) → TreeStore.snapshot.

        Существующий канал state.get_subtree переиспользуется для resync — вместо
        одного литерального 'path' можно передать 'paths' (glob-паттерны, как
        в state.subscribe), сервер строит объединённый снимок.
        """
        mgr = StateStoreManager(
            initial_state={
                "cameras": {"0": {"fps": 30}, "1": {"fps": 25}},
                "renderer": {"theme": "dark"},
            }
        )
        result = mgr.handle_state_get_subtree({"data": {"paths": ["cameras.*.fps"], "request_id": "req-resync"}})
        assert result["status"] == "ok"
        assert result["value"] == {"cameras": {"0": {"fps": 30}, "1": {"fps": 25}}}
        assert result["revision"] == mgr.store.revision

    def test_get_subtree_paths_takes_priority_over_path(self):
        """Если задан 'paths' — используется snapshot, 'path' игнорируется."""
        mgr = StateStoreManager(initial_state={"cameras": {"0": {"fps": 30}}})
        result = mgr.handle_state_get_subtree(
            {"data": {"path": "renderer", "paths": ["cameras.**"], "request_id": "req"}}
        )
        assert result["status"] == "ok"
        assert result["value"] == {"cameras": {"0": {"fps": 30}}}


class TestStateStoreManagerSubscriptions:
    """Тесты handle_state_subscribe / unsubscribe / unsubscribe_all."""

    def test_subscribe(self):
        """Создание подписки."""
        mgr = StateStoreManager()
        result = mgr.handle_state_subscribe(
            {
                "data": {"pattern": "cameras.*", "subscriber": "gui"},
            }
        )
        assert result["status"] == "ok"
        assert "sub_id" in result
        assert mgr.subscription_manager.subscription_count == 1

    def test_subscribe_with_exclude(self):
        """Подписка с exclude_sources."""
        mgr = StateStoreManager()
        result = mgr.handle_state_subscribe(
            {
                "data": {
                    "pattern": "cameras.*",
                    "subscriber": "gui",
                    "exclude_sources": ["gui"],
                },
            }
        )
        assert result["status"] == "ok"

    def test_subscribe_missing_fields(self):
        """Подписка без обязательных полей — ошибка."""
        mgr = StateStoreManager()
        result = mgr.handle_state_subscribe({"data": {"pattern": "cameras.*"}})
        assert result["status"] == "error"

    def test_subscribe_initial_replay_sends_snapshot(self):
        """Initial replay: при subscribe подписчику адресно уходит снимок текущих листьев."""
        router = MockRouter()
        mgr = StateStoreManager(
            router=router,
            initial_state={"processes": {"camera_0": {"state": {"status": "running", "uptime": 12.5}}}},
        )
        result = mgr.handle_state_subscribe({"data": {"pattern": "processes.**", "subscriber": "gui"}})
        assert result["status"] == "ok"
        # Ровно одно state.changed, адресно gui
        assert len(router.sent_messages) == 1
        msg = router.sent_messages[0]
        assert msg["command"] == "state.changed"
        assert msg["targets"] == ["gui"]
        paths = {d["path"] for d in msg["data"]["deltas"]}
        assert "processes.camera_0.state.status" in paths
        assert "processes.camera_0.state.uptime" in paths
        # Только листья — промежуточный dict-узел не реплеится
        assert "processes.camera_0.state" not in paths

    def test_subscribe_replay_empty_when_no_match(self):
        """Нет значений по pattern → реплей-сообщение не отправляется."""
        router = MockRouter()
        mgr = StateStoreManager(router=router, initial_state={"cameras": {"0": {"fps": 30}}})
        result = mgr.handle_state_subscribe({"data": {"pattern": "processes.**", "subscriber": "gui"}})
        assert result["status"] == "ok"
        assert router.sent_messages == []

    def test_subscribe_replay_no_router_ok(self):
        """Без router subscribe не падает (реплей best-effort, тихо пропускается)."""
        mgr = StateStoreManager(initial_state={"processes": {"camera_0": {"state": {"status": "running"}}}})
        result = mgr.handle_state_subscribe({"data": {"pattern": "processes.**", "subscriber": "gui"}})
        assert result["status"] == "ok"

    def test_subscribe_replay_deltas_carry_current_revision(self):
        """Ф4.9a: реплей-дельты несут revision дерева на момент реплея.

        Даёт клиенту (StateProxy._check_and_handle_revision_gap) корректную
        базу отсчёта для watch-from-revision сразу с первого сообщения.
        """
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 30, "source": "s"}})
        mgr.handle_state_set({"data": {"path": "cameras.0.type", "value": "usb", "source": "s"}})
        assert mgr.store.revision == 2

        result = mgr.handle_state_subscribe({"data": {"pattern": "cameras.**", "subscriber": "gui"}})
        assert result["status"] == "ok"

        replay_msg = router.sent_messages[-1]
        assert replay_msg["command"] == "state.changed"
        assert replay_msg["data"]["revision"] == 2
        for d in replay_msg["data"]["deltas"]:
            assert d["revision"] == 2

    def test_replay_by_prefix_equivalent_to_full_tree(self):
        """0.3: реплей по префиксу эквивалентен прежнему get_subtree('')+iter_matches.

        Проверяем ОБА случая — узкий (статический) и wildcard паттерн: множество
        отправленных (path, value) совпадает с эталоном, посчитанным старым
        алгоритмом (полное дерево + iter_matches, фильтр не-dict).
        """
        from multiprocess_framework.modules.state_store_module.core.glob_walker import iter_matches

        initial = {
            "processes": {
                "cam": {"state": {"fps": 30, "status": "running"}},
                "cam2": {"state": {"fps": 24}},
            },
            "system": {"health": {"active": 2}},
        }

        for pattern in ("processes.cam.state.fps", "processes.**", "processes.*.state.fps", "**"):
            router = MockRouter()
            mgr = StateStoreManager(router=router, initial_state=initial)

            # Эталон: старое поведение (полное дерево).
            whole = mgr.store.get_subtree("")
            expected = {(p, v) for p, v in iter_matches(whole, pattern) if not isinstance(v, dict)}

            router.sent_messages.clear()
            mgr.handle_state_subscribe({"data": {"pattern": pattern, "subscriber": "gui"}})

            got: set = set()
            for msg in router.sent_messages:
                if msg.get("command") == "state.changed":
                    for d in msg["data"]["deltas"]:
                        got.add((d["path"], d["new_value"]))

            assert got == expected, f"pattern={pattern}: реплей разошёлся с эталоном"

    def test_replay_narrow_pattern_does_not_copy_root(self):
        """0.3: подписка на узкий паттерн НЕ вызывает get_subtree('') (копию корня)."""
        router = MockRouter()
        mgr = StateStoreManager(
            router=router,
            initial_state={"processes": {"cam": {"state": {"fps": 30}}}},
        )

        calls: list[str] = []
        real_get_subtree = mgr.store.get_subtree

        def spy(path):
            calls.append(path)
            return real_get_subtree(path)

        mgr.store.get_subtree = spy  # type: ignore[method-assign]
        try:
            mgr.handle_state_subscribe({"data": {"pattern": "processes.cam.state.fps", "subscriber": "gui"}})
        finally:
            mgr.store.get_subtree = real_get_subtree  # type: ignore[method-assign]

        # Полностью статический паттерн: корень не копируется вовсе (точечный get).
        assert "" not in calls, f"get_subtree('') не должен вызываться, calls={calls}"

    def test_replay_wildcard_copies_prefix_not_root(self):
        """0.3: wildcard-паттерн копирует поддерево префикса, а не корень."""
        router = MockRouter()
        mgr = StateStoreManager(
            router=router,
            initial_state={
                "processes": {"cam": {"state": {"fps": 30}}},
                "system": {"health": {"active": 1}},
            },
        )

        calls: list[str] = []
        real_get_subtree = mgr.store.get_subtree

        def spy(path):
            calls.append(path)
            return real_get_subtree(path)

        mgr.store.get_subtree = spy  # type: ignore[method-assign]
        try:
            mgr.handle_state_subscribe({"data": {"pattern": "processes.**", "subscriber": "gui"}})
        finally:
            mgr.store.get_subtree = real_get_subtree  # type: ignore[method-assign]

        assert calls == ["processes"], f"ожидался единственный get_subtree('processes'), calls={calls}"

    def test_unsubscribe(self):
        """Отписка по sub_id."""
        mgr = StateStoreManager()
        sub_result = mgr.handle_state_subscribe(
            {
                "data": {"pattern": "cameras.*", "subscriber": "gui"},
            }
        )
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
            "state.set",
            "state.merge",
            "state.delete",
            "state.get",
            "state.get_subtree",
            "state.subscribe",
            "state.unsubscribe",
            "state.unsubscribe_all",
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
        assert len(router.registered_handlers) == 8
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
        sub_result = mgr.handle_state_subscribe(
            {
                "data": {"pattern": "cameras.**", "subscriber": "processor"},
            }
        )
        assert sub_result["status"] == "ok"

        # 2. Устанавливаем значение
        set_result = mgr.handle_state_set(
            {
                "data": {"path": "cameras.0.fps", "value": 30, "source": "gui"},
            }
        )
        assert set_result["status"] == "ok"
        assert set_result["changed"] is True

        # 3. Проверяем что processor получил state.changed
        assert len(router.sent_messages) == 1
        msg = router.sent_messages[0]
        assert msg["command"] == "state.changed"
        assert msg["targets"] == ["processor"]

        # 4. Читаем обратно
        get_result = mgr.handle_state_get(
            {
                "data": {"path": "cameras.0.fps", "request_id": "check-1"},
            }
        )
        assert get_result["value"] == 30

    def test_merge_and_subscribe_flow(self):
        """merge + подписка: несколько дельт в одном сообщении."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.initialize()

        # Подписываем
        mgr.handle_state_subscribe(
            {
                "data": {"pattern": "cameras.**", "subscriber": "monitor"},
            }
        )

        # Merge нескольких полей
        mgr.handle_state_merge(
            {
                "data": {
                    "path": "cameras.0",
                    "data": {"fps": 30, "type": "webcam", "enabled": True},
                    "source": "recipe",
                },
            }
        )

        # Одно сообщение с 3 дельтами
        assert len(router.sent_messages) == 1
        assert len(router.sent_messages[0]["data"]["deltas"]) == 3

    def test_unsubscribe_stops_delivery(self):
        """После отписки дельты не доставляются."""
        router = MockRouter()
        mgr = StateStoreManager(router=router)
        mgr.initialize()

        # Подписываем и тут же отписываем
        sub_result = mgr.handle_state_subscribe(
            {
                "data": {"pattern": "x.*", "subscriber": "gui"},
            }
        )
        mgr.handle_state_unsubscribe({"data": {"sub_id": sub_result["sub_id"]}})

        # set не вызывает рассылку
        mgr.handle_state_set({"data": {"path": "x.y", "value": 42, "source": "test"}})
        assert len(router.sent_messages) == 0


class TestHandleStateGetSubtreeAtomicRevision:
    """Ф4.9-фикс (MED-5, ревью 2026-07-11): value и revision в ответе
    state.get_subtree read'ятся атомарно — конкурентная мутация НЕ может
    попасть в revision, не попав при этом в value (и наоборот).
    """

    def test_atomic_read_blocks_concurrent_mutation(self):
        """Конкурентный state.set во время handle_state_get_subtree не просачивается
        в revision раньше, чем в сам snapshot — ответ всегда самосогласован."""
        import threading
        from unittest.mock import patch

        from multiprocess_framework.modules.state_store_module.core import tree_store as tree_store_module

        mgr = StateStoreManager(initial_state={"cameras": {"0": {"fps": 30}}})

        entered_snapshot = threading.Event()
        release_mutation = threading.Event()
        mutation_done = threading.Event()

        orig_deep_copy = tree_store_module._deep_copy

        def slow_deep_copy(value):
            result = orig_deep_copy(value)
            if not entered_snapshot.is_set():
                entered_snapshot.set()
                release_mutation.wait(timeout=2.0)
            return result

        def mutate():
            entered_snapshot.wait(timeout=2.0)
            mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 999, "source": "camera_0"}})
            mutation_done.set()

        thread = threading.Thread(target=mutate)
        thread.start()
        try:
            with patch.object(tree_store_module, "_deep_copy", side_effect=slow_deep_copy):
                result = mgr.handle_state_get_subtree({"data": {"path": "cameras.0", "request_id": "req-atomic"}})
        finally:
            release_mutation.set()
            thread.join(timeout=2.0)

        # value и revision относятся к одному и тому же моменту: revision=0 (до
        # конкурентной мутации) ⇔ value ещё несёт старое fps=30. Раньше (раздельные
        # локи) конкурентный set() мог успеть повысить revision до 1, пока value
        # (снятый чуть раньше) всё ещё показывал fps=30 — рассинхронизация.
        assert result["status"] == "ok"
        assert result["value"] == {"fps": 30}
        assert result["revision"] == 0

        assert mutation_done.wait(timeout=2.0)
        assert mgr.store.revision == 1
        assert mgr.store.get("cameras.0.fps") == 999
