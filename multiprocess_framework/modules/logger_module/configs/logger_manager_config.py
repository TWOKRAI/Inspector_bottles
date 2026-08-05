# -*- coding: utf-8 -*-
"""
LoggerManagerConfig — SchemaBase / ChannelRoutingConfig для LoggerManager.

Каналы, scopes и modules — отдельные сущности (как в прототипе managers_schema_lite).
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field, field_validator

from ...channel_routing_module import ChannelRoutingConfig
from ...channel_routing_module.buffers.batch_buffer import (
    DEFAULT_MAX_PENDING,
    DEFAULT_OVERFLOW_POLICY,
    validate_overflow_policy,
)
from ...channel_routing_module.levels import (
    LEVEL_ORDER,
    SEVERITY_NUMBERS,
    UNKNOWN_SEVERITY,
    normalize_level_name,
)
from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ..log_enums import LogLevel

_STD_FMT = "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s"
#: Ф2.6. Потолок длины имени источника в выводе фреймворковых каналов.
#: Полное точечное имя продолжает жить в записи и в правилах; укорачивается
#: только то, что видит глаз.
#:
#: Значение выбрано ЗАМЕРОМ, а не копированием дефолта logback (``%logger{36}``):
#: у нас общий префикс пакета длиннее, и 36 его почти не сжимает. Прирост веса
#: логов от перехода на точечные имена, по строкам прогона 2026-08-03:
#:
#: ===========  ==============  ===============  ======
#: потолок      ProcessManager  region_splitter  gui
#: ===========  ==============  ===============  ======
#: 0 (полное)   +9.27%          +16.38%          +4.74%
#: **20**       **+1.20%**      **+3.04%**       **+1.46%**
#: 24           +2.01%          +4.50%           +1.60%
#: 36           +2.92%          +6.00%           +2.19%
#: ===========  ==============  ===============  ======
#:
#: 20 — колено: ниже него выигрыш не растёт, выше цена удваивается. Даёт
#: ``m.m.dispatch_module`` (19 символов против 46 полного и 10 у прежнего
#: плоского ``dispatcher``).
_NAME_MAX_LEN = 20
_FILE_MAX = 10 * 1024 * 1024

#: Порядок уровней — из общего дома трёх плоскостей, а не своей копией.
#: Своя копия здесь уже была: пока она жила рядом, гейт логгера и severity-путь
#: ошибок сравнивали уровни по двум разным кортежам, и расхождение было бы
#: молчаливым (тот же класс, что _RETENTION_STAT_KEYS в Ф0.7).
_LEVEL_ORDER = LEVEL_ORDER


class LoggerChannelSchema(SchemaBase):
    """Описание одного канала логирования."""

    name: str = ""
    type: str = "file"
    enabled: bool = True
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    #: Ф2.6. Потолок длины имени источника В ВЫВОДЕ; 0 — печатать полностью.
    #:
    #: Развязывает две разные задачи, которые до сих пор решались одной строкой:
    #: конфиг и правила адресуют ПОЛНОЕ точечное имя (иначе префиксный резолв
    #: не работает), а в файл пишется сокращённое — иначе каждая строка растёт на
    #: длину пакета. Замер на прогоне 2026-08-03: переход трёх шумных источников
    #: на точечные имена БЕЗ сокращения дал бы +4.7…16.4% к весу ``system.log``,
    #: то есть фаза, которая борется за объём, добавила бы объёма.
    #:
    #: Правило сокращения — как ``%logger{N}`` в logback: ведущие сегменты
    #: сжимаются до первой буквы, последний не трогается никогда
    #: (``multiprocess_framework.modules.dispatch_module`` → ``m.m.dispatch_module``).
    #:
    #: Дефолт 0 выбран сознательно: молча менять вид КАЖДОЙ строки лога у всех,
    #: кто соберёт менеджер сам, — не настройка. Фреймворковые каналы включают
    #: сокращение явно, ниже.
    name_max_len: int = 0
    max_size: int = 10 * 1024 * 1024
    backup_count: int = 5
    rotate: bool = True
    file_path: Optional[str] = None
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    # Только для type="memory": сколько ЗАПИСЕЙ держит кольцо в памяти процесса.
    # Отдельным полем, а не переиспользованием max_size: там байты, и 10 МБ,
    # прочитанные как число записей, дали бы кольцо на 10 миллионов элементов.
    capacity: Optional[int] = None
    # Имя менеджера-владельца. Проставляет НЕ пользователь, а сам менеджер при
    # создании канала: ресурсы, переживающие канал (кольцо в памяти), лежат в
    # процессном реестре, и без владельца одноимённые каналы двух плоскостей-
    # братьев слились бы в одно кольцо.
    owner: Optional[str] = None


class LoggerScopeSchema(SchemaBase):
    """Скоуп логирования (ключи SYSTEM, BUSINESS, …)."""

    enabled: bool = True
    # Литерал, а не ``_LEVEL_ORDER[1]``: дефолт, выведенный из индекса кортежа,
    # молча сменился бы при вставке нового имени в начало порядка (Ф3.1).
    min_level: str = "INFO"
    channels: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)

    @field_validator("min_level")
    @classmethod
    def _normalize_min_level(cls, value: str) -> str:
        """Ф1.1: порог приводится к канону ОДИН раз — на границе конфига.

        Прежняя реализация звала ``self.min_level.upper()`` на КАЖДОЙ записи,
        то есть аллоцировала строку ради решения «писать или нет». Нормализация
        здесь снимает эту цену навсегда и заодно делает ``min_level`` в
        ``model_dump`` каноничным.

        Валидатор поля, а не хранение производной рядом: приватный атрибут
        Pydantic-модели читается через ``__getattr__``, и замер показал **921 нс
        против 47 нс** у обычного поля — «оптимизация» через ``PrivateAttr``
        делала гейт впятеро ДОРОЖЕ прежнего. Поймано бенчем Ф1.6, а не глазом.

        **Ф3.1 — здесь же имя и ПРОВЕРЯЕТСЯ.** До этого валидатор только
        поднимал регистр, и неопознанное имя доезжало до горячего пути, где
        ``should_log`` честно пропускал всё. Воспроизведено: ``min_level='WARN'``
        → ``should_log(DEBUG)`` = ``True``, то есть порог «предупреждения и выше»
        оборачивался firehose, молча. ``WARN`` при этом не опечатка, а каноничное
        имя OTel — поэтому чужие написания раскрываются алиасами, а вот
        действительно неизвестное имя отвергается.

        Отказ безопасен по построению: ``reconfigure`` разбирает конфиг ДО
        разрушения реестра (R9), поэтому отвергнутый порог оставляет менеджер с
        прежним рабочим набором каналов, а не с пустым.
        """
        if not isinstance(value, str):
            return value
        canonical = normalize_level_name(value)
        if canonical is None:
            raise ValueError(
                f"неизвестный уровень '{value}' в min_level (известны: {', '.join(LEVEL_ORDER)}; синонимы: WARN, FATAL)"
            )
        return canonical

    def should_log(self, level: LogLevel, module: str) -> bool:
        """Пройдёт ли запись гейт скоупа. Горячий путь — без аллокаций.

        Незнакомый уровень (или незнакомый ``min_level``) ПРОПУСКАЕТ запись
        вместе с фильтром модулей — ровно как прежняя реализация, где
        ``ValueError`` из ``index()`` возвращал ``True`` до проверки модулей.
        Это характеризовано тестом: «тише DEBUG» из-за опечатки в имени уровня
        было бы тихой потерей.

        Что осталось на пути решения: два обращения к полям модели, два
        словарных лукапа и сравнение int. Ни линейного поиска по кортежу
        (``LEVEL_ORDER.index``), ни ``.upper()``.
        """
        if not self.enabled:
            return False
        min_severity = SEVERITY_NUMBERS.get(self.min_level, UNKNOWN_SEVERITY)
        if min_severity == UNKNOWN_SEVERITY:
            return True
        severity = SEVERITY_NUMBERS.get(level.value, UNKNOWN_SEVERITY)
        if severity == UNKNOWN_SEVERITY:
            return True
        if severity < min_severity:
            return False
        # Список, а не frozenset: он почти всегда пуст, а его материализация в
        # множество жила бы в приватном атрибуте — то есть на дорогом пути.
        modules = self.modules
        if modules and module not in modules:
            return False
        return True


class LoggerRuleSchema(SchemaBase):
    """Правило по иерархическому имени источника (Ф2.2).

    Ключ в :attr:`LoggerManagerConfig.loggers` — префикс имени источника
    (``multiprocess_framework.modules.router_module``), корень — пустая строка.
    Действует по самому длинному совпавшему префиксу; разбор — в
    :class:`~..core.name_hierarchy.NameHierarchy`.

    Оба поля **необязательны и резолвятся независимо**: ``None`` значит «это
    правило про такую-то ось молчит, наследую с более короткого префикса».
    Отличать молчание от объявленной пустоты обязательно — ``channels: []``
    значит «приёмников нет, и это решение», а не «наследую» (то же правило, что
    решение Г3 для слоёв конфига).
    """

    level: Annotated[
        Optional[str],
        FieldMeta("Порог для поддерева (None — наследовать)"),
    ] = None
    channels: Annotated[
        Optional[List[str]],
        FieldMeta("Приёмники для поддерева (None — наследовать, [] — приёмников нет)"),
    ] = None
    channels_extra: Annotated[
        Optional[List[str]],
        FieldMeta("Приёмники ДОПОЛНИТЕЛЬНО к унаследованным (накапливаются по ветке)"),
    ] = None
    """Ф2.6, решение Р-2.6-Ж — вторая операция на оси приёмников.

    **Упущение, а не решение.** Ф2.2 сделала правило ЗАМЕЩАЮЩИМ, и слова
    «additivity»/``propagate`` не было ни в одной врезке. При этом снесённый
    ``modules`` был АДДИТИВНЫМ: ``_route`` добавлял ``module_<имя>`` к каналам
    скоупа, и дефолт это прямо фиксировал («логи с ``module="trace"`` уходят сюда
    ПЛЮС в scope-каналы»). Перенос таких маршрутов на замещающее правило был бы
    тихой сменой поведения: файл остался бы непустым, а из ``system.log`` записи
    исчезли — и приёмка «маршрут жив» этого не заметила бы.

    Выразить это через ``channels`` нельзя в принципе: правило про скоуп не знает,
    а наборы у скоупов разные (``SYSTEM`` — console+system_file, ``BUSINESS`` —
    system_file+messages_file). Пришлось бы скопировать список, который живёт в
    другом месте, — ровно та вторая копия строки, ради устранения которой заведено
    объявление имени (Р-2.6-В).

    Отдельный ключ, а не флаг ``additive: bool``: смысл флага зависел бы от
    соседнего ключа, то есть это второй диалект. Здесь операция самостоятельна и
    резолвится тем же проходом.

    **Накапливается по ВСЕЙ ветке**, в отличие от ``channels`` (там побеждает самый
    длинный префикс). Иначе добавка у листа молча отменяла бы добавку у пакета —
    тот же дефект, ради которого две оси резолвятся независимо.

    ``[]`` — «ничего не добавляю», и это НЕ отмена добавок предков: отмена была бы
    третьей операцией, а её никто не просил. ``None`` — то же самое, ключ просто
    не задан; здесь молчание и объявленная пустота совпадают по смыслу, и это
    сказано прямо, чтобы не искали в них разницу по аналогии с ``channels``.
    """

    @field_validator("level")
    @classmethod
    def _normalize_level(cls, value: Optional[str]) -> Optional[str]:
        """Канон один раз — на границе конфига, как у ``LoggerScopeSchema.min_level``.

        Иначе сравнение рангов на горячем пути платило бы ``.upper()`` за каждую
        запись, а ``model_dump`` отдавал бы пульту неканоничное значение — и
        readback расходился бы с тем, что стоит в гейте.
        """
        return value.upper() if isinstance(value, str) else value


@register_schema("LoggerManagerConfig")
class LoggerManagerConfig(ChannelRoutingConfig):
    """Конфигурация LoggerManager: каналы, scopes, modules."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "LoggerManager"

    app_name: str = "unknown_app"
    default_level: str = "INFO"
    log_directory: Annotated[
        Optional[str],
        FieldMeta(
            "Корень для относительных file_path каналов и modules. "
            "None — каталог из MULTIPROCESS_LOG_DIR / INSPECTOR_LOG_DIR или системный temp "
            "(не текущий каталог пакета)."
        ),
    ] = None
    enable_batching: bool = True
    batch_size: int = 100
    batch_interval: float = 1.0
    batch_max_pending: Annotated[
        int,
        FieldMeta(
            "Потолок неотправленных записей НА КАНАЛ. Медленный сток без потолка "
            "съедает память тихо (Ф0.3). 0 — без потолка."
        ),
    ] = DEFAULT_MAX_PENDING
    batch_overflow_policy: Annotated[
        str,
        FieldMeta("Что терять при переполнении: drop_oldest (кольцо) | drop_newest"),
    ] = DEFAULT_OVERFLOW_POLICY

    # Ф0.7. Ротация ограничивает каждый файл, но не их число: живой замер дал
    # 730 файлов / 291 МБ и ни одного удаления за 82 дня. Обе политики
    # выключены по умолчанию — механизм, который сам решает что удалить, не
    # включается молча.
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
    # Ф6.9. Свип звали только на старте и на reconfigure — на стенде 24/7
    # настроенный ретеншен подметал бы лишь при рестарте, то есть никогда.
    # Поток поднимается ТОЛЬКО если ретеншен реально включён: при выключенных
    # политиках интервал ничего не стоит и ничего не запускает.
    retention_sweep_interval_sec: Annotated[
        float,
        FieldMeta(
            "Период фонового свипа ретеншена, сек (0 — только старт и reconfigure)",
            min=0.0,
            max=86400.0,
        ),
    ] = 3600.0

    loggers: Annotated[
        Dict[str, LoggerRuleSchema],
        FieldMeta("Правила по иерархическому имени источника (префикс → уровень/приёмники)"),
    ] = {}
    """Ф2.2. Пусто по умолчанию — и это часть контракта, а не «ещё не заполнили».

    Пока таблица пуста, гейт и маршрут работают ровно как до Ф2.2: решение
    принимает скоуп. Прикладные правила живут в конфиге приложения
    (``system.yaml`` прототипа), фреймворк несёт только механизм — требование
    2.6 «нулей прикладных имён во фреймворке» начинает соблюдаться сразу, а не
    чинится потом.
    """

    logger_groups: Annotated[
        Dict[str, List[str]],
        FieldMeta("Ярлыки: имя группы → список префиксов источников"),
    ] = {}
    """Ф2.5. Ярлык набора источников — модель ``logging.group.*`` Spring Boot.

    Правило, написанное под ключом-ярлыком в :attr:`loggers`, раскрывается в
    правила по каждому члену при сборке дерева. Ярлык сам префиксом не
    становится, резолв о нём не знает, горячий путь не платит ничего.

    **Пусто по умолчанию, и это часть контракта** — как и ``loggers``. Состав
    групп решает приложение: фреймворк несёт механизм, а «что считать служебной
    болтовнёй» — вопрос той системы, которую собирают (Р-2.5-Д). Spring везёт
    готовые ``web``/``sql``, но у него один известный набор пакетов, а здесь
    приложение может не подключать половину модулей вовсе.
    """

    channels: Annotated[
        Dict[str, LoggerChannelSchema],
        FieldMeta("Каналы: имя → параметры"),
    ] = {
        "system_file": LoggerChannelSchema(
            type="file",
            enabled=True,
            file_path="system.log",
            max_size=_FILE_MAX,
            backup_count=5,
            format=_STD_FMT,
            name_max_len=_NAME_MAX_LEN,
        ),
        "messages_file": LoggerChannelSchema(
            type="file",
            enabled=True,
            file_path="messages.log",
            max_size=_FILE_MAX,
            backup_count=5,
            format=_STD_FMT,
            name_max_len=_NAME_MAX_LEN,
        ),
        # Ф2.6. Снапшот метрик — ЕДИНСТВЕННЫЙ писатель скоупа PERFORMANCE
        # (`statistics_module/channels/log_stats_channel.py`, проверено грепом:
        # прямых `log(LogScope.PERFORMANCE, …)` в проде нет), и он же самый
        # тяжёлый источник в системе. Замер 2026-08-03: 5.27 МБ из 9.38 МБ
        # `system.log` у ProcessManager (56%), 2.33 из 8.88 у gui (26%), 2.08 из
        # 8.63 у region_splitter (24%). Одна строка снапшота весит ~7 КБ —
        # список метрик, отрендеренный в текст.
        #
        # Свой файл, а не правило иерархии: у скоупа один писатель, значит
        # адресовать его отдельным механизмом незачем — ручка «какому скоупу
        # какие приёмники» существует с самого начала и уже оттестирована.
        # Найдено ревью решений Ф2.6: главный выигрыш фазы брался без нового
        # механизма, а мы собирались платить за него таблицей правил.
        #
        # Суммарная запись на диск при этом НЕ уменьшается ни на байт — те же
        # МБ, только в другом файле. Сокращение объёма (сэмплинг, перевод
        # снапшота из логов в телеметрию) — отдельная задача, и приёмку
        # «system.log похудел» нельзя засчитывать как «логов стало меньше».
        "performance_file": LoggerChannelSchema(
            type="file",
            enabled=True,
            file_path="performance.log",
            max_size=_FILE_MAX,
            backup_count=5,
            format=_STD_FMT,
            name_max_len=_NAME_MAX_LEN,
        ),
        "console": LoggerChannelSchema(
            type="console",
            enabled=True,
            format=_STD_FMT,
            name_max_len=_NAME_MAX_LEN,
        ),
    }

    scopes: Annotated[
        Dict[str, LoggerScopeSchema],
        FieldMeta("Скоупы: SYSTEM, BUSINESS, …"),
    ] = {
        "SYSTEM": LoggerScopeSchema(
            enabled=True,
            min_level="WARNING",
            channels=["console", "system_file"],
        ),
        "BUSINESS": LoggerScopeSchema(
            enabled=True,
            min_level="INFO",
            # console НЕ подключён к BUSINESS: пер-кадровые INFO-логи воркеров
            # уходят только в файлы (system_file/messages_file), а не засоряют
            # терминал. В stdout остаётся лишь SYSTEM WARNING+ через свой scope.
            channels=["system_file", "messages_file"],
        ),
        # Ф2.6: свой файл вместо system_file — обоснование у канала
        # `performance_file` выше. Изменение живого поведения названо вслух:
        # снапшоты метрик ПЕРЕСТАЮТ попадать в `system.log`. Это перенос, а не
        # дублирование, и выбран он сознательно — иначе разгрузки не случится
        # вовсе. Закреплено характеризационным тестом, а не оставлено умолчанием.
        "PERFORMANCE": LoggerScopeSchema(
            enabled=True,
            min_level="INFO",
            channels=["performance_file"],
        ),
        # DEBUG-scope по умолчанию ВЫКЛЮЧЕН: на DEBUG в system_file лился пер-кадровый
        # firehose (периодический TRACE-лог PipelineExecutor — снят в Ф7 G.1,
        # channel_dispatcher "no route" на каждый кадр) → ~100 МБ/мин, постоянная
        # ротация затирала историю. INFO+ продолжают писаться в файлы через
        # SYSTEM/BUSINESS. Для отладки временно enabled=True.
        "DEBUG": LoggerScopeSchema(
            enabled=False,
            min_level="DEBUG",
            channels=["system_file"],
        ),
    }

    @field_validator("logger_groups")
    @classmethod
    def _reject_dotted_group_names(cls, value: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Ф2.5 (Р-2.5-Г): ярлык с точкой отвергается на границе конфига.

        Отказ, а не предупреждение: у такого конфига нет правильного прочтения.
        Имя ``a.b`` было бы одновременно алиасом и узлом дерева, и «самое длинное
        совпадение» перестало бы быть однозначным — а на этом свойстве держится
        весь резолв Ф2.2.
        """
        dotted = sorted(name for name in value if "." in str(name))
        if dotted:
            raise ValueError(
                f"имя группы не может содержать точку: {dotted}. Точка — разделитель уровней "
                f"иерархии имён, и ярлык с точкой неотличим от префикса источника"
            )
        return value

    @field_validator("scopes", mode="before")
    @classmethod
    def _normalize_scope_keys(cls, value: Any) -> Any:
        """Ф2.4: имя группы — ОДНО написание, канон заглавными (Р-2.4-А).

        Приведение стоит здесь, а не на пути записи: ``.upper()`` в
        ``_scope_schema`` стоил бы аллокации на каждом промахе кэша, а канон
        нужен ровно один раз — когда конфиг собирают.

        Без этого валидатора слой приложения с ключом ``system:`` не
        переопределял бы дефолтный ``SYSTEM``, а ложился бы РЯДОМ с ним:
        ``deep_merge`` слоёв работает по ключу словаря, и два написания дали бы
        два скоупа, один из которых недостижим (``log()`` спрашивает канон).
        Тихое «настройка не подействовала» — тот же класс, что уже стоил фазе
        288 пустых файлов.

        ``mode="before"`` обязателен: ключи надо поправить ДО того, как Pydantic
        разложит значения по ``LoggerScopeSchema``.
        """
        if not isinstance(value, dict):
            return value
        return {(k.upper() if isinstance(k, str) else k): v for k, v in value.items()}

    @field_validator("batch_overflow_policy")
    @classmethod
    def _check_overflow_policy(cls, value: str) -> str:
        """Отказ на ГРАНИЦЕ конфига, а не в конструкторе буфера.

        Иначе опечатка всплывала бы посреди ``reconfigure``: старый буфер уже
        остановлен, каналы пересозданы, ``self.config`` подменён — и менеджер
        оставался бы в полуприменённом состоянии с молча выключенным батчингом.
        """
        return validate_overflow_policy(value)
