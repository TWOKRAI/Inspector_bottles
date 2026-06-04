# -*- coding: utf-8 -*-
"""
StatsManager — менеджер статистики и метрик.

Наследует ChannelRoutingManager. Метрики агрегируются в AggregationWindow
(counter, gauge, timing, histogram) и периодически сбрасываются во все
зарегистрированные каналы (LogStatsChannel, FileStatsChannel).

Интеграция:
  - ObservableMixin: все менеджеры вызывают _record_metric / _record_timing,
    которые маршрутизируются сюда через register_manager("stats", ...).
  - CommandManager: StatsAdapter регистрирует команды get_metrics и пр.
  - LoggerManager: LogStatsChannel логирует снапшоты через performance().

Примечание: remote-stats (отправка снапшотов в другой процесс через RouterManager)
ещё не реализована — это capability-to-build, а не текущая возможность. До неё
StatsManager не держит ссылку на router (см. ADR comm-system-target-architecture §9.7).
"""

import threading
from typing import Any, Dict, List, Optional, Union

from ...channel_routing_module import ChannelRoutingManager
from ...channel_routing_module.core.config_normalizer import normalize_config
from ..interfaces import IStatsManager
from .metric_record import MetricRecord, MetricType
from .aggregation_window import AggregationWindow
from ...logger_module.core.log_paths import resolve_log_file_path
from ..channels.log_stats_channel import LogStatsChannel
from ..channels.file_stats_channel import FileStatsChannel

_STATS_SENTINEL = "__stats__"


def _metric_key(name: str, tags: Optional[Dict] = None) -> str:
    """Ключ для словаря метрик: name или name|k1:v1|k2:v2 (sorted)."""
    if not tags:
        return name
    parts = [name] + [f"{k}:{v}" for k, v in sorted(tags.items())]
    return "|".join(parts)


class StatsManager(ChannelRoutingManager, IStatsManager):
    """Менеджер статистики: агрегация метрик, flush во все каналы.

    Ключевые особенности:
    - Хранит два уровня: live-метрики (self._metrics) для get_metric() и
      буфер агрегации (AggregationWindow) для периодического flush в каналы.
    - _enqueue_to_buffer ставит данные в буфер ОДИН раз под ключом _STATS_SENTINEL.
      _do_flush транслирует снапшот во ВСЕ зарегистрированные каналы.
      Это предотвращает N-кратный счёт метрик при наличии N каналов.
    - Теги: user tags имеют приоритет над default_tags (для обоих слоёв).
    """

    def __init__(
        self,
        manager_name: str = "StatsManager",
        config: Optional[Union[Dict[str, Any], Any]] = None,
        process: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        if managers is None:
            managers = {}

        cfg = normalize_config(config, default={})
        flush_interval = cfg.get("flush_interval", 10.0)
        aggregation_interval = cfg.get("aggregation_interval", 5.0)

        buffer = AggregationWindow(
            flush_fn=self._do_flush,
            flush_interval=max(flush_interval, aggregation_interval),
        )

        ChannelRoutingManager.__init__(
            self,
            manager_name=manager_name,
            config=config,
            buffer_strategy=buffer,
            dispatcher_key_field="type",
            managers=managers,
            process=process,
            **kwargs,
        )

        self._config_dict = cfg
        self._default_tags: Dict[str, str] = cfg.get("default_tags") or {}
        self._metrics: Dict[str, MetricRecord] = {}
        self._metrics_lock = threading.Lock()

    # =========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ
    # =========================================================================

    def initialize(self) -> bool:
        """Инициализация: dispatcher + каналы + старт flush-таймера."""
        try:
            # Инициализируем dispatcher, НЕ стартуем буфер — делаем это после каналов.
            self._dispatcher.initialize()
            self._setup_channels()
            if self._buffer:
                self._buffer.start()
            self.is_initialized = True
            self._log_info(f"[{self.manager_name}] initialized")
            return True
        except Exception as e:
            self._log_error(f"[{self.manager_name}] initialization failed: {e}")
            return False

    # shutdown() наследуется от ChannelRoutingManager:
    # flush() → buffer.stop() (финальный flush) → _close_all_channels() → dispatcher.shutdown()

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        """Хук CRM.reconfigure: пересоздать каналы агрегации из нового конфига.

        Базовый ``reconfigure`` уже сделал flush() и ``_close_all_channels()``
        (очистил реестр CRM). Здесь обновляем dict-конфиг и default_tags, затем
        вызываем существующий ``_setup_channels()`` (reuse) — он сам добавит
        LogStats/FileStats по новому конфигу плюс fallback-канал при необходимости.

        Live-метрики (``self._metrics``) и буфер агрегации (AggregationWindow)
        НЕ сбрасываются — метрики переживают reconfigure.
        """
        cfg = normalize_config(config, default={})
        self._config_dict = cfg
        self._default_tags = cfg.get("default_tags") or {}
        self._setup_channels()

    # =========================================================================
    # SETUP КАНАЛОВ
    # =========================================================================

    def _setup_channels(self) -> None:
        """Создать и зарегистрировать каналы из конфига."""
        cfg = self._config_dict

        # LogStatsChannel — берём logger_manager из ObservableMixin или process
        logger_manager = self.get_manager("logger")
        if logger_manager is None and self.process is not None:
            logger_manager = getattr(self.process, "logger_manager", None)

        if cfg.get("enable_logging", True) and logger_manager is not None:
            log_ch = LogStatsChannel(
                logger_manager=logger_manager,
                level=cfg.get("log_level", "INFO"),
                name="log_stats",
            )
            self.register_channel(log_ch)

        # FileStatsChannel из секции channels конфига
        channels_cfg = cfg.get("channels", {})
        if isinstance(channels_cfg, dict):
            for ch_name, ch_params in channels_cfg.items():
                if not isinstance(ch_params, dict):
                    continue
                if not ch_params.get("enabled", True):
                    continue
                if ch_params.get("type", "file") == "file":
                    fb = f"logs/stats_{self.manager_name}.json"
                    file_ch = FileStatsChannel(
                        file_path=resolve_log_file_path(
                            ch_params.get("file_path"),
                            fallback=fb,
                            log_directory=None,
                        ),
                        format=ch_params.get("format", "json"),
                        name=ch_name,
                    )
                    self.register_channel(file_ch)

        # Fallback: всегда хотя бы один канал
        if not self._channel_registry.names():
            fb = f"logs/stats_{self.manager_name}.json"
            file_ch = FileStatsChannel(
                file_path=resolve_log_file_path(None, fallback=fb, log_directory=None),
                name="file_stats",
            )
            self.register_channel(file_ch)

    # =========================================================================
    # FLUSH CALLBACK
    # =========================================================================

    def _do_flush(self, channel_name: str, batch: List[Dict[str, Any]]) -> None:
        """Callback AggregationWindow: транслировать снапшот во ВСЕ каналы.

        channel_name игнорируется намеренно — AggregationWindow вызывает flush
        через sentinel "_stats_", а нам нужно отдать данные всем реальным каналам.
        """
        for ch in self._channel_registry.all():
            for item in batch:
                try:
                    ch.write(item)
                except Exception:
                    self._errors += 1

    # =========================================================================
    # ЗАПИСЬ МЕТРИК
    # =========================================================================

    def _merged_tags(self, tags: Optional[Dict]) -> Dict[str, str]:
        """Объединить default_tags с пользовательскими тегами.
        Пользовательские теги имеют приоритет над default_tags.
        """
        return {**self._default_tags, **(tags or {})}

    def _ensure_record(
        self,
        name: str,
        metric_type: MetricType,
        merged_tags: Dict[str, str],
    ) -> MetricRecord:
        """Получить или создать MetricRecord (thread-safe)."""
        key = _metric_key(name, merged_tags)
        with self._metrics_lock:
            if key not in self._metrics:
                self._metrics[key] = MetricRecord(
                    name=name,
                    metric_type=metric_type,
                    tags=merged_tags,
                )
            return self._metrics[key]

    def _enqueue_to_buffer(self, data: Dict[str, Any]) -> None:
        """Поместить данные в AggregationWindow ОДИН раз.

        Используем sentinel _STATS_SENTINEL вместо перебора каналов:
        это предотвращает N-кратную агрегацию при N зарегистрированных каналах.
        _do_flush транслирует снапшот во все реальные каналы при flush.
        """
        if self._buffer is not None:
            self._buffer.enqueue(_STATS_SENTINEL, data)

    def record_metric(
        self,
        name: str,
        value: Any = 1,
        tags: Optional[Dict] = None,
    ) -> None:
        """Записать счётчик (counter)."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.COUNTER, merged)
        rec.add_counter(float(value))
        self._enqueue_to_buffer({"type": "counter", "name": name, "value": float(value), "tags": merged})

    def increment(self, name: str, tags: Optional[Dict] = None) -> None:
        """Увеличить счётчик на 1."""
        self.record_metric(name, 1, tags)

    def record_timing(
        self,
        name: str,
        duration: float,
        tags: Optional[Dict] = None,
    ) -> None:
        """Записать время выполнения (в секундах)."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.TIMING, merged)
        rec.add_timing(duration)
        self._enqueue_to_buffer({"type": "timing", "name": name, "value": duration, "tags": merged})

    def gauge(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать текущее значение (gauge — перезаписывает предыдущее)."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.GAUGE, merged)
        rec.set_gauge(value)
        self._enqueue_to_buffer({"type": "gauge", "name": name, "value": value, "tags": merged})

    def histogram(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать значение в гистограмму."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.HISTOGRAM, merged)
        rec.add_histogram(value)
        self._enqueue_to_buffer({"type": "histogram", "name": name, "value": value, "tags": merged})

    # =========================================================================
    # ЧТЕНИЕ МЕТРИК
    # =========================================================================

    def get_metric(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить агрегированную метрику по имени (первое совпадение)."""
        with self._metrics_lock:
            for rec in self._metrics.values():
                if rec.name == name:
                    return rec.to_dict()
        return None

    def get_all_metrics(self) -> Dict[str, Any]:
        """Получить все метрики (key → агрегированный dict)."""
        with self._metrics_lock:
            return {k: rec.to_dict() for k, rec in self._metrics.items()}

    def reset_metrics(self) -> None:
        """Сбросить все live-метрики (не влияет на буфер агрегации)."""
        with self._metrics_lock:
            self._metrics.clear()

    # =========================================================================
    # ДИАГНОСТИКА
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Полная диагностика: каналы + буфер + метрики."""
        stats = super().get_stats()
        with self._metrics_lock:
            stats["metrics_count"] = len(self._metrics)
            stats["metric_names"] = sorted({r.name for r in self._metrics.values()})
        return stats
