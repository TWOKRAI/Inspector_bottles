"""
QueueRegistry — создание и доступ к очередям процессов.

PSR (ProcessStateRegistry) — единственный source of truth для Queue ссылок.
QueueRegistry делегирует хранение в PSR.

Pickle-safe: Queue ссылки живут в ProcessData (pickle-safe).
"""

import time
from multiprocessing import Queue
from typing import Any, Dict, List, Optional

from ....base_manager import BaseManager, ObservableMixin
from ....logger_module import get_std_logger
from ....logger_module.core.windowed_voice import log_windowed
from ..interfaces import IQueueRegistry
from ...mixins import ManagerStatsMixin
from ...qos import qos_for
from ...state.process_data import ProcessDataKeys

try:
    from multiprocessing.queues import Empty
except ImportError:
    from queue import Empty

from queue import Full

# Вид на процессный LoggerManager — ЕДИНСТВЕННЫЙ живой лог-канал этого файла
# (Ф6.8 — детекторы потерь; Ф6.х.3 — весь остальной класс).
#
# Штатная плоскость (``self._log_*``) здесь молчит ПО ПОСТРОЕНИЮ: ни один
# продовый вызов ``SharedResourcesManager(...)`` не передаёт logger
# (spawner.py, bundle_builder.py, process_runner.py — все три без него),
# поэтому ManagerRegistry пуст и ``_call_manager('logger', …)`` тихо возвращает
# None. Плюс ``ObservableMixin.__getstate__`` выкидывает ``_registry`` при
# pickle — даже переданный logger не пережил бы spawn. Ф6.8 оживила этим видом
# только детекторы потерь; ревью 2026-08-03 нашло в том же классе ещё 12 точек
# на мёртвой плоскости (`initialize failed`, `send_to_queue failed`,
# `Queue not found`…) — Ф6.х.3 перевела их сюда же. ``self._log_*`` в этом
# файле больше не зовётся: полкласса слышно, полкласса нет — хуже, чем ничего.
#
# Раньше здесь стоял ``logging.getLogger(__name__)``, и это был ВТОРОЙ мёртвый
# путь: у stdlib-root в процессах фреймворка нет ни одного хендлера. Итог,
# измеренный живьём: 26 тысяч событий потери и 246 вытеснений кадров → 0 строк
# во всём ``logs/``. Детектор существовал и не срабатывал никогда.
#
# Вид ``get_std_logger`` решает обе беды сразу: он не пиклится (создаётся на
# импорте в КАЖДОМ процессе) и связывается с процессным ``LoggerManager``
# лениво, на первой записи, — то есть уже после ``init_logging()``.
#
# ``fallback_name=__name__`` — чтобы в режиме «менеджера нет» запись уходила в
# stdlib-логгер с ТОЧНЫМ именем модуля, а не с префиксом ``mpf.``: иначе адрес
# записи менялся бы в зависимости от того, поднят ли менеджер.
_loss_logger = get_std_logger(__name__, fallback_name=__name__)

# Исключения в этом файле форматируются через ``%r``, а не ``%s``. Причина
# измерена ревью Ф3 (Б-6, 2026-08-05) на живом шторме: ``queue.Full``
# поднимается БЕЗ аргументов, поэтому ``%s`` давал строку
# ``send_to_queue('gui', 'system') failed:`` и пустоту после двоеточия —
# следствие без причины, класс «проглоченный сбой». ``%r`` печатает
# ``Full()``: класс назван всегда, текст добавляется когда он есть.


class QueueRegistry(BaseManager, ObservableMixin, IQueueRegistry, ManagerStatsMixin):
    """
    Реестр очередей для межпроцессного взаимодействия.

    Создаёт Queue объекты и регистрирует их в PSR.
    PSR — единственный source of truth (ADR-018).
    """

    def __init__(
        self,
        manager_name: str = "QueueRegistry",
        process: Optional[Any] = None,
        process_state_registry: Optional[Any] = None,
        logger: Optional[Any] = None,
        qos_profiles: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name, process=process)

        managers = kwargs.get("managers", {})
        if logger and "logger" not in managers:
            managers["logger"] = logger
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=kwargs.get("config", {}),
            auto_proxy=kwargs.get("auto_proxy", True),
        )

        self._process_state_registry = process_state_registry
        # Queue refs хранятся в PSR (ProcessData._queues_dict) — единственный source of truth

        # Ф7 G.4.a: решение never-drop берётся из ЕДИНОГО QoS-профиля (qos.py), а не из
        # хардкода `queue_type == "system"`. Флаг ON = источник профиль; OFF = прежний
        # хардкод (бит-в-бит). Для system/data профиль даёт тот же вердикт, поэтому флип
        # безопасен; ценность флага материализуется в G.4.b (глубина кольца = history_depth)
        # и на будущих kind. Дефолт False = откат.
        self._qos_profiles: bool = self._resolve_env_flag(qos_profiles, "FW_QOS_PROFILES")

        self._stats = {
            "created": 0,
            "registered": 0,
            "removed": 0,
            "errors": 0,
            # Ф3.3: сколько раз вытеснение из полной system-очереди было заблокировано.
            # System-команды (process.stop/heartbeat) терять нельзя. QoS-модель — Ф7 G.4.a.
            "system_evict_blocked": 0,
            # Ф7 G.4.a: сколько сообщений вытеснено из полной data-очереди (drop_oldest).
            # Всегда-on телеметрия (по образцу G.3-счётчиков): «дроп data виден в state»
            # (heartbeat → state.*). Раньше data-вытеснение было ТИХИМ (счётчика не было).
            "data_evicted": 0,
            # Ф7.3: сколько записей вытеснено из полной очереди наблюдаемости и сколько
            # раз put в неё всё-таки упал (гонка «после вытеснения снова полна»).
            # ОТДЕЛЬНЫЕ ключи, а не общий data_evicted: смешав их, нельзя ответить на
            # вопрос «теряем кадры или диагностику» — а это разные аварии.
            # Оба пути НЕ пишут записи в лог (см. _is_observability_queue).
            "observability_evicted": 0,
            "observability_send_failed": 0,
            # Ф1.4 (M17): сколько раз put не прошёл из-за полной очереди. Ключевое
            # слово — АРИФМЕТИКА: троттлинг голоса не имеет права его трогать,
            # иначе «≤1 запись на окно» и «сколько на самом деле» станут одним
            # числом, и темп потери будет не восстановить.
            "queue_full_events": 0,
        }
        # Ф1.4: ЧЕТЫРЁХ собственных окон здесь больше нет
        # (`_system_evict_*`, `_data_evict_*`, `_queue_missing_*`,
        # `_never_drop_loss_last_log`/`_since_log`). Все они были одной и той же
        # четырежды переписанной механикой «метка времени + счётчик подавленных»
        # с одинаковым 5.0 и без единой настройки. Общий механизм —
        # `ObservableMixin.should_voice` → `logger_module.core.windowed_voice`,
        # окно приходит из политики процесса
        # (`observability.voices.default_window_sec`).
        #
        # Суммарный счётчик потерь остаётся ЗДЕСЬ: он факт, а не голос, и живёт
        # за срок процесса, тогда как «подавлено с прошлой записи» — величина окна.
        self._never_drop_loss_total: int = 0
        # Ф4 Task 4.3 (plans/truth-holes-closure.md): «кто душит очередь X».
        # {"{process}_{queue_type}": {sender: {"put": n, "lost": n}}} — счётчик
        # ПОПЫТОК put ПО ОТПРАВИТЕЛЮ (put считается ДО самой отправки, поэтому это
        # attempted, а не delivered: для never-drop очередей доставлено = put − lost;
        # прочие исключения put в lost не попадают). Счётчики очереди отвечали
        # «сколько потеряно», но не «чьими сообщениями она забита» — а разбор затора
        # начинается именно с этого вопроса. Кардинальность ограничена
        # :data:`_SENDER_CARDINALITY_CAP` (сверх — общее ведро ``__other__``), чтобы
        # трафик со случайными именами отправителей не тёк в память.
        self._sender_puts: Dict[str, Dict[str, Dict[str, int]]] = {}

    @staticmethod
    def _resolve_env_flag(explicit: Optional[bool], env_name: str) -> bool:
        """Разрешить булев флаг Ф7 G.4 (ADR-SRM-012): ctor (не None) > env > default.

        Default теперь берётся из реестра feature_flags."""
        from ....config_module.feature_flags import resolve

        return resolve(env_name, explicit)

    # =========================================================================
    # Жизненный цикл
    # =========================================================================

    def initialize(self) -> bool:
        try:
            self.is_initialized = True
            _loss_logger.info("QueueRegistry '%s' initialized", self.manager_name)
            return True
        except Exception as e:
            _loss_logger.error("QueueRegistry.initialize() failed: %r", e)
            return False

    def shutdown(self) -> bool:
        try:
            self.is_initialized = False
            _loss_logger.info("QueueRegistry shutdown completed")
            return True
        except Exception as e:
            _loss_logger.error("QueueRegistry.shutdown() failed: %r", e)
            return False

    # =========================================================================
    # IQueueRegistry
    # =========================================================================

    def create_queues(
        self,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Queue]:
        """Создать Queue объекты по конфигурации."""
        if not queue_config:
            return {}
        queues: Dict[str, Queue] = {}
        try:
            for queue_type, cfg in queue_config.items():
                maxsize = cfg.get("maxsize", 0) if isinstance(cfg, dict) else 0
                queues[queue_type] = Queue(maxsize=maxsize)
                self._stats["created"] += 1
        except Exception as e:
            _loss_logger.error("create_queues() failed: %r", e)
            self._stats["errors"] += 1
        return queues

    def register_process_queues(
        self,
        process_name: str,
        queues: Dict[str, Queue],
    ) -> bool:
        """Зарегистрировать очереди в PSR (единственный source of truth)."""
        try:
            self._stats["registered"] += len(queues)
            if self._process_state_registry:
                for queue_type, queue in queues.items():
                    self._process_state_registry.add_queue(process_name, queue_type, queue)
            _loss_logger.debug("Registered %d queues for '%s'", len(queues), process_name)
            return True
        except Exception as e:
            _loss_logger.error("register_process_queues('%s') failed: %r", process_name, e)
            self._stats["errors"] += 1
            return False

    def create_and_register_queues(
        self,
        process_name: str,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Queue]:
        """Создать и зарегистрировать очереди для процесса."""
        queues = self.create_queues(queue_config)
        if queues:
            self.register_process_queues(process_name, queues)
        return queues

    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """Получить очередь из PSR."""
        if self._process_state_registry:
            return self._process_state_registry.get_queue(process_name, queue_type)
        return None

    def get_process_queues(self, process_name: str) -> Dict[str, Queue]:
        """Получить все очереди процесса из PSR."""
        if self._process_state_registry:
            pd = self._process_state_registry.get_process_data(process_name)
            if pd:
                return dict(pd.queues.items())
        return {}

    def send_to_queue(
        self,
        process_name: str,
        queue_type: str,
        message: Any,
        timeout: float = 0.0,
        on_evict: Optional[Any] = None,
    ) -> bool:
        """Положить сообщение в очередь процесса (с QoS-вытеснением при переполнении).

        ``on_evict`` (LIVE-2, опционально): колбэк ``(evicted_item, process_name)``,
        вызываемый КОГДА drop_oldest реально вытеснил элемент (data-очередь полна). Нужен
        владельцу кадрового кольца, чтобы отпустить займ вытесненного кадра (иначе free-list
        утекает — см. RouterManager._on_frame_evicted). Слой памяти о кадрах НЕ знает —
        колбэк это чистый Callable, регистрирует его тот, кто про кадры знает (router). На
        flags-off пути (on_evict=None) поведение бит-в-бит прежнее."""
        queue = self.get_queue(process_name, queue_type)
        if queue is None:
            # Ф6.х.3: счётчик — всегда, запись — раз в окно (hot-path; в окне
            # teardown отсутствующая очередь стреляла бы покадрово).
            self._stats["queue_missing"] = self._stats.get("queue_missing", 0) + 1
            self._voice(
                f"queue_missing:{process_name}:{queue_type}",
                "warning",
                f"Queue '{queue_type}' not found for '{process_name}' "
                f"(queue_missing={self._stats['queue_missing']}) — груз не доставлен",
            )
            return False
        self._count_sender(process_name, queue_type, message, "put")
        try:
            evicted = self.remove_old_if_full(queue, queue_type, victim_process=process_name)
            if evicted is not None and on_evict is not None:
                try:
                    on_evict(evicted, process_name)
                except Exception as e:  # noqa: BLE001 — хук наблюдаемости не роняет доставку
                    _loss_logger.error("send_to_queue on_evict hook failed: %r", e)
            if timeout > 0:
                queue.put(message, timeout=timeout)
            else:
                queue.put_nowait(message)
            return True
        except Exception as e:
            # Полная never-drop очередь — это не «ошибка отправки», а ПОТЕРЯ груза,
            # который система сама пометила как нероняемый. Отдельная ветка нужна,
            # потому что только здесь известно ИМЯ получателя: remove_old_if_full
            # видит лишь сам объект очереди и назвать адресата не может.
            if isinstance(e, Full):
                # Ф1.4 (M17): АРИФМЕТИКА переполнения — до любых развилок и до
                # любого троттлинга. Считается КАЖДАЯ неудачная попытка, независимо
                # от типа очереди и от того, прозвучит ли голос: «≤1 запись на окно»
                # имеет смысл только рядом с числом, которое окном не тронуто.
                self._stats["queue_full_events"] += 1
            if isinstance(e, Full) and self._is_never_drop(queue_type):
                self._report_never_drop_loss(process_name, queue_type, queue)
                # Ф4 Task 4.3: потеря записывается ТОМУ ЖЕ отправителю — иначе видно
                # «очередь теряет», но не видно, чей груз пропадает.
                self._count_sender(process_name, queue_type, message, "lost")
                # Ф1.4 (M17): выход ЗДЕСЬ, а не проваливание в общий
                # «send_to_queue failed» ниже. Прежде один инцидент давал ТРИ
                # строки — блокировку вытеснения, отчёт о потере и эту общую, —
                # причём последняя не троттлилась вовсе: замер тестера на пяти
                # попытках дал восемь записей. Отчёт о потере говорит строго
                # больше общей строки (называет получателя, размер очереди и
                # сумму потерь), поэтому терять нечего. Счётчик ``errors``
                # растёт как прежде: он факт, а не голос.
                self._stats["errors"] += 1
                return False
            if isinstance(e, Full) and self._is_observability_queue(queue_type):
                # Ф7.3, звено (а) петли самоусиления. Очередь наблюдаемости droppable,
                # поэтому Full здесь — редкая гонка: между вытеснением и put её успел
                # заполнить другой отправитель. Записи об этом НЕ делаем: она поехала
                # бы тем же хвостом, отказ доставки которого её и породил, — ровно та
                # петля, которую Б-6 намерил на 97 066 отказах. Потеря не молчит:
                # счётчик уходит наружу через get_stats → heartbeat → state. Общий
                # ``errors`` СОЗНАТЕЛЬНО не трогаем: под штормом хвоста он перестал бы
                # отличать «транспорт сломан» от «диагностики слишком много» — этой
                # слепотой Б-6 и запомнился.
                #
                # Ф7.х, M-4: сверка типа обязательна. Без неё ветка глотала ЛЮБОЕ
                # исключение как «хвоста слишком много»: закрытая очередь
                # (``ValueError: is closed``) и непиклящийся груз
                # (``PicklingError``) уходили в тот же тихий счётчик — то есть
                # отказ транспорта выглядел перегрузкой, и починка петли завела
                # свой собственный проглоченный сбой. Всё, что не ``Full``, идёт
                # ниже общей громкой дорогой: это не «диагностики много», это
                # сломано, и молчать об этом нельзя.
                self._stats["observability_send_failed"] += 1
                self._count_sender(process_name, queue_type, message, "lost")
                return False
            # Ф1.4: последнее из ad-hoc-мест этого файла, у которого окна не было
            # ВООБЩЕ. Ключ включает РОД исключения: шторм ``Full`` на одной
            # очереди не имеет права заглушить редкий ``PicklingError`` на ней же
            # — тот же довод, по которому окно роутера ключуется причиной.
            self._voice(
                f"send_failed:{process_name}:{queue_type}:{type(e).__name__}",
                "error",
                f"send_to_queue('{process_name}', '{queue_type}') failed: {e!r}",
            )
            self._stats["errors"] += 1
            return False

    def receive_from_queue(
        self,
        process_name: str,
        queue_type: str,
        timeout: float = 0.0,
    ) -> Optional[Any]:
        queue = self.get_queue(process_name, queue_type)
        if queue is None:
            return None
        try:
            return queue.get(timeout=timeout) if timeout > 0 else queue.get_nowait()
        except Empty:
            return None
        except Exception as e:
            _loss_logger.error("receive_from_queue('%s', '%s') failed: %r", process_name, queue_type, e)
            self._stats["errors"] += 1
            return None

    def broadcast_message(
        self,
        message: Any,
        queue_type: str = "system",
        exclude_process: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам через PSR."""
        if not self._process_state_registry:
            return 0
        sent = 0
        for process_name in list(self._process_state_registry.get_process_names()):
            if exclude_process and process_name == exclude_process:
                continue
            if self.send_to_queue(process_name, queue_type, message):
                sent += 1
        return sent

    def get_queue_sizes(self) -> Dict[str, Dict[str, int]]:
        sizes: Dict[str, Dict[str, int]] = {}
        if not self._process_state_registry:
            return sizes
        for process_name in self._process_state_registry.get_process_names():
            pd = self._process_state_registry.get_process_data(process_name)
            if not pd:
                continue
            sizes[process_name] = {}
            for queue_type in pd.queues:
                queue = pd.get_queue(queue_type)
                if queue is None:
                    continue
                try:
                    sizes[process_name][queue_type] = queue.qsize()
                except (NotImplementedError, OSError, AttributeError):
                    sizes[process_name][queue_type] = 0
        return sizes

    def remove_process_queues(self, process_name: str) -> bool:
        """Удалить процесс из PSR (unregister) — только статистика; PSR чистит SRM/PSR."""
        if self._process_state_registry and self._process_state_registry.has_process(process_name):
            self._stats["removed"] += 1
            return True
        return False

    def get_registered_processes(self) -> List[str]:
        if self._process_state_registry:
            return self._process_state_registry.get_process_names()
        return []

    # =========================================================================
    # Утилиты
    # =========================================================================

    def clear_queue(self, queue: Queue, keep_elements: int = 0) -> None:
        """Надёжная очистка очереди (Windows-safe: не использует queue.empty()).
        Учитывает асинхронность multiprocessing.Queue на macOS/spawn — повторный
        проход после короткой паузы для «задержанных» элементов."""
        saved = []
        try:
            for _ in range(10_000):
                try:
                    saved.append(queue.get_nowait())
                except Empty:
                    break
            # Повторный проход для macOS: put() может быть асинхронным
            for _ in range(3):
                time.sleep(0.05)
                for _ in range(1_000):
                    try:
                        saved.append(queue.get_nowait())
                    except Empty:
                        break
            if keep_elements > 0 and len(saved) > keep_elements:
                saved = saved[-keep_elements:]
            elif keep_elements == 0:
                saved = []
            for item in saved:
                queue.put(item)
        except Exception as e:
            _loss_logger.error("clear_queue() failed: %r", e)
            self._stats["errors"] += 1

    def remove_old_if_full(
        self,
        queue: Queue,
        queue_type: Optional[str] = None,
        victim_process: Optional[str] = None,
    ) -> Optional[Any]:
        """Освободить место в полной очереди перед put (QoS-профиль, Ф7 G.4.a).

        Решение «ронять или нет» берётся из ЕДИНОГО QoS-профиля класса груза
        (``qos.py``: system→never-drop, data→drop_oldest) вместо трёх хардкодов:

        - **never-drop** (system/command): НЕ вытеснять. Control-plane
          (process.stop/heartbeat) терять нельзя, иначе процесс не остановится.
          Throttled ERROR + счётчик ``system_evict_blocked``; put затем упадёт штатно
          (put_nowait → Full → send_to_queue), потеря становится ВИДИМОЙ, не тихой.
        - **drop_oldest** (data/прочее): вытеснить самый старый элемент + счётчик
          ``data_evicted`` (всегда-on) + throttled WARNING. Раньше data-вытеснение
          было ТИХИМ (без счётчика) — «дроп data виден в state» (G.4.a acceptance).

        Флаг ``FW_QOS_PROFILES`` OFF → источник вердикта = прежний хардкод
        ``queue_type == "system"`` (бит-в-бит откат); счётчик ``data_evicted`` и его
        throttled-WARNING — всегда-on телеметрия (по образцу G.3, поведение drop не
        меняют). Для system/data вердикт профиля идентичен хардкоду — флип безопасен.

        Args:
            victim_process: чью очередь вытесняем (Ф6.8). Счётчик ``data_evicted``
                живёт у ОТПРАВИТЕЛЯ, а вытесняется чужая очередь — очередь
                ПОЛУЧАТЕЛЯ. Из-за этого «246 вытеснений у points» на живом
                прогоне читалось ровно наоборот: как будто переполнялась очередь
                самого points, тогда как points переполнял очередь потребителя.
                Имя жертвы попадает и в пер-жертвенный счётчик, и в текст
                WARNING'а — без него запись не отвечает на вопрос «где затор».

        Returns:
            вытесненный элемент (drop_oldest сработал) или ``None`` (очередь не полна,
            never-drop заблокировал вытеснение, либо очередь опустела гонкой). Вызывающий
            (``send_to_queue``) отдаёт его в ``on_evict``-хук — LIVE-2: у вытесненного
            кадра есть незакрытый займ SHM-кольца, который иначе не отпустит никто.
        """
        victim = f"{victim_process}.{queue_type}" if victim_process else f"?.{queue_type}"
        if not queue.full():
            return None
        # process_data.QUEUE_SYSTEM == "system" — каноническое имя system-очереди.
        if self._is_never_drop(queue_type):
            # Ф1.4 (M17), «один разъём на точку»: ЗДЕСЬ ОСТАЁТСЯ ТОЛЬКО СЧЁТЧИК.
            #
            # Голос отсюда убран сознательно, и это не потеря видимости, а её
            # починка. Блокировка вытеснения и последующая потеря груза — ОДИН
            # инцидент: единственный продовый вызывающий (``send_to_queue``)
            # сразу после этого делает ``put``, тот падает ``Full``, и
            # ``_report_never_drop_loss`` говорил о том же самом второй раз. Две
            # строки на одно событие мешали считать: «сколько инцидентов» и
            # «сколько строк» расходились вдвое, а окна у них были РАЗНЫЕ, так
            # что и подавлялись они вразнобой.
            #
            # Голос переехал туда, где известен ИСХОД: если потребитель успел
            # разобрать очередь между проверкой и ``put``, инцидента не было
            # вовсе — теперь об этом и не говорится, а счётчик всё равно растёт.
            # Всё, что знала снятая запись (``system_evict_blocked``), названо в
            # тексте оставшегося голоса.
            self._stats["system_evict_blocked"] += 1
            return None
        try:
            evicted = queue.get_nowait()
        except Empty:
            return None
        if self._is_observability_queue(queue_type):
            # Ф7.3, звено (б) петли. Хвост тоже drop_oldest, но БЕЗ записи: throttled
            # WARNING отсюда поехал бы в тот же хвост, который только что переполнился,
            # то есть каждая потеря порождала бы новую запись. Счётчики — оба (общий и
            # пер-жертвенный), как у data: «терять можно, молчать нельзя» держится ими.
            self._stats["observability_evicted"] += 1
            key = f"observability_evicted.{victim}"
            self._stats[key] = self._stats.get(key, 0) + 1
            return evicted
        # drop_oldest сработал — громкий счётчик (раньше молчал) + throttled WARNING.
        self._stats["data_evicted"] += 1
        # Ф6.8: разбивка по ЖЕРТВЕ. Общий ``data_evicted`` остаётся (его читают
        # heartbeat и introspect), но он отвечает «сколько», а не «где» —
        # а разбор затора начинается со второго вопроса. Кардинальность
        # ограничена топологией: имён процессов единицы.
        key = f"data_evicted.{victim}"
        self._stats[key] = self._stats.get(key, 0) + 1
        # Ф1.4: ЗНАМЕНАТЕЛЬ ДРОССЕЛЯ СМЕНИЛСЯ, и это не побочный эффект переезда.
        # Прежнее ``_data_evict_*`` было одно на весь реестр: «не больше одной
        # строки на окно», сколько бы процессов ни захлёбывалось. Ключ с именем
        # жертвы делает потолок пер-адресным — O(топологии), а не O(1). Замер
        # ревью Task 1.4: четыре процесса-жертвы по три вытеснения в одном окне
        # дают ЧЕТЫРЕ строки, до правки была бы одна.
        #
        # Так лучше диагностически (затор у одного получателя больше не молчит
        # из-за того, что в том же окне высказался другой), но хуже как гарантия
        # тишины: имён процессов единицы, и это единственное, что держит потолок.
        # Понадобится общий предел — брать второй ключ БЕЗ имени жертвы, а не
        # возвращать одно окно на реестр: адресность уже стоила Ф6.8 своей находки.
        self._voice(
            f"queue_evicted:{victim}",
            "warning",
            f"переполнена data-очередь ПОЛУЧАТЕЛЯ '{victim}' — вытеснен старый элемент "
            f"(drop_oldest; вытеснено в неё {self._stats[key]}, "
            f"всего этим процессом {self._stats['data_evicted']}); "
            f"устойчивая перегрузка = теряем кадры, чинить пропускную способность",
        )
        return evicted

    def _voice(self, key: str, level: str, message: str) -> bool:
        """Голос реестра очередей — не чаще окна на ключ (Ф1.4).

        Мимо ``self._log_*`` СОЗНАТЕЛЬНО и по старой причине: штатная плоскость
        логов у ``QueueRegistry`` не подключена ни в одном процессе (см.
        ``_loss_logger`` в шапке модуля), и запись через миксин просто исчезала
        бы — ровно тот дефект, который Ф6.8 намерила как «246 вытеснений, ноль
        строк». Механизм окна при этом общий с остальным деревом; своё у реестра
        только состояние окон (``self._voices()``), и оно своё у каждого
        экземпляра — два реестра в одном процессе не глушат друг друга.

        Окно НЕ передаётся: ``None`` означает «политика процесса»
        (``observability.voices.default_window_sec``).
        """
        return log_windowed(key, None, level, message, logger=_loss_logger, voices=self._voices())

    def _report_never_drop_loss(
        self,
        process_name: str,
        queue_type: Optional[str],
        queue: Queue,
    ) -> None:
        """Отчёт о безвозвратно потерянном never-drop грузе — один голос на окно.

        Почему мимо ``self._log_error``: штатная плоскость логов у QueueRegistry
        не подключена ни в одном процессе (см. ``_loss_logger``), и запись
        просто исчезала. Почему с именем получателя: без него запись не отвечает
        на главный вопрос разбора — КОМУ не доехало; счётчики этого не знают.

        Ф1.4: это ЕДИНСТВЕННЫЙ голос всего инцидента «system-очередь полна».
        Прежде их было два (второй — из ``remove_old_if_full``), и они говорили
        об одном и том же событии в разные окна. Число заблокированных вытеснений
        приехало сюда, в текст, чтобы снятая запись ничего не унесла с собой.

        **Факт и голос разделены:** ``_never_drop_loss_total`` растёт ВСЕГДА,
        окно его не касается; «подавлено с прошлой записи» считает механизм и
        называет в тексте следующего голоса.
        """
        self._never_drop_loss_total += 1  # факт — всегда
        voiced, suppressed = self._voices().take(f"queue_full:{process_name}:{queue_type}")
        if not voiced:
            return
        try:
            size = queue.qsize()
        except (NotImplementedError, OSError, AttributeError):
            size = -1  # qsize недоступен (macOS) — не повод молчать о потере
        tail = f" Подавлено с прошлой записи: {suppressed}." if suppressed else ""
        _loss_logger.error(
            "ПОТЕРЯ СООБЩЕНИЯ: очередь '%s' процесса-получателя '%s' переполнена "
            "(размер %s), вытеснение запрещено QoS-профилем (never-drop, "
            "system_evict_blocked=%d) — сообщение отброшено БЕЗВОЗВРАТНО и не будет "
            "доставлено. всего: %d.%s",
            queue_type,
            process_name,
            size if size >= 0 else "недоступен",
            self._stats["system_evict_blocked"],
            self._never_drop_loss_total,
            tail,
        )

    #: Потолок числа РАЗЛИЧНЫХ отправителей, учитываемых по одной очереди (Ф4 Task 4.3).
    #: Сверх потолка счёт идёт в общее ведро :data:`_SENDER_OTHER_BUCKET`: диагностика
    #: «кто душит» интересуется топ-виновником, а не длинным хвостом, зато память
    #: остаётся ограниченной при трафике со случайными именами отправителей.
    _SENDER_CARDINALITY_CAP = 32
    _SENDER_OTHER_BUCKET = "__other__"
    #: Отправитель не назвался (не-dict груз или конверт без ``sender``). Отдельное
    #: имя, а не пропуск: «не знаем, кто» — это тоже показание, и оно не должно
    #: молча уменьшать сумму put'ов относительно реального трафика.
    _SENDER_UNKNOWN = "__unknown__"

    def _count_sender(self, process_name: str, queue_type: str, message: Any, kind: str) -> None:
        """Учесть put/потерю по имени отправителя (Ф4 Task 4.3, hot-path).

        Дешёвость важнее полноты: один ``dict.get`` по конверту + пара инкрементов.
        Блокировки нет СОЗНАТЕЛЬНО — та же дисциплина, что у ``self._stats`` (инкременты
        int под GIL); гонка двух потоков может стоить одного несчитанного put'а, что для
        диагностики «кто душит очередь» несущественно, а лок на горячем пути кадров —
        существенен.
        """
        try:
            sender = message.get("sender") if isinstance(message, dict) else None
            name = str(sender) if sender else self._SENDER_UNKNOWN
            key = f"{process_name}_{queue_type}"
            per_queue = self._sender_puts.get(key)
            if per_queue is None:
                per_queue = {}
                self._sender_puts[key] = per_queue
            if name not in per_queue and len(per_queue) >= self._SENDER_CARDINALITY_CAP:
                name = self._SENDER_OTHER_BUCKET
            entry = per_queue.get(name)
            if entry is None:
                entry = {"put": 0, "lost": 0}
                per_queue[name] = entry
            entry[kind] += 1
        except Exception:  # noqa: BLE001 — учёт наблюдаемости не смеет ломать доставку
            pass

    def get_sender_stats(self, queue_key: Optional[str] = None) -> Dict[str, Any]:
        """Снимок «кто сколько положил/потерял» по очередям (Ф4 Task 4.3).

        Args:
            queue_key: ``"{process}_{queue_type}"`` — сузить до одной очереди.
                ``None`` → все известные очереди.

        Итерация идёт по ``list(...)``-снимкам СОЗНАТЕЛЬНО (ревью Фазы 4, находка 1):
        писатели (:meth:`_count_sender`) вставляют новые ключи без лока из других
        потоков, а comprehension по живому dict исполняется побайткодово и упал бы
        с ``RuntimeError: dictionary changed size during iteration`` — причём ровно
        в момент появления НОВОГО отправителя/очереди, то есть под тем самым чурном,
        который эта диагностика и должна показывать. ``list()`` — атомарный C-вызов.
        Потеря одного инкремента при гонке допустима, падение интроспекции — нет.

        Returns:
            ``{queue_key: {sender: {"put": n, "lost": n}}}`` — копия (снимок не
            должен мутировать под читателем).
        """
        if queue_key is not None:
            per_queue = self._sender_puts.get(queue_key)
            items = list(per_queue.items()) if per_queue is not None else []
            return {queue_key: {s: dict(v) for s, v in items}}
        return {k: {s: dict(v) for s, v in list(per_queue.items())} for k, per_queue in list(self._sender_puts.items())}

    @staticmethod
    def _is_observability_queue(queue_type: Optional[str]) -> bool:
        """Ф7.3: это очередь хвоста наблюдаемости?

        Единственное следствие ответа — **молчание в логах** на путях потери (вытеснение,
        отказ put). Не оптимизация и не «тише значит лучше»: запись о потерянной записи
        едет тем же хвостом, поэтому обычная диагностика здесь работает усилителем
        сбоя — измерено живьём (Б-6: 97 066 отказов доставки за ~25 минут, из них
        каждый порождал новую запись). Взамен потеря видна счётчиками
        ``observability_evicted`` / ``observability_send_failed``, которые уходят
        наружу тем же путём, что ``data_evicted``.
        """
        return queue_type == ProcessDataKeys.QUEUE_OBSERVABILITY

    def _is_never_drop(self, queue_type: Optional[str]) -> bool:
        """Ронять ли груз данного ``queue_type`` при переполнении (Ф7 G.4.a).

        Флаг ON → вердикт из QoS-профиля (``qos_for(queue_type).never_drop``); OFF →
        прежний хардкод ``queue_type == "system"``. Для system/data результат совпадает.
        ``queue_type is None`` → droppable (прежнее поведение data-ветки).
        """
        if self._qos_profiles and queue_type is not None:
            return qos_for(queue_type).never_drop
        return queue_type == "system"

    # =========================================================================
    # Статистика
    # =========================================================================

    @property
    def data_evicted(self) -> int:
        """Ф7 G.4.a: сколько сообщений вытеснено из полных data-очередей (drop_oldest).
        Дешёвый plain-int аксессор для surface в ``RouterManager.get_stats`` → heartbeat
        → ``state.shm.*`` (без обхода процессов, как в полном get_stats)."""
        return self._stats["data_evicted"]

    @property
    def observability_evicted(self) -> int:
        """Ф7.3: сколько записей вытеснено из полных очередей наблюдаемости.

        Единственный способ узнать о потере хвоста: путь вытеснения молчит в логах
        сознательно (см. :meth:`_is_observability_queue`). Дешёвый plain-int аксессор
        для surface в ``RouterManager.get_stats`` → heartbeat → ``state.shm.*``.
        """
        return self._stats["observability_evicted"]

    @property
    def observability_send_failed(self) -> int:
        """Ф7.3: сколько раз put в очередь наблюдаемости упал (гонка на полной очереди)."""
        return self._stats["observability_send_failed"]

    @property
    def system_evict_blocked(self) -> int:
        """Ф7 G.4.a: сколько раз заблокировано вытеснение из полной system-очереди."""
        return self._stats["system_evict_blocked"]

    @property
    def never_drop_loss_total(self) -> int:
        """Ф4 Task 4.3: сколько never-drop сообщений потеряно БЕЗВОЗВРАТНО.

        Раньше счётчик существовал только внутри ``_report_never_drop_loss`` и уходил
        в stdlib-логгер — инструменту (``introspect.router_stats``/``introspect.queues``)
        он был недоступен, то есть самая тяжёлая потеря системы была невидима из
        интроспекции.
        """
        return self._never_drop_loss_total

    def get_stats(self) -> Dict[str, Any]:
        process_names = self.get_registered_processes()
        total = 0
        if self._process_state_registry:
            for p in process_names:
                pd = self._process_state_registry.get_process_data(p)
                if pd:
                    total += len(pd.queues)
        queue_stats = {
            **self._stats,
            "total_queues": total,
            "processes_count": len(process_names),
            "processes": process_names,
            # Ф4 Task 4.3: безвозвратные потери и топ-отправители — в интроспекцию,
            # а не только в stdlib-лог (см. never_drop_loss_total / _count_sender).
            "never_drop_loss_total": self._never_drop_loss_total,
            "senders": self.get_sender_stats(),
        }
        return self._merge_stats("queues", queue_stats)
