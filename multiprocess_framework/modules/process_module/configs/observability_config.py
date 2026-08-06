# -*- coding: utf-8 -*-
"""
ObservabilityConfig — единый фасад над конфигами наблюдаемости.

Одна секция `observability` в конфиге процесса управляет Logger / Error / Stats /
Command вместо разрозненных Pydantic-defaults. ``expand_observability(dict)``
раскладывает её в ``{"logger": {...}, "error": {...}, "stats": {...}, "command": {...}}``
— словари, совместимые с ``LoggerManagerConfig`` / ``ErrorManagerConfig`` /
``StatsManagerConfig`` / (``command`` мержится в ``managers['command']`` и читается
``CommandManager`` напрямую — под ним нет отдельного manager-класса).

Это **фасад**, а не новые менеджеры: новых полей логики нет, expand только
переименовывает/группирует существующие. Dict at Boundary — между процессами едет dict.

Reuse-first: тогглы ``console``/``file`` переиспользуют дефолтный набор каналов
``LoggerManagerConfig`` (богатый граф scopes/per-module сохраняется), переключая лишь
``enabled`` у первичных каналов нужного типа — без дублирования дефолтов и без потери
per-module логов.

``commands.log_success`` (ADR-PM-018 в духе errors/stats-соседей, живая находка
2026-07-21): рутинный успех команды — не INFO-событие, на hot-path это тысячи строк/сек
(``command_manager.handle_command``). Гейт у ИСТОЧНИКА (CommandManager не форматирует
строку, если выключено), не фильтр на выходе. Дефолт — выключено. Ошибки/неуспех команд
эта секция не трогает — они логируются всегда, как errors всегда on в фасаде.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field, field_validator

from ...channel_routing_module.buffers.batch_buffer import (
    DEFAULT_MAX_PENDING,
    DEFAULT_OVERFLOW_POLICY,
    validate_overflow_policy,
)
from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ...log_declarations import declared_rules


@register_schema("ObservabilityErrorsConfig")
class ObservabilityErrorsConfig(SchemaBase):
    """Под-секция ошибок (фасад над ErrorManagerConfig)."""

    enabled: Annotated[bool, FieldMeta("Создавать ErrorManager")] = True
    level: Annotated[str, FieldMeta("Минимальный уровень ошибок")] = "WARNING"
    include_stacktrace: Annotated[bool, FieldMeta("Включать stacktrace")] = True

    # Task 5.10.b — зеркало верхнеуровневого ``channels`` логгера. До неё
    # плоскость ошибок была адресуема ТОЛЬКО рантаймом: `sink.disable
    # manager=error` работал, но записать его было некуда, и любой
    # `config.reload` молча воскрешал снятый `errors_file`.
    channels: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных каналов ошибок ({имя: {enabled: false}})"),
    ] = Field(default_factory=dict)


@register_schema("ObservabilityStatsConfig")
class ObservabilityStatsConfig(SchemaBase):
    """Под-секция статистики (фасад над StatsManagerConfig)."""

    enabled: Annotated[bool, FieldMeta("Логировать метрики через LoggerManager")] = True
    aggregation_interval: Annotated[
        float,
        FieldMeta("Интервал агрегации, сек", min=0.1, max=60.0),
    ] = 5.0
    # Ф6.х.8 (решение владельца 2026-08-03): ручка «реже» для snapshot-записей.
    # Реальный период записи в каналы = max(flush_interval, aggregation_interval)
    # (stats_manager.py) — прежде flush_interval фасадом не прокидывался вовсе,
    # и «тише 10 с» было невыразимо из конфига, только бинарный «выкл».
    # Дефолт 10.0 НЕ меняется: объём по умолчанию не трогаем до Ф7 (замеры
    # остаются сопоставимыми). Один источник давал 64 % объёма логов (замер #3).
    flush_interval: Annotated[
        float,
        FieldMeta("Интервал записи snapshot'ов в каналы, сек", min=1.0, max=300.0),
    ] = 10.0
    log_level: Annotated[str, FieldMeta("Уровень логирования метрик")] = "INFO"

    # Task 5.10.b — то же зеркало для третьей плоскости. Служебные имена
    # ``log_stats`` / ``file_stats`` описаний в ``channels`` не имеют (их
    # собирают свои сборщики) — но ``{enabled: false}`` про них теперь читается
    # (5.10.c): без этого ключ существовал бы, а гасил ровно ничего.
    channels: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных каналов статистики ({имя: {enabled: false}})"),
    ] = Field(default_factory=dict)


@register_schema("ObservabilityCommandsConfig")
class ObservabilityCommandsConfig(SchemaBase):
    """Под-секция логирования команд (фасад над CommandManagerConfig.log_success).

    Рутинный успех команды («Command 'X' executed successfully in Yс») — не
    ошибка и не редкое событие: на hot-path (``command_manager.handle_command``)
    это тысячи строк в секунду, и именно этот шум топил ротацию логов (живая
    находка 2026-07-21 — messages.log вырос до 645 МБ за один прогон). По
    умолчанию такие записи не производятся вовсе (не «пишем на DEBUG» — гейт
    у источника, строка не форматируется). Ошибки/неуспех команд эта секция
    не трогает — они логируются всегда, независимо от log_success.
    """

    log_success: Annotated[
        bool,
        FieldMeta("Логировать успешное выполнение команды (шумно на hot-path — по умолчанию выключено)"),
    ] = False


@register_schema("ObservabilityConfig")
class ObservabilityConfig(SchemaBase):
    """Единая секция наблюдаемости процесса (Logger + Error + Stats + Command)."""

    log_level: Annotated[str, FieldMeta("Уровень логирования по умолчанию")] = "INFO"
    log_directory: Annotated[
        Optional[str],
        FieldMeta("Корень логов (None — из env MULTIPROCESS_LOG_DIR / INSPECTOR_LOG_DIR)"),
    ] = None
    enable_batching: Annotated[bool, FieldMeta("Батчинг записи (Logger + Error)")] = True
    # Ф0.3: потолок буфера — операторский параметр, а не константа в коде. Без него
    # медленный сток копит записи в памяти без предела и без следа (см. batch_buffer.py).
    batch_max_pending: Annotated[
        int,
        FieldMeta("Потолок неотправленных записей на канал (0 — без потолка)", min=0, max=1_000_000),
    ] = DEFAULT_MAX_PENDING
    batch_overflow_policy: Annotated[
        str,
        FieldMeta("Что терять при переполнении: drop_oldest (кольцо) | drop_newest"),
    ] = DEFAULT_OVERFLOW_POLICY
    console: Annotated[bool, FieldMeta("Включить консольный sink")] = True
    file: Annotated[bool, FieldMeta("Включить файловые sink-каналы (первичные)")] = True

    # Task 5.12 — точечные переопределения ПОВЕРХ тогглов console/file.
    # Тоггл — оптовая ручка «все файловые», а слои требуют адресной: «снять
    # именно messages_file и пережить reload». Без этого поля рантайм-снятие
    # приёмника не выразимо декларативно, и оно жило рантайм-множеством,
    # которое пересборка не видела (блокер ревью 2.9). Форма — частичная:
    # словарь мержится поверх раскрытых каналов, а не заменяет их.
    channels: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных каналов логгера ({имя: {enabled: false}})"),
    ] = Field(default_factory=dict)
    scopes: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Переопределения отдельных скоупов логгера ({имя: {min_level: DEBUG}})"),
    ] = Field(default_factory=dict)

    # Ф2.2 — вторая ось адресации: правило по иерархическому имени источника.
    # Скоуп остаётся оптовой ручкой («весь BUSINESS тише»), а эта — адресной:
    # ключ — любой префикс имени (``multiprocess_framework.modules.router_module``),
    # действует самое длинное совпадение. Без неё «включить DEBUG одному файлу»
    # выражалось только через порог всего скоупа, а раскладка по файлам не
    # выражалась вовсе: на живом прогоне 2026-08-03 из 384 per-module файлов
    # непустыми были 4, и все четыре — по совпадению имени процесса с ключом.
    loggers: Annotated[
        Dict[str, Dict[str, Any]],
        FieldMeta("Правила по имени источника ({префикс: {level: DEBUG, channels: [...]}})"),
    ] = Field(default_factory=dict)

    # Ф2.5 — ярлык набора источников (модель `logging.group.*` Spring Boot).
    # Без него «этим трём тише» переписывается покомпонентно: в конфиге прототипа
    # после 2.6 стояли ДВЕ правки с одинаковым телом, а набор «служебная болтовня»
    # существовал только в голове оператора.
    logger_groups: Annotated[
        Dict[str, List[str]],
        FieldMeta("Ярлыки источников ({имя_группы: [префикс, ...]})"),
    ] = Field(default_factory=dict)

    # Task 5.8 — срок жизни рантайм-правки (слой L3). Поле схемы, а не константа
    # в коде: политика «сколько живёт ручка» машинно-специфична (на стенде час
    # уместен, на линии — нет), а значит обязана задаваться теми же слоями, что
    # и всё остальное. Раскладке в manager-конфиги НЕ подлежит — им про сессию
    # знать нечего; ключ читает только бухгалтерия слоёв.
    session_ttl_sec: Annotated[
        float,
        FieldMeta("Срок жизни рантайм-правки наблюдаемости, сек (0 — бессрочно)", min=0.0, max=86400.0),
    ] = 300.0

    # Ф0.7. Ротация ограничивает каждый файл, но не их число — за 82 дня
    # накопилось 730 файлов / 291 МБ без единого удаления. Обе политики
    # выключены по умолчанию: включать чистку молча нельзя.
    retention_days: Annotated[
        int,
        FieldMeta("Удалять логи старше N суток (0 — выключено)", min=0, max=3650),
    ] = 0
    retention_total_mb: Annotated[
        int,
        FieldMeta("Потолок суммарного веса каталога логов, МБ (0 — выключено)", min=0, max=1_000_000),
    ] = 0
    compress_rotated: Annotated[
        bool,
        FieldMeta("Сжимать ротированные бэкапы (foo.log.1 → foo.log.1.gz)"),
    ] = False
    # Ф6.9. Свип звался только на старте и на reconfigure — на стенде 24/7
    # настроенный ретеншен подметал бы только при рестарте. Поток поднимается
    # ТОЛЬКО если ретеншен реально включён, поэтому дефолт здесь ничего не
    # включает сам по себе.
    retention_sweep_interval_sec: Annotated[
        float,
        FieldMeta("Период фонового свипа ретеншена, сек (0 — только старт и reconfigure)", min=0.0, max=86400.0),
    ] = 3600.0

    # Ф7.1. Дроссель повторяющихся записей: ключ «уровень + текст», first-N
    # then every-Mth с перезапуском по тишине. Выключен по умолчанию, и
    # выключенность выражена параметром (0), а не отдельным флагом. Живёт
    # рядом с ретеншеном не случайно: обе политики САМИ решают, чего не
    # останется, и обе поэтому не включаются молча.
    sampling_first_n: Annotated[
        int,
        FieldMeta("Сколько одинаковых записей пропускать всегда (0 — сэмплинг выключен)", min=0, max=100_000),
    ] = 0
    sampling_every_mth: Annotated[
        int,
        FieldMeta("После первых N проходит каждая M-я одинаковая запись", min=1, max=1_000_000),
    ] = 100
    sampling_burst_reset_sec: Annotated[
        float,
        FieldMeta("Тишина по ключу дольше этого начинает всплеск заново, сек", min=0.0, max=86400.0),
    ] = 5.0
    sampling_max_level: Annotated[
        str,
        FieldMeta("Верхняя граница уровня для дросселя (ERROR/CRITICAL не сэмплируются никогда)"),
    ] = "DEBUG"

    errors: Annotated[
        ObservabilityErrorsConfig,
        FieldMeta("Секция ошибок"),
    ] = Field(default_factory=ObservabilityErrorsConfig)
    stats: Annotated[
        ObservabilityStatsConfig,
        FieldMeta("Секция статистики"),
    ] = Field(default_factory=ObservabilityStatsConfig)
    commands: Annotated[
        ObservabilityCommandsConfig,
        FieldMeta("Секция команд (CommandManager)"),
    ] = Field(default_factory=ObservabilityCommandsConfig)

    @field_validator("batch_overflow_policy")
    @classmethod
    def _check_overflow_policy(cls, value: str) -> str:
        """Отказ на границе конфига — до того, как правка коснётся менеджеров."""
        return validate_overflow_policy(value)

    @field_validator("scopes", mode="before")
    @classmethod
    def _normalize_scope_keys(cls, value: Any) -> Any:
        """Ф2.4: канон имени группы — заглавными, и приводится ЗДЕСЬ ТОЖЕ.

        Копия правила у ``LoggerManagerConfig`` его не покрывает: слои
        наблюдаемости мержатся между собой (``deep_merge``) ДО того, как
        результат доедет до конфига менеджера, и ключ ``system:`` из
        ``system.yaml`` лёг бы рядом с ``SYSTEM`` из дефолта, а не поверх него.
        До менеджера доехали бы ОБА, и настройка «сделать SYSTEM тише» тихо не
        сработала бы.

        Это второе место, а не вторая реализация: правило одно («канон
        заглавными»), а точки его применения — две, потому что и границ конфига
        две. Разъехаться им нечем — приведение регистра целиком в одну строку.
        """
        if not isinstance(value, dict):
            return value
        return {(k.upper() if isinstance(k, str) else k): v for k, v in value.items()}


def _toggled_logger_channels(console: bool, file: bool) -> Dict[str, Dict[str, Any]]:
    """Дефолтные каналы LoggerManagerConfig с переключённым ``enabled`` по типу.

    Reuse: берём богатый граф каналов из дефолта LoggerManagerConfig (имена сохраняются,
    значит scopes продолжают резолвиться), флипаем только ``enabled`` для console/file.
    Ленивый импорт — избегаем цикла process_module ↔ logger_module на уровне модуля.
    """
    from ...logger_module.configs.logger_manager_config import LoggerManagerConfig

    result: Dict[str, Dict[str, Any]] = {}
    for name, ch in LoggerManagerConfig().channels.items():
        keep = console if ch.type == "console" else (file if ch.type == "file" else True)
        result[str(name)] = {**ch.model_dump(), "enabled": bool(ch.enabled and keep)}
    return result


def expand_observability(data: Any) -> Dict[str, Dict[str, Any]]:
    """Разложить секцию observability в четыре manager-конфига.

    Args:
        data: dict | ObservabilityConfig | None — единая секция. None/частичная → defaults.

    Returns:
        ``{"logger": {...}, "error": {...}, "stats": {...}, "command": {...}}`` —
        ``logger``/``error``/``stats`` валидны для соответствующего manager-конфига
        (``error`` всегда непустой — ErrorManager создаётся); ``command`` — сырой dict
        (``{"log_success": bool}``), мержится в ``proc_dict['managers']['command']``
        (см. ``managers_config.merge_managers`` + ``ManagersConfig``) и читается
        ``CommandManager`` напрямую — под ``command`` нет отдельного manager-класса,
        поэтому валидировать через Pydantic-конфиг здесь нечего.

        Ключ ``session_ttl_sec`` (Task 5.8) сюда НЕ раскладывается сознательно: это
        политика слоя L3, а не параметр менеджера — её читает
        ``ObservabilityLayers.effective_session_ttl``.
    """
    cfg = data if isinstance(data, ObservabilityConfig) else ObservabilityConfig.model_validate(data or {})

    logger: Dict[str, Any] = {
        "enable_batching": cfg.enable_batching,
        "batch_max_pending": cfg.batch_max_pending,
        "batch_overflow_policy": cfg.batch_overflow_policy,
        # Ретеншен получает ТОЛЬКО logger: каталог логов один на процесс, и
        # второй подметальщик (error) означал бы два прохода по одному дереву
        # с гонкой за одни и те же файлы. Один каталог — один хозяин.
        "retention_days": cfg.retention_days,
        "retention_total_mb": cfg.retention_total_mb,
        "compress_rotated": cfg.compress_rotated,
        "retention_sweep_interval_sec": cfg.retention_sweep_interval_sec,
        # Ф7.1: дроссель получает ТОЛЬКО logger — у плоскости ошибок его нет по
        # построению (ошибки не сэмплируются), и передавать туда параметры
        # значило бы заявлять ручку, которая ничего не делает.
        "sampling_first_n": cfg.sampling_first_n,
        "sampling_every_mth": cfg.sampling_every_mth,
        "sampling_burst_reset_sec": cfg.sampling_burst_reset_sec,
        "sampling_max_level": cfg.sampling_max_level,
    }
    # log_directory эмитим ТОЛЬКО если задан явно: при overlay-merge поверх дефолтов
    # None затёр бы уже резолвнутый абсолютный путь (managers_from_log_dir). None =
    # «не задано → использовать downstream-дефолт».
    if cfg.log_directory is not None:
        logger["log_directory"] = cfg.log_directory
    # default_level — ТО ЖЕ ПРАВИЛО, доведённое до уровня ключа (A-A4-2 ревью Ф5).
    # ADR-PM-020 объявил «молчание слоёв означает „решает нижний“», но проверял
    # молчание СЕКЦИИ целиком: достаточно было одного ключа `channels.*` в любом
    # слое, чтобы секция перестала быть молчащей — и материализованный дефолт L0
    # `INFO` лёг поверх уровня из `INSPECTOR_LOG_LEVEL`, который к этому моменту
    # уже стоял в базе (`managers_from_log_dir`). Машинный контекст переопределяется
    # только ЯВНЫМ ключом, и «явно» здесь не выводится из значения: у уровня нет
    # свободного `None`, как у каталога, поэтому спрашиваем Pydantic, приезжал ли
    # ключ вообще. Значение, совпавшее с дефолтом L0, остаётся явным — намерение
    # оператора, написавшего INFO поверх DEBUG, не то же самое, что молчание.
    if "log_level" in cfg.model_fields_set:
        logger["default_level"] = cfg.log_level
    # Тогглы применяем только если что-то выключено — иначе LoggerManagerConfig
    # сам подставит дефолтные каналы (идентичный результат, меньше связности).
    if not (cfg.console and cfg.file):
        logger["channels"] = _toggled_logger_channels(cfg.console, cfg.file)
    # Task 5.12: адресные переопределения каналов/скоупов кладём ЧАСТИЧНЫМ словарём.
    # Он всегда попадает в deep-merge поверх полного набора (boot —
    # `merge_managers(base_managers, overlay)`, reload — merge поверх живого/базы),
    # поэтому неполная запись `{имя: {enabled: false}}` валидна: до Pydantic она
    # доезжает уже слитой. Заменять весь набор здесь нельзя — это стёрло бы
    # остальные каналы (ровно тот класс, что дал находку 2026-07-22 на каталоге).
    if cfg.channels:
        from ...data_schema_module import deep_merge

        logger["channels"] = deep_merge(logger.get("channels") or {}, cfg.channels)
    if cfg.scopes:
        logger["scopes"] = {str(k): dict(v) for k, v in cfg.scopes.items()}
    if cfg.logger_groups:
        logger["logger_groups"] = {str(k): list(v) for k, v in cfg.logger_groups.items()}
    # Ф2.2 — тем же способом, что скоупы: раскладываем только когда секция
    # реально что-то сказала. Пустой словарь наверх не эмитим сознательно —
    # он был бы «слой объявил пустоту» по правилу Г3 и стирал бы правила,
    # заданные ниже (ровно тот класс, что дал находку на каталоге каналов).
    # Ф2.7 — объявления модулей идут ПОД конфигом приложения: модуль знает про себя,
    # но последнее слово за тем, кто систему собирает. Порядок распаковки и есть
    # приоритет; переставь его — и правка в `system.yaml` перестанет действовать,
    # оставаясь видимой в файле (тихий отказ того же класса, что уже стоил фазе
    # 288 пустых файлов).
    # Ф2.х (Н1): правило приложения перекрывает объявленное ПО ОСЯМ, а не целиком.
    # `{**declared, **layered}` замещал запись по ключу: приложение, правившее
    # ТОЛЬКО `level`, молча стирало `channels`, объявленные модулем, — а «две оси
    # резолвятся независимо» это аксиома дерева (Ф2.2), и шов слоёв обязан
    # говорить на том же языке. Явное стирание оси осталось выразимым штатно:
    # `channels: []` — «приёмников нет, и это решение» (Г3).
    # `exclude_none=True` — объявление претендует только на оси, про которые
    # модуль реально сказал; молчание не материализуется ключом.
    declared = {name: rule.model_dump(exclude_none=True) for name, rule in declared_rules().items()}
    layered = {str(k): dict(v) for k, v in cfg.loggers.items()} if cfg.loggers else {}
    merged: Dict[str, Any] = dict(declared)
    for name, rule in layered.items():
        base = merged.get(name)
        merged[name] = {**base, **rule} if base else rule
    if merged:
        logger["loggers"] = merged

    error: Dict[str, Any] = {
        "default_level": cfg.errors.level,
        "include_stacktrace": cfg.errors.include_stacktrace,
        "enable_batching": cfg.enable_batching,
        "batch_max_pending": cfg.batch_max_pending,
        "batch_overflow_policy": cfg.batch_overflow_policy,
    }

    stats: Dict[str, Any] = {
        "enable_logging": cfg.stats.enabled,
        "aggregation_interval": cfg.stats.aggregation_interval,
        # Ф6.х.8: без прокида этой ручки менеджер всегда брал дефолт 10.0, и
        # max(flush_interval, aggregation_interval) съедал любую настройку темпа.
        "flush_interval": cfg.stats.flush_interval,
        "log_level": cfg.stats.log_level,
    }

    # Task 5.10.b: адресные переопределения каналов двух младших плоскостей —
    # тем же ЧАСТИЧНЫМ словарём, что у логгера. Полное описание канала здесь не
    # собирается сознательно: severity-каналы ошибок строит
    # ``expand_error_manager_config``, а служебные каналы статистики — её
    # собственные сборщики; наша запись обязана лечь поверх, а не вместо.
    if cfg.errors.channels:
        error["channels"] = {str(k): dict(v) for k, v in cfg.errors.channels.items()}
    if cfg.stats.channels:
        stats["channels"] = {str(k): dict(v) for k, v in cfg.stats.channels.items()}

    command: Dict[str, Any] = {
        "log_success": cfg.commands.log_success,
    }

    return {"logger": logger, "error": error, "stats": stats, "command": command}
