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

from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Optional

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
    raise NotImplementedError


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
      ``None`` без ``seqlock``, исключение самого ``dispatch``.

    Вытеснённые из ящика дескрипторы отдельным счётчиком не ведутся:
    ``received - (delivered + dup + torn + missing + errors)`` = вытеснённые + ещё в ящике.
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
        raise NotImplementedError

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
        raise NotImplementedError

    def unsubscribe(self, timeout: float = 5.0) -> None:
        """Снять подписку. Не бросает.

        Post: локально подписка снята ДО сетевого вызова: ящик очищен, последующие
              push'и игнорируются и не считаются, ``dispatch`` больше не зовётся для
              кадров, прочитанных после возврата; хосту отправлен ``frames.unsubscribe``
              ``{"subscriber": client.subscriber_address}`` (отказ/таймаут/разрыв —
              строка лога, не исключение). Без активной подписки — ни одного сетевого
              вызова. Счётчики не сбрасываются. Идемпотентен.
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def close(self) -> None:
        """Освободить ресурсы. Не бросает, идемпотентен.

        Post: ``unsubscribe()`` выполнен; поток копирования остановлен (join с дедлайном
              ≤ 2 с); все handle'ы SHM закрыты (сегменты хоста НЕ удалены); последующие
              push'и игнорируются. Клиент НЕ закрывается — им владеет вызывающий.
        """
        raise NotImplementedError

    @property
    def stats(self) -> Dict[str, int]:
        """Снимок счётчиков: dict ровно с ключами ``received``, ``delivered``, ``dup``,
        ``torn``, ``missing``, ``errors`` (int ≥ 0, монотонны). Новый dict на каждый вызов.
        """
        raise NotImplementedError


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
