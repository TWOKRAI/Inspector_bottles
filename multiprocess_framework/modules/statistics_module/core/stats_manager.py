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

#: Служебные имена каналов: их нет в секции ``channels`` конфига, но снять и
#: вернуть их через ``set_sink_enabled`` оператор вправе так же, как остальные.
STATS_LOG_CHANNEL = "log_stats"
STATS_FALLBACK_CHANNEL = "file_stats"


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
    - _emit_record — единственная точка эмиссии: сырая запись в tap'ы + ОДНА
      запись в буфер под ключом _STATS_SENTINEL. _do_flush транслирует снапшот
      во ВСЕ зарегистрированные каналы. Это предотвращает N-кратный счёт
      метрик при наличии N каналов.
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
        """Инициализация: каналы + старт flush-таймера."""
        try:
            # Порядок важен: сперва каналы, буфер — после них.
            # (Ф4.6: здесь же инициализировался мёртвый CRM-диспетчер; снят.)
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
    # flush() → buffer.stop() (финальный flush) → _close_all_channels()

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

    def _declaratively_disabled(self, name: str) -> bool:
        """Сказано ли в конфиге ``channels.<имя>.enabled = false`` (Task 5.10.c).

        Служебные каналы (:data:`STATS_LOG_CHANNEL`, :data:`STATS_FALLBACK_CHANNEL`)
        описаний в ``channels`` не имеют — их собирают свои сборщики. Но
        **запись про них** там законна и до 5.10 не читалась ничем: команда
        ``sink.disable file_stats`` работала рантаймом, а её отражение в слое
        конфига гасило ровно ничего, и первая же пересборка возвращала канал.
        Тихий no-op на ключе, который выглядит рабочим, хуже отсутствия ключа.
        """
        params = (self._config_dict.get("channels") or {}).get(name)
        return isinstance(params, dict) and params.get("enabled") is False

    def _setup_channels(self) -> None:
        """Создать и зарегистрировать каналы из конфига."""
        cfg = self._config_dict

        if cfg.get("enable_logging", True) and not self._declaratively_disabled(STATS_LOG_CHANNEL):
            log_ch = self._build_log_channel()
            if log_ch is not None:
                self.register_channel(log_ch)

        # FileStatsChannel из секции channels конфига
        channels_cfg = cfg.get("channels", {})
        if isinstance(channels_cfg, dict):
            for ch_name, ch_params in channels_cfg.items():
                if not isinstance(ch_params, dict):
                    continue
                if not ch_params.get("enabled", True):
                    continue
                file_ch = self._build_file_channel(str(ch_name), ch_params)
                if file_ch is not None:
                    self.register_channel(file_ch)

        # Fallback: всегда хотя бы один канал — КРОМЕ случая, когда оператор снял
        # его явно. «Всегда есть куда писать» ценно как умолчание и вредно как
        # запрет: без исключения снятие fallback'а не пережило бы ни одной
        # пересборки, и ключ конфига врал бы. Молча остаться без приёмников
        # плоскость при этом не может — говорим вслух аварийной функцией
        # (собственные каналы и есть предмет претензии, писать в них нечем).
        if not self._channel_registry.names():
            if self._declaratively_disabled(STATS_FALLBACK_CHANNEL):
                self._log_error(
                    f"[{self.manager_name}] у плоскости статистики не осталось ни одного приёмника: "
                    f"{STATS_FALLBACK_CHANNEL} снят конфигом (channels.{STATS_FALLBACK_CHANNEL}.enabled=false), "
                    "остальные не поднялись — метрики никуда не пишутся"
                )
            else:
                self.register_channel(self._build_fallback_channel())

    # --- сборщики каналов: по одному имени за раз ----------------------------
    # Вынесены из _setup_channels ради Ф0.6: set_sink_enabled(name, True) обязан
    # пересоздать ОДИН канал по имени, а не перестроить весь набор.

    def _build_log_channel(self) -> Optional[LogStatsChannel]:
        """Канал «метрики в лог». None, если логгер-менеджер недоступен."""
        cfg = self._config_dict
        logger_manager = self.get_manager("logger")
        if logger_manager is None and self.process is not None:
            logger_manager = getattr(self.process, "logger_manager", None)
        if logger_manager is None:
            return None
        return LogStatsChannel(
            logger_manager=logger_manager,
            level=cfg.get("log_level", "INFO"),
            name=STATS_LOG_CHANNEL,
        )

    def _build_file_channel(self, name: str, params: Dict[str, Any]) -> Optional[FileStatsChannel]:
        """Файловый канал по описанию из секции ``channels``."""
        if params.get("type", "file") != "file":
            return None
        return FileStatsChannel(
            file_path=resolve_log_file_path(
                params.get("file_path"),
                fallback=self._default_stats_file(),
                log_directory=None,
            ),
            format=params.get("format", "json"),
            name=name,
        )

    def _build_fallback_channel(self) -> FileStatsChannel:
        """Приёмник по умолчанию: у статистики всегда есть куда писать."""
        return FileStatsChannel(
            file_path=resolve_log_file_path(None, fallback=self._default_stats_file(), log_directory=None),
            name=STATS_FALLBACK_CHANNEL,
        )

    def _default_stats_file(self) -> str:
        return f"logs/stats_{self.manager_name}.json"

    def _recreate_channel(self, name: str) -> bool:
        """Пересоздать приёмник статистики по имени — хук ``CRM.set_sink_enabled``.

        Симметрия с логгером (Ф0.6): «включить обратно» пересоздаёт канал из
        собственного конфига этого менеджера. Описание берётся из секции
        ``channels``; два служебных имени (лог-канал и fallback) собираются
        своими сборщиками — в ``channels`` их нет, но снимать и возвращать их
        оператор вправе так же, как остальные.

        ``enabled=False`` в описании канала намеренно игнорируется: включение
        через control-plane — явный override оператора над конфигом, как и у
        логгера.
        """
        if name == STATS_LOG_CHANNEL:
            channel = self._build_log_channel()
        elif name == STATS_FALLBACK_CHANNEL:
            channel = self._build_fallback_channel()
        else:
            params = (self._config_dict.get("channels") or {}).get(name)
            if not isinstance(params, dict):
                return False
            channel = self._build_file_channel(name, params)

        if channel is None:
            return False
        self.register_channel(channel)
        return self._channel_registry.get(name) is not None

    # =========================================================================
    # FLUSH CALLBACK
    # =========================================================================

    def _do_flush(self, channel_name: str, batch: List[Dict[str, Any]]) -> int:
        """Callback AggregationWindow: транслировать снапшот во ВСЕ каналы.

        channel_name игнорируется намеренно — AggregationWindow вызывает flush
        через sentinel "_stats_", а нам нужно отдать данные всем реальным каналам.

        **P5: свой цикл записи заменён общим писателем базы.** В своей копии не
        считался ни один класс потери, кроме исключения, да и то безымянно
        (``_errors`` — «где-то что-то упало»). Отказ канала СТАТУСОМ
        (``{"status": "error"}``) не считался вовсе: снапшот метрик исчезал молча,
        и спросить об этом живой процесс было нечем. Инвариант плана «дроп
        допустим, невидимый дроп — нет» работал для двух плоскостей из трёх.

        Returns:
            Сколько записей каналы фактически ПРИНЯЛИ (контракт ``flush_fn → int``
            из Ф0.3). Не «отдано»: живой-но-сломанный сток отдачу принимает, а
            запись теряет — на этом уже обжигались в буфере логгера.
        """
        names = self._channel_registry.names()
        accepted = 0
        for item in batch:
            accepted += self._write_record_to_channels(item, names)
        return accepted

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

    def _emit_record(self, data: Dict[str, Any]) -> None:
        """Единственная точка эмиссии метрики: tap'ы + буфер агрегации.

        Порядок и роли:

        1. **Tap'ы получают СЫРУЮ запись сразу.** Это симметрия с логами и
           ошибками: tap не участвует в маршрутизации и не ждёт буфера — он
           видит то, что эмитировано, а не то, что осталось после агрегации.
           Для статистики разница принципиальна: ``AggregationWindow``
           намеренно lossy (counter суммируется, gauge перезаписывается), и
           tail, подключённый к сбросу, увидел бы уже свёрнутую картину.
           У метрики нет уровня, поэтому по важности она считается самой
           низкой (``record_severity``, Ф3.1) — tap с порогом ``DEBUG``
           получает всё, с порогом по умолчанию (``ERROR``) не получает
           ничего. В поле ``severity_number`` у плоскости статистики стоит
           ``UNSPECIFIED`` (0), и ставится оно по ВИДУ записи, а не по этому
           числу доставки: иначе метрика и опечатка в имени уровня стали бы
           неразличимы.
        2. **Буфер получает запись ОДИН раз**, под ключом ``_STATS_SENTINEL``:
           перебор каналов здесь дал бы N-кратную агрегацию при N каналах.
           ``_do_flush`` уже сам транслирует снапшот во все реальные каналы.

        Ф0.6: до этой правки ``StatsManager`` получил ``add_tap`` из базы, но
        звать ``_emit_to_taps`` было некому — метод существовал, а поток был
        мёртв. Нашёл независимый тестировщик: «tap регистрируется, буфер
        считает сбросы, файловый канал пишет — а write у tap'а не вызван ни
        разу».
        """
        self._emit_to_taps(data)
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
        self._emit_record({"type": "counter", "name": name, "value": float(value), "tags": merged})

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
        self._emit_record({"type": "timing", "name": name, "value": duration, "tags": merged})

    def gauge(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать текущее значение (gauge — перезаписывает предыдущее)."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.GAUGE, merged)
        rec.set_gauge(value)
        self._emit_record({"type": "gauge", "name": name, "value": value, "tags": merged})

    def histogram(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать значение в гистограмму."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.HISTOGRAM, merged)
        rec.add_histogram(value)
        self._emit_record({"type": "histogram", "name": name, "value": value, "tags": merged})

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
