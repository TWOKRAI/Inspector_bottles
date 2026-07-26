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
    Пачка канала ограничена ``max_pending``. Раньше потолка не было вовсе: если
    сток тормозил (медленный диск, зависший stdout, канал под удержанным
    файловым локом), deque рос без предела — процесс съедал память тихо, а
    наблюдаемость (которая и должна была об этом сказать) сама и была причиной.
    При переполнении запись НЕ теряется молча: ``dropped_by_channel`` называет
    канал-виновник, ``dropped`` даёт итог. Инвариант, проверяемый тестом:

        total_enqueued == total_flushed + Σ pending + dropped

    (в момент, когда ни один flush не выполняется). ``total_enqueued`` считает
    ВСЕ вызовы ``enqueue()``, включая отвергнутые потолком.

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
_OVERFLOW_POLICIES = (OVERFLOW_DROP_OLDEST, OVERFLOW_DROP_NEWEST)


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

        self._lock = threading.Lock()
        self._batches: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        self._last_flush_time: Dict[str, float] = {}

        if self._config.overflow_policy not in _OVERFLOW_POLICIES:
            raise ValueError(
                f"BatchConfig.overflow_policy={self._config.overflow_policy!r} — допустимы {_OVERFLOW_POLICIES}"
            )

        self._total_enqueued: int = 0
        self._total_batches: int = 0
        self._total_flushed: int = 0
        self._urgent_flush_requests: int = 0
        self._dropped: int = 0
        self._dropped_by_channel: Dict[str, int] = defaultdict(int)
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
        """Остановить фоновый поток и сбросить оставшиеся данные."""
        self._stop_event.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)
        self._timer_thread = None
        self.flush()

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
            if 0 < limit <= len(batch):
                self._dropped += 1
                self._dropped_by_channel[channel] += 1
                if self._config.overflow_policy == OVERFLOW_DROP_NEWEST:
                    # Новую запись не принимаем — пачка остаётся как была.
                    return
                batch.popleft()

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
            elif current_size >= self._config.max_size:
                should_flush = True
            elif elapsed >= self._config.flush_interval:
                should_flush = True

        if should_flush:
            self._flush_channel(channel)

    def flush(self, channel: Optional[str] = None) -> None:
        """Принудительно сбросить буфер.

        channel=None → сбросить все каналы.
        """
        if channel is not None:
            self._flush_channel(channel)
        else:
            self.flush_all()

    def flush_all(self) -> None:
        """Принудительно сбросить все каналы."""
        with self._lock:
            channels = list(self._batches.keys())
        for ch in channels:
            self._flush_channel(ch)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pending = {ch: len(buf) for ch, buf in self._batches.items()}
            dropped_by_channel = dict(self._dropped_by_channel)
        return {
            "type": "batch",
            "total_enqueued": self._total_enqueued,
            "total_batches": self._total_batches,
            "urgent_flush_requests": self._urgent_flush_requests,
            "total_flushed": self._total_flushed,
            # Имя ключа совпадает с AsyncSenderBuffer.stats["dropped"] — у соседней
            # стратегии потолок и счётчик потерь были с самого начала.
            "dropped": self._dropped,
            "dropped_by_channel": dropped_by_channel,
            "max_pending": self._config.max_pending,
            "overflow_policy": self._config.overflow_policy,
            "errors": self._errors,
            "pending": pending,
            "running": bool(self._timer_thread and self._timer_thread.is_alive()),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_channel(self, channel: str) -> None:
        """Атомарно извлечь пачку, затем вызвать flush_fn вне lock-а."""
        with self._lock:
            if not self._batches.get(channel):
                return
            batch = list(self._batches[channel])
            self._batches[channel].clear()
            self._last_flush_time[channel] = time.time()
            self._total_batches += 1
            self._total_flushed += len(batch)

        try:
            self._flush_fn(channel, batch)
        except Exception:
            self._errors += 1

    def _timer_worker(self) -> None:
        """Периодически вызывает flush_all() по интервалу."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._config.flush_interval)
            if not self._stop_event.is_set():
                try:
                    self.flush_all()
                except Exception:
                    pass
