"""
QueueRegistry — создание и доступ к очередям процессов.

PSR (ProcessStateRegistry) — единственный source of truth для Queue ссылок.
QueueRegistry делегирует хранение в PSR.

Pickle-safe: Queue ссылки живут в ProcessData (pickle-safe).
"""

import logging
import time
from multiprocessing import Queue
from typing import Any, Dict, List, Optional

from ....base_manager import BaseManager, ObservableMixin
from ..interfaces import IQueueRegistry
from ...mixins import ManagerStatsMixin
from ...qos import qos_for

try:
    from multiprocessing.queues import Empty
except ImportError:
    from queue import Empty

from queue import Full

# Отдельный stdlib-логгер для сообщений о БЕЗВОЗВРАТНОЙ потере груза.
# Штатная плоскость (self._log_*) здесь молчит по построению: ни один продовый
# вызов SharedResourcesManager(...) не передаёт logger (spawner.py, bundle_builder.py,
# process_runner.py — все три без него), поэтому ManagerRegistry пуст и
# _call_manager('logger', ...) тихо возвращает None. Плюс ObservableMixin.__getstate__
# выкидывает _registry при pickle, так что даже переданный logger не пережил бы spawn.
# Итог до этой правки: 26 тысяч событий потери → 0 строк во всём logs/.
# Тот же приём, что _fallback_logger в logger_module (log_channel.py / logger_core.py).
_fallback_logger = logging.getLogger(__name__)


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
        }
        # Throttle для ERROR-лога переполнения system-очереди: логируем раз на окно,
        # а не на каждый put (send_to_queue — hot-path). Счётчик инкрементируется всегда.
        self._system_evict_log_window: float = 5.0
        self._system_evict_last_log: float = 0.0
        # Throttle громкого WARNING про drop_oldest из data-очереди (тот же приём).
        self._data_evict_log_window: float = 5.0
        self._data_evict_last_log: float = 0.0
        # Учёт безвозвратных потерь never-drop груза (см. _report_never_drop_loss).
        # Копится всегда, пишется в лог раз в окно; _since_log нужен, чтобы
        # троттлированная запись честно называла ТЕМП потери, а не только факт.
        self._never_drop_loss_total: int = 0
        self._never_drop_loss_since_log: int = 0
        self._never_drop_loss_last_log: float = 0.0
        # Ф4 Task 4.3 (plans/truth-holes-closure.md): «кто душит очередь X».
        # {"{process}_{queue_type}": {sender: {"put": n, "lost": n}}} — счётчик
        # положенных в очередь сообщений ПО ОТПРАВИТЕЛЮ. Счётчики очереди отвечали
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
            self._log_info(f"QueueRegistry '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"QueueRegistry.initialize() failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self.is_initialized = False
            self._log_info("QueueRegistry shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"QueueRegistry.shutdown() failed: {e}")
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
            self._log_error(f"create_queues() failed: {e}")
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
            self._log_debug(f"Registered {len(queues)} queues for '{process_name}'")
            return True
        except Exception as e:
            self._log_error(f"register_process_queues('{process_name}') failed: {e}")
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
            self._log_warning(f"Queue '{queue_type}' not found for '{process_name}'")
            return False
        self._count_sender(process_name, queue_type, message, "put")
        try:
            evicted = self.remove_old_if_full(queue, queue_type)
            if evicted is not None and on_evict is not None:
                try:
                    on_evict(evicted, process_name)
                except Exception as e:  # noqa: BLE001 — хук наблюдаемости не роняет доставку
                    self._log_error(f"send_to_queue on_evict hook failed: {e}")
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
            if isinstance(e, Full) and self._is_never_drop(queue_type):
                self._report_never_drop_loss(process_name, queue_type, queue)
                # Ф4 Task 4.3: потеря записывается ТОМУ ЖЕ отправителю — иначе видно
                # «очередь теряет», но не видно, чей груз пропадает.
                self._count_sender(process_name, queue_type, message, "lost")
            self._log_error(f"send_to_queue('{process_name}', '{queue_type}') failed: {e}")
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
            self._log_error(f"receive_from_queue('{process_name}', '{queue_type}') failed: {e}")
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
            self._log_error(f"clear_queue() failed: {e}")
            self._stats["errors"] += 1

    def remove_old_if_full(self, queue: Queue, queue_type: Optional[str] = None) -> Optional[Any]:
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

        Returns:
            вытесненный элемент (drop_oldest сработал) или ``None`` (очередь не полна,
            never-drop заблокировал вытеснение, либо очередь опустела гонкой). Вызывающий
            (``send_to_queue``) отдаёт его в ``on_evict``-хук — LIVE-2: у вытесненного
            кадра есть незакрытый займ SHM-кольца, который иначе не отпустит никто.
        """
        if not queue.full():
            return None
        # process_data.QUEUE_SYSTEM == "system" — каноническое имя system-очереди.
        if self._is_never_drop(queue_type):
            self._stats["system_evict_blocked"] += 1
            now = time.monotonic()
            if now - self._system_evict_last_log >= self._system_evict_log_window:
                self._system_evict_last_log = now
                self._log_error(
                    "system-очередь переполнена — вытеснение заблокировано "
                    f"(system_evict_blocked={self._stats['system_evict_blocked']}); "
                    "system-команда может быть потеряна при put"
                )
            return None
        try:
            evicted = queue.get_nowait()
        except Empty:
            return None
        # drop_oldest сработал — громкий счётчик (раньше молчал) + throttled WARNING.
        self._stats["data_evicted"] += 1
        now = time.monotonic()
        if now - self._data_evict_last_log >= self._data_evict_log_window:
            self._data_evict_last_log = now
            self._log_warning(
                f"data-очередь '{queue_type}' переполнена — вытеснен старый элемент "
                f"(drop_oldest; data_evicted={self._stats['data_evicted']}); "
                "устойчивая перегрузка = теряем кадры, чинить пропускную способность"
            )
        return evicted

    #: Не чаще одной записи о потере за это окно (сек). Троттлинг по ВРЕМЕНИ, а не
    #: «каждая N-я потеря»: на живом рецепте переполнение идёт непрерывно (~17
    #: событий/с), и порог по счётчику всё равно давал бы несколько записей в
    #: секунду. Окно даёт предсказуемый потолок независимо от темпа — иначе
    #: получаем вторую беду того же рода, что раздула messages.log до 645 МБ.
    _NEVER_DROP_LOSS_LOG_INTERVAL_SEC = 5.0

    def _report_never_drop_loss(
        self,
        process_name: str,
        queue_type: Optional[str],
        queue: Queue,
    ) -> None:
        """Троттлированный отчёт о безвозвратно потерянном never-drop грузе.

        Почему мимо ``self._log_error``: штатная плоскость логов у QueueRegistry
        не подключена ни в одном процессе (см. ``_fallback_logger``), и запись
        просто исчезала. Почему с именем получателя: без него запись не отвечает
        на главный вопрос разбора — КОМУ не доехало; счётчики этого не знают.
        """
        self._never_drop_loss_total += 1
        self._never_drop_loss_since_log += 1
        now = time.monotonic()
        if now - self._never_drop_loss_last_log < self._NEVER_DROP_LOSS_LOG_INTERVAL_SEC:
            return
        self._never_drop_loss_last_log = now
        lost_in_window = self._never_drop_loss_since_log
        self._never_drop_loss_since_log = 0
        try:
            size = queue.qsize()
        except (NotImplementedError, OSError, AttributeError):
            size = -1  # qsize недоступен (macOS) — не повод молчать о потере
        _fallback_logger.error(
            "ПОТЕРЯ СООБЩЕНИЯ: очередь '%s' процесса-получателя '%s' переполнена "
            "(размер %s), вытеснение запрещено QoS-профилем (never-drop) — "
            "сообщение отброшено БЕЗВОЗВРАТНО и не будет доставлено. "
            "Потерь с прошлой записи: %d, всего: %d (запись не чаще раза в %.0f с)",
            queue_type,
            process_name,
            size if size >= 0 else "недоступен",
            lost_in_window,
            self._never_drop_loss_total,
            self._NEVER_DROP_LOSS_LOG_INTERVAL_SEC,
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

        Returns:
            ``{queue_key: {sender: {"put": n, "lost": n}}}`` — копия (снимок не
            должен мутировать под читателем).
        """
        if queue_key is not None:
            per_queue = self._sender_puts.get(queue_key, {})
            return {queue_key: {s: dict(v) for s, v in per_queue.items()}}
        return {k: {s: dict(v) for s, v in per_queue.items()} for k, per_queue in self._sender_puts.items()}

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
