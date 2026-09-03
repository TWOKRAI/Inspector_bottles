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

from pydantic import Field, field_validator, model_validator

from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ...observability_declarations import declared_rules
from ...logger_module.configs.logger_manager_config import MIN_BURST_RESET_SEC
from ...statistics_module import DEFAULT_LOG_LINE_MAX_BYTES, DEFAULT_MAX_SERIES
from ...channel_routing_module.levels import LEVEL_ORDER, normalize_level_name
from .observation_policy import ObservationPolicyConfig

#: Ключи, снятые Ф7.4 вместе с батчингом записи. Схема принимает лишние ключи
#: МОЛЧА (проверено), поэтому без сверки конфиг с ``enable_batching: true`` после
#: сноса просто перестал бы что-либо значить: оператор правит ручку, ничего не
#: меняется, и никто ему об этом не говорит — ровно класс «проглоченный сбой»,
#: который эта фаза и лечит. Константа модульная (не приватное поле схемы):
#: у Pydantic ``_имя`` в теле класса становится ``ModelPrivateAttr`` и из
#: валидатора не читается.
REMOVED_BATCHING_KEYS = (
    "enable_batching",
    "batch_size",
    "batch_interval",
    "batch_max_pending",
    "batch_overflow_policy",
)


@register_schema("ObservabilityDocumentsConfig")
class ObservabilityDocumentsConfig(SchemaBase):
    """Под-секция плоскости документов (Ф8.5) — второе правило допуска.

    Здесь нет ни пути к БД, ни срока хранения: и то и другое едет в ``config``
    неразобранным. Фреймворк владеет ВОПРОСОМ («куда девать запись, чья ценность не
    выражается severity»), а ответ — SQL, файл, сетевой сервис — принадлежит
    композиционному корню. Знай фреймворк про ``db_path``, он знал бы, что плоскость
    реализована базой, — то есть импорт ``Services`` вернулся бы через конфиг
    (правило слоёв 9).

    ``factory`` пуст → плоскости нет, поведение прежнее (аудит живёт кольцом и
    строкой журнала). Заполнен и не сработал → процесс стартует БЕЗ плоскости и
    пишет WARNING с адресом ключа: молчаливый ``sink is None`` неотличим от
    «не настроено», а это ровно класс «проглоченный сбой».
    """

    factory: Annotated[
        str,
        FieldMeta("Import-path фабрики стока, 'модуль:атрибут' или 'модуль.атрибут' (пусто — плоскости нет)"),
    ] = ""
    config: Annotated[
        Dict[str, Any],
        FieldMeta("Словарь фабрики, отдаётся ей as-is (db_path, retention_sec, purge_interval_sec, …)"),
    ] = Field(default_factory=dict)


@register_schema("ObservabilityEventsConfig")
class ObservabilityEventsConfig(SchemaBase):
    """Под-секция отбора широких записей о единице работы (Ф4, задача 4.1).

    Wide event — одна запись со всем контекстом единицы (вердикт, счётчики, ROI,
    спаны). Фронты решения (``decisive=True``) идут мимо отбора ВСЕГДА; здесь
    настраивается только ПОТОК — записи о каждой рядовой единице.

    **Дефолт 0/0 = поток не пишется вовсе.** Выключенность выражена параметрами,
    а не отдельным флагом: два способа сказать «выключено» рано или поздно
    разъезжаются (правило «флаги не костыли», тот же довод у ``sampling_first_n``).

    **Ловушка имён.** Рядом, в этой же секции, живут ``sampling_first_n`` /
    ``sampling_every_mth`` логгера — те же слова, но ДРУГОЙ ключ отбора (пара
    «уровень + текст» записи, а не род единицы) и другой смысл нуля: у дросселя
    логгера ``every_mth`` имеет ``min=1`` и ноль там невыразим, здесь же ноль —
    штатное «после первых N не проходит ничего». Слить их в один механизм нельзя:
    у wide event текст свой у каждой единицы, и дроссель по тексту не дросселирует
    ничего по построению.
    """

    first_n: Annotated[
        int,
        FieldMeta(
            "Сколько потоковых записей КАЖДОГО рода пропускать всегда (0 — поток не пишется)",
            min=0,
            max=100_000,
        ),
    ] = 0
    every_mth: Annotated[
        int,
        FieldMeta(
            "После первых N проходит каждая M-я запись рода (0 — дальше не проходит ничего)",
            min=0,
            max=1_000_000,
        ),
    ] = 0


@register_schema("ObservabilityVoicesConfig")
class ObservabilityVoicesConfig(SchemaBase):
    """Под-секция окон голоса — повторяющееся состояние говорит раз в окно (Ф1.4, M17).

    Политика, а не параметр менеджера: держателей окон в процессе много (роутер,
    реестр очередей, менеджер процессов), и ни один из них не является плоскостью
    наблюдаемости. Читает секцию живой механизм
    (:mod:`...logger_module.core.windowed_voice`) через ``wire_voices_policy`` на
    старте и ``apply_voices_policy`` на пересборке — по той же схеме трёх точек,
    что ``events`` / ``flight`` / ``observation``.

    **Одно отличие от них названо прямо, потому что на нём уже поскользнулись.**
    У соседей получатель ручки — ЖИВОЙ ОБЪЕКТ процесса (селектор, рекордер,
    гейт), который вызывающий обязан прокинуть в readback; здесь получателя нет,
    политика процессная, и readback читает её у самого механизма — безусловно.
    Имена полей при этом обязаны совпадать с именами ЭТОЙ схемы на всём пути:
    ревью Task 1.4 воспроизвело, как ``default_window_sec`` уезжал наружу под
    именем ``window_sec``, и подача собственного readback'а обратно молча
    сбрасывала окно в дефолт — ``extra=ignore`` съедает незнакомое имя без
    единого слова.

    Окно ЖИВЁТ ЗДЕСЬ, а не литералом в коде, потому что до этой задачи его
    переписывали вручную от файла к файлу — все копии со значением 5.0 и ни одна
    не настраиваемая, так что «тише на линии, разговорчивее на стенде» было
    невыразимо. Поимённый реестр копий —
    ``logger_module.core.windowed_voice.REPLACED_MANUAL_WINDOWS``; числом он
    здесь не пересказывается, и это правка ревью Task 1.3a: прежняя редакция
    говорила «семь раз» при шести перечисленных, а сосед в тот же момент говорил
    «шесть» — ровно тот разъезд слова с перечнем, который реестр и снимает.

    **Потолок карты и такт протухания (Task 2.7, добор ревью Ф1).** До этой
    задачи ``MAX_TRACKED_KEYS``/``_STALE_WINDOWS`` были литералами прямо в
    ``windowed_voice.py`` — ёмкость и такт без ручки и без readback (нарушение
    правила 2 §1 плана ``observability-closure``, при том что механизм-сосед,
    дроссель-сэмплер ``core/sampling.py``, уже публиковал и число ключей, и
    насыщение). L0-дефолты полей ниже совпадают с бывшими литералами (512, 10)
    — задача переносит их в конфиг БЕЗ смены поведения по умолчанию.
    """

    default_window_sec: Annotated[
        float,
        FieldMeta("Окно голоса по умолчанию, сек (0 — не голосить чаще, чем каждый раз)", min=0.0, max=3600.0),
    ] = 5.0

    #: Строго «больше порога»: 3 означает, что четвёртый подряд говорит громко.
    #: Ось повторов ПОДРЯД, а не времени: единичный фолбэк готовности — норма
    #: старта, серия подряд — симптом. Одним окном это не выражается.
    escalate_after_repeats: Annotated[
        int,
        FieldMeta("Повторов подряд по ключу до эскалации INFO → WARNING", min=1, max=1000),
    ] = 3

    #: Бывший ``windowed_voice.MAX_TRACKED_KEYS``. Потолок ОБЕИХ карт держателя
    #: (окон и серий — один потолок, не дублирование, см. докстринг механизма).
    #: Верхняя граница 1_000_000 — не расчётная, а защита от опечатки в 0/1
    #: лишним нулём на конфиге прототипа: ни один живой держатель не подходит к
    #: тысячам ключей сегодня.
    max_tracked_keys: Annotated[
        int,
        FieldMeta("Потолок карты ключей держателя окон (обе карты — окна и серии)", min=1, max=1_000_000),
    ] = 512

    #: Бывший ``windowed_voice._STALE_WINDOWS``. Такт в единицах ОКНА ключа
    #: (``e[2]`` — своё окно записи), а не в секундах: ключи с разными окнами
    #: протухают по-разному, и абсолютное время смешало бы две оси.
    stale_windows: Annotated[
        int,
        FieldMeta("Сколько окон молчания до того, как бездолжный ключ считается протухшим", min=1, max=10_000),
    ] = 10


@register_schema("ObservabilityFlightConfig")
class ObservabilityFlightConfig(SchemaBase):
    """Под-секция flight recorder'а — дампа кольца записей по требованию (Ф5, 5.1).

    Кольцо ЗАПИСЕЙ, а не пикселей: дамп отвечает на «что происходило вокруг
    момента брака» строками плоскости логов этого процесса, включая широкие
    записи Ф4. Изображения кадров сюда не едут и не поедут — у них свои
    механизмы (copy_out, датасет).

    **Выключенность выражена ОДНИМ ключом с ОДНИМ адресом** (Р5.1-5). Соблазн
    был выразить её вторым способом — «нет memory-канала в конфиге процесса», —
    и он отвергнут: два независимых способа быть выключенным дают ровно тот
    класс, где оператор гасит один, а действует другой. Здесь нет канала —
    механизм отвечает ДРУГИМ названным отказом (см. ``sink``), а не тем же
    самым.

    **Ловушка соседней двери, названная явно** (Р5.1-7). Само кольцо объявляется
    не здесь, а в ``observability.channels.<имя>`` — и там обязателен
    ``type: memory``. Без него общий цикл секции каналов строит ФАЙЛОВЫЙ
    приёмник под тем же именем (дефолт ``LoggerChannelSchema.type == "file"``),
    и снаружи разница не видна: канал есть, ``sink`` на него указывает, а
    ``tail()`` у файла отсутствует — дамп отвечает «приёмник записей не хранит».
    Маршрут в кольцо (``observability.scopes``) обязателен по той же причине:
    объявленный и не смаршрутизированный канал поднят и вечно пуст.
    """

    enabled: Annotated[
        bool,
        FieldMeta("Писать ли дампы кольца по вызову ctx.flight_dump (единственный выключатель)"),
    ] = False
    sink: Annotated[
        str,
        FieldMeta("Имя memory-приёмника ЛОГГЕРА, чьё кольцо уходит в дамп (пусто — читать нечего)"),
    ] = ""
    keep: Annotated[
        int,
        FieldMeta("Сколько последних дампов держать в каталоге flight/ (0 — без предела)", min=0, max=10_000),
    ] = 5
    limit: Annotated[
        int,
        FieldMeta("Сколько последних записей кольца брать в дамп (0 — всё, что лежит)", min=0, max=1_000_000),
    ] = 0


@register_schema("ObservabilityHistoryConfig")
class ObservabilityHistoryConfig(SchemaBase):
    """Под-секция истории (SQLite-стор) — порог записи и пределы ретеншена (Ф5.2, Ф2 задача 2.2).

    До задачи 2.2 эти четыре значения читались МИМО схемы — прямо строковым
    ``.get()`` из разрешённых слоёв (``resolve_history_policy``), поэтому
    ``history.level`` отвергался операторской дверью (``config.reload`` inline)
    как незнакомый ключ: сверка имён (``unknown_section_keys``, задача 5.4)
    судит round-trip через ``ObservabilityConfig``, а секции ``history`` в ней
    не было вовсе. Дефолты здесь — те же числа, что раньше жили литералами в
    ``managers/observability_wiring.py`` (``DEFAULT_HISTORY_*``); та модуль
    теперь читает их у ЭТОЙ схемы (см. докстринг констант), а не дублирует.

    ``enabled``/``db_path`` — вторая пара, которой раньше не было НИГДЕ: стор
    поднимался ВСЕГДА, когда есть hub, и путь к БД был только машинным дефолтом
    (``resolve_default_db_path()``). Читает их проводка (``ProcessModule.
    _wire_observability_hub``) АТРИБУТОМ схемы (``cfg.history.enabled`` /
    ``cfg.history.db_path``) — ровно та же дорога, что у остальных четырёх
    полей.
    """

    enabled: Annotated[
        bool,
        FieldMeta("Вести историю (стор создаётся только когда True и у процесса есть hub)"),
    ] = True
    level: Annotated[str, FieldMeta("Минимальный уровень записи в историю")] = "INFO"
    max_rows: Annotated[
        int,
        FieldMeta("Потолок таблицы по числу строк (0 — предела нет)", min=0, max=100_000_000),
    ] = 200_000
    max_age_sec: Annotated[
        float,
        FieldMeta("Возраст, старше которого запись уходит, сек (0 — предела нет)", min=0.0, max=31_536_000.0),
    ] = 7 * 24 * 3600.0
    purge_interval_sec: Annotated[
        float,
        FieldMeta("Период фонового свипа истории, сек", min=0.0, max=86400.0),
    ] = 300.0
    db_path: Annotated[
        str,
        FieldMeta("Путь к SQLite-файлу стора (пусто — resolve_default_db_path())"),
    ] = ""

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, value):
        return canonical_level_or_raise(value, field="history.level")


def canonical_level_or_raise(value: Any, *, field: str) -> Any:
    """Каноничное имя уровня либо громкий отказ с адресом ключа (B2).

    Одна позиция правила на все ручки уровня секции: `log_level`,
    `errors.level`, `stats.log_level`, `sampling_max_level`. Пока копий было бы
    четыре, они разошлись бы на первом же новом синониме — и «неизвестный
    уровень» значило бы разное в соседних ключах одной секции.

    Отказ несёт И адрес ключа, И список допустимых значений: WARNING без адреса
    уже был находкой Ф8.5 — по нему нельзя понять, что именно править.
    """
    if not isinstance(value, str):
        return value
    canonical = normalize_level_name(value)
    if canonical is None:
        raise ValueError(
            f"неизвестный уровень '{value}' в {field} (известны: {', '.join(LEVEL_ORDER)}; синонимы: WARN, FATAL)"
        )
    return canonical


def canonical_scope_keys(value: Any) -> Any:
    """Ф2.4: канон имени группы — заглавными, и приводится ЗДЕСЬ ТОЖЕ.

    Копия правила у ``LoggerManagerConfig`` его не покрывает: слои
    наблюдаемости мержатся между собой (``deep_merge``) ДО того, как результат
    доедет до конфига менеджера, и ключ ``system:`` из ``system.yaml`` лёг бы
    рядом с ``SYSTEM`` из дефолта, а не поверх него. До менеджера доехали бы
    ОБА, и настройка «сделать SYSTEM тише» тихо не сработала бы.

    Это второе место, а не вторая реализация: правило одно («канон заглавными»),
    а точки его применения — две, потому что и границ конфига две. Разъехаться
    им нечем — приведение регистра целиком в одну строку.

    **Задача 5.4 — третий вызывающий, и ради него правило стало функцией.**
    :func:`~.observability_layers.unknown_section_keys` сверяет ключи запроса с
    теми, что выжили в round-trip через схему, а схема к этому моменту УЖЕ
    переименовала ``scopes.system`` в ``scopes.SYSTEM``: сравнение сырых путей
    объявляло законное строчное имя незнакомым (проверено до правки —
    ``unknown_keys == ['scopes.system.channels']`` при работающей настройке).
    Пока это жило только в вердикте, ценой был ложный ``failed``; с отказом на
    границе ценой стал бы отказ законной правке. Поэтому сверяющий приводит
    запрос ТЕМ ЖЕ правилом, а не своей копией регистра.
    """
    if not isinstance(value, dict):
        return value
    return {(k.upper() if isinstance(k, str) else k): v for k, v in value.items()}


@register_schema("ObservabilityErrorsConfig")
class ObservabilityErrorsConfig(SchemaBase):
    """Под-секция ошибок (фасад над ErrorManagerConfig)."""

    enabled: Annotated[bool, FieldMeta("Создавать ErrorManager")] = True
    level: Annotated[str, FieldMeta("Минимальный уровень ошибок")] = "WARNING"
    include_stacktrace: Annotated[bool, FieldMeta("Включать stacktrace")] = True

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, value):
        return canonical_level_or_raise(value, field="errors.level")

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
    """Под-секция статистики (фасад над StatsManagerConfig).

    **Ф2, задача 2.1: ``enabled`` сменил смысл** (развилка Р-3, вариант «а»,
    решение владельца). Было — «логировать метрики через LoggerManager», то есть
    ручка ОДНОГО канала. Стало — ПЛОСКОСТЬ: ``false`` означает, что числа не
    собираются вовсе (окно пусто, каналы молчат, счётчик
    ``numbers_policy_dropped`` растёт). Прежний смысл переехал в новый ключ
    :attr:`log_snapshots` с дефолтом ``True``, поэтому конфиг со старым
    ``enabled: true`` ведёт себя дословно как раньше.

    Это ЕДИНСТВЕННАЯ смена поведения существующего ключа во всей фазе, и
    митигация к ней прилагается вся, а не наполовину: ADR-PM-046, паритетный
    тест на боевом конфиге прототипа и громкий голос при чтении старого
    ``enabled: false`` (:meth:`_complain_about_repurposed_enabled`).
    """

    enabled: Annotated[
        bool,
        FieldMeta(
            "Плоскость чисел включена (false — метрики не собираются вовсе)",
            info="Ф2/Р-3а: до этой задачи ключ означал «логировать снапшоты» — этот смысл "
            "переехал в stats.log_snapshots (дефолт true)",
        ),
    ] = True
    log_snapshots: Annotated[
        bool,
        FieldMeta(
            "Писать снапшоты метрик в журнал через LoggerManager",
            info="Прежний смысл stats.enabled. Независим от плоскости: числа можно собирать "
            "и не логировать (log_snapshots=false), но не наоборот",
        ),
    ] = True
    aggregation_interval: Annotated[
        float,
        FieldMeta("Интервал агрегации, сек (действует max с flush_interval)", min=0.1, max=60.0),
    ] = 5.0
    # Ф6.х.8 (решение владельца 2026-08-03): ручка «реже» для snapshot-записей.
    # Реальный период записи в каналы = max(flush_interval, aggregation_interval)
    # (stats_manager.resolve_tempo) — прежде flush_interval фасадом не прокидывался
    # вовсе, и «тише 10 с» было невыразимо из конфига, только бинарный «выкл».
    # Дефолт 10.0 НЕ меняется: объём по умолчанию не трогаем до Ф7 (замеры
    # остаются сопоставимыми). Один источник давал 64 % объёма логов (замер #3).
    #
    # B1 / Р-3(б): это ПОЛ, и он объявлен полом здесь, в WARNING менеджера и в
    # readback'е. Значение `aggregation_interval` ниже пола не действует —
    # `config_reload_verified` вернёт `failed` с обоими числами, а не «успех».
    flush_interval: Annotated[
        float,
        FieldMeta("ПОЛ интервала записи snapshot'ов, сек — темп ниже него недостижим", min=1.0, max=300.0),
    ] = 10.0
    log_level: Annotated[str, FieldMeta("Уровень логирования метрик")] = "INFO"

    # 3.4: предел объёма ОДНОЙ строки снапшота. Живёт здесь, а не только в
    # `StatsManagerConfig`, потому что этот фасад — единственная дорога конфига
    # приложения к плоскости: ключ, которого тут нет, схема отбрасывает молча.
    # Проверено живым прогоном ДО правки: `config.reload` на восьми процессах вернул
    # `failed` (ключ не выжил round-trip), а прямой тест менеджера при этом был зелёным.
    log_line_max_bytes: Annotated[
        int,
        FieldMeta("Предел объёма строки снапшота, байт (0 — без предела)", min=0, max=1_048_576),
    ] = DEFAULT_LOG_LINE_MAX_BYTES

    # 2.2: потолок уникальных серий (имя × теги) — на окно агрегации И на живой
    # слой сразу. Живёт здесь по той же причине, что `log_line_max_bytes`: этот
    # фасад — единственная дорога конфига приложения к плоскости, и ключ,
    # которого тут нет, схема отбрасывает МОЛЧА. Дорога трёх точек §3.2:
    # схема → фасад/`expand_observability` → readback живого стража
    # (`StatsManager.observability_readback`).
    max_series: Annotated[
        int,
        FieldMeta("Потолок уникальных серий метрик (имя × теги); 0 — без предела", min=0, max=1_000_000),
    ] = DEFAULT_MAX_SERIES

    @model_validator(mode="before")
    @classmethod
    def _complain_about_repurposed_enabled(cls, data: Any) -> Any:
        """Назвать смену смысла ``stats.enabled`` вслух — при чтении старого ``false``.

        Митигация (3) развилки Р-3, условие владельца. Конфиг, написанный ДО Ф2,
        просил «не логировать снапшоты», а получит «не собирать числа вовсе» —
        разница видна только тому, кто про неё знает, и молчать здесь значило бы
        поменять поведение боевого стенда без единого слова.

        **Голос жестом ``REMOVED_BATCHING_KEYS``**, а не отказом: конфиг с
        унаследованной ручкой не должен вставать колом на стенде.

        **Адрес голоса — ВИД (``FallbackLogger``), а НЕ аварийный выход
        ``emergency_log``. Прежняя редакция объясняла выбор так: «он работает до
        подъёма логгера, а конфиг читают именно тогда» — посылка верна, вывод
        ложен, и это снято замером (вердикт CTO, задача 2.12).** Замер: настоящий
        ``LoggerManager`` с файловым каналом, по одной записи ДО его подъёма и
        после, обеими дорогами. Вид дал **2 строки в файле** (ранняя слита из
        буфера ``std_facade._EARLY`` первой же строкой), ``emergency_log`` —
        **0 строк в файле** и обе в stderr через ``logging.lastResort``, потому
        что у stdlib-root в процессах фреймворка нет ни одного хендлера. То есть
        вид работает до подъёма логгера ТОЖЕ, и вдобавок доезжает до журнала.

        Аварийный выход остаётся тем, чем объявлен в его собственном контракте
        (``_fallback.py``): дверью для того, «кто сломался и сообщает о
        собственной поломке». Валидатор конфига — не маршрут наблюдаемости,
        рассказывающий о своём отказе, и рекурсии здесь нет. До правки правило
        ADR-PM-046 звучало ровно один раз на действие — и не попадало ни в один
        файл ``logs/``; оператор со стендом его не читал.

        **Только при ``false``, и это не половинчатость.** При ``enabled: true``
        старое и новое поведение совпадают дословно (плоскость включена, канал
        снапшотов включён дефолтом ``log_snapshots=True``) — предупреждать не о
        чем, а голос на каждом конфиге проекта превратился бы в фон, который
        перестают читать.

        **Задача 2.12 — «один раз на чтение» было ЗАЯВЛЕНО прежней редакцией
        этого докстринга, а замер опроверг заявление.** Было написано: «"Один
        раз" здесь означает "один раз на ЧТЕНИЕ конфига"» — то есть один голос
        на один вызов оператора (boot, ``config.reload``). Независимый тестер и
        координатор сняли числа порознь и сошлись:

        * прямой ``ObservabilityConfig.model_validate({"stats": {"enabled":
          False}})`` — **1** срабатывание валидатора;
        * ОДИН ``config.reload`` через операторскую дверь (харнесс ``_wired``,
          настоящий ``CommandManager.handle_command``) — **6** срабатываний;
        * три ``config.reload`` подряд — **18** (6+6+6 — между вызовами нет
          вообще никакого гашения).

        **Причина — НЕ «Pydantic пересобирает вложенные модели по ходу резолва
        слоёв».** Так утверждала первая редакция этой правки, и вердикт CTO снял
        утверждение стеком вызовов: шесть — это шесть РАЗНЫХ ЯВНЫХ разборов
        секции из ТРЁХ стадий команды ``config.reload``, а не пересборка внутри
        одного разбора:

        * стадия «проверить» — ``builtin_commands.py:1923`` →
          ``observability_layers.py:1321`` (``model_validate``) и
          ``:1333`` → ``unknown_section_keys:1212`` (``model_validate``);
        * стадия «применить» — ``builtin_commands.py:2158`` →
          ``observability_reload.py:1350/1415`` → ``compose_managers_payload:219``
          → ``expand_observability:861``;
        * стадия «сверить» — ``builtin_commands.py:2285`` →
          ``observability_verified:806`` → ``unknown_section_keys:1212``, затем
          ``:808`` (``model_validate``) и ``:814`` → ``expand_observability:861``.

        Трёхстадийность («сперва проверить, потом применить, потом сверить») —
        сознательное решение (B2, Task 5.7), и шесть разборов словаря размером с
        секцию дефектом не являются. Дефект в другом: **ввод-вывод внутри
        функции, которую зовут как парсер.** Окно это МАСКИРУЕТ, а не убирает —
        и следствие названо вслух ниже, в абзаце про «подавлено».

        **Корень — отдельная задача, и он назван проверяемо:** голос обязан
        переехать на стадию «применяю» (``compose_managers_payload``, единственную
        со смыслом применения; обе дороги — boot через ``process_managers.py:130``
        и reload через ``observability_reload.py:219`` — уже зовут её). Окно
        останется вторым рубежом для цикла ассемблера по процессам. До переезда
        число в «подавлено: N» считает РАЗБОРЫ, а не действия оператора: три
        ``config.reload`` за одно окно дают «подавлено: 17», и это честное число
        не той величины, которую ждёт читатель.

        **Дросселирует ОКНО по ключу (:mod:`...logger_module.core.windowed_voice`),
        а НЕ процессный флаг «уже предупреждали» — и довод в пользу окна не
        изменился от того, что счёт голосов оказался другим, он остаётся
        дословно тем же, что и в прежней редакции.** Флаг сделал бы громкость
        правила зависимой от ПОРЯДКА: первый прочитавший конфиг тест или процесс
        съедал бы предупреждение НАВСЕГДА, а ``config.reload`` оператора через
        час молчал бы, хотя это НОВОЕ действие НОВОГО человека. Окно эту
        зависимость снимает: голос звучит не чаще
        ``observability.voices.default_window_sec`` (L0-дефолт 5.0, политика
        процесса, а не литерал этой функции) независимо от того, кто и когда
        прочитал конфиг раньше, а следующее реальное нарушение правила (новое
        чтение после окна тишины) снова говорит вслух и называет, сколько
        попыток голоса было подавлено с прошлой записи.

        Ключ голоса — ``stats.enabled.repurposed`` (решение владельца Р-12,
        план ``observability-closure``, задача 2.12) — собственный, ни с одним
        соседним дросселируемым голосом не общий. Держатель
        (:func:`~.windowed_voice.process_voices`) резолвится НА КАЖДЫЙ вызов, а
        не захватывается в переменную при импорте:
        :func:`~.windowed_voice.reset_process_voices` подменяет глобальный
        держатель целиком, и захваченная ссылка сделала бы фикстуры сброса
        тестов невидимыми для этого валидатора, а состояние — протекающим
        между чтениями конфига.
        """
        if isinstance(data, dict) and data.get("enabled") is False:
            from ..._fallback import FallbackLogger
            from ...logger_module.core.windowed_voice import (
                compose_voice_text,
                process_voices,
            )

            voiced, suppressed = process_voices().take("stats.enabled.repurposed", None)
            if voiced:
                FallbackLogger("observability_config").warning(
                    compose_voice_text(
                        "stats.enabled: false — с Ф2 этот ключ означает ПЛОСКОСТЬ ЧИСЕЛ: "
                        "метрики не будут собираться вовсе (окно пустое, все каналы "
                        "статистики молчат). Прежний смысл «не писать снапшоты в журнал» "
                        "переехал в stats.log_snapshots — если вы хотели именно его, "
                        "замените на 'enabled: true, log_snapshots: false' (ADR-PM-046)",
                        suppressed,
                    )
                )
        return data

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value):
        return canonical_level_or_raise(value, field="stats.log_level")

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

    # B2 (major-8): проверка имени уровня стояла ТОЛЬКО на резолве — в
    # `LoggerManagerConfig`, то есть уже ПОСЛЕ записи значения в слой.
    # Воспроизведено: `config.reload {"log_level": "БОЛТОВНЯ"}` → `success: true`,
    # мусор лёг в L3 со сроком, применение откатилось, действовал прежний
    # уровень. Проверка переехала на границу записи (см.
    # `observability_layers.validate_layer_section`), а здесь стоит её тело.
    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value):
        return canonical_level_or_raise(value, field="log_level")

    log_directory: Annotated[
        Optional[str],
        FieldMeta("Корень логов (None — из env MULTIPROCESS_LOG_DIR / INSPECTOR_LOG_DIR)"),
    ] = None
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
        FieldMeta("Переопределения приёмников групп логгера ({имя: {channels: [...]}}) — порог задаётся loggers"),
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

    # Ф2 (задача 2.3, M9, «Честный такт»). БЫЛ голым `get_config("heartbeat_interval",
    # 5.0)` в `ProcessHeartbeat.start()` — процессный ключ вне слоёв, без провенанса и
    # без применения без рестарта. Полем схемы (как `session_ttl_sec` выше) он получает
    # оба: генерик `_schema_keys()` (`observability_layers.provenance`) видит его без
    # отдельной проводки, а `config.reload` принимает его на границе (белый список —
    # это и есть поля этой схемы, см. `validate_layer_section`/`unknown_section_keys`).
    # В manager-конфиги НЕ раскладывается (`expand_observability` его не берёт, тем же
    # доводом, что и `session_ttl_sec`) — получатель не менеджер, а ЖИВОЙ
    # `ProcessHeartbeat._interval`; третья точка дороги — `apply_heartbeat_interval` в
    # `managers/observability_reload.py`, доставляющая значение без рестарта процесса.
    # Старый ключ `heartbeat_interval` (боевой `start()`) этой задачей НЕ снимается и
    # не меняется — она вводит только рантайм-правку ПОВЕРХ загрузочного значения.
    heartbeat_interval_sec: Annotated[
        float,
        FieldMeta(
            "Такт heartbeat/телеметрии процесса, сек — эффективный тик = min(это, tick_sec)",
            min=0.0,
            max=86400.0,
        ),
    ] = 5.0

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
        FieldMeta("Тишина по ключу дольше этого начинает всплеск заново, сек", min=MIN_BURST_RESET_SEC, max=86400.0),
    ] = 5.0
    sampling_max_level: Annotated[
        str,
        FieldMeta("Верхняя граница уровня для дросселя (ERROR/CRITICAL не сэмплируются никогда)"),
    ] = "DEBUG"

    # Ф7.х: валидатор-близнец к тому, что стоит на ``LoggerManagerConfig``.
    # Асимметрия слоёв — отдельный класс дефекта этого плана: L3 принимал
    # ``sampling_max_level: "TRACE"`` молча, а L0 то же значение отвергал.
    # Оператор правит секцию ``observability`` — то есть попадает ровно в тот
    # слой, который проверял меньше.
    #
    # Нижнюю границу ``burst_reset_sec`` держит ``FieldMeta(min=...)`` через
    # ``SchemaBase`` — своего валидатора для неё здесь нет по тому же доводу,
    # что и в ``LoggerManagerConfig``: два предохранителя прячут, кто держит.

    @field_validator("sampling_max_level", mode="before")
    @classmethod
    def _normalize_sampling_max_level(cls, value):
        return canonical_level_or_raise(value, field="sampling_max_level")

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
    #: Ф8.5. В manager-конфиги НЕ раскладывается (как ``session_ttl_sec``): это не
    #: параметр менеджера, а адрес второй плоскости. Читает его сшивка процесса
    #: (``wire_document_sink``) прямо из разрешённых слоёв — поэтому ключ настраивается
    #: и рецептом (L2), и командой (L3), тем же правом, что и всё остальное здесь.
    documents: Annotated[
        ObservabilityDocumentsConfig,
        FieldMeta("Плоскость документов: фабрика стока и её словарь (Ф8.5)"),
    ] = Field(default_factory=ObservabilityDocumentsConfig)
    #: Ф4 (задача 4.1). В manager-конфиги НЕ раскладывается — ровно как
    #: ``documents`` и ``session_ttl_sec``: это не параметр менеджера, а политика
    #: отбора, которую читает живой ``WideEventSelector`` процесса
    #: (``wire_event_selector`` на старте, ``apply_event_selector`` на пересборке).
    #: Ключ живёт в ТОЙ ЖЕ секции ``observability``, а не в ``telemetry.*``:
    #: пятой двери конфига этап не заводит (правило Б.1), а под-секции
    #: ``observability`` закрытого списка не имеют.
    events: Annotated[
        ObservabilityEventsConfig,
        FieldMeta("Отбор широких записей о единице работы: first_n / every_mth (Ф4)"),
    ] = Field(default_factory=ObservabilityEventsConfig)
    #: Ф5 (задача 5.1). В manager-конфиги НЕ раскладывается — по тому же доводу,
    #: что ``documents``/``events``/``session_ttl_sec``: это не параметр менеджера,
    #: а политика дампа, которую читает живой ``FlightRecorder`` процесса
    #: (``wire_flight_recorder`` на старте, ``apply_flight_recorder`` на пересборке).
    #: Ключ живёт в ТОЙ ЖЕ секции ``observability`` — пятой двери конфига этап не
    #: заводит (правило Б.1), ``telemetry.*`` не трогается.
    flight: Annotated[
        ObservabilityFlightConfig,
        FieldMeta("Дамп кольца записей по вызову: enabled / sink / keep / limit (Ф5)"),
    ] = Field(default_factory=ObservabilityFlightConfig)
    #: Ф4 плана «порт наблюдений» (задача 4.1). В manager-конфиги НЕ
    #: раскладывается — по тому же доводу, что ``documents``/``events``/``flight``:
    #: это не параметр менеджера, а политика публикации порта, которую читает
    #: живой ``TelemetryGate`` процесса (``_build_telemetry_gate`` на старте,
    #: ``apply_observation_policy`` на пересборке). Ключ живёт в ТОЙ ЖЕ секции
    #: ``observability`` — пятой двери конфига этап не заводит (правило Б.1);
    #: легаси-секция ``telemetry.publish`` при этом остаётся ИМЕНОВАННЫМ
    #: источником той же сборки, а не второй дверью (ADR-PM-041).
    observation: Annotated[
        ObservationPolicyConfig,
        FieldMeta("Политика порта наблюдений: glob-правила по пути дерева (Ф4)"),
    ] = Field(default_factory=ObservationPolicyConfig)
    #: Ф1.4 (M17). В manager-конфиги НЕ раскладывается — по тому же доводу, что
    #: ``documents``/``events``/``flight``/``observation``: это не параметр
    #: менеджера, а политика окон голоса, которую читает живой механизм
    #: ``windowed_voice`` (``wire_voices_policy`` на старте, ``apply_voices_policy``
    #: на пересборке). Ключ живёт в ТОЙ ЖЕ секции ``observability`` — пятой двери
    #: конфига задача не заводит (правило Б.1).
    voices: Annotated[
        ObservabilityVoicesConfig,
        FieldMeta("Окна голоса: окно по умолчанию и порог эскалации повторов (Ф1.4)"),
    ] = Field(default_factory=ObservabilityVoicesConfig)
    #: Ф5.2 / Ф2 (задача 2.2). В manager-конфиги НЕ раскладывается — по тому же
    #: доводу, что ``documents``/``events``/``flight``/``observation``/``voices``:
    #: это не параметр менеджера, а политика ПЕРСИСТЕНТНОГО стора (SQLite),
    #: которую читает проводка процесса (``ProcessModule._wire_observability_hub``
    #: — enabled/db_path АТРИБУТОМ; такт уборки — ``resolve_history_policy``,
    #: level/max_rows/max_age_sec/purge_interval_sec). Ключ живёт в ТОЙ ЖЕ секции
    #: ``observability`` — пятой двери конфига задача не заводит (правило Б.1).
    history: Annotated[
        ObservabilityHistoryConfig,
        FieldMeta("Персистентная история (SQLite-стор): порог записи, пределы ретеншена, путь к БД (Ф5.2)"),
    ] = Field(default_factory=ObservabilityHistoryConfig)

    #: Ключи, снятые Ф7.4 вместе с батчингом записи. Схема принимает лишние ключи
    #: МОЛЧА (проверено), поэтому без этой сверки конфиг с ``enable_batching: true``
    #: после сноса просто перестал бы что-либо значить — оператор правит ручку,
    #: ничего не меняется, и никто ему об этом не говорит. Ровно класс «проглоченный
    #: сбой», который эта фаза и лечит.
    @model_validator(mode="before")
    @classmethod
    def _complain_about_removed_batching_keys(cls, data: Any) -> Any:
        """Назвать снятые ключи вслух — но не уронить систему из-за старого конфига.

        Отказ (``raise``) был бы честнее по форме, но дороже по существу: конфиг с
        унаследованной ручкой встал бы колом на боевом стенде из-за строки, которая
        ничего не делает. Поэтому — предупреждение через аварийный вывод (он работает
        до подъёма логгера, а конфиг читают именно тогда) и продолжение работы.
        """
        if isinstance(data, dict):
            stale = [k for k in REMOVED_BATCHING_KEYS if k in data]
            if stale:
                from ..._fallback import emergency_log

                emergency_log(
                    "observability_config",
                    "WARNING",
                    "конфиг наблюдаемости содержит снятые ключи %s: батчинг записи убран "
                    "(Ф7.4, замер показал ноль экономии на границе ОС и худший хвост p99) — "
                    "запись теперь синхронна ВСЕГДА, эти ключи не делают ничего",
                    ", ".join(stale),
                )
        return data

    @field_validator("scopes", mode="before")
    @classmethod
    def _normalize_scope_keys(cls, value: Any) -> Any:
        """Ф2.4: канон имени группы — заглавными. Тело — :func:`canonical_scope_keys`."""
        return canonical_scope_keys(value)


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
        ``ObservabilityLayers.effective_session_ttl``. По тому же доводу здесь нет
        ни ``documents`` (адрес второй плоскости, читает ``wire_document_sink``),
        ни ``events`` (политика отбора, читает ``WideEventSelector`` процесса),
        ни ``flight`` (политика дампа, читает ``FlightRecorder`` процесса),
        ни ``voices`` (политика окон голоса, читает ``windowed_voice`` процесса —
        Ф1.4), ни ``history`` (политика персистентного стора — читает
        ``ProcessModule._wire_observability_hub`` атрибутом схемы, такт уборки —
        ``resolve_history_policy``, Ф5.2/Ф2 2.2). Держателей окон в процессе
        много и ни один из них не менеджер наблюдаемости, поэтому «разложить в
        конфиг менеджера» здесь просто некуда.
    """
    cfg = data if isinstance(data, ObservabilityConfig) else ObservabilityConfig.model_validate(data or {})

    logger: Dict[str, Any] = {
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
    # `INFO` лёг поверх уровня из `MULTIPROCESS_LOG_LEVEL`, который к этому моменту
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

    # Ф2 (задача 2.2, критерий 2): `errors.enabled` был в схеме (дефолт True) и
    # НЕ ЧИТАЛСЯ здесь вовсе — `ErrorManager` создавался всегда, независимо от
    # ключа (`_create_error_manager` смотрит только на непустоту словаря).
    # Гейт стоит РОВНО тут, у ЕДИНСТВЕННОЙ точки раскладки: `False` даёт ПУСТОЙ
    # словарь, и `_create_error_manager` (managers/process_managers.py) видит
    # пустой `managers_config.get("error", {})` — тем же путём, что и процесс
    # БЕЗ секции `error` вовсе (см. докстринг `ProcessModule._install_process_hooks`:
    # дорога инцидента `report_error` → health есть у ЛЮБОГО процесса и без
    # ErrorManager, плоскость ошибок добавляет к ней запись, а не создаёт её).
    error: Dict[str, Any] = (
        {
            "default_level": cfg.errors.level,
            "include_stacktrace": cfg.errors.include_stacktrace,
        }
        if cfg.errors.enabled
        else {}
    )

    stats: Dict[str, Any] = {
        # Ф2 (2.1, Р-3а): судьбу ЛОГ-КАНАЛА решает `log_snapshots`, а не
        # `enabled`. Прежде здесь стоял `cfg.stats.enabled`, и это была ЕДИНСТВЕННАЯ
        # работа ключа; теперь `enabled` — плоскость, и он едет отдельной строкой
        # ниже. Две ручки, две строки: слитые в одну, они означали бы, что числа
        # нельзя собирать не логируя, — а это ровно тот сценарий, ради которого
        # ключи и разведены.
        "enable_logging": cfg.stats.log_snapshots,
        # Плоскость чисел. Четвёртая точка дороги ключа (схема → фасад →
        # `StatsManagerConfig` → менеджер): пропусти её здесь — и `enabled`
        # стоял бы в схеме, показывался бы оператору и не значил бы ничего.
        # Тот же дефект трижды ловили `flush_interval`, `log_line_max_bytes` и
        # `max_series`.
        "enabled": cfg.stats.enabled,
        "aggregation_interval": cfg.stats.aggregation_interval,
        # Ф6.х.8: без прокида этой ручки менеджер всегда брал дефолт 10.0, и
        # max(flush_interval, aggregation_interval) съедал любую настройку темпа.
        "flush_interval": cfg.stats.flush_interval,
        "log_level": cfg.stats.log_level,
        # 3.4: без прокида ключ существовал бы в фасаде и не доезжал до менеджера —
        # ровно та половинчатость, которой уже был `flush_interval` (Ф6.х.8).
        "log_line_max_bytes": cfg.stats.log_line_max_bytes,
        # 2.2: третья точка той же дороги. Без этой строки ручка стояла бы в
        # схеме, показывалась бы оператору и не значила бы ничего — менеджер
        # брал бы дефолт (тот же дефект, что дважды ловили `flush_interval` и
        # `log_line_max_bytes`).
        "max_series": cfg.stats.max_series,
    }

    # Task 5.10.b: адресные переопределения каналов двух младших плоскостей —
    # тем же ЧАСТИЧНЫМ словарём, что у логгера. Полное описание канала здесь не
    # собирается сознательно: severity-каналы ошибок строит
    # ``expand_error_manager_config``, а служебные каналы статистики — её
    # собственные сборщики; наша запись обязана лечь поверх, а не вместо.
    # Ф2 (2.2): гейт выше может оставить `error` пустым (`errors.enabled=False`) —
    # дописывать в него каналы значило бы сделать словарь непустым и оживить
    # `ErrorManager`, которого гейт как раз погасил. `error`, а не `cfg.errors.enabled`
    # ещё раз: одна проверка, а не вторая копия того же условия.
    if cfg.errors.channels and error:
        error["channels"] = {str(k): dict(v) for k, v in cfg.errors.channels.items()}
    if cfg.stats.channels:
        stats["channels"] = {str(k): dict(v) for k, v in cfg.stats.channels.items()}

    command: Dict[str, Any] = {
        "log_success": cfg.commands.log_success,
    }

    return {"logger": logger, "error": error, "stats": stats, "command": command}
