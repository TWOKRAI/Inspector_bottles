"""remote_command_sender.py — :class:`CommandSender` поверх сокета (Task 1.2, gui-service).

Контракт-в-коде (module-contract, уровень lite).

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
Она регистрируется в клиенте через ``client.add_send_middleware`` и штампует только
исходящие с ``sender == name`` — команды этого отправителя (F2). ``state.*`` прокси
(``sender`` — адрес соединения) не штампуются: хост перештамповывает ``_fence`` у всего
трафика, входящего через сокет, своим (ревью 1.2, проверено вживую).
Форма на проводе: ``_fence = {"sender": name, "inc": int, "epoch": int|None}``.
Отказ stale-команд внешнего отправителя этим НЕ обеспечивается (у детей нет PSR-записи
внешнего клиента → легаси-проход) — вне задачи, G1b.

Источник inc/epoch при ``fence=None`` — ответ ``supervision.status`` хоста, перечитанный
:meth:`refresh_fence`: ``epoch = reply["epoch"]``, ``inc = reply["processes"][name]["incarnation"]``.
Если ``name`` хосту не известен (нет в ``processes`` — штатный случай для внешнего
клиента, которого супервизор не запускал) — штамп ставится с ``inc=0`` и эпохой хоста
(решение лида, Task 1.2 GREEN): без штампа Пульт не держал бы паритет структуры с
встроенным GUI (AC3). ``inc=0`` у получателя — «самый старый инстанс»: fence-фильтр
дочернего процесса знает incarnation только тех, кто есть в его PSR, внешнего там нет →
легаси-проход, отказа нет (G1b). Неудачный refresh (F1) — ``(None, None)``, штампа нет.

Инварианты
----------
F1. После :meth:`refresh_fence` ни одно исходящее не несёт inc/epoch, прочитанные до него:
    неудачный refresh сбрасывает fence в ``(None, None)`` (не штамповать), а не оставляет старый.
    Пара привязана к ``client.session``, на котором её прочли: после ``connect()`` (новый
    session) провайдер отдаёт ``(None, None)``, пока не пройдёт следующий refresh.
F2. Несколько ``RemoteCommandSender`` на одном клиенте не перетирают штампы друг друга:
    каждый middleware штампует только сообщения со своим ``sender`` (и сообщения без
    ``sender`` — у них владельца нет, остаётся штамп последнего зарегистрированного).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from multiprocess_framework.modules.frontend_module.bridge.command_sender import CommandSender
from multiprocess_framework.modules.logger_module import get_std_logger
from multiprocess_framework.modules.message_module import build_command_message
from multiprocess_framework.modules.message_module.fencing.token import (
    FenceProvider,
    make_fence_stamp_middleware,
)
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient

_logger = get_std_logger(__name__)

# Имя процесса-хоста, у которого спрашиваем supervision.status (паритет с дефолтом
# ``server_target`` у StateProxy — хост внешнего GUI и есть ProcessManager).
_HOST_PROCESS = "ProcessManager"
_REFRESH_TIMEOUT = 5.0


class _ClientRequester:
    """``router_manager`` для :class:`CommandSender`: ``request(msg, timeout)`` → клиент."""

    def __init__(self, client: SocketClient) -> None:
        self._client = client

    def request(self, msg: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        return self._client.request(msg, timeout=timeout)


class _SocketProcess:
    """«Процесс» под ``CommandSender`` (``IRequestingProcess``) поверх :class:`SocketClient`.

    ``target`` в ``send_message`` не нужен: адрес уже лежит в ``targets`` билета, его
    разводит роутер хоста.
    """

    def __init__(self, client: SocketClient, name: str) -> None:
        self.name = name
        self._client = client
        self.router_manager = _ClientRequester(client)

    def send_message(self, target: str, msg: Dict[str, Any]) -> None:
        self._client.send_nowait(msg)


class RemoteCommandSender(CommandSender):
    """``CommandSender``, чей транспорт — :class:`SocketClient`.

    Всё публичное (``send_command``, ``send_field_command``, ``send_action_command``,
    ``flush``, ``send_system_command``, ``request_command``, ``request_system_command``)
    унаследовано: сигнатуры и возвращаемые значения — как у ``CommandSender``.
    Форма ошибок ОТЛИЧАЕТСЯ от ``CommandSender`` поверх очередей (решение — Task 1.4):
      * разрыв соединения — исключение ``client._lost_exc`` (``SocketConnectionLost``), а не
        error-dict: встроенный GUI такого исключения не видит никогда;
      * таймаут/не подключён/намеренный ``close`` — error-dict клиента
        ``{"success": False, "error": "timeout"|"not connected"|"connection closed",
        "request_id": ...}`` (у ``RouterManager.request`` ключ ``correlation_id``);
      * отказ на хосте — конверт хоста как есть (``{"success": False, "error": ...}``);
      * ``send_command``/``send_system_command`` при разрыве поднимают ``_lost_exc``, при
        отсутствии соединения — ``ConnectionError`` (``send_nowait``); на очередях — тихо.
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
        super().__init__(_SocketProcess(client, name))
        self._client = client
        self._name = name
        self._fixed_fence = fence
        # (session, inc, epoch): пара действительна только на соединении, где её прочли.
        self._fence_state: Tuple[Optional[str], Optional[int], Optional[int]] = (None, None, None)
        provider: FenceProvider = fence if fence is not None else self._current_fence
        stamp = make_fence_stamp_middleware(name, provider)

        def _stamp_own(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            # F2: чужой sender (второй отправитель, state.* прокси) — не наш штамп.
            # Сообщение БЕЗ sender (сырой send_nowait владельца клиента) штампуется —
            # так его пинит приёмочный тест F1; с двумя отправителями на таком
            # сообщении останется штамп последнего зарегистрированного.
            sender = msg.get("sender")
            return stamp(msg) if sender is None or sender == name else msg

        client.add_send_middleware(_stamp_own)

    def _current_fence(self) -> Tuple[Optional[int], Optional[int]]:
        # Кортеж подменяется целиком (одно присваивание) — читатель на любом потоке
        # видит либо старую, либо новую пару, но не смесь.
        session, inc, epoch = self._fence_state
        if session is None or session != self._client.session:
            return None, None  # пара прочитана на другом соединении (или не прочитана)
        return inc, epoch

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
              ``name`` хосту не известен → ``(0, epoch)`` (см. «Fence» в докстринге модуля).
        """
        if self._fixed_fence is not None:
            return
        # F1: сбросить ДО запроса — пока ответа нет, старая пара уже не штампуется.
        self._fence_state = (None, None, None)
        # Сессия — ДО запроса: ответ относится к соединению, на котором ушёл запрос.
        session = self._client.session
        msg = build_command_message(_HOST_PROCESS, "supervision.status", {}, sender=self._name)
        try:
            envelope = self._client.request(msg, timeout=_REFRESH_TIMEOUT)
        except self._client._lost_exc:
            raise
        except Exception as exc:  # noqa: BLE001 — отказ refresh = «не штамповать» (F1)
            _logger.warning("RemoteCommandSender.refresh_fence: запрос не удался: %s", exc)
            return
        state = self._parse_status(envelope)
        if state is None:
            _logger.warning("RemoteCommandSender.refresh_fence: нет inc/epoch в ответе: %r", envelope)
            return
        self._fence_state = (session, *state)

    def _parse_status(self, envelope: Any) -> Optional[Tuple[int, Optional[int]]]:
        """Конверт ``{"success", "result": {"epoch", "processes"}}`` → ``(inc, epoch)`` | None."""
        if not isinstance(envelope, dict) or envelope.get("success") is False:
            return None
        status = envelope.get("result", envelope)
        if not isinstance(status, dict):
            return None
        processes = status.get("processes")
        if "epoch" not in status or not isinstance(processes, dict):
            return None
        epoch = status["epoch"]
        if not isinstance(epoch, int) or isinstance(epoch, bool):
            epoch = None  # эпоха на проводе — int|None (только диагностика)
        entry = processes.get(self._name)
        inc = entry.get("incarnation") if isinstance(entry, dict) else None
        if not isinstance(inc, int) or isinstance(inc, bool):
            inc = 0  # хост не знает имя (внешний клиент) — штамп с inc=0 (решение лида)
        return inc, epoch


__all__ = ["RemoteCommandSender"]
