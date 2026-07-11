"""test_watch_from_revision.py — приёмочный тест Ф4.9 (watch-from-revision + resync).

Сквозной сценарий (StateStoreManager + StateProxy, связанные через один
роутер-тестер): симулируется потеря ОДНОГО сообщения state.changed (как при
реальном сетевом сбое/переполнении очереди). StateProxy обнаруживает разрыв
по revision, самостоятельно ресинкается через существующий канал
state.get_subtree (ADR-SS-015) и сходится с серверной истиной — БЕЗ участия
внешнего кода (никто не вызывает resync вручную).

Критерий приёмки (план Ф4.9):
    "пропущенная дельта → resync, кэш сходится": подписчик пропускает одну
    дельту, детектит разрыв по revision, ресинкается, финальное состояние
    кэша == серверному.
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
    StateStoreManager,
)
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy


class _RelayRouter:
    """Тестовый роутер: доставляет сообщения синхронно между mgr и proxy.

    Умеет один раз «потерять» исходящее state.changed (drop_next_state_changed)
    — симуляция сетевого сбоя/переполнения очереди, единственный способ
    воспроизвести пропуск дельты для watch-from-revision теста.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, object] = {}
        self.dropped: list[dict] = []
        self.sent: list[dict] = []
        self._drop_next_changed = False

    def register_message_handler(self, key, handler, expects_full_message=True) -> None:
        self._handlers[key] = handler

    def drop_next_state_changed(self) -> None:
        self._drop_next_changed = True

    def resync_requests(self) -> list[dict]:
        """Запросы state.get_subtree с data.paths — именно они уходят из _resync()."""
        return [m for m in self.sent if m.get("command") == "state.get_subtree" and "paths" in m.get("data", {})]

    def _dispatch_key(self, message: dict) -> str | None:
        return message.get("command") or message.get("type")

    def send_async(self, message: dict, priority: str = "normal") -> None:
        self.sent.append(message)
        if message.get("command") == "state.changed" and self._drop_next_changed:
            self._drop_next_changed = False
            self.dropped.append(message)
            return  # симуляция потери — подписчик НЕ получает это сообщение
        handler = self._handlers.get(self._dispatch_key(message))
        if handler is not None:
            handler(message)

    def send(self, message: dict):
        self.sent.append(message)
        handler = self._handlers.get(self._dispatch_key(message))
        if handler is not None:
            return handler(message)
        return None


def _wire_manager_and_proxy() -> tuple[StateStoreManager, StateProxy, _RelayRouter]:
    router = _RelayRouter()
    mgr = StateStoreManager(router=router, initial_state={})
    mgr.initialize()  # регистрирует все state.* handlers (включая state.changed НЕ трогает)

    proxy = StateProxy("gui", router=router, server_target="ProcessManager")
    router.register_message_handler("state.changed", proxy.on_state_changed)
    return mgr, proxy, router


def test_dropped_delta_triggers_resync_and_cache_converges():
    """Пропущенная дельта → StateProxy детектит разрыв revision → resync → кэш сходится."""
    mgr, proxy, router = _wire_manager_and_proxy()

    proxy.subscribe("cameras.0.**", lambda _deltas: None, exclude_self=False)

    # Мутация №1 — доставлена нормально. revision=1.
    mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 10, "source": "camera_0"}})
    assert proxy.get("cameras.0.fps") == 10
    assert proxy._last_revision == 1

    # Мутация №2 — симулируем потерю сообщения state.changed. revision=2 на
    # сервере применена, но proxy её никогда не увидит.
    router.drop_next_state_changed()
    mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 20, "source": "camera_0"}})
    assert len(router.dropped) == 1
    # Кэш proxy НЕ обновился (сообщение потеряно) — всё ещё старое значение.
    assert proxy.get("cameras.0.fps") == 10
    assert proxy._last_revision == 1

    # Мутация №3 — доставлена нормально, но revision=3 (не 2, как proxy ждёт)
    # → разрыв обнаружен здесь.
    mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 30, "source": "camera_0"}})

    # Финальное состояние кэша сошлось с сервером — несмотря на пропущенную
    # промежуточную дельту (20), которую proxy никогда не видел напрямую.
    assert proxy.get("cameras.0.fps") == mgr.store.get("cameras.0.fps") == 30
    assert proxy._last_revision == mgr.store.revision == 3
    # Ресинк реально произошёл ровно один раз (по факту разрыва).
    assert len(router.resync_requests()) == 1


def test_no_loss_no_resync_needed():
    """Контроль: без потери сообщений revision растёт последовательно, resync не требуется."""
    mgr, proxy, router = _wire_manager_and_proxy()
    proxy.subscribe("cameras.0.**", lambda _deltas: None, exclude_self=False)

    mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 10, "source": "camera_0"}})
    mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 20, "source": "camera_0"}})
    mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 30, "source": "camera_0"}})

    assert proxy.get("cameras.0.fps") == 30
    assert proxy._last_revision == mgr.store.revision == 3
    # Ни одного запроса на ресинк за весь сценарий.
    assert router.resync_requests() == []


def test_dropped_delta_on_unrelated_sibling_path_also_converges():
    """Разрыв обнаруживается и по мутациям СОСЕДНЕГО пути под тем же pattern."""
    mgr, proxy, router = _wire_manager_and_proxy()
    proxy.subscribe("cameras.0.**", lambda _deltas: None, exclude_self=False)

    mgr.handle_state_set({"data": {"path": "cameras.0.fps", "value": 10, "source": "camera_0"}})
    assert proxy.get("cameras.0.fps") == 10

    router.drop_next_state_changed()
    mgr.handle_state_set({"data": {"path": "cameras.0.type", "value": "usb", "source": "camera_0"}})

    mgr.handle_state_set({"data": {"path": "cameras.0.state.status", "value": "running", "source": "camera_0"}})

    # resync подтягивает ВСЁ поддерево cameras.0.** — включая пропущенное type.
    assert proxy.get("cameras.0.fps") == 10
    assert proxy.get("cameras.0.type") == "usb"
    assert proxy.get("cameras.0.state.status") == "running"
    assert proxy._last_revision == mgr.store.revision == 3
