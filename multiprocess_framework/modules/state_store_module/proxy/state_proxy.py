"""state_proxy.py — Клиент StateStore для ProcessModule.

StateProxy живёт в каждом ProcessModule. Общается с StateStoreManager
через IPC (любой router, реализующий IRouter Protocol).
Кэширует подписанные пути для быстрого чтения.

IPC-протокол (Dict at Boundary):
  Отправка:  state.set / state.merge / state.subscribe / state.unsubscribe / state.get
  Получение: state.changed → on_state_changed()

ADR-SS-002: server_target — конфигурируемое имя процесса-сервера StateStore.
По умолчанию "ProcessManager" — для обратной совместимости.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable

from ...base_manager import BaseManager, ObservableMixin
from ..core.delta import MISSING, Delta
from ..interfaces import IRouter, IStateProxy

# Sentinel для отличия "default не передан" от None
_SENTINEL = object()


class StateProxy(BaseManager, ObservableMixin, IStateProxy):
    """Клиент StateStore. Создаётся в каждом ProcessModule.

    Общается с StateStoreManager через IPC (любой IRouter).
    Кэширует подписанные пути для быстрого чтения.

    Пример использования:
        proxy = StateProxy("camera_0", router=router, server_target="ProcessManager")
        router.register_message_handler("state.changed", proxy.on_state_changed)

        # Запись
        proxy.set("cameras.0.config.fps", 30)

        # Подписка
        proxy.subscribe("cameras.0.**", my_callback)

        # Чтение (из кэша или IPC fallback)
        fps = proxy.get("cameras.0.config.fps", default=25)
    """

    def __init__(
        self,
        process_name: str,
        router: IRouter | None = None,
        server_target: str = "ProcessManager",
        manager_name: str | None = None,
        logger: Any = None,
    ) -> None:
        """
        Args:
            process_name: имя этого процесса (используется как sender и subscriber).
            router: реализация IRouter для IPC (None допустимо для тестов).
            server_target: имя процесса, в котором живёт StateStoreManager.
                По умолчанию "ProcessManager" (обратная совместимость, ADR-SS-002).
            manager_name: имя для BaseManager (по умолчанию StateProxy:<process_name>).
            logger: LoggerManager или ObservableMixin-совместимый объект.
        """
        BaseManager.__init__(self, manager_name=manager_name or f"StateProxy:{process_name}")
        ObservableMixin.__init__(self, managers={"logger": logger})
        self._process_name = process_name
        self._router = router
        self._server_target = server_target
        # Кэш подписанных данных: path → значение
        self._cache: dict[str, Any] = {}
        # Реестр callbacks: sub_id → список Callable[[list[Delta]], None]
        self._callbacks: dict[str, list[Callable]] = {}
        # Список активных sub_id для shutdown cleanup
        self._sub_ids: list[str] = []

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    # -------------------------------------------------------------------
    # Свойства
    # -------------------------------------------------------------------

    @property
    def process_name(self) -> str:
        """Имя этого процесса."""
        return self._process_name

    @property
    def cache(self) -> dict[str, Any]:
        """Копия текущего кэша (только для чтения/тестов)."""
        return dict(self._cache)

    # -------------------------------------------------------------------
    # Запись
    # -------------------------------------------------------------------

    def set(self, path: str, value: Any) -> None:
        """Отправить state.set в StateStoreManager через IPC.

        Args:
            path: путь к узлу, например 'cameras.0.config.fps'.
            value: новое значение (должно быть pickle-совместимым).
        """
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.set",
            "data": {
                "path": path,
                "value": value,
                "source": self._process_name,
            },
        }
        self._send(msg)

    def merge(self, path: str, data: dict) -> None:
        """Отправить state.merge в StateStoreManager через IPC.

        Args:
            path: путь к поддереву.
            data: dict с ключами и значениями для слияния.
        """
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.merge",
            "data": {
                "path": path,
                "data": data,
                "source": self._process_name,
            },
        }
        self._send(msg)

    # -------------------------------------------------------------------
    # Чтение
    # -------------------------------------------------------------------

    def get(self, path: str, default: Any = _SENTINEL) -> Any:
        """Чтение значения. Сначала из кэша, потом IPC fallback.

        Args:
            path: путь к узлу.
            default: значение по умолчанию если путь не найден.

        Returns:
            Значение из кэша или IPC.

        Raises:
            KeyError: если путь не в кэше, default не передан, и router=None.
        """
        # Сначала проверяем кэш
        if path in self._cache:
            return self._cache[path]

        # Fallback: IPC-запрос
        if self._router is not None:
            request_id = str(uuid.uuid4())
            msg = {
                "type": "command",
                "sender": self._process_name,
                "targets": [self._server_target],
                "command": "state.get",
                "data": {
                    "path": path,
                    "request_id": request_id,
                },
            }
            response = self._send_sync(msg)
            if response is not None and response.get("status") == "ok":
                return response["value"]

        # Возвращаем default или бросаем KeyError
        if default is not _SENTINEL:
            return default

        raise KeyError(f"Путь не найден в кэше: '{path}' (router={self._router!r})")

    def get_subtree(self, path: str) -> dict:
        """Запросить поддерево через IPC.

        Args:
            path: путь к поддереву.

        Returns:
            dict с содержимым поддерева, или пустой dict при ошибке/нет router.
        """
        if self._router is None:
            return {}

        request_id = str(uuid.uuid4())
        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.get_subtree",
            "data": {
                "path": path,
                "request_id": request_id,
            },
        }
        response = self._send_sync(msg)
        if response is not None and response.get("status") == "ok":
            value = response.get("value", {})
            return value if isinstance(value, dict) else {}
        return {}

    # -------------------------------------------------------------------
    # Подписки
    # -------------------------------------------------------------------

    def subscribe(
        self,
        pattern: str,
        callback: Callable[[list[Delta]], None],
        exclude_self: bool = True,
    ) -> str:
        """Подписаться на изменения по паттерну.

        1. Отправляет state.subscribe в StateStoreManager через IPC.
        2. Регистрирует callback локально по sub_id.
        3. exclude_self=True → exclude_sources=(self._process_name,).

        Args:
            pattern: glob-паттерн пути (например 'cameras.*.config.*').
            callback: функция, вызываемая при получении дельт.
            exclude_self: исключить изменения от этого же процесса.

        Returns:
            sub_id — строка-идентификатор подписки.
        """
        exclude_sources: list[str] = [self._process_name] if exclude_self else []

        # Генерируем локальный sub_id — он может быть переопределён ответом сервера
        local_sub_id = str(uuid.uuid4())

        msg = {
            "type": "command",
            "sender": self._process_name,
            "targets": [self._server_target],
            "command": "state.subscribe",
            "data": {
                "pattern": pattern,
                "subscriber": self._process_name,
                "exclude_sources": exclude_sources,
            },
        }

        # Если есть router — пробуем получить sub_id от сервера
        if self._router is not None:
            response = self._send_sync(msg)
            if response is not None and response.get("status") == "ok":
                server_sub_id = response.get("sub_id")
                if server_sub_id:
                    local_sub_id = server_sub_id
        else:
            self._log_debug(
                f"StateProxy.subscribe: router=None, подписка '{pattern}' только локальная"
            )

        # Регистрируем callback локально
        self._callbacks[local_sub_id] = [callback]
        self._sub_ids.append(local_sub_id)

        self._log_debug(
            f"StateProxy '{self._process_name}': подписка sub_id={local_sub_id}, pattern={pattern}"
        )
        return local_sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """Отписаться. Удаляет локальный callback + IPC unsubscribe.

        Args:
            sub_id: идентификатор подписки, полученный из subscribe().
        """
        # Удаляем локальный callback
        self._callbacks.pop(sub_id, None)
        if sub_id in self._sub_ids:
            self._sub_ids.remove(sub_id)

        # IPC-отписка
        if self._router is not None:
            msg = {
                "type": "command",
                "sender": self._process_name,
                "targets": [self._server_target],
                "command": "state.unsubscribe",
                "data": {"sub_id": sub_id},
            }
            self._send(msg)

    # -------------------------------------------------------------------
    # Обработка входящих сообщений
    # -------------------------------------------------------------------

    def on_state_changed(self, msg: dict) -> None:
        """Вызывается при получении state.changed от StateStoreManager.

        Регистрируется как message_handler в Router:
            router.register_message_handler("state.changed", proxy.on_state_changed)

        1. Десериализует дельты из msg["data"]["deltas"].
        2. Обновляет кэш.
        3. Вызывает все зарегистрированные callbacks.

        Args:
            msg: IPC-сообщение с полем data.deltas.
        """
        deltas = self._deserialize_deltas(msg)
        if not deltas:
            return

        self._update_cache(deltas)
        self._invoke_callbacks(deltas)

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def shutdown(self) -> bool:
        """Отписать все активные подписки.

        Отправляет state.unsubscribe_all в StateStoreManager и
        очищает локальный реестр callbacks.
        """
        if self._router is not None and self._sub_ids:
            msg = {
                "type": "command",
                "sender": self._process_name,
                "targets": [self._server_target],
                "command": "state.unsubscribe_all",
                "data": {"subscriber": self._process_name},
            }
            self._send(msg)

        self._callbacks.clear()
        self._sub_ids.clear()
        self.is_initialized = False
        self._log_debug(f"StateProxy '{self._process_name}': shutdown, все подписки удалены")
        return True

    # -------------------------------------------------------------------
    # Вспомогательные методы (используются в GuiStateProxy)
    # -------------------------------------------------------------------

    def _deserialize_deltas(self, msg: dict) -> list[Delta]:
        """Десериализовать дельты из IPC-сообщения.

        Args:
            msg: IPC-сообщение state.changed.

        Returns:
            Список объектов Delta. Пустой список при ошибке или отсутствии дельт.
        """
        try:
            data = msg.get("data", {})
            raw_deltas = data.get("deltas", [])
            return [Delta.from_dict(d) for d in raw_deltas]
        except Exception as exc:
            self._log_error(
                f"StateProxy '{self._process_name}': ошибка десериализации дельт: {exc}"
            )
            return []

    def _update_cache(self, deltas: list[Delta]) -> None:
        """Обновить кэш на основе списка дельт.

        Правила:
        - delta.new_value is MISSING → удалить path из кэша
        - иначе → записать delta.new_value в кэш

        Args:
            deltas: список Delta для обновления кэша.
        """
        for delta in deltas:
            if delta.new_value is MISSING:
                # Удаление узла
                self._cache.pop(delta.path, None)
            else:
                self._cache[delta.path] = delta.new_value

    def _invoke_callbacks(self, deltas: list[Delta]) -> None:
        """Вызвать все зарегистрированные callbacks с переданными дельтами.

        Вызывается напрямую в StateProxy (synchronous).
        В GuiStateProxy переопределяется для Qt-thread-safety.

        Args:
            deltas: список Delta для передачи в callbacks.
        """
        for sub_id, cbs in list(self._callbacks.items()):
            for cb in cbs:
                try:
                    cb(deltas)
                except Exception as exc:
                    self._log_error(
                        f"StateProxy '{self._process_name}': ошибка в callback sub_id={sub_id}: {exc}"
                    )

    # -------------------------------------------------------------------
    # IPC-хелперы
    # -------------------------------------------------------------------

    def _send(self, msg: dict) -> None:
        """Отправить IPC-сообщение асинхронно (fire-and-forget).

        При router=None — только логируем (тестовый режим).

        Args:
            msg: IPC-сообщение для отправки.
        """
        if self._router is not None:
            try:
                self._router.send_async(msg, priority="normal")
            except Exception as exc:
                self._log_error(
                    f"StateProxy '{self._process_name}': ошибка отправки команды '{msg.get('command')}': {exc}"
                )
        else:
            self._log_debug(
                f"StateProxy '{self._process_name}': router=None, команда '{msg.get('command')}' не отправлена"
            )

    def _send_sync(self, msg: dict) -> dict | None:
        """Отправить IPC-сообщение синхронно и вернуть ответ.

        При router=None или ошибке — возвращает None.

        Args:
            msg: IPC-сообщение для отправки.

        Returns:
            dict с ответом или None.
        """
        if self._router is None:
            return None
        try:
            return self._router.send(msg)
        except Exception as exc:
            self._log_error(
                f"StateProxy '{self._process_name}': ошибка синхронной отправки '{msg.get('command')}': {exc}"
            )
            return None
