# -*- coding: utf-8 -*-
"""
BatchBuffer — буферная стратегия с пакетной записью.

Адаптация logger_module/batcher/batch_manager.py к интерфейсу IBufferStrategy.
Подходит для LoggerManager и других менеджеров с требованиями к батчингу.

Принцип:
    enqueue() накапливает данные в deque по каналу.
    Сброс происходит по трём триггерам:
      1. priority_flush=True и priority == "urgent" → немедленно
      2. Размер пачки >= max_size
      3. Прошло >= flush_interval секунд с последнего сброса

    ВАЖНО про триггер 1: сбрасывается ВСЯ накопленная пачка канала, а не одна
    приоритетная запись, и делает это поток-эмитент. Замер на дефолтной пачке
    100 записей — 1.3 мс p50 / 1.6 мс p95; последующие urgent-записи стоят
    ~0.02 мс, потому что пачка уже осушена. Счётчик ``urgent_flush_requests``
    в stats отделяет такие сбросы от сбросов по заполнению.

Потолок и потери (Ф0.3):
    Раньше буфер был безлимитным. Память при этом росла НЕ в deque (его держит
    триггер ``max_size``), а в пачках «в полёте»: медленный сток не мешал каждому
    следующему потоку начать СВОЙ сброс, и число одновременно живых пачек ничем
    не ограничивалось. Поэтому лечение двойное:

      1. ``_in_flight`` — один сбрасывающий поток на канал. Остальные копят;
      2. ``max_pending`` — потолок накопленного, с политикой ``overflow_policy``.

    Ключевое свойство: потолок роняет записи ТОЛЬКО пока сток занят. При
    свободном стоке переполнение лечится сбросом, поэтому конфигурация
    ``max_pending < max_size`` не превращает батчинг в сэмплирование на здоровой
    системе (находка ревью первой редакции Ф0.3).

    Ничто не теряется молча. Две разные потери названы по-разному:
    ``dropped``/``dropped_by_channel`` — не приняли на входе (потолок);
    ``flush_failed``/``flush_failed_by_channel`` — отдали в сток, а сток не
    принял (канала нет, ``write`` упал). Инвариант, проверяемый тестом:

        total_enqueued == total_flushed + Σ pending + dropped
                          + flush_failed + in_flight_records

    Он честен В ЛЮБОЙ момент, включая момент активного сброса, — именно тогда
    на счётчики и смотрят. ``total_enqueued`` считает ВСЕ вызовы ``enqueue()``,
    включая отвергнутые потолком.

    Контракт ``flush_fn``: возврат ``int`` = число ФАКТИЧЕСКИ принятых записей.
    Возврат ``None`` (прежний контракт) означает «сток не рапортует» — пачка
    считается доставленной целиком. Без этого `total_flushed` означал бы
    «отдано», а не «записано», и счётчики показывали бы здоровую плоскость при
    стопроцентной потере (вторая находка того же ревью).

    Кто этим пользуется: с Ф0.9 — НИКТО из лог-слоя. ``LoggerCore`` и
    ``ErrorManager`` больше не кладут error/critical в буфер вообще (пишут
    синхронно, см. logger_module/README.md), поэтому priority-ветка осталась
    штатной возможностью буфера для будущих потребителей, а не механизмом,
    на котором держится гарантия crash-лога.

    flush_fn(channel: str, batch: List[dict]) вызывается ВНЕ lock-а —
    медленный I/O не блокирует потоки, вызывающие enqueue().

Thread safety:
    _lock защищает batches и last_flush_time.
    Список каналов для flush_all() берётся атомарно.
"""

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Dict, Deque, List, Optional

from ..interfaces import IBufferStrategy


#: Политики поведения при переполнении пачки канала.
OVERFLOW_DROP_OLDEST = "drop_oldest"
OVERFLOW_DROP_NEWEST = "drop_newest"
OVERFLOW_POLICIES = (OVERFLOW_DROP_OLDEST, OVERFLOW_DROP_NEWEST)

#: Дефолты потолка — ОДИН источник на весь фреймворк. Схемы конфигов
#: (logger/error/observability) импортируют их, а не переписывают числом:
#: пять копий дефолта расходятся молча.
DEFAULT_MAX_PENDING = 10_000
DEFAULT_OVERFLOW_POLICY = OVERFLOW_DROP_OLDEST

#: Сколько явный flush()/stop() ждёт чужого сброса, прежде чем сдаться.
#: Ограничение обязательно: барьер без таймаута превращает подвисший сток в
#: подвисший процесс. Исчерпание считается в ``flush_timeouts``, а не молчит.
DEFAULT_FLUSH_BARRIER_TIMEOUT = 5.0


def validate_overflow_policy(value: str) -> str:
    """Проверить политику переполнения. Единая точка для схем и для буфера.

    Вызывается валидаторами конфигов (отказ на ГРАНИЦЕ — до того, как правка
    коснётся живых менеджеров) и конструктором буфера (защита в глубину).
    """
    if value not in OVERFLOW_POLICIES:
        raise ValueError(f"overflow_policy={value!r} — допустимы {OVERFLOW_POLICIES}")
    return value


@dataclass
class BatchConfig:
    """Параметры пакетной буферизации."""

    max_size: int = 100  # Максимальный размер пачки
    flush_interval: float = 1.0  # Интервал принудительного сброса (сек)
    priority_flush: bool = True  # "urgent" priority → немедленный сброс

    #: Потолок неотправленных записей НА КАНАЛ. При достижении срабатывает
    #: overflow_policy. Значение <= 0 — без потолка (поведение до Ф0.3;
    #: оставлено осознанной опцией, не дефолтом).
    max_pending: int = 10_000
    #: "drop_oldest" — выбросить самую старую запись канала (кольцо: ближний к
    #: падению контекст важнее давнего). "drop_newest" — не принять новую.
    overflow_policy: str = OVERFLOW_DROP_OLDEST


class BatchBuffer(IBufferStrategy):
    """Потокобезопасная пакетная буферная стратегия.

    Пример использования:
        def _do_flush(channel_name: str, batch: list) -> None:
            ch = registry.get(channel_name)
            for item in batch:
                ch.write(item)

        buf = BatchBuffer(flush_fn=_do_flush, config=BatchConfig(max_size=50))
        buf.start()
        buf.enqueue("logs", {"level": "INFO", "message": "..."})
        buf.flush()   # принудительный сброс всех каналов
        buf.stop()
    """

    def __init__(
        self,
        flush_fn: Callable[[str, List[Dict[str, Any]]], Any],
        config: Optional[BatchConfig] = None,
    ) -> None:
        """
        Args:
            flush_fn: fn(channel_name: str, batch: List[dict]) → Any
                      Вызывается при каждом сбросе пачки (вне lock-а).
            config:   Параметры батчинга. По умолчанию BatchConfig().
        """
        self._flush_fn = flush_fn
        self._config = config or BatchConfig()

        # Condition, а не Lock: явный flush()/stop() обязан ДОЖДАТЬСЯ чужого
        # сброса, иначе он перестаёт быть барьером и хвост теряется молча.
        # Внутри — обычный Lock (не RLock по умолчанию): случайная реентерантность
        # должна падать дедлоком, а не проходить незамеченной.
        self._lock = threading.Condition(threading.Lock())
        self._batches: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        self._last_flush_time: Dict[str, float] = {}

        # Защита в глубину: основная проверка живёт в схемах конфигов (отказ на
        # границе, до касания живых менеджеров), здесь — для прямых вызовов.
        validate_overflow_policy(self._config.overflow_policy)

        #: Каналы, для которых сброс сейчас выполняется (пачка «в полёте»).
        #: Гарантирует один сбрасывающий поток на канал — см. _flush_channel.
        self._in_flight: set = set()
        #: Сколько записей прямо сейчас находится внутри flush_fn. Без этой
        #: графы инвариант учёта не сходился бы в момент сброса — а именно в
        #: этот момент оператор и смотрит на подвисший сток.
        self._in_flight_records: int = 0

        self._total_enqueued: int = 0
        self._total_batches: int = 0
        self._total_flushed: int = 0
        self._urgent_flush_requests: int = 0
        self._dropped: int = 0
        self._dropped_by_channel: Dict[str, int] = defaultdict(int)
        self._flush_failed: int = 0
        self._flush_failed_by_channel: Dict[str, int] = defaultdict(int)
        self._flush_skipped_busy: int = 0
        self._flush_timeouts: int = 0
        self._flush_contract_violations: int = 0
        self._dropped_at_stop: int = 0
        self._errors: int = 0

        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # IBufferStrategy — lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Запустить фоновый поток периодического flush."""
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_worker,
            name="batch-buffer-timer",
            daemon=True,
        )
        self._timer_thread.start()

    def stop(self) -> None:
        """Остановить фоновый поток и сбросить оставшиеся данные.

        Два прохода барьерного flush: первый дожидается сброса, идущего прямо
        сейчас, второй забирает то, что накопилось за время его полёта. Если
        после этого что-то осталось (эмитенты всё ещё пишут), это НЕ тишина —
        остаток считается в ``dropped_at_stop``.
        """
        self._stop_event.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)
        self._timer_thread = None

        self.flush()
        self.flush()

        with self._lock:
            left = sum(len(buf) for buf in self._batches.values())
            if left:
                self._dropped_at_stop += left

    # ------------------------------------------------------------------
    # IBufferStrategy — enqueue / flush
    # ------------------------------------------------------------------

    def enqueue(
        self,
        channel: str,
        data: Dict[str, Any],
        priority: str = "normal",
    ) -> None:
        """Добавить данные в буфер канала.

        При необходимости (priority_flush, max_size, flush_interval) немедленно
        сбрасывает накопленную пачку. При достижении ``max_pending`` применяет
        ``overflow_policy`` и считает потерю в ``dropped_by_channel``.
        """
        should_flush = False

        with self._lock:
            if channel not in self._last_flush_time:
                self._last_flush_time[channel] = time.time()

            batch = self._batches[channel]
            self._total_enqueued += 1

            limit = self._config.max_pending
            overflowed = 0 < limit <= len(batch)
            sink_busy = channel in self._in_flight

            # Потолок роняет запись ТОЛЬКО когда сбросом место не освободить —
            # то есть сток уже занят предыдущей пачкой. При свободном стоке
            # переполнение лечится сбросом, а не потерей: иначе конфигурация
            # max_pending < max_size молча превращала бы батчинг в сэмплирование
            # на полностью здоровой системе (находка ревью Ф0.3).
            accept = True
            if overflowed and sink_busy:
                self._dropped += 1
                self._dropped_by_channel[channel] += 1
                if self._config.overflow_policy == OVERFLOW_DROP_NEWEST:
                    # Новую запись не принимаем — пачка остаётся как была.
                    # ВАЖНО: не выходим из метода. Ранний return пропускал бы
                    # расчёт триггеров, и канал с этой политикой залипал
                    # навсегда (сток занят → нет сброса → сток не освободится).
                    # Флаг, а не ``data = None``: иначе вызов с data=None (контракт
                    # это запрещает, но проверки нет) молча ломал бы инвариант,
                    # и причину искали бы в буфере.
                    accept = False
                else:
                    batch.popleft()

            if accept:
                batch.append(data)

            current_size = len(batch)
            elapsed = time.time() - self._last_flush_time[channel]

            if self._config.priority_flush and priority == "urgent":
                should_flush = True
                # Отдельно от _total_batches: с приходом urgent-записей (Ф0.1 плана
                # observability-unified-routing) число сбросов перестало быть мерой
                # эффективности батчинга — часть из них вызвана приоритетом, а не
                # заполнением пачки. Считаем их отдельно, чтобы сигнал не врал.
                # Имя говорит «запросов», а не «сбросов»: фактический сброс делает
                # _flush_channel уже вне lock-а, и при гонке пачку может осушить
                # соседний поток — тогда запросов больше, чем записанных пачек.
                self._urgent_flush_requests += 1
            elif current_size >= self._config.max_size or overflowed:
                should_flush = True
            elif elapsed >= self._config.flush_interval:
                should_flush = True

            # Сток занят — попытка сброса заведомо будет отбита. Не назначаем её:
            # иначе flush_skipped_busy считал бы «сколько раз писали в занятый
            # канал» (10 401 на 12 000 записей в замере ревью) вместо обещанного
            # именем «сколько сбросов пропущено», плюс лишний захват лока.
            if sink_busy:
                should_flush = False

        if should_flush:
            self._flush_channel(channel)

    def flush(
        self,
        channel: Optional[str] = None,
        *,
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> None:
        """Принудительно сбросить буфер. channel=None → все каналы.

        ``wait=True`` (дефолт) делает вызов БАРЬЕРОМ: если канал сейчас
        сбрасывает другой поток, ждём его и забираем накопленное следом.
        Барьерность здесь не роскошь — на ней держатся два контракта:
        порядок «контекст раньше ошибки» (``LoggerCore._write_error_record``)
        и полнота слива при ``stop()``.
        """
        if channel is not None:
            self._flush_channel(channel, wait=wait, timeout=timeout)
        else:
            self.flush_all(wait=wait, timeout=timeout)

    def flush_all(self, *, wait: bool = True, timeout: Optional[float] = None) -> None:
        """Принудительно сбросить все каналы."""
        with self._lock:
            channels = list(self._batches.keys())
        for ch in channels:
            self._flush_channel(ch, wait=wait, timeout=timeout)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Когерентный снимок: ВСЕ счётчики читаются под одним локом.

        Иначе опубликованный наружу инвариант нарушался бы на здоровом процессе
        (`dropped != sum(dropped_by_channel)`), а по нему теперь судят операторы
        и агенты через ``introspect.observability``. Это не hot-path.
        """
        with self._lock:
            return {
                "type": "batch",
                "total_enqueued": self._total_enqueued,
                "total_batches": self._total_batches,
                "urgent_flush_requests": self._urgent_flush_requests,
                "total_flushed": self._total_flushed,
                # Имя ключа совпадает с AsyncSenderBuffer.stats["dropped"] — у соседней
                # стратегии потолок и счётчик потерь были с самого начала.
                "dropped": self._dropped,
                "dropped_by_channel": dict(self._dropped_by_channel),
                # Отдано в сток, но сток НЕ принял (канала нет, write упал).
                # Отдельно от dropped: там потеря на входе, здесь — на выходе.
                "flush_failed": self._flush_failed,
                "flush_failed_by_channel": dict(self._flush_failed_by_channel),
                "flush_skipped_busy": self._flush_skipped_busy,
                # Барьерный flush не дождался чужого сброса за отведённое время.
                "flush_timeouts": self._flush_timeouts,
                # flush_fn вернул число вне [0, len(batch)] — баг стока, не буфера.
                "flush_contract_violations": self._flush_contract_violations,
                # Не успели записать при остановке. Именованная потеря вместо
                # записей, тихо оставшихся в pending у уходящего процесса.
                "dropped_at_stop": self._dropped_at_stop,
                "in_flight": sorted(self._in_flight),
                "in_flight_records": self._in_flight_records,
                "max_pending": self._config.max_pending,
                "overflow_policy": self._config.overflow_policy,
                "errors": self._errors,
                "pending": {ch: len(buf) for ch, buf in self._batches.items()},
                "running": bool(self._timer_thread and self._timer_thread.is_alive()),
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_channel(
        self,
        channel: str,
        *,
        wait: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        """Атомарно извлечь пачку, затем вызвать flush_fn вне lock-а.

        Один канал сбрасывается не более чем одним потоком одновременно
        (``_in_flight``). Без этого медленный сток порождал неограниченное число
        параллельных сбросов — и память росла не в deque (его держит max_size),
        а в пачках «в полёте», которых потолок не касается вовсе.

        ``wait`` разводит две семантики (иначе явный ``flush()`` перестаёт быть
        барьером и хвост теряется молча — находка ревью итерации 2):

          * ``False`` — оппортунистический путь из ``enqueue``/таймера: канал
            занят → пропускаем, сброс произойдёт по следующему триггеру;
          * ``True`` — явные ``flush()`` / ``flush_all()`` / ``stop()``: ждём
            завершения чужого сброса и только потом забираем накопленное.
            Ожидание ограничено таймаутом; его исчерпание — не тишина, а
            счётчик ``flush_timeouts``.

        Учёт доставки: если ``flush_fn`` возвращает int, это число ФАКТИЧЕСКИ
        принятых записей; разница уходит в ``flush_failed``. Возврат ``None``
        (старый контракт) означает «сток не рапортует» — тогда пачка считается
        доставленной целиком. Значение вне ``[0, len(batch)]`` — нарушение
        контракта стоком: считается в ``flush_contract_violations``, и пачка
        НЕ засчитывается доставленной (недоказанное не выдаём за записанное).
        """
        with self._lock:
            if channel in self._in_flight:
                if not wait:
                    self._flush_skipped_busy += 1
                    return
                limit = DEFAULT_FLUSH_BARRIER_TIMEOUT if timeout is None else timeout
                if not self._lock.wait_for(lambda: channel not in self._in_flight, timeout=limit):
                    self._flush_timeouts += 1
                    return
            if not self._batches.get(channel):
                return
            batch = list(self._batches[channel])
            self._batches[channel].clear()
            self._last_flush_time[channel] = time.time()
            self._total_batches += 1
            self._in_flight.add(channel)
            self._in_flight_records += len(batch)

        written: Any = None
        failed = False
        try:
            written = self._flush_fn(channel, batch)
        except Exception:  # noqa: BLE001 — сбой стока НЕ имеет права ронять эмитента
            failed = True
        except BaseException:
            # KeyboardInterrupt / SystemExit — пробрасываем (глушить их нельзя),
            # но флаг канала снимается в finally. Раньше снятие жило в обычном
            # блоке после try: один Ctrl+C внутри ch.write (он приходит в главный
            # поток в произвольной точке) оставлял канал в _in_flight НАВСЕГДА —
            # сток здоров, а записей ноль.
            failed = True
            raise
        finally:
            with self._lock:
                size = len(batch)
                if failed:
                    self._errors += 1
                    accepted = 0
                elif isinstance(written, int) and not isinstance(written, bool):
                    if 0 <= written <= size:
                        accepted = written
                    else:
                        # Сток соврал о числе принятых записей. Молча кламповать —
                        # значит спрятать его баг; недоказанное не доставлено.
                        self._flush_contract_violations += 1
                        accepted = 0
                else:
                    accepted = size
                self._total_flushed += accepted
                lost = size - accepted
                if lost:
                    self._flush_failed += lost
                    self._flush_failed_by_channel[channel] += lost
                self._in_flight.discard(channel)
                self._in_flight_records -= size
                self._lock.notify_all()

    def _timer_worker(self) -> None:
        """Периодически вызывает flush_all() по интервалу."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._config.flush_interval)
            if not self._stop_event.is_set():
                try:
                    self.flush_all(wait=False)
                except Exception:
                    pass
