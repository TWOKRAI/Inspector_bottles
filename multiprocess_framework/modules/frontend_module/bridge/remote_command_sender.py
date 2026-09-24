"""remote_command_sender.py — :class:`CommandSender` поверх сокета (Task 1.2, gui-service).

Контракт-в-коде (module-contract, уровень lite). Стадия INTERFACE: тела методов
``raise NotImplementedError``.

Назначение
----------
Внешний GUI (Пульт) шлёт команды тем же объектом, что встроенный: ``RemoteCommandSender``
— подкласс :class:`CommandSender`, поэтому ``isinstance(x, CommandSender)`` у виджетов
истинно, а debounce, PM-relay и билдеры протокола наследуются без изменений.
Отличие одно — «процесс» под ``CommandSender`` не очередь, а адаптер над
:class:`SocketClient` (удовлетворяет ``IRequestingProcess``):
    ``send_message(target, msg)``        → ``client.send_nowait(msg)``;
    ``router_manager.request(msg, timeout)`` → ``client.request(msg, timeout)``.
Qt-free.

Fence (паритет СТРУКТУРЫ со штампом дочернего процесса, вердикт cto 2026-09-24)
-------------------------------------------------------------------------------
Штамп ставит импортированная ``make_fence_stamp_middleware(name, provider)`` — не копия.
Она регистрируется в клиенте через ``client.add_send_middleware`` и потому штампует ВСЁ
исходящее этого соединения (как process-level middleware встроенного GUI — включая
``state.*``). Форма на проводе: ``_fence = {"sender": name, "inc": int, "epoch": int|None}``.
Отказ stale-команд внешнего отправителя этим НЕ обеспечивается (у детей нет PSR-записи
внешнего клиента → легаси-проход) — вне задачи, G1b.

Источник inc/epoch при ``fence=None`` — ответ ``supervision.status`` хоста, перечитанный
:meth:`refresh_fence`: ``epoch = reply["epoch"]``, ``inc = reply["processes"][name]["incarnation"]``.
Если ``name`` хосту не известен (нет в ``processes``) — ``inc is None`` → фабрика НЕ штампует
(её fail-open), сообщения уходят без ``_fence``.

Инварианты
----------
F1. После :meth:`refresh_fence` ни одно исходящее не несёт inc/epoch, прочитанные до него:
    неудачный refresh сбрасывает fence в ``(None, None)`` (не штамповать), а не оставляет старый.
F2. Один клиент — одна fence-идентичность: второй ``RemoteCommandSender`` на том же клиенте
    добавит второй middleware, и на проводе останется штамп последнего зарегистрированного.
"""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.bridge.command_sender import CommandSender
from multiprocess_framework.modules.message_module.fencing.token import FenceProvider
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient


class RemoteCommandSender(CommandSender):
    """``CommandSender``, чей транспорт — :class:`SocketClient`.

    Всё публичное (``send_command``, ``send_field_command``, ``send_action_command``,
    ``flush``, ``send_system_command``, ``request_command``, ``request_system_command``)
    унаследовано: сигнатуры и возвращаемые значения — как у ``CommandSender``.
    ``request_*`` возвращают конверт ``RouterManager.request`` хоста
    (``{"success": ..., "result"|"error": ...}``) и БЛОКИРУЮТ — не с Qt main thread и
    не с reader-потока клиента (там — guard error-dict, см. ``SocketClient.request``).
    """

    def __init__(
        self,
        client: SocketClient,
        *,
        name: str,
        fence: FenceProvider | None = None,
    ) -> None:
        """Pre:  ``name`` — непустое имя отправителя (поле ``sender`` команд и ``_fence.sender``);
              ``client`` может быть ещё не подключён.
        Post: ``self._process.name == name``; fence-middleware зарегистрирован в клиенте
              (ровно один на экземпляр); при ``fence=None`` провайдер отдаёт ``(None, None)``
              до первого :meth:`refresh_fence` (сообщения не штампуются); при заданном
              ``fence`` провайдер — он сам, а :meth:`refresh_fence` — no-op.
        Ни одного сетевого вызова в конструкторе.
        """
        raise NotImplementedError

    def refresh_fence(self) -> None:
        """Перечитать inc/epoch из ``supervision.status`` хоста (блокирующий request).

        Вызывать после КАЖДОГО ``client.connect()`` до первой команды (протокол реконнекта —
        докстринг ``socket_client``).

        Pre:  клиент подключён; вызов не с reader-потока и не с Qt main thread.
        Post: успех → провайдер отдаёт ``(processes[name].incarnation | None, epoch)`` из ответа;
              любой отказ (error-dict, таймаут, нет полей) → провайдер отдаёт ``(None, None)``
              (F1), исключение наружу не летит — КРОМЕ ``SocketConnectionLost``/``_lost_exc``
              клиента, который пробрасывается (владелец соединения обязан его увидеть).
              При заданном в конструкторе ``fence`` — no-op, сети не трогает.
        """
        raise NotImplementedError


__all__ = ["RemoteCommandSender"]
