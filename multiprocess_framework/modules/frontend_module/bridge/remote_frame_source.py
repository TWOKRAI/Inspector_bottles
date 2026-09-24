"""remote_frame_source.py — кадры бэкенда во внешнем процессе (Task 1.3, gui-service).

Два конца одного протокола «мост кадров»:

* **хост** — процесс ``gui`` в воплощении ``BridgeGuiProcess`` (прототип): вычерпывает
  data-очередь, как headless, и на каждый кадровый конверт шлёт подписчикам маленький
  **дескриптор** (имя слота SHM, не пиксели) router-пушем ``frames.frame`` — путём
  ui_tap (``RouterPushChannel`` → relay хаба → ``SocketChannel`` → сокет клиента);
* **клиент** — :class:`RemoteFrameSource` (Qt-free) поверх ``SocketClient``: принимает
  дескриптор, открывает слот SHM по имени, копирует кадр в свой буфер и отдаёт колбэку.

Пиксели сокет не пересекают: оба процесса на одной машине, кадр читается из того же
сегмента, куда его положил продюсер. Поэтому читатель обязан **не удалять чужой
сегмент** на своём выходе — ``ShmFrameReader(track=False)``.

Команды хоста (``targets=[<имя процесса gui>]``, ``data`` — dict)
--------------------------------------------------------------------
``frames.subscribe {"subscriber": <адрес>, "senders": [<имя>, ...] | None}``
    Успех — РОВНО ``{"success": True, "seqlock": bool, "owner_incarnation": bool}``
    (значения флагов ``FW_SHM_SEQLOCK`` / ``FW_SHM_OWNER_INCARNATION`` хоста).
    Отказ — ``{"success": False, "reason": str}``; при включённом на хосте
    ``FW_SHM_LOAN_PROTOCOL`` ``reason`` содержит подстроку ``"FW_SHM_LOAN_PROTOCOL"``
    (заём слота мост не возвращает — Task 2.1).
``frames.unsubscribe {"subscriber": <адрес>}``
``frames.stats {}`` — счётчики отправленного по адресам.

Push хоста подписчику
---------------------
``{"type": "event", "targets": [<адрес>], "queue_type": "observability",
"command": "frames.frame", "sender": <имя процесса gui>, "data": <дескриптор>}``.

Дескриптор — dict ровно с ключами :data:`DESCRIPTOR_KEYS` (см. :func:`build_frame_descriptor`).
``display_id``, ``shape``, ``dtype`` в нём нет намеренно: дисплей Пульт вычисляет из
``sender`` по рецепту, форма и тип лежат в заголовке слота.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional

from multiprocess_framework.modules.shared_resources_module.memory.reader import ShmFrameReader

if TYPE_CHECKING:
    import numpy as np

    from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient

#: Команда подписки на дескрипторы кадров (хост — процесс ``gui``).
FRAMES_SUBSCRIBE: str = "frames.subscribe"
#: Команда снятия подписки; её же брокер наблюдаемости шлёт при смерти сессии.
FRAMES_UNSUBSCRIBE: str = "frames.unsubscribe"
#: Поле ``command`` push-сообщения с дескриптором.
FRAMES_PUSH: str = "frames.frame"
#: Команда чтения счётчиков моста.
FRAMES_STATS: str = "frames.stats"
#: Ключи дескриптора — ровно эти, в этом порядке, никаких других.
DESCRIPTOR_KEYS: tuple = ("sender", "name", "idx", "seqlock", "bseq", "ts")
#: Потолок размера дескриптора: ``len(json.dumps(descriptor).encode()) <= 300``.
DESCRIPTOR_MAX_BYTES: int = 300

#: Имя потока копирования (виден в дампах потоков Пульта).
COPY_THREAD_NAME: str = "remote-frame-copy"

_STAT_KEYS = ("received", "delivered", "dup", "torn", "missing", "errors", "superseded")
#: LRU-кэп handle'ов при owner_incarnation: по слоту на кадр кольца, с запасом.
_HANDLE_CAP = 32
_IDLE_WAIT_SEC = 0.5
_CLOSE_JOIN_SEC = 2.0
_RESUBSCRIBE_TIMEOUT = 5.0

_log = logging.getLogger(__name__)

#: Маршалинг колбэка: принимает нуль-арную функцию и исполняет её там, где решит
#: владелец (Qt main thread через сигнал; в тестах — ``lambda fn: fn()``).
Dispatch = Callable[[Callable[[], None]], None]

#: Колбэк кадра: ``on_frame(sender, frame, bseq)``.
OnFrame = Callable[[str, "np.ndarray", int], None]


class RemoteFrameSourceError(RuntimeError):
    """Хост отказал в подписке или не ответил.

    ``str(exc)`` содержит ``reason`` хоста дословно (при отказе из-за
    ``FW_SHM_LOAN_PROTOCOL`` — подстроку ``"FW_SHM_LOAN_PROTOCOL"``), либо
    ``error`` клиента (``"timeout"``, ``"not connected"`` …).
    """


def build_frame_descriptor(sender: Any, data: Any, bseq: int) -> Optional[Dict[str, Any]]:
    """Дескриптор кадра из ``data`` data-конверта, либо ``None``, если это не кадр.

    Pre:  ``sender`` — ``msg["sender"]`` конверта (имя продюсера); ``data`` — ``msg["data"]``
          (что угодно); ``bseq`` — int, номер дескриптора моста.
    Post: ``None``, если ``data`` не dict либо в нём нет непустой строки
          ``"shm_actual_name"`` (кадр ушёл не через SHM — описывать нечего);
          либо ``sender`` не непустая строка.
          Иначе dict с ключами РОВНО :data:`DESCRIPTOR_KEYS` в этом порядке:

          * ``"sender"``  — ``sender`` (str);
          * ``"name"``    — ``data["shm_actual_name"]`` (str, имя слота SHM);
          * ``"idx"``     — ``int(data["shm_index"])``, либо ``None``, если ключа нет;
          * ``"seqlock"`` — ``bool(data.get("shm_seqlock", False))``;
          * ``"bseq"``    — ``int(bseq)``;
          * ``"ts"``      — ``time.time()`` в момент построения (float, секунды эпохи).

          Остальные поля ``data`` (``owner``, ``shm_name``, ``width`` …) не копируются.
          Для ``sender`` и ``name`` длиной ≤ 64 ASCII-символа
          ``len(json.dumps(result).encode()) <= DESCRIPTOR_MAX_BYTES``.
          Не бросает: любой неподходящий вход — ``None``.
    """
    if not isinstance(sender, str) or not sender or not isinstance(data, dict):
        return None
    name = data.get("shm_actual_name")
    if not isinstance(name, str) or not name:
        return None
    try:
        raw_idx = data.get("shm_index")
        idx = None if raw_idx is None else int(raw_idx)
        seq = int(bseq)
    except (TypeError, ValueError):
        return None
    return {
        "sender": sender,
        "name": name,
        "idx": idx,
        "seqlock": bool(data.get("shm_seqlock", False)),
        "bseq": seq,
        "ts": time.time(),
    }


class RemoteFrameSource:
    """Подписчик на кадры процесса ``gui`` поверх одного :class:`SocketClient`.

    Один экземпляр на клиент: хост хранит подписку по адресу
    ``client.subscriber_address``, повторный ``subscribe`` ЗАМЕНЯЕТ фильтр и колбэк.

    Потоки
    ------
    * reader-поток клиента (push-слушатель) — только разбор дескриптора и запись в
      почтовый ящик; SHM не трогает, колбэк не зовёт.
    * собственный поток копирования (daemon, имя ``"remote-frame-copy"``) — открытие
      слота по имени, копия кадра, дедупликация, вызов ``dispatch``.
    * колбэк ``on_frame`` исполняется там, где его исполнит ``dispatch``; сам источник
      зовёт ``dispatch`` только со своего потока копирования, никогда с reader-потока
      клиента и никогда из ``subscribe``/``unsubscribe``.

    Почтовый ящик: не больше одного необработанного дескриптора на ``sender``
    (latest-wins) — новый дескриптор того же ``sender`` вытесняет необработанный.
    Медленный колбэк поэтому теряет кадры, но не копит очередь и не тормозит продюсера.

    Счётчики (:attr:`stats`)
    -------------------------
    * ``received``  — push'ей ``frames.frame``, принятых при активной подписке
      (push при отсутствии подписки игнорируется и не считается);
    * ``delivered`` — кадров, переданных в ``dispatch`` (передано, а не «колбэк отработал»);
    * ``dup``       — дескрипторов, пропущенных дедупликацией: ``bseq`` равен ``bseq``
      последнего доставленного кадра того же ``sender``, либо (при ``seqlock``) пара
      (имя слота, поколение) равна паре последнего доставленного кадра того же ``sender``;
    * ``torn``      — чтений при ``seqlock=True``, вернувших ``None`` (слот перезаписан во
      время копии — кадр отброшен);
    * ``missing``   — слотов, которых нет (``FileNotFoundError`` при открытии по имени);
      не исключение наружу — счётчик и строка лога, следующий дескриптор обрабатывается;
    * ``errors``    — всё прочее: дескриптор без нужных ключей, иное исключение чтения,
      ``None`` без ``seqlock``, исключение самого ``dispatch``;
    * ``superseded`` — дескрипторов, вытесненных из ящика новым дескриптором того же
      ``sender`` до того, как поток копирования их забрал (latest-wins); сюда же —
      выброшенные из ящика или из обработки снятием подписки, повторным ``subscribe``
      или ``on_reconnected`` (иначе они навсегда остались бы вне инварианта).

    Инвариант (в любой момент, снимок :attr:`stats`):
    ``received == delivered + dup + torn + missing + errors + superseded + in_flight``,
    где ``in_flight`` — дескрипторы, принятые, но ещё не отнесённые ни к одному счётчику
    (лежат в ящике или обрабатываются потоком копирования), не больше одного в ящике на
    ``sender`` плюс один в обработке. В покое (писатель остановлен, поток копирования
    всё разобрал) ``in_flight == 0``.
    """

    def __init__(
        self,
        client: "SocketClient",
        *,
        dispatch: Dispatch,
        target: str = "gui",
        logger: Any = None,
    ) -> None:
        """Pre:  ``client`` — ``SocketClient`` (подключённость в конструкторе НЕ требуется);
              ``dispatch`` — callable, принимающий нуль-арную функцию; ``target`` — имя
              процесса-хоста моста (``targets`` команд ``frames.*``).
        Post: push-слушатель зарегистрирован в клиенте ровно один раз
              (``client.add_push_listener``); ни одного сетевого вызова, ни одного
              потока, ни одного открытого сегмента; все счётчики :attr:`stats` = 0;
              подписки нет.
        """
        self._client = client
        self._dispatch = dispatch
        self._target = target
        self._log = logger if logger is not None else _log
        # Одна Condition на всё разделяемое: ящик, счётчики, подписку. Reader-поток клиента
        # держит её только на запись в ящик; SHM и dispatch — всегда ВНЕ неё.
        self._cond = threading.Condition()
        self._mailbox: Dict[str, Dict[str, Any]] = {}
        self._stats: Dict[str, int] = dict.fromkeys(_STAT_KEYS, 0)
        self._active = False
        self._senders: Optional[List[str]] = None
        self._on_frame: Optional[OnFrame] = None
        # Эпоха подписки: subscribe/unsubscribe/on_reconnected её сдвигают — кадр,
        # прочитанный в старой эпохе, до dispatch не доходит.
        self._epoch = 0
        # sender → (bseq, имя слота, поколение) последнего доставленного кадра (дедуп).
        self._last: Dict[str, tuple] = {}
        self._reader: Optional[ShmFrameReader] = None
        self._reader_cached: Optional[bool] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        client.add_push_listener(self._on_push)

    def subscribe(
        self,
        senders: Optional[Iterable[str]],
        on_frame: OnFrame,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Подписаться на кадры (блокирует до ответа хоста).

        Pre:  клиент подключён (``client.subscriber_address is not None``); вызов НЕ с
              reader-потока клиента; ``senders`` — имена продюсеров либо ``None`` (все);
              ``on_frame(sender: str, frame: np.ndarray, bseq: int)``.
        Действие: ``client.request`` с сообщением
              ``{"type": "command", "sender": <адрес>, "targets": [target],
              "command": "frames.subscribe", "data": {"subscriber": <адрес>,
              "senders": list(senders) | None}}``, где ``<адрес>`` =
              ``client.subscriber_address``.
        Post (успех): возвращает ответ хоста
              ``{"success": True, "seqlock": bool, "owner_incarnation": bool}``;
              подписка активна: каждый последующий push ``frames.frame`` читается и
              доставляется ``on_frame`` через ``dispatch`` как ``(descriptor["sender"],
              frame, descriptor["bseq"])``, где ``frame`` — СОБСТВЕННАЯ копия кадра
              (не view в SHM; ``shape``/``dtype`` — из заголовка слота), побитово равная
              содержимому слота на момент копии. Поток копирования запущен. Кэш
              handle'ов SHM включён, только если хост ответил ``owner_incarnation=True``
              (иначе open/close на каждый кадр). Сегменты открываются
              ``ShmFrameReader(track=False)`` — выход процесса-читателя сегмент хоста
              не удаляет. Повторный вызов заменяет фильтр и колбэк.
        Raises: :class:`RemoteFrameSourceError` — хост ответил ``success`` не ``True``
              (текст содержит его ``reason``) либо клиент вернул error-dict (таймаут,
              не подключён); подписка после этого НЕ активна.
              Исключение разрыва клиента (``client._lost_exc``) пробрасывается как есть.
        """
        address = self._client.subscriber_address
        if address is None:
            raise RemoteFrameSourceError("RemoteFrameSource.subscribe: клиент не подключён")
        senders_list = None if senders is None else [str(s) for s in senders]
        try:
            reply = self._request_subscribe(address, senders_list, timeout)
        except BaseException:
            self._deactivate()
            raise
        with self._cond:
            self._senders = senders_list
            self._on_frame = on_frame
            self._begin_epoch_locked()
            self._ensure_reader_locked(bool(reply.get("owner_incarnation")))
            self._active = True
            self._ensure_thread_locked()
        return reply

    def unsubscribe(self, timeout: float = 5.0) -> None:
        """Снять подписку. Не бросает.

        Post: локально подписка снята ДО сетевого вызова: ящик очищен, последующие
              push'и игнорируются и не считаются, ``dispatch`` больше не зовётся для
              кадров, прочитанных после возврата; хосту отправлен ``frames.unsubscribe``
              ``{"subscriber": client.subscriber_address}`` (отказ/таймаут/разрыв —
              строка лога, не исключение). Без активной подписки — ни одного сетевого
              вызова. Счётчики не сбрасываются. Идемпотентен.
        """
        address = self._client.subscriber_address
        if not self._deactivate():
            return
        message = {
            "type": "command",
            "sender": address,
            "targets": [self._target],
            "command": FRAMES_UNSUBSCRIBE,
            "data": {"subscriber": address},
        }
        try:
            reply = _unwrap(self._client.request(message, timeout=timeout))
        except Exception as exc:  # noqa: BLE001 — контракт: не бросает
            self._warn(f"RemoteFrameSource.unsubscribe: хост не ответил: {exc!r}")
            return
        if not isinstance(reply, dict) or reply.get("success") is not True:
            self._warn(f"RemoteFrameSource.unsubscribe: хост отказал: {reply!r}")

    def on_reconnected(self) -> None:
        """Восстановить подписку после ``client.connect()`` с новым ``session``.

        Вызывает владелец соединения (протокол реконнекта ``socket_client``, шаг 4),
        не reader-поток.

        Pre:  клиент подключён заново (``client.subscriber_address`` — новый адрес).
        Post: если подписка была активна — хосту отправлен ``frames.subscribe`` с НОВЫМ
              ``subscriber_address`` и прежним ``senders``; колбэк прежний (подписчик
              ничего не перерегистрирует); ящик очищен; память дедупликации сброшена
              (хост мог перезапуститься — ``bseq`` начинается заново); кэш handle'ов
              закрыт (сегменты могли пересоздаться); включение кэша — по новому ответу.
              Без активной подписки — ни одного сетевого вызова.
        Raises: :class:`RemoteFrameSourceError` — хост отказал (подписка после этого не
              активна); исключение разрыва клиента пробрасывается.
        """
        with self._cond:
            if not self._active:
                return
            senders_list = self._senders
            # Хост мог перезапуститься: bseq начинается заново, сегменты пересозданы.
            self._begin_epoch_locked()
            self._last.clear()
            reader, self._reader, self._reader_cached = self._reader, None, None
        if reader is not None:
            reader.close()
        address = self._client.subscriber_address
        if address is None:
            self._deactivate()
            raise RemoteFrameSourceError("RemoteFrameSource.on_reconnected: клиент не подключён")
        try:
            reply = self._request_subscribe(address, senders_list, _RESUBSCRIBE_TIMEOUT)
        except BaseException:
            self._deactivate()
            raise
        with self._cond:
            self._ensure_reader_locked(bool(reply.get("owner_incarnation")))

    def close(self) -> None:
        """Освободить ресурсы. Не бросает, идемпотентен.

        Post: ``unsubscribe()`` выполнен; поток копирования остановлен (join с дедлайном
              ≤ 2 с); все handle'ы SHM закрыты (сегменты хоста НЕ удалены); последующие
              push'и игнорируются. Клиент НЕ закрывается — им владеет вызывающий.
        """
        try:
            self.unsubscribe()
        except Exception as exc:  # noqa: BLE001 — контракт: не бросает
            self._warn(f"RemoteFrameSource.close: unsubscribe упал: {exc!r}")
        with self._cond:
            self._stop = True
            self._cond.notify_all()
            thread, reader = self._thread, self._reader
            self._thread, self._reader, self._reader_cached = None, None, None
        if thread is not None and thread is not threading.current_thread():
            # Дедлайн: колбэк, исполняемый dispatch'ем прямо на потоке копирования, может
            # спать сколько угодно — close() его не ждёт дольше.
            thread.join(_CLOSE_JOIN_SEC)
        if reader is not None:
            reader.close()

    @property
    def stats(self) -> Dict[str, int]:
        """Снимок счётчиков: dict ровно с ключами ``received``, ``delivered``, ``dup``,
        ``torn``, ``missing``, ``errors``, ``superseded`` (int ≥ 0, монотонны). Новый dict на каждый вызов.
        """
        with self._cond:
            return dict(self._stats)

    # ------------------------------------------------------------------ внутреннее

    def _warn(self, text: str) -> None:
        try:
            self._log.warning(text)
        except Exception:  # noqa: BLE001 — лог не должен ронять поток копирования
            pass

    def _request_subscribe(self, address: str, senders_list: Optional[List[str]], timeout: float) -> Dict[str, Any]:
        message = {
            "type": "command",
            "sender": address,
            "targets": [self._target],
            "command": FRAMES_SUBSCRIBE,
            "data": {"subscriber": address, "senders": senders_list},
        }
        reply = _unwrap(self._client.request(message, timeout=timeout))
        if not isinstance(reply, dict) or reply.get("success") is not True:
            reason = reply.get("reason") or reply.get("error") if isinstance(reply, dict) else None
            raise RemoteFrameSourceError(f"frames.subscribe отклонён хостом '{self._target}': {reason or reply!r}")
        return reply

    def _begin_epoch_locked(self) -> None:
        """Новая эпоха: всё, что лежит в ящике, выброшено (superseded — инвариант)."""
        self._epoch += 1
        self._stats["superseded"] += len(self._mailbox)
        self._mailbox.clear()

    def _deactivate(self) -> bool:
        """Снять подписку локально; ``True`` — она была активна."""
        with self._cond:
            was_active = self._active
            self._active = False
            self._begin_epoch_locked()
            return was_active

    def _ensure_reader_locked(self, cached: bool) -> None:
        # Кэш handle'ов — только при owner_incarnation (иначе realloc под тем же именем
        # оставил бы нас на старом сегменте). track=False: сегмент хоста не наш.
        if self._reader is not None and self._reader_cached == cached:
            return
        old = self._reader
        self._reader = ShmFrameReader(cache_enabled=cached, zero_copy=False, cap=_HANDLE_CAP, track=False)
        self._reader_cached = cached
        if old is not None:
            old.close()

    def _ensure_thread_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._copy_loop, name=COPY_THREAD_NAME, daemon=True)
        self._thread.start()

    def _on_push(self, msg: Dict[str, Any]) -> None:
        """Reader-поток клиента: только ящик (O(1) под lock), ни SHM, ни колбэка."""
        if msg.get("command") != FRAMES_PUSH:
            return
        with self._cond:
            if not self._active:
                return
            self._stats["received"] += 1
            descriptor = msg.get("data")
            sender = descriptor.get("sender") if isinstance(descriptor, dict) else None
            if not isinstance(sender, str) or not sender:
                self._stats["errors"] += 1
                return
            if sender in self._mailbox:
                self._stats["superseded"] += 1
                del self._mailbox[sender]  # в конец — очередь sender'ов по свежести
            self._mailbox[sender] = descriptor
            self._cond.notify()

    def _copy_loop(self) -> None:
        while True:
            with self._cond:
                while not self._stop and not self._mailbox:
                    self._cond.wait(_IDLE_WAIT_SEC)
                if self._stop:
                    return
                sender = next(iter(self._mailbox))
                descriptor = self._mailbox.pop(sender)
                epoch, on_frame, reader = self._epoch, self._on_frame, self._reader
            try:
                outcome = self._process(sender, descriptor, epoch, on_frame, reader)
            except Exception as exc:  # noqa: BLE001 — поток копирования не умирает
                self._warn(f"RemoteFrameSource: сбой обработки кадра '{sender}': {exc!r}")
                outcome = "errors"
            with self._cond:
                self._stats[outcome] += 1

    def _process(self, sender: str, descriptor: Dict[str, Any], epoch: int, on_frame: Any, reader: Any) -> str:
        """Один дескриптор → имя счётчика, в который он попал."""
        name = descriptor.get("name")
        bseq = descriptor.get("bseq")
        seqlock = bool(descriptor.get("seqlock"))
        if not isinstance(name, str) or not name or not isinstance(bseq, int) or on_frame is None or reader is None:
            return "errors"
        last = self._last.get(sender)
        if last is not None and last[0] == bseq:
            return "dup"
        meta: Dict[str, Any] = {}
        try:
            frame = reader.read_frame(name, seqlock=seqlock, copy=True, view_meta=meta)
        except FileNotFoundError:
            self._warn(f"RemoteFrameSource: слота '{name}' нет (sender={sender}, bseq={bseq})")
            return "missing"
        if frame is None:
            return "torn" if seqlock else "errors"
        gen = int(meta.get("_shm_generation", -1)) if seqlock else -1
        if gen >= 0 and last is not None and last[1] == name and last[2] == gen:
            return "dup"
        with self._cond:
            if epoch != self._epoch:
                return "superseded"  # подписку сняли/заменили, пока копировали
            self._last[sender] = (bseq, name, gen)
        self._dispatch(lambda: on_frame(sender, frame, bseq))
        return "delivered"


def _unwrap(reply: Any) -> Any:
    """Ответ обработчика из конверта ``request``: ``{"success", "result": {...}}`` → ``result``."""
    while isinstance(reply, dict) and "seqlock" not in reply and isinstance(reply.get("result"), dict):
        reply = reply["result"]
    return reply


__all__ = [
    "DESCRIPTOR_KEYS",
    "DESCRIPTOR_MAX_BYTES",
    "FRAMES_PUSH",
    "FRAMES_STATS",
    "FRAMES_SUBSCRIBE",
    "FRAMES_UNSUBSCRIBE",
    "Dispatch",
    "OnFrame",
    "RemoteFrameSource",
    "RemoteFrameSourceError",
    "build_frame_descriptor",
]
