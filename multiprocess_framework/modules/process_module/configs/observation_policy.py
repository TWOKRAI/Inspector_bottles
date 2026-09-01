# -*- coding: utf-8 -*-
"""Политика публикации порта наблюдений — правила по ПУТИ дерева (Ф4, задача 4.1).

Соседний :mod:`.telemetry_publish_config` решает «поедет ли метрика» по ИМЕНИ
ЛИСТА (суффиксу): правило ``metrics.fps`` действует на любой ``fps``, где бы он
ни лежал. Пока листья плагинов лежали рядом с агрегатом фреймворка, различать их
было нечем; Ф1 развела их по путям (``processes.<P>.state.fps`` против
``processes.<P>.state.plugins.<писатель>.fps``), и адресовать одну плоскость, не
задев другую, стало ВЫРАЗИМО — но только на языке путей. Этот модуль и есть тот
язык: glob-выражение по дереву, движок — публичный матчер стора
(``state_store_module.match_pattern`` / ``split_pattern``), второго не заводится.

**Где живут ключи.** В секции ``observability`` (поле
:class:`~.observability_config.ObservabilityConfig.observation`), в тех же
четырёх слоях L0→L1→L2→L3, что и логи. Пятая дверь конфига не открывается
(решение владельца, зафиксировано в ``DECISIONS.md``, ADR-PM-041).

**Четыре источника решения, три из них называет оператор** (вариант «в»
развилки умолчания, решение владельца 2026-08-25):

* :data:`SOURCE_RULE` — явное правило оператора (``observation.rules``);
* :data:`SOURCE_SUBTREE_DEFAULT` — дефолтное правило поддерева порта
  (:data:`PORT_SUBTREE_PATTERN`) с ЯВНОЙ частотой значением
  (``observation.subtree_interval_sec``), а не подразумеваемой;
* :data:`SOURCE_WHITELIST` — легаси-секция ``telemetry.publish``: её белый список
  ``metrics.<имя>`` и её же умолчание ``default_enabled``. Она читается ТОЙ ЖЕ
  сборкой как ИМЕНОВАННЫЙ источник, а не второй дверью, и провенанс называет её
  вслух (:data:`LEGACY_SOURCE_NAME`);
* :data:`SOURCE_UNGATED` — легаси-секции нет вовсе. Паритет с сегодняшним
  ``ProcessHeartbeat._build_telemetry_gate`` → ``None``: вне поддерева порта
  гейта нет, метрика едет каждый тик.

**Порядок разрешения — ЯВНОСТЬ, затем longest-prefix** (ред. 2026-08-25, решение
владельца по блокеру Б1 ревью Ф4). Старший разряд ключа — ступень явности
источника (:func:`resolution_key`), и только внутри одной ступени спор решает
специфичность паттерна:

1. :data:`TIER_RULE` — явное правило оператора по пути (``observation.rules``);
2. :data:`TIER_LEGACY_ENTRY` — ЯВНАЯ запись легаси-белого-списка
   (``telemetry.publish.metrics.<имя>``): оператор написал это имя намеренно;
3. :data:`TIER_SUBTREE_DEFAULT` — дефолтное правило поддерева порта;
4. :data:`TIER_UMBRELLA` — зонтичные умолчания (``default_enabled`` легаси-секции,
   а также «легаси-секции нет вовсе»).

**Почему явность выше специфичности.** Владелец согласился на «два умолчания в
одной секции», но НЕ на «умолчание перебивает явное заявление оператора».
Воспроизведение до правки (ревью Ф4): при ``{"default_enabled": false,
"metrics": {"fps": {"enabled": false}}}`` — то есть оператор ЗАПРЕТИЛ ``fps`` —
путь ``processes.cam1.state.plugins.capture.fps`` резолвился в ``enabled=True``
источником ``subtree_default``, потому что у дефолта поддерева (3 литерала,
5 сегментов) специфичность выше, чем у суффиксной формы ``**.fps`` (1 литерал,
2 сегмента). Живое следствие: чекбокс и частота ПЛАГИННЫХ строк пульта не делали
ничего, а команда отвечала ``success``.

Критерий М1 при этом цел и сторожится тестом: у НОВОЙ метрики записи в
``metrics`` нет вовсе, поэтому легаси отвечает зонтиком
(:data:`TIER_UMBRELLA`), и дефолт поддерева его перекрывает — новая метрика
плагина по-прежнему едет при нулевых правках конфига.

Внутри :data:`TIER_RULE` порядок прежний и ОТЛИЧАЕТСЯ от соседа
``telemetry_reload._central_rule_for_metric`` (тот берёт СТРОЖАЙШИЙ интервал).
Расхождение намеренное, довод — в ``DECISIONS.md`` (ADR-PM-042): у соседа
предохранитель IPC, где строжайший ответ безопасен, а здесь — заявка оператора,
где выигрывать обязан ТОЧНЕЕ АДРЕСОВАННЫЙ, иначе широкое правило поддерева
навсегда перебивало бы точечное.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Dict, Iterable, Optional, Tuple

from pydantic import Field, field_validator

from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ...state_store_module import match_pattern, split_pattern
from .telemetry_publish_config import MetricRule, TelemetryPublishConfig

#: Адрес поддерева порта наблюдений в дереве состояния. Константа, а не ручка:
#: адрес поддерева — следствие конструкции Ф1 («владение = путь»), а не настройка.
#: Понадобится другой адрес — он выражается обычным правилом в ``rules``.
PORT_SUBTREE_PATTERN = "processes.*.state.plugins.**"

#: Умолчание частоты дефолтного правила поддерева, сек. ЗНАЧЕНИЕ, а не
#: подразумевание: предохранитель, который нельзя измерить, предохранителем не
#: является (прямое условие владельца, перенесённое в вариант «в» без ослабления).
DEFAULT_SUBTREE_INTERVAL_SEC = 1.0

#: Адрес поддерева плоскости ЧИСЕЛ (Ф2, задача 2.1; развилка Р-2, вариант «а»):
#: ``processes.<процесс>.stats.<имя метрики>``. Теги в путь не входят — правило
#: режет метрику целиком, со всеми её сериями (сказано в ``CONTROL_PANEL.md`` и в
#: докстринге ``NumbersGate.allow``).
STATS_SUBTREE_PATTERN = "processes.*.stats.**"

#: Умолчание частоты чисел, сек. **Ноль, и это не забытая ручка.** Число —
#: событие (каждый вызов значим для суммы и p95), а не «сколько сейчас»: тиком
#: его схлопнуть нельзя, и дефолтный троттл здесь означал бы молчаливую потерю
#: слагаемых. Частота у чисел выражается ЯВНЫМ правилом оператора.
STATS_SUBTREE_INTERVAL_SEC = 0.0

#: Литералы источника решения — они же значения поля ``source`` в провенансе.
SOURCE_RULE = "rule"
SOURCE_SUBTREE_DEFAULT = "subtree_default"
SOURCE_WHITELIST = "whitelist"
SOURCE_UNGATED = "ungated"

#: Имя легаси-источника в провенансе — адрес, по которому оператор его грепнет.
LEGACY_SOURCE_NAME = "telemetry.publish"

#: **Ступени ЯВНОСТИ — старший разряд ключа разрешения** (:func:`resolution_key`).
#: Числа сравниваются, а не перечисляются по месту: порядок обязан быть один на
#: все ветки :meth:`ObservationPolicy.resolve`, иначе он превращается в набор
#: частных случаев, разъезжающихся при первой же правке.
TIER_RULE = 3  #: явное правило оператора по пути (`observation.rules`)
TIER_LEGACY_ENTRY = 2  #: явная запись `telemetry.publish.metrics.<имя>`
TIER_SUBTREE_DEFAULT = 1  #: дефолтное правило поддерева порта
TIER_UMBRELLA = 0  #: зонтик: `default_enabled` либо «легаси-секции нет вовсе»

#: Плейсхолдер имени процесса, когда гейт собран без него (прямая конструкция в
#: тесте). Один сегмент, поэтому ``processes.*.…`` продолжает совпадать, а
#: адресное ``processes.cam1.…`` — нет, и это честно: имени нам не сообщили.
PROCESS_UNKNOWN = "-"

#: Ключ под-секции внутри разрешённых слоёв ``observability``.
OBSERVATION_SECTION_KEY = "observation"

#: Путь набора правил в плоском namespace слоёв. Набор — НЕПРОЗРАЧНЫЙ лист
#: (см. ``observability_layers.OPAQUE_LAYER_PATHS``): ключи здесь — glob-паттерны,
#: а в них есть точки, и per-ключевая бухгалтерия слоёв резала бы паттерн на
#: сегменты пути — тот же слом, который уже разобран у ``telemetry.throttle``.
OBSERVATION_RULES_PATH = f"{OBSERVATION_SECTION_KEY}.rules"


@register_schema("ObservationPolicyConfig")
class ObservationPolicyConfig(SchemaBase):
    """Секция ``observability.observation`` — политика порта наблюдений.

    - ``subtree_enabled`` / ``subtree_interval_sec`` — дефолтное правило поддерева
      порта (:data:`PORT_SUBTREE_PATTERN`). Живёт отдельными полями, а не записью
      внутри ``rules``, по прозаичной причине: Pydantic заменяет словарь целиком,
      и первый же операторский ``rules: {…}`` снёс бы дефолт вместе с
      предохранителем. Разрешается оно в ТОМ ЖЕ glob-множестве и тем же ключом
      (:func:`resolution_key`, см. :meth:`ObservationPolicy.resolve`) —
      операторское правило перекрывает его ПОРЯДКОМ (ступень явности), а не
      особым случаем в коде;
    - ``rules`` — правила оператора: ``{glob-путь: {enabled, interval_sec}}``.
      Значение правила — тот же :class:`MetricRule`, что у легаси-секции: две
      схемы для одной формы разошлись бы на первом же новом поле.
    """

    subtree_enabled: Annotated[
        bool,
        FieldMeta(
            "Действует ли дефолтное правило поддерева порта",
            info=f"Поддерево — {PORT_SUBTREE_PATTERN}. False возвращает поддерево "
            "под общее умолчание секции telemetry.publish (deny-by-default с белым списком).",
        ),
    ] = True
    subtree_interval_sec: Annotated[
        float,
        FieldMeta("Частота дефолтного правила поддерева порта, сек", min=0.0),
    ] = DEFAULT_SUBTREE_INTERVAL_SEC
    rules: Annotated[
        Dict[str, MetricRule],
        FieldMeta("Правила по glob-пути дерева: {'processes.*.state.plugins.*.fps': {interval_sec: 1.0}}"),
    ] = Field(default_factory=dict)

    @field_validator("rules", mode="before")
    @classmethod
    def _reject_malformed_patterns(cls, value: Any) -> Any:
        """Отвергнуть паттерн, который не может совпасть ни с чем.

        Пустая строка и пустой сегмент (``a..b``, ``.a``) — это не «правило про
        экзотику», а опечатка: матчер режет паттерн по точкам, и пустой сегмент
        не совпадёт ни с одним сегментом пути НИКОГДА. Молчаливое принятие такого
        ключа дало бы ``success=true`` у правки, которая не делает ничего, —
        класс дефекта, названный в этом проекте «молчащий детектор наоборот».

        Опечатка в ИМЕНИ сегмента (``procesess`` вместо ``processes``) здесь не
        ловится и пойматься не может: имя процесса — прикладное, фреймворк его
        каталога не знает. Её голос — счётчик ``matched_nothing`` в readback'е
        (:meth:`ObservationPolicy.rules_matched_nothing`).
        """
        if not isinstance(value, dict):
            return value
        bad = sorted(str(key) for key in value if not str(key).strip() or any(seg == "" for seg in str(key).split(".")))
        if bad:
            raise ValueError(
                "observation.rules: пустой сегмент в glob-пути "
                f"({', '.join(repr(b) for b in bad)}) — такой паттерн не совпадёт ни с одним путём"
            )
        return value

    def to_dict(self) -> Dict[str, Any]:
        """Сериализовать в dict (Dict at Boundary — уходит в IPC/конфиг)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Any) -> "ObservationPolicyConfig":
        """Собрать из dict (граница процесса). ``None``/частичный → дефолты."""
        return cls.model_validate(data or {})


@dataclass(frozen=True)
class PolicyDecision:
    """Решение политики по ОДНОМУ пути дерева.

    Attributes:
        enabled: публиковать ли лист вообще.
        interval_sec: минимальный интервал публикации, сек.
        source: КТО решил — один из :data:`SOURCE_RULE` /
            :data:`SOURCE_SUBTREE_DEFAULT` / :data:`SOURCE_WHITELIST` /
            :data:`SOURCE_UNGATED`. Без этого поля оператор не отличает
            «разрешено дефолтом» от «разрешено руками», а в секции с ДВУМЯ
            разными умолчаниями (цена варианта «в») это единственный способ
            увидеть переворот с пульта.
        pattern: паттерн победившего правила (у легаси — суффиксная форма
            ``**.<имя>`` либо ``**`` у общего умолчания).
    """

    enabled: bool
    interval_sec: float
    source: str
    pattern: str


def pattern_specificity(pattern: str) -> Tuple[int, int, str]:
    """Ключ сортировки «longest-prefix» для glob-паттерна: больше — точнее.

    Три ступени, и третья не украшение:

    1. число ЛИТЕРАЛЬНЫХ сегментов (не ``*``/``**``) — сколько паттерн реально
       зафиксировал. Именно она делает ``…plugins.capture.fps`` точнее
       ``…plugins.*.fps``, а того — точнее ``…plugins.**``;
    2. общее число сегментов — при равном числе литералов длиннее значит уже;
    3. сам паттерн строкой — детерминизм. Без него два одинаково специфичных
       правила разрешались бы порядком словаря, то есть порядком строк в YAML,
       и «одинаковый конфиг — одинаковое поведение» перестало бы выполняться
       молча. Правило пары зафиксировано тестом с двумя пересекающимися
       правилами и литеральным ожиданием.
    """
    segments = split_pattern(pattern)
    literals = sum(1 for seg in segments if seg not in ("*", "**"))
    return (literals, len(segments), pattern)


def resolution_key(tier: int, pattern: str) -> Tuple[int, int, int, str]:
    """Полный ключ разрешения кандидата: **явность, затем longest-prefix**.

    Старший разряд — ступень явности источника (``TIER_*``), младшие три —
    :func:`pattern_specificity`. Порядок живёт ЗДЕСЬ, одной функцией, а не
    ветками в :meth:`ObservationPolicy.resolve`: правило «явное заявление
    оператора не проигрывает умолчанию» — свойство ПОРЯДКА, и спрятанное в
    ветку оно перестаёт быть проверяемым одним местом.

    Почему явность старше специфичности — в докстринге модуля (воспроизведение
    блокера Б1: дефолт поддерева перебивал операторский запрет ``metrics.fps``).
    """
    literals, segments, text = pattern_specificity(pattern)
    return (int(tier), literals, segments, text)


#: Сегменты дефолтных поддеревьев, посчитанные ОДИН раз на импорт. Разрешение
#: зовётся на каждое число и на каждый лист тика; пересчитывать разбор двух
#: константных паттернов на каждом вызове — работа на горячем пути ради нуля.
_STATS_SUBTREE_SEGMENTS = split_pattern(STATS_SUBTREE_PATTERN)
#: То же для поддерева уровней (Ф2, задача 2.4) — до этой правки
#: :data:`PORT_SUBTREE_PATTERN` разбирался внутри :meth:`ObservationPolicy.resolve`
#: заново на КАЖДЫЙ путь, не имея своей константы рядом с соседом выше.
_PORT_SUBTREE_SEGMENTS = split_pattern(PORT_SUBTREE_PATTERN)


class ObservationPolicy:
    """Разрешение «поедет ли ЭТОТ путь и как часто» — одним glob-множеством.

    Тотальна по построению: у любого пути есть ответ, потому что легаси-источник
    (или его отсутствие) замыкает список кандидатов паттерном ``**``, а у путей
    плоскости чисел ответ замыкает дефолт :data:`STATS_SUBTREE_PATTERN`.

    **Две плоскости, один язык, но РАЗНЫЕ умолчания** (Ф2, задача 2.1).
    ``processes.<P>.state.**`` — уровни, ``processes.<P>.stats.<имя>`` — числа.
    Правила оператора (``observation.rules``) действуют на обе одинаково — это и
    есть «один язык». Легаси-секция ``telemetry.publish`` к числам НЕ
    применяется, и это не вкусовщина: в боевом конфиге прототипа она
    deny-by-default (``system.yaml:277``), а её правила суффиксные
    (``**.<лист>``) — пусти её в решение по числам, и зонтик ``**`` выключил бы
    ВСЮ плоскость чисел молча, в момент попадания этой задачи в main. Сторожится
    паритетным тестом на реальном файле конфига прототипа.

    Потокобезопасность: объект НЕИЗМЕНЯЕМ после сборки (правки прилетают новым
    объектом и атомарной подменой ссылки — тот же приём, что у
    ``ProcessHeartbeat._telemetry_gate``). Изменяемого состояния два: счётчик
    попаданий :attr:`_hits` (набор ключей фиксирован конструктором) и счётчик
    тиков :attr:`_evaluated_ticks`.

    **С Ф2 у :attr:`_hits` больше одного писателя, и это названо, а не
    заговорено.** Прежде оба поля писал ОДИН поток такта heartbeat'а; теперь
    попадания считает ещё и гейт чисел (``NumbersGate.allow``), которого зовёт
    ЛЮБОЙ поток, пишущий метрику. ``+= 1`` не атомарен — под конкуренцией счёт
    может недосчитать единицы, поэтому ``rule_hits`` заявляется как нижняя
    граница, а не как точный аудит. Что от этого НЕ ломается: набор ключей
    по-прежнему фиксирован конструктором (вставок нет → словарь не
    перестраивается под читателем), а :meth:`rules_matched_nothing` спрашивает
    «ноль или не ноль» — потерянная единица не превращает ненулевой счёт в
    нулевой. Считать попадания чисел ОТДЕЛЬНЫМ счётчиком было бы хуже: правило
    по числам, реально работающее, попало бы в ``rules_matched_nothing``, то
    есть единственный голос про опечатку в пути начал бы обвинять здоровые
    правила (находка З3 ревью Ф4, ради которой перенос счёта и заводился).
    """

    def __init__(
        self,
        config: Optional[ObservationPolicyConfig] = None,
        legacy: Optional[TelemetryPublishConfig] = None,
        *,
        hits: Optional[Dict[str, int]] = None,
        evaluated_ticks: int = 0,
        rule_first_tick: Optional[Dict[str, int]] = None,
    ) -> None:
        """
        Args:
            config: секция ``observability.observation`` (``None`` → дефолты L0,
                то есть дефолтное правило поддерева включено).
            legacy: секция ``telemetry.publish`` как ИМЕНОВАННЫЙ источник
                (``None`` → гейта вне поддерева порта нет вовсе).
            hits: счёт попаданий ПРЕДЫДУЩЕЙ политики (``{паттерн: сколько раз}``).
                Переносятся только те паттерны, которые есть и в новом наборе:
                правило с тем же текстом — то же правило, а переписанное
                оператором начинается с нуля честно.

                **Зачем перенос** (находка З3 ревью Ф4): политику пересобирает
                КАЖДАЯ соседняя правка (``telemetry.reconfigure``, любое движение
                пульта — ``_make_gate`` собирает новый объект). Без переноса
                чужая правка обнуляла бы счёт, и работающее правило возвращалось
                бы в ``rules_matched_nothing``, то есть единственный голос про
                опечатку в пути кричал бы на здоровые правила.
            evaluated_ticks: сколько ЦИКЛОВ оценки прожила предыдущая политика
                (Ф0.4, m6). Переносится по той же причине, что и ``hits``.
            rule_first_tick: ``{паттерн: номер тика, на котором правило впервые
                увидено}`` предыдущей политики.

                **Почему возраст живёт на ПРАВИЛЕ, а не на политике** (правка
                исполнителя к дизайну тестера, Ф0.4). Один счётчик на политику
                возвращает ровно тот ложноположительный ответ, ради которого
                задача и делается: правило, ДОБАВЛЕННОЕ пересборкой на 50-м
                тике, унаследовало бы «уже оценено» и в тот же миг стало бы
                обвиняемым в ``rules_matched_nothing``, ни разу не будучи
                оценённым. Паттерн, которого нет в переносе, — новый, и его
                возраст начинается с ТЕКУЩЕГО тика; переживший пересборку свой
                возраст сохраняет.
        """
        self._config = config if config is not None else ObservationPolicyConfig()
        self._legacy = legacy
        self._rules: Dict[str, MetricRule] = dict(self._config.rules)
        # Ключи фиксированы здесь и больше не меняются — см. докстринг класса.
        carried = hits or {}
        self._hits: Dict[str, int] = {pattern: int(carried.get(pattern, 0)) for pattern in self._rules}
        self._evaluated_ticks = int(evaluated_ticks)
        carried_first = rule_first_tick or {}
        self._first_tick: Dict[str, int] = {
            pattern: int(carried_first.get(pattern, self._evaluated_ticks)) for pattern in self._rules
        }
        # Задача 2.4: паттерны правил оператора разбираются ОДИН раз на сборку
        # политики, а не на каждый резолв. ``self._rules`` неизменен после
        # конструктора (докстринг класса), поэтому разбор, сделанный здесь,
        # действителен на всю жизнь объекта — второй раз его делать не для чего.
        self._rule_segments: Dict[str, Tuple[str, ...]] = {pattern: split_pattern(pattern) for pattern in self._rules}
        # Кэш решений по ПОЛНОМУ пути дерева (задача 2.4) — «выключенный лист не
        # стоит ничего, кроме поиска в кэше». Ключ — путь, значение — пара
        # (готовое решение, паттерны правил ОПЕРАТОРА, которые за него голосовали
        # при первом резолве). Вторая половина пары нужна ИМЕННО для того, чтобы
        # кэш-хит продолжал считаться :meth:`rule_hits` — см. докстринг
        # :meth:`resolve`, где счёт разведён с самим кэшированием.
        #
        # Живёт НА ЭКЗЕМПЛЯРЕ, не в модульной глобали. Это и есть инвалидация:
        # политика неизменяема (докстринг класса), а её ЗАМЕНА на новую
        # (``_install_observation_policy`` при ``config.reload`` — см.
        # ``process_heartbeat.py``) всегда собирает НОВЫЙ объект
        # ``ObservationPolicy`` с пустым кэшем; старый объект вместе со своим
        # кэшем уходит в сборщик мусора. Кэш, вынесенный в модульную переменную
        # или в class-level словарь, пережил бы замену объекта и продолжал бы
        # отвечать по СТАРЫМ правилам — «новое правило действует после reload»
        # стало бы ложным; ровно это доказывает инъекция задачи 2.4
        # (``TestCacheDoesNotSurviveAPolicyReplacement``).
        #
        # Потокобезопасность: запись — обычный ``dict[str] = ...`` без лока.
        # Под GIL присваивание атомарно, поэтому гонка на НОВОМ пути — это в
        # худшем случае повторное (но идентичное — резолв детерминирован)
        # вычисление у второго потока, не порча значения. Тот же довод, каким
        # в этом файле уже живёт ``PathSchedule.due`` по соседству.
        self._cache: Dict[str, Tuple[PolicyDecision, Tuple[str, ...]]] = {}

    # ------------------------------------------------------------------ чтение

    @property
    def config(self) -> ObservationPolicyConfig:
        """Секция, из которой политика собрана (источник readback'а)."""
        return self._config

    @property
    def legacy(self) -> Optional[TelemetryPublishConfig]:
        """Легаси-секция ``telemetry.publish``, если она есть."""
        return self._legacy

    @property
    def evaluated_ticks(self) -> int:
        """Сколько ЦИКЛОВ оценки политика прожила (Ф0.4, m6).

        Растёт :meth:`mark_tick`, а не :meth:`resolve`: количество резолвов —
        это количество ПУТЕЙ, а не циклов, и диагностическое чтение
        (:meth:`provenance_for`) резолвит с ``count=False`` вовсе. Тик и чтение
        обязаны различаться явно, иначе «правило дожило до оценки» опять стало
        бы выводом из чужого числа.
        """
        return self._evaluated_ticks

    def mark_tick(self) -> None:
        """Отметить завершение одного цикла оценки (зовёт поток такта heartbeat'а)."""
        self._evaluated_ticks += 1

    def rule_first_tick(self) -> Dict[str, int]:
        """``{паттерн: тик, на котором правило впервые увидено}`` — перенос при пересборке."""
        return dict(self._first_tick)

    def _rule_ticks(self, pattern: str) -> int:
        """Сколько циклов оценки ПРОЖИЛО конкретное правило (возраст, не счёт попаданий)."""
        return self._evaluated_ticks - self._first_tick.get(pattern, self._evaluated_ticks)

    def resolve(self, path: str, *, count: bool = True) -> PolicyDecision:
        """Решение по полному пути дерева (``processes.cam1.state.plugins.a.fps``).

        Кандидаты собираются ВСЕ, победитель — старший по :func:`resolution_key`:
        сначала ступень ЯВНОСТИ (``TIER_*``), внутри неё — специфичность
        паттерна. Явное правило оператора и дефолт поддерева живут в одном
        множестве: если оператор написал ровно :data:`PORT_SUBTREE_PATTERN`, его
        запись вытесняет дефолт СТУПЕНЬЮ (правило явное, дефолт — нет), поэтому
        дефолт добавляется лишь когда такого паттерна нет в ``rules``.

        Путь плоскости ЧИСЕЛ (:data:`STATS_SUBTREE_PATTERN`) замыкается СВОИМ
        дефолтом и до легаси-кандидатов не доходит — довод и воспроизведение в
        докстринге класса. Правила оператора при этом обходятся ТЕМ ЖЕ циклом
        выше: язык правил один на обе плоскости, разные у них только умолчания.

        **Задача 2.4 — O(1) после первого вызова.** Само решение — чистая
        функция от ``path`` и неизменяемой политики (:meth:`_decide`), поэтому
        оно считается РОВНО ОДИН РАЗ на путь и кладётся в :attr:`_cache`; второй
        и следующие резолвы того же пути отвечают словарным поиском. Счёт
        попаданий правил (:attr:`_hits`) — сознательно ОТДЕЛЬНЫЙ шаг: он не
        часть кэшируемого значения, а побочный эффект КАЖДОГО вызова с
        ``count=True``, кэш-хит включительно. Иначе второй и далее резолвы
        уже включённой метрики перестали бы засчитываться в ``rule_hits``, и
        :meth:`rules_matched_nothing` начала бы обвинять здоровое, часто
        читаемое правило в «ни разу не совпало» — тот самый класс дефекта
        (счётчик, который лжёт о том, что считает), ради которого в этом файле
        уже разведены ``count=True``/``count=False`` (находка З3 ревью Ф4).

        Args:
            path: полный путь листа в дереве состояния.
            count: считать ли попадания правил (``rules_matched_nothing``).
                ``False`` — для ДИАГНОСТИЧЕСКОГО чтения (:meth:`provenance_for`).
                Собственный докстринг соседа ``TelemetryGate.decide`` объявляет
                этот принцип дословно — «опрос состояния, меняющий состояние, это
                наблюдатель, который врёт о том, что наблюдает», — и до находки
                З3 ревью Ф4 нарушался ровно здесь: два подряд
                ``introspect.observability`` без единого такта процесса между
                ними убирали работающее правило из списка «не совпало ни с чем».
        """
        key = str(path)
        cached = self._cache.get(key)
        if cached is None:
            decision, matched = self._decide(key)
            self._cache[key] = (decision, matched)
        else:
            decision, matched = cached
        if count:
            for pattern in matched:
                self._hits[pattern] = self._hits.get(pattern, 0) + 1
        return decision

    def _decide(self, path: str) -> Tuple[PolicyDecision, Tuple[str, ...]]:
        """Тело резолва БЕЗ побочных эффектов — вызывается :meth:`resolve` РОВНО
        ОДИН РАЗ на путь (задача 2.4), результат кэшируется вызывающим.

        Returns:
            Пара ``(решение, паттерны правил ОПЕРАТОРА, которые совпали с этим
            путём)``. Второй элемент — не только победитель: правило может
            совпасть и проиграть по ступени явности (см. :func:`resolution_key`),
            и оно всё равно обязано попасть в ``rule_hits`` — так было устроено
            до кэша (счёт вёлся внутри цикла ниже), и вынос в отдельный кортеж
            сохраняет это буквально, лишь перенося момент инкремента в
            :meth:`resolve`.
        """
        segments = tuple(path.split("."))
        best_key: Optional[Tuple[int, int, int, str]] = None
        best: Optional[PolicyDecision] = None
        matched: list[str] = []

        def _offer(pattern: str, enabled: bool, interval: float, source: str, tier: int) -> None:
            nonlocal best_key, best
            key = resolution_key(tier, pattern)
            if best_key is None or key > best_key:
                best_key = key
                best = PolicyDecision(
                    enabled=bool(enabled), interval_sec=float(interval), source=source, pattern=pattern
                )

        default_interval = self._legacy.default_interval_sec if self._legacy is not None else 0.0

        for pattern, rule in self._rules.items():
            if match_pattern(self._rule_segments[pattern], segments):
                matched.append(pattern)
                interval = rule.interval_sec if rule.interval_sec is not None else default_interval
                _offer(pattern, rule.enabled, interval, SOURCE_RULE, TIER_RULE)

        cfg = self._config
        # Плоскость ЧИСЕЛ (Ф2, 2.1) — своё поддерево и свой замыкающий дефолт.
        # Проверяется ОДИН раз и решает обе развилки ниже: и какой дефолт
        # предложить, и пускать ли легаси-секцию в кандидаты (нет — довод и
        # воспроизведение в докстринге класса).
        if match_pattern(_STATS_SUBTREE_SEGMENTS, segments):
            if STATS_SUBTREE_PATTERN not in self._rules:
                _offer(
                    STATS_SUBTREE_PATTERN,
                    True,
                    STATS_SUBTREE_INTERVAL_SEC,
                    SOURCE_SUBTREE_DEFAULT,
                    TIER_SUBTREE_DEFAULT,
                )
            # Тотальность: паттерн `processes.*.stats.**` совпадает с ЛЮБЫМ путём
            # этой плоскости, поэтому кандидат здесь есть всегда — либо этот
            # дефолт, либо одноимённое правило оператора из цикла выше.
            assert best is not None  # noqa: S101 — инвариант тотальности, а не проверка ввода
            return best, tuple(matched)

        if (
            cfg.subtree_enabled
            and PORT_SUBTREE_PATTERN not in self._rules
            and match_pattern(_PORT_SUBTREE_SEGMENTS, segments)
        ):
            _offer(
                PORT_SUBTREE_PATTERN,
                True,
                cfg.subtree_interval_sec,
                SOURCE_SUBTREE_DEFAULT,
                TIER_SUBTREE_DEFAULT,
            )

        if self._legacy is None:
            # Легаси-секции нет — гейта нет: паритет с `_build_telemetry_gate` → None.
            # Зонтик: это НЕ заявление про имя, а отсутствие механизма.
            _offer("**", True, 0.0, SOURCE_UNGATED, TIER_UMBRELLA)
        else:
            leaf = segments[-1] if segments else ""
            rule = self._legacy.metrics.get(leaf)
            if rule is not None:
                interval = rule.interval_sec if rule.interval_sec is not None else default_interval
                # Суффиксное правило `имя` ≡ `**.имя` — старые правила валидны буквально.
                # Ступень ЯВНАЯ: оператор написал это имя руками (блокер Б1).
                _offer(f"**.{leaf}", rule.enabled, interval, SOURCE_WHITELIST, TIER_LEGACY_ENTRY)
            else:
                # `default_enabled` — зонтик над ВСЕМИ именами, а не заявление про
                # это. Поэтому дефолт поддерева порта его перекрывает, и критерий
                # М1 («новая метрика — ноль правок конфига») цел.
                _offer("**", self._legacy.default_enabled, default_interval, SOURCE_WHITELIST, TIER_UMBRELLA)

        # `best` не может остаться None: последняя ветка всегда предлагает `**`.
        assert best is not None  # noqa: S101 — инвариант тотальности, а не проверка ввода
        return best, tuple(matched)

    # ------------------------------------------------------------- диагностика

    def rules_matched_nothing(self) -> list[str]:
        """Правила оператора, которые за жизнь политики не совпали ни с чем.

        **Единственный голос про опечатку в ПУТИ правила.** Соседний сверщик
        секций (``observability_layers._telemetry_publish_problems``) намеренно
        не судит имена под ``metrics`` («незнакомое имя метрики законно»), и это
        решение верное для ИМЁН — но правило по ПУТИ судить некому вовсе:
        ``procesess.*.state.fps`` (опечатка в первом сегменте) проходит схему,
        ложится в слой под срок, отвечает ``success=true`` и не делает НИЧЕГО.
        Здесь оно становится видимым числом, а не выводом из отсутствия эффекта.

        Показание НАКОПИТЕЛЬНОЕ и читается «ни разу с момента применения
        политики»: правило, чей писатель ещё не появился, будет здесь до его
        первой публикации — это не ложная тревога, а честное «пока не совпало».
        Счёт ПЕРЕЖИВАЕТ пересборку политики соседней правкой (см. ``hits=`` у
        конструктора) и не растёт от диагностического чтения
        (:meth:`provenance_for` резолвит с ``count=False``) — обе половины
        находки З3 ревью Ф4.

        **Правило моложе одного тика сюда не попадает** (Ф0.4, m6): «ноль
        попаданий» у только что применённого правила означает «ещё не
        спрашивали», а не «не совпало ни с чем», и обвинять его не за что. Такие
        едут отдельным :meth:`rules_pending` — два РАЗНЫХ факта в двух полях, а
        не один список, который читатель обязан домысливать.
        """
        return sorted(pattern for pattern, hits in self._hits.items() if hits == 0 and self._rule_ticks(pattern) >= 1)

    def rules_pending(self) -> list[str]:
        """Правила, ещё не дожившие до цикла оценки (Ф0.4, m6).

        Возраст считается ПО ПРАВИЛУ: правило, добавленное пересборкой на 50-м
        тике политики, ещё не оценивалось ни разу — сколько бы тиков ни прожили
        его соседи (см. ``rule_first_tick`` у конструктора).

        **Правило с попаданиями сюда не попадает даже в нулевом возрасте**, и это
        не перестраховка. Возраст растёт отметкой :meth:`mark_tick`, а попадания —
        вызовом :meth:`resolve`; сегодня оба делает ОДИН вызывающий
        (``TelemetryGate``) в одной ветке такта, поэтому «есть попадания, а тиков
        ноль» не воспроизводится. Держится это на том, что вызывающий один, —
        а не на устройстве полей: второй вызывающий, резолвящий мимо такта, дал бы
        readback, где ``rule_hits`` показывает совпадения, а ``rules_pending``
        рядом утверждает «ещё не оценивалось». Совпадение — доказательство того,
        что правило оценивали, и оно сильнее счётчика тиков.
        """
        return sorted(
            pattern for pattern in self._rules if self._rule_ticks(pattern) < 1 and self._hits.get(pattern, 0) == 0
        )

    def rule_hits(self) -> Dict[str, int]:
        """``{паттерн: сколько путей он рассудил}`` — счёт, а не «ноль/не ноль».

        Выбрано вместо булева ответа осознанно (открытый вопрос З3 ревью Ф4):
        «ноль» отличает опечатку от здорового правила, но НЕ отличает правило,
        совпадающее раз в час, от совпадающего каждый такт. Оператор с числом
        видит и то, и другое; цена — одно поле в readback'е.
        """
        return dict(self._hits)

    def rules_view(self) -> Dict[str, Dict[str, Any]]:
        """Правила оператора в НОРМАЛИЗОВАННОЙ форме — для readback'а и сверки.

        Нормализация одна на оба берега (запрошенное и действующее), иначе
        частичная запись ``{"interval_sec": 1.0}`` не сошлась бы с полной формой
        живого объекта и вердикт ``config_reload_verified`` объявлял бы провал
        там, где всё применилось.
        """
        return {pattern: rule.model_dump() for pattern, rule in self._rules.items()}

    def effective_view(self) -> Dict[str, Any]:
        """Действующая политика целиком — ответ на «что действует» (М4, пункт а)."""
        return {
            "subtree": PORT_SUBTREE_PATTERN,
            "subtree_enabled": self._config.subtree_enabled,
            "subtree_interval_sec": self._config.subtree_interval_sec,
            "rules": self.rules_view(),
            "legacy_source": LEGACY_SOURCE_NAME if self._legacy is not None else None,
            # Ф0.4 (m6): возраст политики в ответе `config.reload`. Без него
            # пустой `rules_matched_nothing` не отличить: «правила здоровы» и
            # «судить ещё рано» выглядят одинаково.
            "evaluated_ticks": self._evaluated_ticks,
        }

    def provenance_for(self, paths: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """``{путь: {source, pattern, enabled, interval_sec}}`` — кто решил по каждому.

        Считается ТЕМ ЖЕ :meth:`resolve`, которым решение и принимается: свой
        пересчёт «по смыслу» показывал бы согласие всегда, в том числе когда
        живой гейт решает иначе. Но ``count=False``: диагностика не имеет права
        менять то, что показывает (находка З3 ревью Ф4 — воспроизведение в
        докстринге :meth:`resolve`).
        """
        out: Dict[str, Dict[str, Any]] = {}
        for path in paths:
            decision = self.resolve(str(path), count=False)
            out[str(path)] = {
                "source": decision.source,
                "pattern": decision.pattern,
                "enabled": decision.enabled,
                "interval_sec": decision.interval_sec,
            }
        return out


def cap_candidates(view: Any) -> Dict[str, Dict[str, Any]]:
    """Правила, чью частоту обязаны сверять с потолками, — ВКЛЮЧАЯ дефолт поддерева.

    Один сборщик на обоих сверщиков (:func:`~..heartbeat.telemetry.capped_metrics`
    и :func:`~..managers.telemetry_reload.detect_throttle_caps`). До находки З1
    ревью Ф4 их охват РАЗЛИЧАЛСЯ: первый учитывал дефолт поддерева, второй
    получал только ``rules`` и о нём не знал вовсе — два отчёта о потолках,
    расходящихся в охвате, при том что дефолт поддерева и есть НАЗНАЧЕННЫЙ
    предохранитель варианта «в».

    Args:
        view: :meth:`ObservationPolicy.effective_view` (или любой dict той же
            формы: ``subtree`` / ``subtree_enabled`` / ``subtree_interval_sec`` /
            ``rules``).

    Returns:
        ``{паттерн: {"enabled": bool, "interval_sec": float|None}}``. Дефолт
        поддерева не добавляется, если оператор написал такой паттерн сам, —
        та же оговорка, что в :meth:`ObservationPolicy.resolve`.
    """
    if not isinstance(view, dict):
        return {}
    rules = view.get("rules")
    out: Dict[str, Dict[str, Any]] = {
        str(pattern): dict(rule) for pattern, rule in (rules or {}).items() if isinstance(rule, dict)
    }
    subtree = str(view.get("subtree") or PORT_SUBTREE_PATTERN)
    if view.get("subtree_enabled") and subtree not in out:
        out[subtree] = {"enabled": True, "interval_sec": view.get("subtree_interval_sec")}
    return out


def normalized_observation_section(section: Any) -> Dict[str, Any]:
    """Плоские ключи запрошенной секции ``observation`` — для ``observability_verified``.

    Форма ключей ДОСЛОВНО совпадает с тем, что даёт ``flatten_section`` над
    readback'ом той же секции (``observation.rules`` — непрозрачный лист, см.
    :data:`OBSERVATION_RULES_PATH`). Совпадение здесь не косметика: расходись
    берега формой ключа — и каждая правка порта отвечала бы ``unverifiable`` при
    ``checked=0``, то есть «никто не смотрел», ровно та ловушка, которую задача
    обязана сторожить.
    """
    if not isinstance(section, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in section.items():
        if key == "rules":
            rules = value if isinstance(value, dict) else {}
            out[OBSERVATION_RULES_PATH] = {
                str(name): MetricRule.model_validate(rule or {}).model_dump() for name, rule in rules.items()
            }
        else:
            out[f"{OBSERVATION_SECTION_KEY}.{key}"] = value
    return out


__all__ = [
    "DEFAULT_SUBTREE_INTERVAL_SEC",
    "LEGACY_SOURCE_NAME",
    "OBSERVATION_RULES_PATH",
    "OBSERVATION_SECTION_KEY",
    "PORT_SUBTREE_PATTERN",
    "PROCESS_UNKNOWN",
    "STATS_SUBTREE_INTERVAL_SEC",
    "STATS_SUBTREE_PATTERN",
    "SOURCE_RULE",
    "SOURCE_SUBTREE_DEFAULT",
    "SOURCE_UNGATED",
    "SOURCE_WHITELIST",
    "TIER_LEGACY_ENTRY",
    "TIER_RULE",
    "TIER_SUBTREE_DEFAULT",
    "TIER_UMBRELLA",
    "ObservationPolicy",
    "ObservationPolicyConfig",
    "PolicyDecision",
    "cap_candidates",
    "normalized_observation_section",
    "pattern_specificity",
    "resolution_key",
]
