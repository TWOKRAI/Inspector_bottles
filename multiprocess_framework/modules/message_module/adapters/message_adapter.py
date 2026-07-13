# -*- coding: utf-8 -*-
"""
MessageAdapter — контекстно-зависимая фабрика сообщений для процессов/менеджеров.

Роль в архитектуре:
    ProcessModule / Manager  →  MessageAdapter  →  Message.create()

Адаптер предоставляет:
  - Фиксированный sender (имя процесса/менеджера) — не надо указывать каждый раз.
  - Методы-шаблоны: command(), log(), event(), system(), request(), response(),
    broadcast(), data() — единый стиль создания сообщений во всей системе.
  - Валидацию (is_valid / validate) перед отправкой.

Что НЕ делает адаптер:
  - Не отправляет сообщения — это зона RouterManager.
  - Не знает о каналах и маршрутах.

Пример использования в процессе:
    from multiprocess_framework.modules.message_module import MessageAdapter

    class MyProcess:
        def __init__(self, name):
            self.msg = MessageAdapter(sender=name)

        def on_start(self):
            self.router.send(self.msg.command(
                targets=["orchestrator"],
                command="ready",
                args={"pid": os.getpid()},
            ))

        def on_error(self, err):
            self.router.send(self.msg.log("error", str(err)))
"""

from typing import Any, Dict, List, Optional, Union

from ..core.message import Message
from ..types.message_types import MessageType, Priority, LogLevel


class MessageAdapter:
    """Контекстно-зависимая фабрика сообщений.

    Создаётся один раз для каждого процесса/менеджера
    и используется для создания всех его исходящих сообщений.

    Attrs:
        sender: Имя отправителя (process/manager name), фиксируется при создании.
    """

    def __init__(self, sender: str) -> None:
        """
        Args:
            sender: Имя процесса или менеджера, от имени которого
                    будут создаваться сообщения.
        """
        if not sender:
            raise ValueError("MessageAdapter: sender cannot be empty")
        self._sender = sender

    # =========================================================================
    # Базовый метод создания
    # =========================================================================

    def create(
        self,
        msg_type: Union[MessageType, str],
        targets: Union[List[str], str],
        **kwargs: Any,
    ) -> Message:
        """Создать сообщение произвольного типа от имени этого sender'а.

        Args:
            msg_type: MessageType enum или строка ('command', 'log', ...).
            targets:  Список получателей или одна строка.
            **kwargs: Дополнительные поля сообщения.

        Returns:
            Новый экземпляр Message.
        """
        if isinstance(targets, str):
            targets = [targets]
        return Message.create(msg_type, sender=self._sender, targets=targets, **kwargs)

    # =========================================================================
    # Методы-шаблоны по типу сообщения
    # =========================================================================

    def command(
        self,
        targets: Union[List[str], str],
        command: str,
        args: Optional[Dict[str, Any]] = None,
        need_ack: bool = False,
        priority: Union[Priority, str] = "normal",
        **kwargs: Any,
    ) -> Message:
        """Создать COMMAND сообщение — команда для выполнения действия.

        Единый конверт команд (Ф7 G.2, решение владельца 2026-07-09): payload
        кладётся под ключ ``data`` (как ``command_envelopes.build_command_message``),
        а НЕ под отдельный ``args`` — исторические два формата (args vs data)
        сведены к одному. Получатели читают payload из ``data`` (диспетчер
        ``data_field="data"``); ``sql_manager._normalize_command`` больше не нужен.

        Args:
            targets:  Получатели команды.
            command:  Имя команды (например, 'start', 'stop', 'ping').
            args:     Аргументы команды (едут под ``data``).
            need_ack: True если требуется подтверждение исполнения.
            priority: Приоритет доставки.

        Returns:
            Message с type='command' и payload под ``data``.
        """
        return self.create(
            MessageType.COMMAND,
            targets=targets,
            command=command,
            data_type=command,
            data=args or {},
            need_ack=need_ack,
            priority=priority,
            **kwargs,
        )

    def log(
        self,
        level: Union[LogLevel, str],
        message: str,
        module: Optional[str] = None,
        **kwargs: Any,
    ) -> Message:
        """Создать LOG сообщение — запись в централизованный лог.

        Args:
            level:   LogLevel enum или строка ('debug','info','warning','error','critical').
            message: Текст лог-записи.
            module:  Модуль/компонент источника (по умолчанию — sender).

        Returns:
            Message с type='log', targets=['logger'], channel='log'.
        """
        return self.create(
            MessageType.LOG,
            targets=["logger"],
            level=level if isinstance(level, str) else level.value,
            message=message,
            module=module or self._sender,
            **kwargs,
        )

    def system(
        self,
        targets: Union[List[str], str],
        action: str,
        data: Any = None,
        priority: Union[Priority, str] = "high",
        **kwargs: Any,
    ) -> Message:
        """Создать SYSTEM сообщение — управление жизненным циклом.

        Args:
            targets:  Получатели (обычно 'orchestrator' или конкретный процесс).
            action:   Системное действие ('shutdown', 'restart', 'status', ...).
            data:     Дополнительные данные действия.
            priority: Приоритет (по умолчанию 'high').

        Returns:
            Message с type='system'.
        """
        return self.create(
            MessageType.SYSTEM,
            targets=targets,
            action=action,
            data=data,
            priority=priority,
            **kwargs,
        )

    def broadcast(
        self,
        content: Any,
        exclude: Optional[List[str]] = None,
        priority: Union[Priority, str] = "normal",
        **kwargs: Any,
    ) -> Message:
        """Создать BROADCAST сообщение — рассылка всем процессам.

        Args:
            content: Содержимое рассылки.
            exclude: Список получателей для исключения.
            priority: Приоритет.

        Returns:
            Message с type='broadcast', targets=['all'].
        """
        return self.create(
            MessageType.BROADCAST,
            targets=["all"],
            content=content,
            exclude=exclude or [],
            priority=priority,
            **kwargs,
        )

    def data(
        self,
        targets: Union[List[str], str],
        data_type: str,
        data: Any = None,
        use_shared_memory: bool = False,
        memory_key: Optional[str] = None,
        **kwargs: Any,
    ) -> Message:
        """Создать DATA сообщение — передача данных (возможно через shared memory).

        Args:
            targets:            Получатели.
            data_type:          Тип данных ('frame', 'tensor', 'result', ...).
            data:               Данные (если не shared memory).
            use_shared_memory:  True → передавать через shared memory.
            memory_key:         Ключ в shared memory (если use_shared_memory=True).

        Returns:
            Message с type='data'.
        """
        return self.create(
            MessageType.DATA,
            targets=targets,
            data_type=data_type,
            data=data,
            use_shared_memory=use_shared_memory,
            memory_key=memory_key,
            **kwargs,
        )

    def request(
        self,
        targets: Union[List[str], str],
        request_type: str,
        query: Any = None,
        timeout: float = 5.0,
        **kwargs: Any,
    ) -> Message:
        """Создать REQUEST сообщение — запрос с ожиданием ответа.

        Args:
            targets:      Получатель запроса.
            request_type: Тип запроса ('get_status', 'get_config', ...).
            query:        Параметры запроса.
            timeout:      Таймаут ожидания ответа (секунды).

        Returns:
            Message с type='request'. Используй msg.id как correlation_id.
        """
        return self.create(
            MessageType.REQUEST,
            targets=targets,
            request_type=request_type,
            query=query,
            timeout=timeout,
            **kwargs,
        )

    def response(
        self,
        targets: Union[List[str], str],
        request_id: str,
        result: Any = None,
        success: bool = True,
        error: Optional[str] = None,
        **kwargs: Any,
    ) -> Message:
        """Создать RESPONSE сообщение — ответ на REQUEST.

        Args:
            targets:    Получатель ответа (тот, кто отправил request).
            request_id: id оригинального REQUEST сообщения (correlation_id).
            result:     Результат обработки запроса.
            success:    True если запрос выполнен успешно.
            error:      Описание ошибки (если success=False).

        Returns:
            Message с type='response'.
        """
        return self.create(
            MessageType.RESPONSE,
            targets=targets,
            request_id=request_id,
            result=result,
            success=success,
            error=error,
            **kwargs,
        )

    def event(
        self,
        event_type: str,
        targets: Union[List[str], str] = "all",
        event_data: Any = None,
        **kwargs: Any,
    ) -> Message:
        """Создать EVENT сообщение — событие в стиле pub/sub.

        Args:
            event_type: Тип события ('frame_ready', 'config_changed', ...).
            targets:    Подписчики ('all' → broadcast).
            event_data: Данные события.

        Returns:
            Message с type='event'.
        """
        if isinstance(targets, str):
            targets = [targets]
        return self.create(
            MessageType.EVENT,
            targets=targets,
            event_type=event_type,
            event_data=event_data,
            **kwargs,
        )

    # =========================================================================
    # Утилиты
    # =========================================================================

    @property
    def sender(self) -> str:
        """Имя отправителя (процесса/менеджера)."""
        return self._sender

    def __repr__(self) -> str:
        return f"MessageAdapter(sender={self._sender!r})"
