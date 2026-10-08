# -*- coding: utf-8 -*-
"""interfaces.py — Protocol-контракты backend_ctl (правило проекта №2).

Структурные контракты (PEP 544 :class:`typing.Protocol`) для трёх ролей driver'а.
Не наследуются — служат явной документацией контракта и точкой типизации для
потребителей (MCP-сервер, harness), устойчивой к распилу ``driver.py`` (Phase C):
реализация может переехать между модулями, контракт остаётся здесь.

  * :class:`ISubscriptionRegistry` — реестр durable-намерений (``subscriptions.py``);
  * :class:`IEventSource` — событийный канал push-сообщений (``events_page`` внутри driver);
  * :class:`IBackendClient` — ядро TCP-клиента: соединение + request-response +
    команды + durable-подписки (``BackendDriver``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

EventCallback = Any  # Callable[[Dict[str, Any]], None] — избегаем циклов импорта


@runtime_checkable
class ISubscriptionRegistry(Protocol):
    """Реестр durable-намерений подписки: пережить реконнект без молчаливой потери."""

    def add(self, command: str, target: str, args: Dict[str, Any]) -> None:
        """Запомнить намерение подписки; повторный вызов с тем же ключом перезаписывает запись.

        Ключ — ``(command, target, pattern|subscriber из args)``; ``args`` сохраняется копией."""
        ...

    def remove(self, command: str, target: str, args: Optional[Dict[str, Any]] = None) -> None:
        """Снять намерение; отсутствующее — игнорируется.

        При ``args=None`` снимаются все намерения с данными ``command`` + ``target``."""
        ...

    def remove_by_command(self, command: str) -> None:
        """Снять все намерения команды ``command`` по всем ``target``."""
        ...

    def export(self) -> List[Dict[str, Any]]:
        """Снимок намерений: список ``{command, target, args}`` (копии, реестр не меняется)."""
        ...

    def load(self, intents: List[Dict[str, Any]]) -> None:
        """Загрузить намерения (формат ``export``) через ``add``; ``None``/пустой список — ничего не делает."""
        ...


@runtime_checkable
class IEventSource(Protocol):
    """Событийный канал: push-сообщения без reply (state.changed / observability.record).

    ``events_page`` — курсорное недеструктивное чтение по плоскостям (B.1) — ЕДИНСТВЕННЫЙ
    публичный способ читать события; легаси-деструктивный дренаж ``events()`` удалён (F.1).
    """

    def subscribe(self, callback: EventCallback) -> EventCallback:
        """Подписать ``callback`` на каждое push-сообщение; вернуть его же (хэндл для ``unsubscribe``).

        Колбэк вызывается синхронно в reader-потоке — должен быть лёгким."""
        ...

    def unsubscribe(self, callback: EventCallback) -> None:
        """Отписать ранее зарегистрированный ``callback``; если его нет — ничего не делает."""
        ...

    def events_page(
        self,
        plane: Optional[str] = None,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Страница событий плоскости от курсора, недеструктивное чтение.

        Args:
            plane: имя плоскости или ``None``/``"all"`` — все события в порядке прихода.
            cursor: ``next_cursor``/``bookmark`` прошлой страницы; ``None`` — с самого старого доступного.
            limit: максимум событий в странице (по умолчанию 100, потолок 500).

        Returns:
            dict ``{"success": True, "items", "count", "next_cursor", "dropped", "bookmark", ...}``.
            Ошибка курсора → ``success: False`` с ``reset_required`` (начать заново с ``cursor=None``);
            неизвестная плоскость или нецелый ``limit`` → ``success: False`` с текстом ``error``."""
        ...


@runtime_checkable
class IBackendClient(Protocol):
    """Ядро driver'а: соединение + request-response + команды + durable-подписки.

    Контракт, на который опираются потребители (MCP-сервер через DriverSession,
    harness). Не перечисляет все доменные обёртки — только несущий каркас клиента.
    """

    def connect(self, timeout: float = 5.0) -> None:
        """Открыть TCP-соединение с бэкендом и запустить reader-поток.

        Raises:
            OSError: хост недоступен за ``timeout`` секунд (состояние не меняется).
        Post: новая сессия (``subscriber`` обновлён), соединение считается живым."""
        ...

    def close(self) -> None:
        """Закрыть соединение намеренно; повторный вызов безопасен.

        Ожидающие ``request`` возвращают error-dict ``connection closed`` (не исключение)."""
        ...

    def request(self, message: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """Отправить сообщение и дождаться ответа по ``request_id`` (блокирует); вернуть ответ-dict.

        Таймаут, «не подключён» и намеренный ``close`` — error-dict ``{"success": False, "error": ...}``.
        Смерть соединения — исключение (в ``BackendDriver`` — ``BackendUnavailable``).
        Вызов из reader-потока отклоняется error-dict (защита от дедлока)."""
        ...

    def send_command(
        self,
        target: str,
        command: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Отправить команду ``command`` процессу ``target`` с аргументами ``args`` и вернуть ответ.

        Собирает сообщение команды и отправляет через ``request``; ошибки — как у ``request``."""
        ...

    def export_subscriptions(self) -> List[Dict[str, Any]]:
        """Снимок durable-намерений подписки (список ``{command, target, args}``) для передачи новому клиенту."""
        ...

    def import_subscriptions(self, intents: List[Dict[str, Any]]) -> None:
        """Загрузить durable-намерения (после реконнекта) в реестр этого клиента.

        ``subscriber`` собственного адреса перенацеливается на текущую сессию; на бэкенд ничего не отправляется."""
        ...

    def replay_subscriptions(self) -> List[Dict[str, Any]]:
        """Повторить записанные подписки на текущем соединении (после реконнекта).

        Returns:
            список ``{command, target, success}`` по каждому намерению; реестр не меняется."""
        ...


__all__ = ["ISubscriptionRegistry", "IEventSource", "IBackendClient"]
