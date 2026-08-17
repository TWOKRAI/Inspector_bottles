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
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from ...channel_routing_module import ChannelRoutingManager
from ...channel_routing_module.core.config_normalizer import normalize_config
from ..configs.stats_config import StatsManagerConfig
from ..interfaces import IStatsManager
from .metric_record import MetricRecord, MetricType
from .aggregation_window import AggregationWindow
from .cardinality_guard import CardinalityGuard
from ...logger_module.core.log_paths import resolve_log_file_path
from ..channels.log_stats_channel import DEFAULT_LOG_LINE_MAX_BYTES, LogStatsChannel
from ..channels.file_stats_channel import FileStatsChannel
from ..channels.hub_stats_channel import STATS_HUB_CHANNEL, HubStatsChannel

_STATS_SENTINEL = "__stats__"

#: Служебные имена каналов: их нет в секции ``channels`` конфига, но снять и
#: вернуть их через ``set_sink_enabled`` оператор вправе так же, как остальные.
STATS_LOG_CHANNEL = "log_stats"
STATS_FALLBACK_CHANNEL = "file_stats"

#: Слот менеджеров, в котором лежит hub наблюдаемости процесса (задача 2.1).
#: Именно СЛОТ, а не поле: канал в hub обязан пережить ``config.reload`` —
#: базовый ``reconfigure`` чистит реестр каналов и зовёт ``_setup_channels``
#: заново, поэтому канал, зарегистрированный снаружи, исчез бы на первой же
#: перезагрузке конфига (тот же класс, что «runtime-конфиг умирает с
#: процессом»). Пересборка читает hub отсюда и поднимает канал сама.
HUB_MANAGER_SLOT = "observability_hub"


def _metric_key(name: str, tags: Optional[Dict] = None) -> str:
    """Ключ для словаря метрик: name или name|k1:v1|k2:v2 (sorted)."""
    if not tags:
        return name
    parts = [name] + [f"{k}:{v}" for k, v in sorted(tags.items())]
    return "|".join(parts)


def _float_or(value: Any, default: float) -> float:
    """Мусор на месте числа не роняет плоскость — берётся дефолт схемы."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _schema_default(field_name: str) -> float:
    """Дефолт темпа — ИЗ СХЕМЫ, а не вторая копия числа в коде.

    Одна и та же величина в двух позициях расходится молча, и совпадение
    значений маскирует расхождение до первого изменения дефолта (оплаченный
    урок A1). Здесь позиция одна: :class:`StatsManagerConfig`.
    """
    return float(StatsManagerConfig.model_fields[field_name].default)


def resolve_max_series(cfg: Mapping[str, Any]) -> int:
    """Потолок серий из конфига — ОДНА позиция чтения ключа на обе позиции стража.

    Дефолт берётся из схемы (:data:`DEFAULT_MAX_SERIES` через
    :class:`StatsManagerConfig`), а не второй копией числа в коде: совпадение
    значений маскировало бы расхождение до первой правки дефолта.
    """
    raw = cfg.get("max_series", StatsManagerConfig.model_fields["max_series"].default)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return int(StatsManagerConfig.model_fields["max_series"].default)


def resolve_tempo(cfg: Mapping[str, Any]) -> Tuple[float, float, float]:
    """``(запрошенный интервал агрегации, пол, действующий темп записи)``.

    Действующий темп = ``max(пол, запрошенный)``. Решение владельца **Р-3(б)**:
    пол ОСТАЁТСЯ (совместимость темпа не ломается), но перестаёт действовать
    молча — он объявлен в схеме (:class:`StatsManagerConfig`,
    ``ObservabilityStatsConfig``), назван в WARNING при срабатывании
    (:meth:`StatsManager._warn_if_floor_raises_tempo`) и виден в readback'е
    отдельным ключом ``flush_interval``.

    Формула живёт ровно здесь. Пока она стояла инлайном в ``__init__``,
    пересборка конфига её не звала вовсе — и правка темпа на лету не
    действовала (major-3).
    """
    requested = _float_or(cfg.get("aggregation_interval"), _schema_default("aggregation_interval"))
    floor = _float_or(cfg.get("flush_interval"), _schema_default("flush_interval"))
    return requested, floor, max(requested, floor)


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

        # Стражи кардинальности (2.2) — ДВА экземпляра ОДНОЙ реализации, по
        # одному на накопительную позицию. Владелец обоих — менеджер, а не
        # окно: окно подменяется на каждой смене темпа
        # (``_swap_aggregation_window``), и страж, живущий внутри окна, уезжал
        # бы вместе с ним — вместе с потолком, счётом опущенных и правом на
        # голос. Создаются ДО окна, потому что окно берёт свой в конструкторе.
        limit = resolve_max_series(cfg)
        self._window_guard = CardinalityGuard(limit, position="окно агрегации", warn=self._log_warning)
        self._live_guard = CardinalityGuard(limit, position="живой слой", warn=self._log_warning)

        buffer = AggregationWindow(
            flush_fn=self._do_flush,
            flush_interval=resolve_tempo(cfg)[2],
            guard=self._window_guard,
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
            self._warn_if_floor_raises_tempo()
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
        """Хук CRM.reconfigure: пересоздать каналы и ОКНО агрегации из нового конфига.

        Базовый ``reconfigure`` уже сделал flush() и ``_close_all_channels()``
        (очистил реестр CRM). Здесь обновляем dict-конфиг и default_tags, затем
        вызываем существующий ``_setup_channels()`` (reuse) — он сам добавит
        LogStats/FileStats по новому конфигу плюс fallback-канал при необходимости.

        Live-метрики (``self._metrics``) НЕ сбрасываются — они переживают
        reconfigure.

        **B1 (major-3): окно агрегации теперь пересобирается.** Прежде здесь
        стояло «буфер НЕ сбрасывается», и это было не решением, а дефектом:
        темп записи задаётся ``AggregationWindow.flush_interval``, окно
        создавалось единожды в ``__init__``, и правка темпа на лету не
        действовала вовсе. Живой замер ревью: 115 → 138 сбросов за 187 с при
        заявленных «30».
        """
        cfg = normalize_config(config, default={})
        self._config_dict = cfg
        self._default_tags = cfg.get("default_tags") or {}
        self._setup_channels()
        # Потолок серий обновляется ОТДЕЛЬНО от подмены окна и БЕЗУСЛОВНО.
        # ``_swap_aggregation_window`` выходит рано, когда темп не изменился, —
        # и правка одного лишь `max_series` не доехала бы до окна вовсе:
        # ручка выглядела бы применённой (она в конфиге и в readback'е), а
        # действовала бы прежняя. Ровно тот класс, которым уже болел темп
        # (major-3) и предел строки (3.4).
        limit = resolve_max_series(cfg)
        self._window_guard.set_limit(limit)
        self._live_guard.set_limit(limit)
        # Строго ПОСЛЕ каналов: подмена окна делает финальный flush старого, и
        # ему нужно, куда писать, — на этом шаге реестр уже пересобран.
        self._swap_aggregation_window(cfg)
        self._warn_if_floor_raises_tempo()

    def _swap_aggregation_window(self, cfg: Dict[str, Any]) -> None:
        """Подменить окно агрегации, если СМЕНИЛСЯ ТЕМП.

        Порядок здесь и есть суть:

        1. новое окно встаёт на место ДО остановки старого — эмиссия, идущая
           прямо сейчас из чужого потока, попадает в живое окно, а не в
           закрываемое;
        2. старое окно останавливается: ``stop()`` гасит его таймер (иначе
           рядом остался бы второй писатель с прежним темпом — два разных
           периода записи одновременно) и делает ФИНАЛЬНЫЙ flush. Второе важно
           именно на этом шве: базовый ``reconfigure`` сбрасывает буфер ДО
           закрытия каналов, но эмиссия на время пересборки не замирает, и
           запись, попавшая в старое окно после того flush'а, исчезла бы вместе
           с окном.

        Темп не изменился — окно не трогаем: пересоздание ради того же числа
        обнуляло бы накопленную агрегацию на каждом ``config.reload``.

        **Страж кардинальности переезжает в новое окно** — тот же объект, не
        копия: его потолок обновляет ``_rebuild_from_config`` до этого вызова,
        а счёт опущенных и право на голос принадлежат ПРОЦЕССУ, а не окну.
        """
        tempo = resolve_tempo(cfg)[2]
        old = self._buffer
        if old is not None and getattr(old, "flush_interval", None) == tempo:
            return
        was_running = bool(old is not None and old.stats.get("running"))
        new = AggregationWindow(flush_fn=self._do_flush, flush_interval=tempo, guard=self._window_guard)
        self._buffer = new
        if old is not None:
            old.stop()
        if was_running:
            new.start()

    def _warn_if_floor_raises_tempo(self) -> None:
        """Сказать вслух, что пол поднял темп (решение Р-3б).

        Адрес ключа — в тексте: WARNING без адреса уже был находкой Ф8.5, по
        нему нельзя понять, ЧТО править. Пара к этому предупреждению —
        молчание, когда пол не сработал: детектор, срабатывающий всегда, не
        отличает настроенное от заглушенного.
        """
        requested, floor, tempo = resolve_tempo(self._config_dict)
        if requested >= floor:
            return
        self._log_warning(
            f"[{self.manager_name}] stats.aggregation_interval={requested} ниже пола "
            f"stats.flush_interval={floor} — действует {tempo} с. "
            f"Темп ниже пола задаётся только уменьшением stats.flush_interval."
        )

    def observability_readback(self) -> Dict[str, Any]:
        """Действующее состояние плоскости — для ``introspect.observability`` (B1).

        **Темп читается из ЖИВОГО окна**, а не пересчитывается из конфига:
        пересчёт дал бы то же число и при полностью несработавшей пересборке,
        то есть «effective» снова был бы эхом запроса (major-13). Пол
        (``flush_interval``) отдаётся рядом отдельным ключом — без него
        действующий темп, разошедшийся с запрошенным, нечем объяснить.

        ``enable_logging`` — про ЖИВОЙ реестр каналов, а не про то, что
        просили: логгер-менеджер мог не подняться, а канал мог быть снят
        оператором, и обе ситуации выглядят из конфига одинаково.

        Метод существует потому, что общий readback
        (``observability_effective``) читал у плоскостей ``self.config``, а у
        ``StatsManager`` этого атрибута нет вовсе — ``self.config`` ставит
        ``LoggerCore``, общий предок логгера и ошибок. Ветка stats не
        исполнялась ни разу: воспроизведено до правки —
        ``observability_effective(stats=mgr)`` → ``{}``.
        """
        out: Dict[str, Any] = {}
        tempo = getattr(self._buffer, "flush_interval", None)
        if tempo is not None:
            out["aggregation_interval"] = tempo
        out["flush_interval"] = resolve_tempo(self._config_dict)[1]
        log_channel = self._channel_registry.get(STATS_LOG_CHANNEL)
        out["enable_logging"] = log_channel is not None
        level = getattr(log_channel, "level", None)
        if level is not None:
            out["log_level"] = level
        # 3.4: без этого ключа `config_reload_verified` не может подтвердить предел —
        # живой прогон вернул `failed` на всех восьми процессах, и это было верно:
        # ключ не выживал round-trip через фасад и не показывался наружу. Ручка,
        # которую нельзя прочитать, неотличима от неприменённой.
        max_bytes = getattr(log_channel, "max_bytes", None)
        if max_bytes is not None:
            out["log_line_max_bytes"] = max_bytes
        # 2.2: потолок серий читается у ЖИВОГО стража, а не из конфига — по той
        # же причине, что темп и предел строки. Ручка, которую нельзя
        # прочитать, неотличима от неприменённой (урок 3.4), а пересчёт из
        # конфига вернул бы запрошенное число даже при несработавшей правке.
        # Оба стража держат ОДИН потолок, поэтому ключ один; расхождение между
        # ними было бы дефектом, и его сторожит тест.
        out["max_series"] = self._live_guard.limit
        return out

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
                if ch_name == STATS_HUB_CHANNEL:
                    # У этого имени СВОЙ сборщик (`_build_hub_channel`), а тип по
                    # умолчанию здесь — "file". Найдено инъекцией 2.1: запись
                    # `channels.hub_stats.enabled = true` поднимала под этим
                    # именем FileStatsChannel, то есть дверь оператора включала
                    # не тот канал, и снаружи разница была не видна — имя в
                    # реестре то же. Секция `channels` описывает файловые
                    # приёмники; служебные имена в ней читаются только ключом
                    # `enabled` (см. `_declaratively_disabled`).
                    #
                    # У соседа `log_stats` та же дыра, и она СТАРШЕ этой задачи:
                    # здесь не трогается намеренно — это смена поведения для
                    # существующих конфигов без воспроизведённой жалобы. Названа,
                    # чтобы не выглядеть незамеченной.
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

        # Задача 2.1 — СТРОГО после решения о fallback'е. Канал в hub тоже
        # «куда писать», но зачесть его в этом условии значило бы тихо снять
        # файловый приёмник у процесса без логгера: hub — bounded-буфер, и его
        # содержимое живёт до дренажа, а не до конца смены.
        hub_ch = self._build_hub_channel()
        if hub_ch is not None and not self._declaratively_disabled(STATS_HUB_CHANNEL):
            self.register_channel(hub_ch)

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
            max_bytes=cfg.get("log_line_max_bytes", DEFAULT_LOG_LINE_MAX_BYTES),
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

    def _build_hub_channel(self) -> Optional[HubStatsChannel]:
        """Канал «снапшот окна → hub наблюдаемости». None, если hub не подключён.

        Процесс без hub'а (не пилот телеметрии) — штатное состояние, а не
        деградация: у плоскости просто нет этой дороги, остальные работают.
        """
        hub = self.get_manager(HUB_MANAGER_SLOT)
        if hub is None:
            return None
        return HubStatsChannel(hub, name=STATS_HUB_CHANNEL)

    def attach_observability_hub(self, hub: Any) -> bool:
        """Подключить hub процесса: снапшоты окна поедут в стор и живой хвост (2.1).

        Зовётся composition root'ом процесса ПОСЛЕ создания hub'а
        (``wire_process_observability``) — раньше его просто нет.

        **Запрет из конфига проверяется ЗДЕСЬ, а не в `_recreate_channel`.**
        Тот намеренно игнорирует ``enabled=false`` — он обслуживает
        ``sink.enable``, то есть ЯВНЫЙ override оператора над конфигом. Проводка
        процесса override'ом не является, и без этой проверки дверь
        ``channels.hub_stats.enabled = false`` не действовала бы на боевой
        дороге вовсе: на старте `_setup_channels` отрабатывает ДО появления
        hub'а и просто не доходит до этого канала, а всю работу делает attach.
        Найдено ревью задачи 2.1 воспроизведением: снятый оператором канал
        поднимался и слал снапшоты, а `config.reload` потом молча его убирал —
        поведение менялось само, без команды.

        Returns:
            Поднялся ли канал. ``False`` штатен и означает «снят конфигом» —
            об этом сказано в лог; вызывающему решать нечего, значение здесь
            ради тестов и симметрии с ``_recreate_channel``.
        """
        self.register_manager(HUB_MANAGER_SLOT, hub)
        if self._declaratively_disabled(STATS_HUB_CHANNEL):
            self._log_info(
                f"[{self.manager_name}] канал {STATS_HUB_CHANNEL} не поднят: снят конфигом "
                f"(channels.{STATS_HUB_CHANNEL}.enabled=false) — снапшоты окна в стор и живой "
                "хвост не поедут"
            )
            return False
        return self._recreate_channel(STATS_HUB_CHANNEL)

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
        elif name == STATS_HUB_CHANNEL:
            channel = self._build_hub_channel()
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
        # 2.2: такт окна — момент, когда страж ЖИВОГО слоя говорит вслух. Своего
        # такта у него нет (слой не сбрасывается вовсе), а на горячем пути
        # предупреждение и стоило бы дорого, и несло бы числа первой секунды.
        # Страж окна говорит сам, из ``flush_all``. Оба зовутся вне локов.
        #
        # Без аргумента — сознательно: у живого слоя ПЕРИОДА нет, он не
        # чистится вовсе, и его числа законно накапливаются за срок процесса.
        # Отчёт передают там, где закрытие периода их у стража ЗАБИРАЕТ (окно):
        # иначе голос читал бы уже обнулённое.
        self._live_guard.speak()
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
    ) -> Optional[MetricRecord]:
        """Получить или создать MetricRecord (thread-safe).

        ``None`` — потолок серий живого слоя (2.2). Этот слой не чистится
        вовсе: ``reset_metrics`` зовут вручную, а на живом стенде за две минуты
        в нём накапливалось 226 серий, и рос он весь срок процесса. Потолок
        ограничивает ТОЛЬКО справочник ``get_metric``/``get_all_metrics``:
        доставка не страдает — эмиссия в окно и в tap'ы происходит в любом
        случае, и это разделение названо решением Р2.2-7.
        """
        key = _metric_key(name, merged_tags)
        with self._metrics_lock:
            record = self._metrics.get(key)
            if record is None:
                if self._live_guard.allow(key, self._metrics, name):
                    record = MetricRecord(
                        name=name,
                        metric_type=metric_type,
                        tags=merged_tags,
                    )
                    self._metrics[key] = record
        return record

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
        """Записать счётчик (counter).

        ``rec is None`` — серия не пущена в живой справочник потолком 2.2.
        Эмиссия при этом происходит ВСЕГДА: стражи двух позиций независимы, и
        отказ справочника не имеет права остановить доставку (Р2.2-7). Так же
        устроены остальные три дороги ниже.
        """
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.COUNTER, merged)
        if rec is not None:
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
        """Записать время выполнения (**в секундах**).

        Единица несущая: границы бакетов (``DEFAULT_DURATION_BUCKETS_SEC``)
        живут в секундах, и миллисекунды, посланные сюда, легли бы в бакет
        ``+Inf`` целиком — p95 стал бы константой при зелёном тесте памяти
        (§2-П7 плана этапа 6).
        """
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.TIMING, merged)
        if rec is not None:
            rec.add_timing(duration)
        self._emit_record({"type": "timing", "name": name, "value": duration, "tags": merged})

    def gauge(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать текущее значение (gauge — перезаписывает предыдущее)."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.GAUGE, merged)
        if rec is not None:
            rec.set_gauge(value)
        self._emit_record({"type": "gauge", "name": name, "value": value, "tags": merged})

    def histogram(self, name: str, value: float, tags: Optional[Dict] = None) -> None:
        """Записать значение в гистограмму (та же механика бакетов, что у timing)."""
        merged = self._merged_tags(tags)
        rec = self._ensure_record(name, MetricType.HISTOGRAM, merged)
        if rec is not None:
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
        """Сбросить все live-метрики (не влияет на буфер агрегации).

        Стражу говорят об этом ЯВНО: у живого слоя условие снимает событие,
        реально освобождающее место, а не тихий такт (справочник не чистится
        сам). Без этого вызова страж, упершийся однажды, замолчал бы навсегда —
        оператор, починивший кардинальность именно сбросом, о следующем
        переполнении не услышал бы.
        """
        with self._metrics_lock:
            self._metrics.clear()
        self._live_guard.lift()

    # =========================================================================
    # ДИАГНОСТИКА
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Полная диагностика: каналы + буфер + метрики.

        Числа потолка серий (2.2) едут ЗДЕСЬ, а не в ``LOSS_COUNTER_KEYS``
        (решение Р2.2-8): те пять классов описывают стык «менеджер → канал» и
        общие для трёх плоскостей, а кардинальность — потеря НА ВХОДЕ и
        существует только у статистики. В общем кортеже она объявила бы вечный
        ноль у логгера и у ошибок.

        **Серии и эмиссии — РАЗНЫЕ числа, и ключи названы так, чтобы их нельзя
        было перепутать.** ``series_dropped`` — сколько различных серий не
        пущено в справочник; ``observations_dropped`` — сколько эмиссий при
        этом отвергнуто (одна отказанная серия даёт столько, сколько раз её
        прислали). Пока это была одна величина, она врала на обоих вопросах.

        Числа живого слоя — за срок процесса: сам слой не чистится, и его
        отчёт никто не забирает. У окна берётся только счётчик ЭМИССИЙ за срок
        процесса: «сколько различных серий опущено» — величина окна, она едет
        в записи снапшота и там же обнуляется, а в диагностике процесса
        означала бы «в последнем незакрытом окне» и читалась бы как итог.
        """
        stats = super().get_stats()
        live = self._live_guard.report()
        window = self._window_guard.report()
        with self._metrics_lock:
            stats["metrics_count"] = len(self._metrics)
            stats["metric_names"] = sorted({r.name for r in self._metrics.values()})
        stats["max_series"] = self._live_guard.limit
        stats["series_dropped"] = live["series"]
        stats["observations_dropped"] = live["observations"]
        stats["series_dropped_is_lower_bound"] = live["series_is_lower_bound"]
        stats["dropped_series"] = live["names"]
        # Отказы окна названы ОТДЕЛЬНО: слить их с живым слоем в одну сумму
        # значило бы спрятать, какая из двух позиций уперлась, — а лечатся они
        # разным (справочник — сбросом, окно — темпом или тегами эмитента).
        #
        # **Симметрию имён здесь пробовали завести и откатили — записано, чтобы
        # не завели снова.** Правка «пусть окно отдаёт ту же четвёрку, что живой
        # слой» выглядела устранением асимметрии, а на деле смешала ПЕРИОДЫ:
        # у стража окна `series` и признак оценки снизу живут до ближайшего
        # `take_report()` (его забирает построение снапшота), а `observations`
        # и имена — за срок процесса. Воспроизведено ревью: `window_series_dropped=4`
        # → `flush()` → **0**, при том что `window_observations_dropped` остался 4.
        # Одноимённые величины с разными периодами хуже названной асимметрии:
        # первое читается неверно молча, второе хотя бы заставляет спросить.
        # «Сколько СЕРИЙ опущено за окно» и так едет в КАЖДОЙ записи снапшота
        # (`total_count − len(metrics)`), где период однозначен по построению.
        stats["window_observations_dropped"] = window["observations"]
        stats["window_dropped_series"] = window["names"]
        return stats
