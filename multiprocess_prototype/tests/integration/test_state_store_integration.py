"""Интеграционный тест end-to-end: StateStoreManager + StateProxy.

Доказывает что серверная сторона (StateStoreManager) и клиентская (StateProxy)
корректно взаимодействуют через MockBus — без реального multiprocessing/IPC.

Покрытые сценарии:
  1. initialize() регистрирует все 7 handlers
  2. Proxy.set() → Manager → state.changed → подписчик получает дельту
  3. exclude_self=True — источник НЕ получает собственные дельты
  4. Полный lifecycle камеры (как в camera/process.py:63-81)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest

from multiprocess_prototype.state_store.bootstrap import build_initial_state
from multiprocess_prototype.state_store.core.delta import Delta
from multiprocess_prototype.state_store.manager.state_store_manager import StateStoreManager
from multiprocess_prototype.state_store.proxy.state_proxy import StateProxy


# ---------------------------------------------------------------------------
# MockBus — расширенный mock-роутер для интеграции нескольких Proxy
# ---------------------------------------------------------------------------

class MockBus:
    """Синхронная шина сообщений, заменяющая RouterManager в тестах.

    Умеет:
    - register_message_handler(topic, handler) — несколько подписчиков на один topic
    - send_async(msg, priority) — синхронная доставка handler-ам по msg["command"]
    - send(msg) — синхронный вызов handler-а по msg["command"] с возвратом ответа

    Достаточно для end-to-end теста StateStoreManager + StateProxy
    без реальных процессов.
    """

    def __init__(self) -> None:
        # topic → list[handler] — несколько подписчиков на один topic
        self._handlers: dict[str, list] = defaultdict(list)
        # Лог всех отправленных сообщений (для assertions)
        self.sent_messages: list[dict] = []

    def register_message_handler(
        self,
        key: str,
        handler: Any,
        expects_full_message: bool = True,
    ) -> None:
        """Зарегистрировать обработчик на topic.

        Поддерживает несколько обработчиков на один topic
        (например state.changed для нескольких Proxy).
        """
        self._handlers[key].append(handler)

    def send_async(self, message: dict, priority: str = "normal") -> None:
        """Fire-and-forget: доставляет сообщение всем handler-ам по command.

        Для state.changed — доставка только тем процессам, которые указаны в targets.
        """
        self.sent_messages.append(message)
        command = message.get("command", "")
        targets = message.get("targets", [])

        for handler in self._handlers.get(command, []):
            # Для state.changed нужно доставлять только целевым процессам.
            # Handler — это proxy.on_state_changed, привязанный к конкретному proxy.
            # Получаем process_name из proxy через __self__ (bound method).
            if command == "state.changed" and targets:
                proxy = getattr(handler, "__self__", None)
                if proxy is not None and hasattr(proxy, "process_name"):
                    if proxy.process_name not in targets:
                        continue
            handler(message)

    def send(self, message: dict) -> dict | None:
        """Синхронный вызов: доставляет сообщение handler-у по command, возвращает ответ.

        Используется StateProxy для subscribe/get (ожидает ответ от сервера).
        Вызывает ПЕРВЫЙ зарегистрированный handler (обычно StateStoreManager).
        """
        self.sent_messages.append(message)
        command = message.get("command", "")
        handlers = self._handlers.get(command, [])
        if handlers:
            return handlers[0](message)
        return None

    @property
    def handler_keys(self) -> set[str]:
        """Множество зарегистрированных topic-ов (для assertions)."""
        return set(self._handlers.keys())


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def bus() -> MockBus:
    """Создаёт чистый MockBus."""
    return MockBus()


@pytest.fixture
def initial_state() -> dict:
    """Начальное дерево с одной камерой (camera_id=0)."""
    app_config = {
        "cameras": [
            {
                "camera_id": 0,
                "camera_type": "webcam",
                "fps": 25,
                "resolution_width": 1920,
                "resolution_height": 1080,
            }
        ],
    }
    return build_initial_state(app_config)


@pytest.fixture
def manager_and_bus(bus, initial_state):
    """StateStoreManager + MockBus, инициализированный и готовый."""
    mgr = StateStoreManager(router=bus, initial_state=initial_state)
    mgr.initialize()
    return mgr, bus


# ---------------------------------------------------------------------------
# Тест 1: initialize() регистрирует все 7 handlers
# ---------------------------------------------------------------------------

class TestManagerInitialize:
    """Проверяет что StateStoreManager.initialize() корректно регистрирует handlers."""

    def test_manager_initialize_registers_handlers(self, manager_and_bus):
        """После initialize() MockBus содержит handlers для всех 7 команд."""
        _mgr, bus = manager_and_bus
        expected_commands = {
            "state.set",
            "state.merge",
            "state.get",
            "state.get_subtree",
            "state.subscribe",
            "state.unsubscribe",
            "state.unsubscribe_all",
        }
        assert expected_commands.issubset(bus.handler_keys), (
            f"Не все команды зарегистрированы. "
            f"Ожидаемые: {expected_commands}, "
            f"Фактические: {bus.handler_keys}"
        )

    def test_each_command_has_exactly_one_handler_after_init(self, manager_and_bus):
        """Каждая из 7 команд имеет ровно один handler (от Manager)."""
        _mgr, bus = manager_and_bus
        for cmd in [
            "state.set", "state.merge", "state.get",
            "state.get_subtree", "state.subscribe",
            "state.unsubscribe", "state.unsubscribe_all",
        ]:
            assert len(bus._handlers[cmd]) == 1, (
                f"Команда '{cmd}' должна иметь 1 handler, "
                f"а имеет {len(bus._handlers[cmd])}"
            )


# ---------------------------------------------------------------------------
# Тест 2: set через Proxy → дельта доставляется подписчику
# ---------------------------------------------------------------------------

class TestSetViaPropagation:
    """camera_0 ставит fps → gui получает state.changed → proxy.get() возвращает 30."""

    def test_set_via_proxy_propagates_to_subscriber(self, manager_and_bus):
        """End-to-end: StateProxy.set() → StateStoreManager → state.changed → подписчик."""
        mgr, bus = manager_and_bus

        # --- Создаём два proxy на одном bus ---
        camera_proxy = StateProxy("camera_0", router=bus)
        gui_proxy = StateProxy("gui", router=bus)

        # Регистрируем on_state_changed для обоих proxy
        bus.register_message_handler("state.changed", camera_proxy.on_state_changed)
        bus.register_message_handler("state.changed", gui_proxy.on_state_changed)

        # --- gui подписывается на cameras.0.config.* ---
        sub_id = gui_proxy.subscribe(
            "cameras.0.config.*",
            callback=lambda deltas: None,  # callback не критичен для этого теста
            exclude_self=False,
        )
        assert sub_id, "subscribe() должен вернуть sub_id"

        # --- camera_0 устанавливает fps=30 ---
        camera_proxy.set("cameras.0.config.fps", 30)

        # --- Проверка 1: gui_proxy получил дельту в кэш ---
        assert gui_proxy.get("cameras.0.config.fps") == 30, (
            "gui_proxy должен получить fps=30 через state.changed"
        )

        # --- Проверка 2: дельта доставлена через bus ---
        changed_msgs = [
            m for m in bus.sent_messages if m.get("command") == "state.changed"
        ]
        assert len(changed_msgs) >= 1, "Должно быть хотя бы одно state.changed сообщение"

        # --- Проверка 3: targets содержит gui ---
        gui_changed = [m for m in changed_msgs if "gui" in m.get("targets", [])]
        assert gui_changed, "gui должен быть в targets state.changed"

    def test_set_updates_tree_store_directly(self, manager_and_bus):
        """set через proxy — TreeStore на сервере обновляется."""
        mgr, bus = manager_and_bus

        camera_proxy = StateProxy("camera_0", router=bus)
        camera_proxy.set("cameras.0.config.fps", 30)

        # Читаем из TreeStore напрямую
        assert mgr.store.get("cameras.0.config.fps") == 30

    def test_get_via_proxy_ipc_fallback(self, manager_and_bus):
        """Proxy.get() через IPC (не из кэша) — синхронный запрос к Manager."""
        mgr, bus = manager_and_bus

        gui_proxy = StateProxy("gui", router=bus)
        # Не подписаны, кэш пуст — get() идёт через IPC
        value = gui_proxy.get("cameras.0.config.fps", default=None)
        # initial_state содержит fps=25 от bootstrap
        assert value == 25, (
            f"get() через IPC должен вернуть 25 (из initial_state), получили {value}"
        )


# ---------------------------------------------------------------------------
# Тест 3: exclude_self — источник НЕ получает собственные дельты
# ---------------------------------------------------------------------------

class TestExcludeSelf:
    """exclude_self=True → callback НЕ вызывается для собственных изменений."""

    def test_subscribe_exclude_self_does_not_deliver_to_source(self, manager_and_bus):
        """camera_0 подписан с exclude_self=True → его callback НЕ вызывается."""
        mgr, bus = manager_and_bus

        camera_proxy = StateProxy("camera_0", router=bus)
        bus.register_message_handler("state.changed", camera_proxy.on_state_changed)

        # Счётчик вызовов callback
        call_count = {"value": 0}

        def camera_callback(deltas: list[Delta]) -> None:
            call_count["value"] += 1

        # Подписка с exclude_self=True (по умолчанию)
        camera_proxy.subscribe(
            "cameras.0.config.*",
            callback=camera_callback,
            exclude_self=True,
        )

        # camera_0 сам устанавливает значение
        camera_proxy.set("cameras.0.config.fps", 60)

        # callback НЕ должен быть вызван
        assert call_count["value"] == 0, (
            f"callback вызван {call_count['value']} раз, "
            "но при exclude_self=True не должен вызываться"
        )

    def test_subscribe_exclude_self_delivers_from_others(self, manager_and_bus):
        """camera_0 подписан с exclude_self=True → callback вызывается для чужих изменений."""
        mgr, bus = manager_and_bus

        camera_proxy = StateProxy("camera_0", router=bus)
        gui_proxy = StateProxy("gui", router=bus)

        bus.register_message_handler("state.changed", camera_proxy.on_state_changed)
        bus.register_message_handler("state.changed", gui_proxy.on_state_changed)

        received_deltas: list[Delta] = []

        def camera_callback(deltas: list[Delta]) -> None:
            received_deltas.extend(deltas)

        # camera_0 подписан с exclude_self=True
        camera_proxy.subscribe(
            "cameras.0.config.*",
            callback=camera_callback,
            exclude_self=True,
        )

        # gui устанавливает значение — camera_0 должен получить
        gui_proxy.set("cameras.0.config.fps", 45)

        assert len(received_deltas) == 1, (
            f"camera_0 должен получить 1 дельту от gui, получил {len(received_deltas)}"
        )
        assert received_deltas[0].path == "cameras.0.config.fps"
        assert received_deltas[0].new_value == 45

    def test_exclude_self_false_delivers_own_changes(self, manager_and_bus):
        """exclude_self=False → callback вызывается даже для собственных изменений."""
        mgr, bus = manager_and_bus

        camera_proxy = StateProxy("camera_0", router=bus)
        bus.register_message_handler("state.changed", camera_proxy.on_state_changed)

        call_count = {"value": 0}

        def camera_callback(deltas: list[Delta]) -> None:
            call_count["value"] += 1

        camera_proxy.subscribe(
            "cameras.0.config.*",
            callback=camera_callback,
            exclude_self=False,
        )

        camera_proxy.set("cameras.0.config.fps", 60)

        assert call_count["value"] == 1, (
            f"callback должен быть вызван 1 раз, вызван {call_count['value']}"
        )


# ---------------------------------------------------------------------------
# Тест 4: Полный lifecycle камеры (camera/process.py:63-81)
# ---------------------------------------------------------------------------

class TestCameraLifecycleSmoke:
    """Расширенный сценарий: воспроизводим реальную последовательность из CameraProcess."""

    def test_full_camera_lifecycle_smoke(self, manager_and_bus):
        """Воспроизводит инициализацию камеры из process.py:63-81.

        1. camera_0 создаёт StateProxy
        2. Регистрирует state.changed handler
        3. Подписывается на cameras.0.config.* с exclude_self=True
        4. Устанавливает cameras.0.state.status = "initialized"
        5. Проверяем: дерево содержит "initialized", подписчики получают дельту
        """
        mgr, bus = manager_and_bus
        camera_id = 0

        # Имитируем gui-подписчика (мониторинг статусов)
        gui_proxy = StateProxy("gui", router=bus)
        bus.register_message_handler("state.changed", gui_proxy.on_state_changed)

        gui_status_updates: list[Delta] = []

        def gui_status_callback(deltas: list[Delta]) -> None:
            gui_status_updates.extend(deltas)

        # gui подписывается на ВСЕ изменения камеры
        gui_proxy.subscribe(
            f"cameras.{camera_id}.**",
            callback=gui_status_callback,
            exclude_self=False,
        )

        # === Код аналогичный camera/process.py:63-81 ===
        camera_proxy = StateProxy(
            f"camera_{camera_id}", router=bus
        )
        bus.register_message_handler("state.changed", camera_proxy.on_state_changed)

        config_changes: list[Delta] = []

        def on_config_changed(deltas: list[Delta]) -> None:
            config_changes.extend(deltas)

        # Подписка на config — exclude_self, чтобы не реагировать на собственные записи
        camera_proxy.subscribe(
            f"cameras.{camera_id}.config.*",
            callback=on_config_changed,
            exclude_self=True,
        )

        # Начальная запись state
        camera_proxy.set(
            f"cameras.{camera_id}.state.status", "initialized"
        )

        # === Проверки ===

        # 1. Дерево содержит "initialized"
        assert mgr.store.get(f"cameras.{camera_id}.state.status") == "initialized", (
            "TreeStore должен содержать status=initialized"
        )

        # 2. gui получил дельту
        assert len(gui_status_updates) >= 1, "gui должен получить уведомление о смене статуса"
        status_deltas = [
            d for d in gui_status_updates if d.path == f"cameras.{camera_id}.state.status"
        ]
        assert len(status_deltas) == 1
        assert status_deltas[0].new_value == "initialized"
        assert status_deltas[0].old_value == "stopped"  # из bootstrap

        # 3. camera_0 НЕ получил config callback (т.к. set был для state, не config)
        assert len(config_changes) == 0, (
            "config callback не должен быть вызван — set был для state.status"
        )

    def test_camera_lifecycle_gui_changes_config(self, manager_and_bus):
        """gui меняет config.fps → camera_0 получает уведомление через callback."""
        mgr, bus = manager_and_bus
        camera_id = 0

        # camera_0 инициализируется
        camera_proxy = StateProxy(f"camera_{camera_id}", router=bus)
        bus.register_message_handler("state.changed", camera_proxy.on_state_changed)

        config_changes: list[Delta] = []

        def on_config_changed(deltas: list[Delta]) -> None:
            config_changes.extend(deltas)

        camera_proxy.subscribe(
            f"cameras.{camera_id}.config.*",
            callback=on_config_changed,
            exclude_self=True,
        )

        # gui меняет fps
        gui_proxy = StateProxy("gui", router=bus)
        gui_proxy.set(f"cameras.{camera_id}.config.fps", 60)

        # camera_0 получил уведомление
        assert len(config_changes) == 1
        assert config_changes[0].path == f"cameras.{camera_id}.config.fps"
        assert config_changes[0].new_value == 60
        assert config_changes[0].old_value == 25  # из bootstrap

        # camera_0 может прочитать из кэша
        assert camera_proxy.get(f"cameras.{camera_id}.config.fps") == 60

    def test_camera_set_status_then_gui_reads_via_ipc(self, manager_and_bus):
        """camera_0 пишет status → gui читает через IPC (get)."""
        mgr, bus = manager_and_bus

        camera_proxy = StateProxy("camera_0", router=bus)
        camera_proxy.set("cameras.0.state.status", "running")

        gui_proxy = StateProxy("gui", router=bus)
        # gui не подписан — читает через IPC fallback
        status = gui_proxy.get("cameras.0.state.status")
        assert status == "running"

    def test_multiple_cameras_independent(self, manager_and_bus):
        """Две камеры — подписки независимы, дельты не перепутываются."""
        mgr, bus = manager_and_bus

        # Добавим вторую камеру в дерево
        mgr.handle_state_merge({
            "data": {
                "path": "cameras.1",
                "data": {
                    "config": {"fps": 20, "camera_type": "hikvision"},
                    "state": {"status": "stopped"},
                },
                "source": "bootstrap",
            },
        })

        cam0_proxy = StateProxy("camera_0", router=bus)
        cam1_proxy = StateProxy("camera_1", router=bus)
        bus.register_message_handler("state.changed", cam0_proxy.on_state_changed)
        bus.register_message_handler("state.changed", cam1_proxy.on_state_changed)

        cam0_deltas: list[Delta] = []
        cam1_deltas: list[Delta] = []

        cam0_proxy.subscribe(
            "cameras.0.config.*",
            callback=lambda ds: cam0_deltas.extend(ds),
            exclude_self=True,
        )
        cam1_proxy.subscribe(
            "cameras.1.config.*",
            callback=lambda ds: cam1_deltas.extend(ds),
            exclude_self=True,
        )

        # gui меняет fps только camera_0
        gui_proxy = StateProxy("gui", router=bus)
        gui_proxy.set("cameras.0.config.fps", 120)

        # cam0 получил, cam1 нет
        assert len(cam0_deltas) == 1
        assert cam0_deltas[0].new_value == 120
        assert len(cam1_deltas) == 0

    def test_unsubscribe_stops_delivery(self, manager_and_bus):
        """После unsubscribe дельты больше не доставляются."""
        mgr, bus = manager_and_bus

        gui_proxy = StateProxy("gui", router=bus)
        bus.register_message_handler("state.changed", gui_proxy.on_state_changed)

        received: list[Delta] = []
        sub_id = gui_proxy.subscribe(
            "cameras.0.config.*",
            callback=lambda ds: received.extend(ds),
            exclude_self=False,
        )

        # Первая запись — должна прийти
        camera_proxy = StateProxy("camera_0", router=bus)
        camera_proxy.set("cameras.0.config.fps", 30)
        assert len(received) == 1

        # Отписка
        gui_proxy.unsubscribe(sub_id)

        # Вторая запись — не должна прийти
        camera_proxy.set("cameras.0.config.fps", 60)
        assert len(received) == 1, (
            "После unsubscribe дельты не должны приходить"
        )

    def test_shutdown_proxy_cleans_up(self, manager_and_bus):
        """Proxy.shutdown() очищает callbacks и sub_ids."""
        mgr, bus = manager_and_bus

        proxy = StateProxy("camera_0", router=bus)
        proxy.subscribe(
            "cameras.0.**",
            callback=lambda ds: None,
            exclude_self=True,
        )
        assert len(proxy._sub_ids) == 1
        assert len(proxy._callbacks) == 1

        proxy.shutdown()
        assert len(proxy._sub_ids) == 0
        assert len(proxy._callbacks) == 0
